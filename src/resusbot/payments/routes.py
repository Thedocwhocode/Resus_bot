"""
Rotas HTTP de pagamentos.

- POST /payments/webhook/mercadopago — recebe webhook do MP (idempotente)
- GET  /payments/return — landing pós-checkout, redireciona para o bot
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from resusbot.config import settings
from resusbot.db.session import get_session_context
from resusbot.security.rate_limit import limiter
from resusbot.services.payments_service import payments_service

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/webhook/mercadopago")
@limiter.limit("60/minute")
async def mercadopago_webhook(request: Request) -> JSONResponse:
    raw_body = await request.body()
    try:
        payload: dict[str, Any] = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception as e:
        log.warning("webhook_invalid_json")
        raise HTTPException(status_code=400, detail="Invalid JSON") from e

    headers = {k.lower(): v for k, v in request.headers.items()}

    async with get_session_context() as session:
        result = await payments_service.process_webhook_event(
            session=session,
            provider_name="mercadopago",
            raw_body=raw_body,
            headers=headers,
            payload=payload,
        )

    status = result.get("status", "unknown")
    if status == "invalid_signature":
        raise HTTPException(status_code=403, detail="Invalid signature")

    # MP espera 200 OK em todos os outros casos (mesmo se ignorado por idempotência)
    return JSONResponse({"status": status}, status_code=200)


@router.get("/return", response_class=HTMLResponse)
async def payment_return(request: Request) -> HTMLResponse:
    """Landing simples pós-checkout. Redireciona para o bot Telegram."""
    raw_url = settings.mp_return_url or "https://t.me/"
    # Valida esquema para prevenir XSS via javascript: ou data: URIs
    bot_url = raw_url if raw_url.startswith(("https://", "http://")) else "https://t.me/"
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <title>Pagamento — ResusBot</title>
  <meta http-equiv="refresh" content="3; url={bot_url}">
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 600px; margin: 4rem auto; text-align: center; padding: 0 1rem; }}
    h1 {{ color: #1a73e8; }}
    .btn {{ background: #1a73e8; color: white; padding: 0.7rem 1.5rem; border-radius: 6px; text-decoration: none; display: inline-block; margin-top: 1rem; }}
  </style>
</head>
<body>
  <h1>✅ Pagamento recebido!</h1>
  <p>Seus créditos serão liberados automaticamente em alguns instantes.</p>
  <p>Volte ao Telegram para continuar pesquisando.</p>
  <a class="btn" href="{bot_url}">📱 Abrir ResusBot</a>
</body>
</html>"""
    return HTMLResponse(html)
