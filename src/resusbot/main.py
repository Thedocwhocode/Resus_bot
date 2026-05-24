"""
Ponto de entrada da aplicação.
FastAPI + lifespan que inicia DB, Redis e o bot Telegram (polling ou webhook).
"""

import secrets
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from telegram import Update

from resusbot.config import settings
from resusbot.dashboard.routes import router as dashboard_router
from resusbot.logging_setup import setup_logging
from resusbot.security.rate_limit import limiter

setup_logging(settings.log_level)
log: structlog.stdlib.BoundLogger = structlog.get_logger("resusbot.main")

_bot_app = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _bot_app
    log.info("resusbot_starting", mode=settings.telegram_mode, env=settings.app_env)

    # Aplica migrations (cria schema na primeira execução)
    from resusbot.db.session import run_migrations

    await run_migrations()
    log.info("database_ready")

    # Seed de categorias e planos de billing
    from resusbot.scripts.seed_categories import seed_categories
    from resusbot.scripts.seed_plans import seed_plans

    await seed_categories()
    await seed_plans()

    # Inicia scheduler de jobs (reset mensal, expiração de créditos)
    from resusbot.services.scheduler import start_scheduler, stop_scheduler

    start_scheduler()

    # Constrói aplicação Telegram
    from resusbot.telegram.bot import build_application, setup_webhook, start_polling

    _bot_app = build_application()

    if settings.telegram_mode == "polling":
        await start_polling(_bot_app)
        log.info("telegram_polling_started")
    else:
        await setup_webhook(_bot_app)
        log.info("telegram_webhook_configured")

    yield

    # Shutdown
    from resusbot.cache.redis_client import close_redis
    from resusbot.telegram.bot import stop_polling
    from resusbot.tools.base import close_http_client

    if settings.telegram_mode == "polling" and _bot_app:
        await stop_polling(_bot_app)

    stop_scheduler()
    await close_http_client()
    await close_redis()
    log.info("resusbot_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="ResusBot API",
        description="Bot Telegram para pesquisa de artigos científicos médicos.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    # CORS restrito ao domínio do dashboard; em dev, permite apenas localhost
    origins = (
        [settings.dashboard_domain]
        if settings.dashboard_domain
        else ["http://localhost:8000", "http://127.0.0.1:8000"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # Security headers
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next: Callable[..., Any]) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    # Rate limit exceeded handler
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
        return Response(content="Rate limit exceeded", status_code=429)

    # ── Rotas ─────────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health() -> dict:
        from resusbot.cache.redis_client import ping_redis
        from resusbot.db.session import engine

        try:
            async with engine.connect() as conn:
                await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
        redis_ok = await ping_redis()
        status = "ok" if (db_ok and redis_ok) else "degraded"
        return {"status": status, "db": db_ok, "redis": redis_ok}

    @app.get("/ready")
    async def ready() -> dict:
        return {"status": "ok", "bot": settings.telegram_mode}

    # Telegram webhook endpoint
    @app.post("/telegram/webhook/{secret_token}")
    async def telegram_webhook(secret_token: str, request: Request) -> dict:
        if not secrets.compare_digest(secret_token, settings.telegram_webhook_secret):
            raise HTTPException(status_code=403, detail="Invalid secret")
        # Valida também o header enviado pelo Telegram
        tg_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secrets.compare_digest(tg_token, settings.telegram_webhook_secret):
            raise HTTPException(status_code=403, detail="Invalid token header")
        if _bot_app is None:
            raise HTTPException(status_code=503, detail="Bot not ready")
        data = await request.json()
        update = Update.de_json(data, _bot_app.bot)
        await _bot_app.process_update(update)
        return {"ok": True}

    # Dashboard
    app.include_router(dashboard_router)

    # Payments (webhook MP + landing)
    from resusbot.payments.routes import router as payments_router

    app.include_router(payments_router)

    # WhatsApp (open-wa sidecar webhook)
    from resusbot.whatsapp.routes import router as whatsapp_router

    app.include_router(whatsapp_router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "resusbot.main:app", host="0.0.0.0", port=settings.port, reload=not settings.is_production
    )
