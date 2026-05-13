"""
Serviço de gestão de créditos.

Regra de cobrança: 1 crédito é consumido se a busca retornou pelo menos 1 artigo
com `pdf_url` válido OU `oa_status` aberto. Cache hits COM PDF também consomem
(margem extra — custo Groq zero). Erros, respostas vazias e resultados sem PDF
não consomem.

Quota gratuita mensal: `settings.free_monthly_credits` (default 10). Reseta no
primeiro dia do mês (UTC-3 / America/Sao_Paulo). Créditos comprados expiram em
`settings.credit_validity_days` (default 60).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from resusbot.config import settings
from resusbot.db.models import CreditBalance, CreditTransaction, Plan, Subscription, User

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass
class BalanceInfo:
    balance: int
    monthly_quota: int
    monthly_quota_used: int
    monthly_quota_remaining: int
    quota_resets_at: datetime
    plan_slug: str | None
    plan_name: str | None
    subscription_expires_at: datetime | None


def _next_month_reset(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    if now.month == 12:
        return now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


async def _get_or_create_balance(session: AsyncSession, user_id: int) -> CreditBalance:
    result = await session.execute(select(CreditBalance).where(CreditBalance.user_id == user_id))
    bal = result.scalar_one_or_none()
    if bal is None:
        bal = CreditBalance(
            user_id=user_id,
            balance=0,
            monthly_quota_used=0,
            quota_resets_at=_next_month_reset(),
        )
        session.add(bal)
        await session.flush()
    return bal


async def _maybe_reset_quota(bal: CreditBalance) -> None:
    """Reseta quota mensal se passou da data de reset."""
    now = datetime.now(timezone.utc)
    quota_resets = bal.quota_resets_at
    if quota_resets.tzinfo is None:
        quota_resets = quota_resets.replace(tzinfo=timezone.utc)
    if now >= quota_resets:
        bal.monthly_quota_used = 0
        bal.quota_resets_at = _next_month_reset(now)


async def has_credits(session: AsyncSession, user_id: int) -> bool:
    """True se o usuário pode realizar 1 busca cobrável."""
    bal = await _get_or_create_balance(session, user_id)
    await _maybe_reset_quota(bal)

    free_quota = settings.free_monthly_credits
    if bal.monthly_quota_used < free_quota:
        return True
    if bal.balance > 0:
        return True
    return False


async def check_balance(session: AsyncSession, user_id: int) -> BalanceInfo:
    bal = await _get_or_create_balance(session, user_id)
    await _maybe_reset_quota(bal)
    await session.commit()

    user_result = await session.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()

    plan_slug: str | None = None
    plan_name: str | None = None
    expires_at: datetime | None = None
    if user and user.current_plan_id:
        plan_result = await session.execute(select(Plan).where(Plan.id == user.current_plan_id))
        plan = plan_result.scalar_one_or_none()
        if plan:
            plan_slug = plan.slug
            plan_name = plan.name
        sub_result = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.status == "active")
            .order_by(Subscription.current_period_end.desc())
        )
        sub = sub_result.scalars().first()
        if sub:
            expires_at = sub.current_period_end

    free_quota = settings.free_monthly_credits
    return BalanceInfo(
        balance=bal.balance,
        monthly_quota=free_quota,
        monthly_quota_used=bal.monthly_quota_used,
        monthly_quota_remaining=max(0, free_quota - bal.monthly_quota_used),
        quota_resets_at=bal.quota_resets_at,
        plan_slug=plan_slug,
        plan_name=plan_name,
        subscription_expires_at=expires_at,
    )


async def consume(
    session: AsyncSession,
    user_id: int,
    search_log_id: int | None = None,
) -> bool:
    """
    Consome 1 crédito. Preferência: usar quota gratuita primeiro, depois balance pago.
    Retorna True se consumiu, False se sem créditos.
    """
    bal = await _get_or_create_balance(session, user_id)
    await _maybe_reset_quota(bal)

    free_quota = settings.free_monthly_credits
    if bal.monthly_quota_used < free_quota:
        bal.monthly_quota_used += 1
        balance_after = bal.balance
        tx_reason = "consume"
    elif bal.balance > 0:
        bal.balance -= 1
        balance_after = bal.balance
        tx_reason = "consume"
    else:
        log.warning("consume_no_credits", user_id=user_id)
        return False

    session.add(CreditTransaction(
        user_id=user_id,
        delta=-1,
        reason=tx_reason,
        search_log_id=search_log_id,
        balance_after=balance_after,
    ))
    await session.commit()
    log.info("credit_consumed", user_id=user_id, balance_after=balance_after, search_log_id=search_log_id)
    return True


async def credit(
    session: AsyncSession,
    user_id: int,
    amount: int,
    reason: str,
    payment_id: int | None = None,
    expires_at: datetime | None = None,
) -> CreditTransaction:
    """Adiciona créditos ao balance. Usado por purchase, refund, bonus."""
    bal = await _get_or_create_balance(session, user_id)
    bal.balance += amount

    if expires_at is None and reason == "purchase":
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.credit_validity_days)

    tx = CreditTransaction(
        user_id=user_id,
        delta=amount,
        reason=reason,
        payment_id=payment_id,
        expires_at=expires_at,
        balance_after=bal.balance,
    )
    session.add(tx)
    await session.commit()
    log.info("credit_added", user_id=user_id, amount=amount, reason=reason, balance=bal.balance)
    return tx


async def refund(
    session: AsyncSession,
    user_id: int,
    search_log_id: int,
    reason: str = "refund",
) -> CreditTransaction:
    """Devolve 1 crédito ao saldo do usuário."""
    return await credit(session, user_id, amount=1, reason=reason)


async def expire_old_credits(session: AsyncSession) -> int:
    """
    Verifica transações de purchase cujo `expires_at` passou e ainda não foram expiradas.
    Cria transação compensatória de expiração. Retorna número de usuários afetados.

    Heurística simples: por usuário, soma transações `purchase` expiradas vs `expiration`
    já registradas. Diferença vira nova `expiration` que zera balance até esse limite.
    """
    now = datetime.now(timezone.utc)
    affected = 0
    user_ids_result = await session.execute(
        select(CreditTransaction.user_id)
        .where(
            CreditTransaction.reason == "purchase",
            CreditTransaction.expires_at.is_not(None),
            CreditTransaction.expires_at <= now,
        )
        .distinct()
    )
    user_ids = [row[0] for row in user_ids_result]

    for uid in user_ids:
        purchases_result = await session.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.user_id == uid,
                CreditTransaction.reason == "purchase",
                CreditTransaction.expires_at.is_not(None),
                CreditTransaction.expires_at <= now,
            )
        )
        purchases = list(purchases_result.scalars())
        expirations_result = await session.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.user_id == uid,
                CreditTransaction.reason == "expiration",
            )
        )
        already_expired_total = -sum(t.delta for t in expirations_result.scalars())
        total_expired_credits = sum(t.delta for t in purchases)
        to_expire = total_expired_credits - already_expired_total

        if to_expire <= 0:
            continue

        bal = await _get_or_create_balance(session, uid)
        consumed_so_far = max(0, total_expired_credits - bal.balance)
        actual_expire = max(0, to_expire - consumed_so_far)
        if actual_expire <= 0:
            continue
        actual_expire = min(actual_expire, bal.balance)
        if actual_expire == 0:
            continue

        bal.balance -= actual_expire
        session.add(CreditTransaction(
            user_id=uid,
            delta=-actual_expire,
            reason="expiration",
            balance_after=bal.balance,
        ))
        affected += 1
        log.info("credits_expired", user_id=uid, amount=actual_expire)

    await session.commit()
    return affected


async def reset_all_monthly_quotas(session: AsyncSession) -> int:
    """Reseta quota gratuita de todos usuários cujo `quota_resets_at` passou."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(CreditBalance).where(CreditBalance.quota_resets_at <= now)
    )
    count = 0
    for bal in result.scalars():
        bal.monthly_quota_used = 0
        bal.quota_resets_at = _next_month_reset(now)
        session.add(CreditTransaction(
            user_id=bal.user_id,
            delta=0,
            reason="monthly_reset",
            balance_after=bal.balance,
        ))
        count += 1
    await session.commit()
    log.info("monthly_quotas_reset", count=count)
    return count


def is_billable(payload: dict[str, Any]) -> bool:
    """
    Define se um payload de resposta é cobrável.
    Regra: pelo menos 1 artigo com `pdf_url` não-nulo OU OA confirmado.
    Considera tanto cache hit quanto cache miss.
    """
    articles_count = payload.get("articles_count", 0)
    if articles_count == 0:
        return False
    has_pdf_flag = payload.get("has_pdf")
    if has_pdf_flag is not None:
        return bool(has_pdf_flag)
    # Heurística: verifica no texto se há link de download
    response = payload.get("response", "") or ""
    return any(token in response.lower() for token in ("pdf", "doi.org", "europepmc", "pubmed", "open access"))
