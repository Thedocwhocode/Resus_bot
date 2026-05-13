"""Queries agregadas para o dashboard de billing (MRR, churn, ARPU, etc.)."""
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from resusbot.db.models import (
    CreditTransaction,
    Payment,
    Plan,
    SearchLog,
    Subscription,
    User,
)

# Custo Groq por busca cobrável real (cache miss). Cache hits têm custo 0.
COST_GROQ_PER_MISS_BRL_CENTS = 3  # R$ 0,029 ≈ 3 centavos


async def get_billing_kpis(session: AsyncSession) -> dict[str, Any]:
    # MRR = soma dos planos das subscriptions ativas
    mrr_result = await session.execute(
        select(func.sum(Plan.price_brl_cents))
        .select_from(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.status == "active")
    )
    mrr_cents = mrr_result.scalar() or 0

    # Usuários totais e pagantes
    total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    paying_result = await session.execute(
        select(func.count(func.distinct(Subscription.user_id)))
        .where(Subscription.status == "active")
    )
    paying_users: int = paying_result.scalar() or 0

    arpu_cents = (mrr_cents / paying_users) if paying_users else 0

    # Conversão free → pago (últimos 90d)
    cutoff_90 = datetime.now(timezone.utc) - timedelta(days=90)
    new_users_result = await session.execute(
        select(func.count(User.id)).where(User.first_seen >= cutoff_90)
    )
    new_users = new_users_result.scalar() or 0

    paid_users_result = await session.execute(
        select(func.count(func.distinct(Payment.user_id)))
        .where(Payment.status == "paid", Payment.paid_at >= cutoff_90)
    )
    paid_users: int = paid_users_result.scalar() or 0
    conversion_rate = round((paid_users / new_users * 100), 1) if new_users else 0.0

    # Churn: assinaturas que viraram 'cancelled' ou 'expired' nos últimos 30d
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    churned_result = await session.execute(
        select(func.count(Subscription.id))
        .where(
            Subscription.status.in_(["cancelled", "expired"]),
            Subscription.updated_at >= cutoff_30,
        )
    )
    churned: int = churned_result.scalar() or 0
    churn_rate = round((churned / max(paying_users + churned, 1) * 100), 1)

    # Custo Groq do mês (cache miss)
    cutoff_month = datetime.now(timezone.utc) - timedelta(days=30)
    miss_result = await session.execute(
        select(func.count(SearchLog.id))
        .where(SearchLog.cache_hit.is_(False), SearchLog.created_at >= cutoff_month)
    )
    miss_count = miss_result.scalar() or 0
    groq_cost_cents = miss_count * COST_GROQ_PER_MISS_BRL_CENTS

    return {
        "mrr_brl": round(mrr_cents / 100, 2),
        "arpu_brl": round(arpu_cents / 100, 2),
        "paying_users": paying_users,
        "total_users": total_users,
        "conversion_rate": conversion_rate,
        "churn_rate": churn_rate,
        "groq_cost_brl": round(groq_cost_cents / 100, 2),
        "miss_count_30d": miss_count,
    }


async def get_subscribers(
    session: AsyncSession, plan_slug: str | None = None, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    stmt = (
        select(Subscription, Plan, User)
        .join(Plan, Plan.id == Subscription.plan_id)
        .join(User, User.id == Subscription.user_id)
        .order_by(desc(Subscription.current_period_end))
        .limit(limit)
    )
    if plan_slug:
        stmt = stmt.where(Plan.slug == plan_slug)
    if status:
        stmt = stmt.where(Subscription.status == status)

    rows = await session.execute(stmt)

    import hashlib

    out = []
    for sub, plan, user in rows:
        out.append({
            "telegram_id_hash": hashlib.sha256(str(user.telegram_id).encode()).hexdigest()[:12],
            "plan_name": plan.name,
            "status": sub.status,
            "started_at": sub.started_at.strftime("%d/%m/%Y"),
            "current_period_end": sub.current_period_end.strftime("%d/%m/%Y"),
            "auto_renew": sub.auto_renew,
            "price_brl": round(plan.price_brl_cents / 100, 2),
        })
    return out


async def get_revenue_timeseries(session: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    """Receita diária (paid payments) nos últimos N dias."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await session.execute(
        select(
            func.date(Payment.paid_at).label("day"),
            func.sum(Payment.amount_brl_cents).label("total"),
        )
        .where(Payment.status == "paid", Payment.paid_at >= cutoff)
        .group_by("day")
        .order_by("day")
    )
    return [
        {"day": row.day if isinstance(row.day, str) else row.day.isoformat(), "total_brl": round((row.total or 0) / 100, 2)}
        for row in rows
    ]
