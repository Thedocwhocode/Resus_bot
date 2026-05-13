"""
Orquestra: verificação de cache → workflow AGNO → persistência no DB.
"""
import asyncio
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

    async def handle(self, query: str, telegram_id: int, username: str | None = None) -> dict[str, Any]:
        """
        Processa uma query de pesquisa.

        Fluxo:
        1. Normaliza query e verifica cache (Redis → SQLite fallback)
        2. Cache hit: retorna resposta salva, loga cache_hit=True
        3. Cache miss: executa workflow AGNO, persiste artigos, grava cache
        """
        start = time.monotonic()
        normalized = normalize_query(query)

        # Upsert user
        user_id = await self._upsert_user(telegram_id, username)

        # Cache check
        cached = await get_cached_response(query)
        if cached is None:
            cached = await get_cached_response_fallback(query)

        if cached is not None:
            latency = int((time.monotonic() - start) * 1000)
            await self._log_search(
                user_id=user_id,
                query_raw=query,
                query_normalized=normalized,
                cache_hit=True,
                articles_returned=cached.get("articles_count", 0),
                latency_ms=latency,
                article_ids=cached.get("article_ids", []),
            )
            return {**cached, "cache_hit": True, "latency_ms": latency}

        # Cache miss — executa workflow
        response_text = await self._run_workflow(query)
        latency = int((time.monotonic() - start) * 1000)

        # Extrai metadados básicos do texto de resposta para persistência
        article_ids = await self._persist_article_from_response(response_text)

        payload: dict[str, Any] = {
            "response": response_text,
            "cache_hit": False,
            "latency_ms": latency,
            "articles_count": len(article_ids),
            "article_ids": article_ids,
        }

        await set_cached_response(query, payload)
        await self._log_search(
            user_id=user_id,
            query_raw=query,
            query_normalized=normalized,
            cache_hit=False,
            articles_returned=len(article_ids),
            latency_ms=latency,
            article_ids=article_ids,
        )
        return payload

    async def _run_workflow(self, query: str) -> str:
        """Executa o workflow AGNO em thread separada (é código síncrono)."""
        loop = asyncio.get_event_loop()
        workflow = self._get_workflow()

        def _run_sync() -> str:
            last = "Não foi possível processar sua solicitação."
            for resp in workflow.run(query):
                if resp.content:
                    last = resp.content
            return last

        return await loop.run_in_executor(None, _run_sync)

    async def _persist_article_from_response(self, response_text: str) -> list[int]:
        """Extrai DOI da resposta e persiste artigo no banco."""
        import re
        doi_match = re.search(r"10\.\d{4,}/\S+", response_text)
        if not doi_match:
            return []

        doi = doi_match.group(0).rstrip(".,;)")
        try:
            from resusbot.db.session import get_session_context
            from resusbot.services.category_classifier import classify_article
            from resusbot.services.dedup_service import upsert_article_safe

            # Tenta extrair título básico da resposta
            title_match = re.search(r"📄\s*(.+?)(?:\n|👥)", response_text)
            title = title_match.group(1).strip() if title_match else None

            article_data: dict[str, Any] = {"doi": doi, "title": title}
            article_data["category_id"] = classify_article(article_data)

            async with get_session_context() as session:
                article_id = await upsert_article_safe(session, article_data)

            return [article_id] if article_id else []
        except Exception as e:
            log.warning("persist_article_error", error=str(e))
            return []

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

    async def _log_search(self, **kwargs: Any) -> None:
        try:
            from resusbot.db.repository import log_search
            from resusbot.db.session import get_session_context
            async with get_session_context() as session:
                await log_search(session, **kwargs)
        except Exception as e:
            log.warning("log_search_error", error=str(e))


research_service = ResearchService()
