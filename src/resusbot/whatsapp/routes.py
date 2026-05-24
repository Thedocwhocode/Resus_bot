"""
FastAPI router for the open-wa webhook endpoint.

open-wa POSTs all incoming events to:
  POST /whatsapp/webhook

A shared secret (WA_WEBHOOK_SECRET) is validated via the
X-WA-Webhook-Secret header that open-wa is configured to include.

Rate-limited at the same tier as the Telegram webhook (IP level).
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from resusbot.config import settings
from resusbot.security.rate_limit import limiter
from resusbot.whatsapp.handlers import dispatch, parse_openwa_payload

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.post("/webhook")
@limiter.limit("120/minute")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Receive and dispatch messages from the open-wa sidecar.

    Returns 200 immediately; message processing runs in a background task
    so open-wa doesn't time out waiting for the pipeline to finish.
    """
    # ── Validate shared secret ────────────────────────────────────────────────
    if settings.wa_webhook_secret:
        provided = request.headers.get("x-wa-webhook-secret", "")
        if not secrets.compare_digest(provided, settings.wa_webhook_secret):
            log.warning("wa_webhook_invalid_secret", ip=request.client.host if request.client else "?")
            raise HTTPException(status_code=403, detail="Invalid secret")

    # ── Parse payload ─────────────────────────────────────────────────────────
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    msg = parse_openwa_payload(payload)
    if msg is None:
        # Non-actionable event (QR, ack, group message, etc.)
        return JSONResponse({"ok": True, "skipped": True})

    log.info(
        "wa_webhook_received",
        event_type=payload.get("type"),
        chat_id=msg.chat_id[:12],
        body_len=len(msg.body),
    )

    # ── Dispatch in background so we return 200 fast ──────────────────────────
    background_tasks.add_task(_safe_dispatch, msg)
    return JSONResponse({"ok": True})


@router.get("/health")
async def whatsapp_health() -> dict:
    """Check if the open-wa sidecar is reachable."""
    from resusbot.whatsapp.client import ping

    ok = await ping()
    return {
        "openwa_reachable": ok,
        "openwa_url": settings.openwa_base_url or "not configured",
    }


async def _safe_dispatch(msg: object) -> None:
    try:
        await dispatch(msg)  # type: ignore[arg-type]
    except Exception:
        log.exception("wa_dispatch_unhandled")
