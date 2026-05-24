"""
WhatsApp message handlers — mirrors the Telegram handler pattern.

Routes incoming open-wa webhook payloads to the same services used by Telegram:
  - ResearchService  → /search  or plain text
  - StudyService     → /study   /deep   /case

User identity: phone numbers (e.g. "5511999999999@c.us") are hashed into
a stable integer so existing services that accept telegram_id: int work unchanged.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import structlog

from resusbot.security.sanitize import clean
from resusbot.study.models import PedagogicalResponse, StudyMode
from resusbot.whatsapp import client as wa_client
from resusbot.whatsapp.formatters import (
    format_error,
    format_pedagogical_response,
    format_research_response,
    format_study_typing,
    format_typing,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_STUDY_COMMANDS = {
    "/study": StudyMode.STUDY_20_80,
    "/deep": StudyMode.DEEP_DIVE,
    "/case": StudyMode.CLINICAL_CASE,
}


@dataclass
class IncomingMessage:
    chat_id: str      # "5511999999999@c.us"
    body: str         # raw message text
    sender_name: str  # display name (may be empty)
    is_group: bool    # True if from a group

    @property
    def user_int_id(self) -> int:
        """Stable integer derived from the chat_id — compatible with telegram_id fields."""
        digest = hashlib.sha256(self.chat_id.encode()).hexdigest()
        return int(digest[:15], 16)


def parse_openwa_payload(payload: dict) -> IncomingMessage | None:
    """
    Parse an open-wa webhook payload into an IncomingMessage.

    Returns None for:
    - Non-message events (qr, ready, message_ack, …)
    - Messages sent by the bot itself (fromMe)
    - Group messages (we skip these by default to avoid noise)
    """
    event_type = payload.get("type", "")
    if event_type != "message":
        return None

    data = payload.get("data", {})
    if not isinstance(data, dict):
        return None

    msg_id = data.get("id", {})
    if isinstance(msg_id, dict) and msg_id.get("fromMe"):
        return None
    if data.get("fromMe"):
        return None

    body: str = data.get("body", "").strip()
    if not body:
        return None

    is_group: bool = bool(data.get("isGroupMsg", False))
    if is_group:
        # Group messages need explicit mention — skip for MVP
        return None

    chat_id: str = data.get("from", "")
    if not chat_id:
        return None

    sender_name: str = ""
    sender = data.get("sender", {})
    if isinstance(sender, dict):
        sender_name = sender.get("name", "") or sender.get("pushname", "")

    return IncomingMessage(
        chat_id=chat_id,
        body=body,
        sender_name=sender_name,
        is_group=is_group,
    )


async def dispatch(msg: IncomingMessage) -> None:
    """Route an IncomingMessage to the appropriate pipeline."""
    body = msg.body.strip()
    lower = body.lower()

    # ── /help ────────────────────────────────────────────────────────────────
    if lower.startswith("/help") or lower.startswith("/start"):
        await wa_client.send_text(msg.chat_id, _help_text())
        return

    # ── /study  /deep  /case ─────────────────────────────────────────────────
    for cmd, mode in _STUDY_COMMANDS.items():
        if lower.startswith(cmd):
            query = body[len(cmd):].strip()
            if not query:
                await wa_client.send_text(
                    msg.chat_id,
                    f"Por favor, informe o tema após {cmd}.\nEx: {cmd} sepse",
                )
                return
            await _handle_study(msg, query, mode)
            return

    # ── /search or plain text → research pipeline ─────────────────────────────
    if lower.startswith("/search"):
        query = body[7:].strip()
    else:
        query = body  # plain text goes to research pipeline

    await _handle_research(msg, query)


# ── Internal handlers ─────────────────────────────────────────────────────────

async def _handle_research(msg: IncomingMessage, raw_query: str) -> None:
    query = clean(raw_query)
    if not query:
        await wa_client.send_text(msg.chat_id, format_error("Mensagem inválida ou muito curta."))
        return

    log.info("wa_research_request", chat_id=msg.chat_id[:12], query_len=len(query))
    await wa_client.send_text(msg.chat_id, format_typing())
    start = time.monotonic()

    try:
        from resusbot.services.research_service import research_service

        result = await research_service.handle(query=query, telegram_id=msg.user_int_id)
        latency_ms = int((time.monotonic() - start) * 1000)

        if result.get("error") == "insufficient_credits":
            await wa_client.send_text(
                msg.chat_id,
                "💳 Créditos insuficientes.\nDigite /planos para ver os planos disponíveis.",
            )
            return

        await wa_client.send_text(
            msg.chat_id, format_research_response(result["response"])
        )
        log.info(
            "wa_research_done",
            chat_id=msg.chat_id[:12],
            latency_ms=latency_ms,
            cache_hit=result.get("cache_hit"),
        )
    except Exception:
        log.exception("wa_research_error", chat_id=msg.chat_id[:12])
        await wa_client.send_text(msg.chat_id, format_error("Erro ao processar. Tente novamente."))


async def _handle_study(msg: IncomingMessage, raw_query: str, mode: StudyMode) -> None:
    query = clean(raw_query)
    if not query:
        await wa_client.send_text(msg.chat_id, format_error("Mensagem inválida ou muito curta."))
        return

    mode_labels = {
        StudyMode.STUDY_20_80: "Revisão 20/80",
        StudyMode.DEEP_DIVE: "Deep Dive",
        StudyMode.CLINICAL_CASE: "Caso Clínico",
    }
    log.info("wa_study_request", chat_id=msg.chat_id[:12], mode=mode.value, query_len=len(query))
    await wa_client.send_text(msg.chat_id, format_study_typing(query[:40], mode_labels[mode]))
    start = time.monotonic()

    try:
        from resusbot.study.service import study_service

        result = await study_service.handle(
            query=query,
            telegram_id=msg.user_int_id,
            mode_override=mode.value,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        if result.get("error"):
            await wa_client.send_text(msg.chat_id, format_error(str(result["response"])))
            return

        response = result["response"]
        if isinstance(response, PedagogicalResponse):
            for message_part in format_pedagogical_response(response):
                await wa_client.send_text(msg.chat_id, message_part)
        else:
            await wa_client.send_text(msg.chat_id, str(response)[:4096])

        log.info(
            "wa_study_done",
            chat_id=msg.chat_id[:12],
            latency_ms=latency_ms,
            mode=mode.value,
        )
    except Exception:
        log.exception("wa_study_error", chat_id=msg.chat_id[:12])
        await wa_client.send_text(msg.chat_id, format_error("Erro ao processar. Tente novamente."))


def _help_text() -> str:
    return (
        "👋 Olá! Sou o *ResusBot*, especializado em medicina de emergência.\n\n"
        "📚 *Comandos disponíveis:*\n"
        "• /search <query> — pesquisa artigo científico\n"
        "• /study <tema>  — revisão 20/80 focada\n"
        "• /deep <tema>   — deep dive completo + fontes externas\n"
        "• /case <caso>   — caso clínico com raciocínio socrático\n"
        "• /help          — esta mensagem\n\n"
        "💡 *Exemplos:*\n"
        "/study sepse\n"
        "/deep choque obstrutivo\n"
        "/case paciente 45 anos, dor torácica, PA 80/50\n"
        "ROX index prediction intubation\n\n"
        "_ℹ️ Conteúdo informativo. Não substitui julgamento clínico._"
    )
