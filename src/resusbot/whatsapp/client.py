"""
HTTP client that wraps the open-wa REST API for sending WhatsApp messages.

open-wa runs as a Docker sidecar that exposes:
  POST /sendText   — send plain text
  POST /sendImage  — send image with caption
  GET  /getStatus  — health check

All sends are fire-and-forget from the caller's perspective;
errors are logged but never raise so the pipeline never stalls.
"""

from __future__ import annotations

import structlog

from resusbot.config import settings
from resusbot.tools.base import get_http_client

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_MAX_MSG_CHARS = 4096  # WhatsApp single-message soft limit


async def send_text(chat_id: str, text: str) -> bool:
    """
    Send a plain-text WhatsApp message via the open-wa REST API.

    Args:
        chat_id: open-wa chat ID, e.g. "5511999999999@c.us"
        text: Message body (max 4096 chars; longer texts are split).

    Returns:
        True if the API accepted the request, False on any error.
    """
    if not settings.openwa_base_url:
        log.warning("openwa_not_configured")
        return False

    chunks = _split_message(text)
    client = get_http_client()
    base = settings.openwa_base_url.rstrip("/")

    for chunk in chunks:
        try:
            resp = await client.post(
                f"{base}/sendText",
                json={"chatId": chat_id, "text": chunk},
                headers=_auth_headers(),
                timeout=15.0,
            )
            resp.raise_for_status()
        except Exception:
            log.exception("openwa_send_failed", chat_id=chat_id[:12])
            return False

    return True


async def ping() -> bool:
    """Return True if the open-wa sidecar is reachable."""
    if not settings.openwa_base_url:
        return False
    try:
        client = get_http_client()
        resp = await client.get(
            f"{settings.openwa_base_url.rstrip('/')}/getStatus",
            headers=_auth_headers(),
            timeout=5.0,
        )
        return resp.status_code < 500
    except Exception:
        return False


def _auth_headers() -> dict[str, str]:
    """Optional API key header — configure in open-wa via WA_API_KEY."""
    if settings.openwa_api_key:
        return {"x-api-key": settings.openwa_api_key}
    return {}


def _split_message(text: str) -> list[str]:
    """Split long text into chunks that fit within WhatsApp limits."""
    if len(text) <= _MAX_MSG_CHARS:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:_MAX_MSG_CHARS])
        text = text[_MAX_MSG_CHARS:]
    return chunks
