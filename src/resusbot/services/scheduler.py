"""
Scheduler de jobs recorrentes (APScheduler async).

Jobs:
- monthly_quota_reset: diariamente às 00:05 — reseta quota gratuita de usuários
  cujo `quota_resets_at` passou.
- credit_expiration: diariamente às 03:00 — expira créditos comprados há > N dias.
- subscription_expiration: diariamente às 03:30 — marca subscriptions vencidas.
"""
from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _job_reset_monthly_quotas() -> None:
    from resusbot.db.session import get_session_context
    from resusbot.services import credits_service

    try:
        async with get_session_context() as session:
            count = await credits_service.reset_all_monthly_quotas(session)
        log.info("scheduler_quotas_reset", count=count)
    except Exception as e:
        log.exception("scheduler_quotas_reset_error", error=str(e))


async def _job_expire_credits() -> None:
    from resusbot.db.session import get_session_context
    from resusbot.services import credits_service

    try:
        async with get_session_context() as session:
            affected = await credits_service.expire_old_credits(session)
        log.info("scheduler_credits_expired", users_affected=affected)
    except Exception as e:
        log.exception("scheduler_credits_expired_error", error=str(e))


async def _job_expire_subscriptions() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from resusbot.db.models import Subscription
    from resusbot.db.session import get_session_context

    try:
        async with get_session_context() as session:
            now = datetime.now(timezone.utc)
            result = await session.execute(
                select(Subscription).where(
                    Subscription.status == "active",
                    Subscription.current_period_end <= now,
                    Subscription.auto_renew.is_(False),
                )
            )
            count = 0
            for sub in result.scalars():
                sub.status = "expired"
                count += 1
            await session.commit()
        log.info("scheduler_subs_expired", count=count)
    except Exception as e:
        log.exception("scheduler_subs_expired_error", error=str(e))


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler(timezone="America/Sao_Paulo")

    # Reset diário às 00:05 (verifica usuários com quota_resets_at no passado)
    _scheduler.add_job(
        _job_reset_monthly_quotas,
        CronTrigger(hour=0, minute=5),
        id="reset_monthly_quotas",
        replace_existing=True,
    )

    # Expiração de créditos diária às 03:00
    _scheduler.add_job(
        _job_expire_credits,
        CronTrigger(hour=3, minute=0),
        id="expire_credits",
        replace_existing=True,
    )

    # Expiração de assinaturas diária às 03:30
    _scheduler.add_job(
        _job_expire_subscriptions,
        CronTrigger(hour=3, minute=30),
        id="expire_subscriptions",
        replace_existing=True,
    )

    _scheduler.start()
    log.info("scheduler_started", jobs=["reset_monthly_quotas", "expire_credits", "expire_subscriptions"])


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        log.info("scheduler_stopped")
