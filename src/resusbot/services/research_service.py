"""
Orquestra: verificação de cache → workflow AGNO → persistência no DB.
"""

import asyncio
import re
import time
from typing import Any

import structlog

from resusbot.cache.query_cache import (
    get_cached_response,
    get_cached_response_fallback,
    normalize_query,
    set_cached_response,
)
from resusbot.config import settings

_DOI_PATTERN = re.compile(r"^10\.\d{4,}/\S+$")


def _is_doi_query(query: str) -> bool:
    """True se a query inteira é um DOI (ex: '10.1056/NEJMoa2001282')."""
    return bool(_DOI_PATTERN.match(query.strip()))


log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class ResearchService:
    def __init__(self) -> None:
        self._workflow = None

    def _get_workflow(self) -> Any:
        if self._workflow is None:
            from resusbot.workflows.research_workflow import ResearchWorkflow

            self._workflow = ResearchWorkflow(
                name="resusbot-workflow",
                debug_mode=not settings.is_production,
            )
        return self._workflow

    async def handle(
        self, query: str, telegram_id: int, username: str | None = None
    ) -> dict[str, Any]:
        """
        Processa uma query de pesquisa.

        Fluxo:
        0. Gate de créditos — bloqueia se sem saldo
        1. Normaliza query e verifica cache (Redis → SQLite fallback)
        2. Cache hit: retorna resposta salva; consome crédito se billable
        3. Cache miss: executa workflow AGNO, persiste artigos, grava cache, consome crédito se billable
        """
        from resusbot.db.session import get_session_context
        from resusbot.services import credits_service

        start = time.monotonic()
        normalized = normalize_query(query)

        # Upsert user
        user_id = await self._upsert_user(telegram_id, username)

        # Gate de créditos
        if user_id:
            async with get_session_context() as session:
                if not await credits_service.has_credits(session, user_id):
                    return {
                        "error": "insufficient_credits",
                        "response": (
                            "💳 Você não tem créditos disponíveis.\n\n"
                            f"Sua cota gratuita ({settings.free_monthly_credits}/mês) "
                            "foi consumida e seu saldo está em zero.\n\n"
                            "Use /planos para adquirir mais créditos."
                        ),
                        "cache_hit": False,
                        "articles_count": 0,
                        "article_ids": [],
                    }

        # Cache check
        cached = await get_cached_response(query)
        if cached is None:
            cached = await get_cached_response_fallback(query)

        if cached is not None:
            latency = int((time.monotonic() - start) * 1000)
            payload = {**cached, "cache_hit": True, "latency_ms": latency}
            search_log_id = await self._log_search(
                user_id=user_id,
                query_raw=query,
                query_normalized=normalized,
                cache_hit=True,
                articles_returned=payload.get("articles_count", 0),
                latency_ms=latency,
                article_ids=payload.get("article_ids", []),
            )
            await self._maybe_consume_credit(user_id, payload, search_log_id)
            await self._maybe_warn_low_credits(telegram_id, user_id)
            return payload

        # Cache miss — atalho para DOI direto (pula Planner + Search + DOIResolver)
        if _is_doi_query(query):
            response_text = await self._run_doi_shortcut(query)
        else:
            response_text = await self._run_workflow(query)
        latency = int((time.monotonic() - start) * 1000)

        # Extrai metadados básicos do texto de resposta para persistência
        article_ids, has_pdf = await self._persist_article_from_response(response_text)

        payload = {
            "response": response_text,
            "cache_hit": False,
            "latency_ms": latency,
            "articles_count": len(article_ids),
            "article_ids": article_ids,
            "has_pdf": has_pdf,
        }

        await set_cached_response(query, payload)
        search_log_id = await self._log_search(
            user_id=user_id,
            query_raw=query,
            query_normalized=normalized,
            cache_hit=False,
            articles_returned=len(article_ids),
            latency_ms=latency,
            article_ids=article_ids,
        )
        await self._maybe_consume_credit(user_id, payload, search_log_id)
        await self._maybe_warn_low_credits(telegram_id, user_id)
        return payload

    async def _maybe_warn_low_credits(self, telegram_id: int, user_id: int) -> None:
        """Avisa o usuário via Telegram quando restar ≤ 3 créditos pagos."""
        if not user_id:
            return
        try:
            from resusbot.db.session import get_session_context
            from resusbot.services import credits_service

            async with get_session_context() as session:
                info = await credits_service.check_balance(session, user_id)
            # Avisa só quando balance pago (não quota) estiver baixo
            if 0 < info.balance <= 3:
                from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
                from telegram.constants import ParseMode

                from resusbot.config import settings

                if not settings.telegram_bot_token:
                    return
                kb = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("💳 Ver planos", callback_data="plan:list")]]
                )
                bot = Bot(token=settings.telegram_bot_token)
                await bot.send_message(
                    chat_id=telegram_id,
                    text=f"⚠️ Você tem apenas `{info.balance}` crédito\\(s\\) restante\\(s\\)\\!\n\nUse /planos para recarregar antes que acabem\\.",
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=kb,
                )
        except Exception as e:
            log.debug("low_credits_warn_error", error=str(e))

    async def _maybe_consume_credit(
        self, user_id: int, payload: dict[str, Any], search_log_id: int | None
    ) -> None:
        """Consome 1 crédito se o payload for billable (regra de cobrança 'no sucesso')."""
        if not user_id:
            return
        from resusbot.db.session import get_session_context
        from resusbot.services import credits_service

        if not credits_service.is_billable(payload):
            log.info("not_billable_skip", user_id=user_id, articles=payload.get("articles_count"))
            return

        try:
            async with get_session_context() as session:
                await credits_service.consume(session, user_id, search_log_id)
        except Exception as e:
            log.warning("consume_error", user_id=user_id, error=str(e))

    async def _run_doi_shortcut(self, doi: str) -> str:
        """
        Atalho para queries que já são um DOI puro.
        Pula Planner + Search + DOIResolver — vai direto a PDFLink + Formatter.
        Economiza ~3 chamadas LLM (~60 % do custo Groq nesse caso).
        """
        loop = asyncio.get_running_loop()
        workflow = self._get_workflow()

        def _run_sync() -> str:
            last = "Não foi possível processar sua solicitação."
            doi_context = f"DOI confirmado pelo usuário: {doi}\nURL: https://doi.org/{doi}"
            pdf_result = workflow.pdf_finder.run(f"Metadados do artigo:\n{doi_context}")
            final_context = (
                f"Pergunta do usuário: {doi}\n\n"
                f"Metadados encontrados:\n{doi_context}\n\n"
                f"Link de PDF:\n{pdf_result.content or ''}"
            )
            final = workflow.formatter.run(final_context)
            if final.content:
                last = final.content
            return last

        return await loop.run_in_executor(None, _run_sync)

    async def _run_workflow(self, query: str) -> str:
        """Executa o workflow AGNO em thread separada (é código síncrono)."""
        loop = asyncio.get_running_loop()
        workflow = self._get_workflow()

        def _run_sync() -> str:
            last = "Não foi possível processar sua solicitação."
            for resp in workflow.run(query):
                if resp.content:
                    last = resp.content
            return last

        return await loop.run_in_executor(None, _run_sync)

    async def _persist_article_from_response(self, response_text: str) -> tuple[list[int], bool]:
        """
        Extrai DOI da resposta e persiste artigo no banco.
        Retorna (article_ids, has_pdf_link).
        """
        import re

        doi_match = re.search(r"10\.\d{4,}/\S+", response_text)
        if not doi_match:
            return [], False

        doi = doi_match.group(0).rstrip(".,;)")
        # Detecta link de PDF na resposta
        has_pdf = bool(
            re.search(
                r"(\.pdf|europepmc|pubmed|/pmc/|✅ PDF|open access)", response_text, re.IGNORECASE
            )
        )
        # Tenta extrair URL do PDF
        pdf_url_match = re.search(r"https?://\S+\.pdf\b", response_text)
        pdf_url = pdf_url_match.group(0) if pdf_url_match else None

        try:
            from resusbot.db.session import get_session_context
            from resusbot.services.category_classifier import classify_article
            from resusbot.services.dedup_service import upsert_article_safe

            # Tenta extrair título básico da resposta
            title_match = re.search(r"📄\s*(.+?)(?:\n|👥)", response_text)
            title = title_match.group(1).strip() if title_match else None

            article_data: dict[str, Any] = {"doi": doi, "title": title}
            if pdf_url:
                article_data["pdf_url"] = pdf_url
                article_data["oa_status"] = "open"
            article_data["category_id"] = classify_article(article_data)

            async with get_session_context() as session:
                article_id = await upsert_article_safe(session, article_data)

            return ([article_id] if article_id else []), has_pdf
        except Exception as e:
            log.warning("persist_article_error", error=str(e))
            return [], has_pdf

    async def _upsert_user(self, telegram_id: int, username: str | None) -> int:
        try:
            from resusbot.db.repository import upsert_user
            from resusbot.db.session import get_session_context

            async with get_session_context() as session:
                user = await upsert_user(session, telegram_id, username)
                return user.id
        except Exception as e:
            log.warning("upsert_user_error", error=str(e))
            return 0

    async def _log_search(self, **kwargs: Any) -> int | None:
        try:
            from resusbot.db.repository import log_search
            from resusbot.db.session import get_session_context

            async with get_session_context() as session:
                entry = await log_search(session, **kwargs)
                return entry.id
        except Exception as e:
            log.warning("log_search_error", error=str(e))
            return None


research_service = ResearchService()
