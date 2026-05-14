"""
Handlers Telegram para a camada de billing/SaaS:
- /saldo, /planos, /historico, /cancelar
- CallbackQueryHandler para botões inline (compra de plano, confirmação cancelar)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import desc, select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode

from resusbot.security.sanitize import escape_markdown_v2

if TYPE_CHECKING:
    from telegram.ext import ContextTypes

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def _format_price(cents: int) -> str:
    return f"R$ {cents / 100:.2f}".replace(".", ",")


async def saldo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        from resusbot.db.repository import upsert_user
        from resusbot.db.session import get_session_context
        from resusbot.services import credits_service

        async with get_session_context() as session:
            user = await upsert_user(
                session,
                update.effective_user.id,
                update.effective_user.username,
                increment_count=False,
            )
            info = await credits_service.check_balance(session, user.id)

        plan_line = (
            f"📦 Plano: *{escape_markdown_v2(info.plan_name)}*"
            if info.plan_name
            else "📦 Plano: *Gratuito*"
        )
        expires_line = ""
        if info.subscription_expires_at:
            expires_line = f"\n📅 Renova em: `{info.subscription_expires_at.strftime('%d/%m/%Y')}`"
        msg = (
            f"💳 *Seu saldo*\n\n"
            f"{plan_line}\n"
            f"💰 Créditos pagos: `{info.balance}`\n"
            f"🎁 Quota grátis: `{info.monthly_quota_remaining}/{info.monthly_quota}`"
            f"{expires_line}\n\n"
            f"Use /planos para adquirir mais créditos\\."
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        log.warning("saldo_handler_error", error=str(e))
        await update.message.reply_text(
            "Não foi possível consultar seu saldo no momento\\.", parse_mode=ParseMode.MARKDOWN_V2
        )


async def planos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    try:
        from resusbot.db.models import Plan
        from resusbot.db.session import get_session_context

        async with get_session_context() as session:
            result = await session.execute(
                select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_brl_cents)
            )
            plans = list(result.scalars())

        lines = ["💎 *Planos disponíveis*\n"]
        buttons = []
        for p in plans:
            if p.is_free:
                lines.append(
                    f"\n🎁 *{escape_markdown_v2(p.name)}*: `{p.monthly_credits}` créditos/mês — grátis para sempre"
                )
                continue
            price = escape_markdown_v2(_format_price(p.price_brl_cents))
            per_credit = escape_markdown_v2(_format_price(p.price_brl_cents // p.monthly_credits))
            lines.append(
                f"\n📦 *{escape_markdown_v2(p.name)}*: `{p.monthly_credits}` créditos por {price}"
                f"\n   ↳ {per_credit} por crédito, válido por {p.validity_days} dias"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"💳 Assinar {p.name} — {_format_price(p.price_brl_cents)}",
                        callback_data=f"plan:buy:{p.slug}",
                    )
                ]
            )

        lines.append(
            "\n\nℹ️ _Cada crédito \\= 1 busca bem\\-sucedida com link de PDF\\._"
            "\n_Buscas sem link ou com erro não consomem crédito\\._"
        )
        kb = InlineKeyboardMarkup(buttons) if buttons else None
        await update.message.reply_text(
            "".join(lines),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb,
        )
    except Exception as e:
        log.warning("planos_handler_error", error=str(e))
        await update.message.reply_text(
            "Não foi possível listar os planos\\.", parse_mode=ParseMode.MARKDOWN_V2
        )


async def historico_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        from resusbot.db.models import CreditTransaction
        from resusbot.db.repository import upsert_user
        from resusbot.db.session import get_session_context

        async with get_session_context() as session:
            user = await upsert_user(
                session,
                update.effective_user.id,
                update.effective_user.username,
                increment_count=False,
            )
            result = await session.execute(
                select(CreditTransaction)
                .where(CreditTransaction.user_id == user.id)
                .order_by(desc(CreditTransaction.created_at))
                .limit(10)
            )
            txs = list(result.scalars())

        if not txs:
            await update.message.reply_text(
                "Nenhuma transação encontrada ainda\\.", parse_mode=ParseMode.MARKDOWN_V2
            )
            return

        emoji_by_reason = {
            "purchase": "🛒",
            "consume": "🔍",
            "refund": "↩️",
            "bonus": "🎁",
            "monthly_reset": "🔄",
            "expiration": "⏰",
        }

        lines = ["📜 *Histórico \\(últimas 10\\)*\n"]
        for tx in txs:
            ts = tx.created_at.strftime("%d/%m %H:%M")
            sign = "\\+" if tx.delta > 0 else ""
            emoji = emoji_by_reason.get(tx.reason, "•")
            reason_label = escape_markdown_v2(
                {
                    "purchase": "compra",
                    "consume": "busca",
                    "refund": "reembolso",
                    "bonus": "bônus",
                    "monthly_reset": "reset mensal",
                    "expiration": "expiração",
                }.get(tx.reason, tx.reason)
            )
            lines.append(
                f"\n{emoji} `{ts}` — {reason_label}: `{sign}{tx.delta}` \\(saldo: `{tx.balance_after}`\\)"
            )

        await update.message.reply_text("".join(lines), parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        log.warning("historico_handler_error", error=str(e))
        await update.message.reply_text(
            "Não foi possível consultar seu histórico\\.", parse_mode=ParseMode.MARKDOWN_V2
        )


async def cancelar_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        from resusbot.db.models import Subscription
        from resusbot.db.repository import upsert_user
        from resusbot.db.session import get_session_context

        async with get_session_context() as session:
            user = await upsert_user(
                session,
                update.effective_user.id,
                update.effective_user.username,
                increment_count=False,
            )
            result = await session.execute(
                select(Subscription)
                .where(Subscription.user_id == user.id, Subscription.status == "active")
                .order_by(desc(Subscription.current_period_end))
            )
            sub = result.scalars().first()

            if not sub:
                await update.message.reply_text(
                    "Você não tem assinatura ativa para cancelar\\.",
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return

            sub.auto_renew = False
            sub.cancel_at = sub.current_period_end
            await session.commit()
            expires = sub.current_period_end.strftime("%d/%m/%Y")

        await update.message.reply_text(
            f"✅ Renovação automática cancelada\\.\n"
            f"Seus créditos permanecem ativos até `{expires}`\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        log.warning("cancelar_handler_error", error=str(e))
        await update.message.reply_text(
            "Não foi possível processar o cancelamento\\.", parse_mode=ParseMode.MARKDOWN_V2
        )


async def plan_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler para callbacks de botões inline:
    - `plan:list` → mostra lista de planos
    - `plan:buy:<slug>` → gera link de pagamento MP
    """
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return
    await query.answer()

    parts = query.data.split(":")
    if len(parts) < 2 or parts[0] != "plan":
        return

    if parts[1] == "list":
        # Reaproveita o conteúdo de /planos
        from resusbot.db.models import Plan
        from resusbot.db.session import get_session_context

        async with get_session_context() as session:
            result = await session.execute(
                select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_brl_cents)
            )
            plans = list(result.scalars())

        buttons = []
        lines = ["💎 *Planos disponíveis*\n"]
        for p in plans:
            if p.is_free:
                continue
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"💳 {p.name} — {_format_price(p.price_brl_cents)} ({p.monthly_credits} créditos)",
                        callback_data=f"plan:buy:{p.slug}",
                    )
                ]
            )
            price = escape_markdown_v2(_format_price(p.price_brl_cents))
            lines.append(
                f"\n📦 *{escape_markdown_v2(p.name)}*: `{p.monthly_credits}` créditos por {price}"
            )
        kb = InlineKeyboardMarkup(buttons) if buttons else None
        await query.edit_message_text(
            "".join(lines), parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb
        )
        return

    if len(parts) != 3 or parts[1] != "buy":
        return
    slug = parts[2]

    try:
        from resusbot.db.models import Plan
        from resusbot.db.repository import upsert_user
        from resusbot.db.session import get_session_context
        from resusbot.services.payments_service import payments_service

        async with get_session_context() as session:
            user = await upsert_user(
                session, update.effective_user.id, update.effective_user.username
            )
            plan_result = await session.execute(select(Plan).where(Plan.slug == slug))
            plan = plan_result.scalar_one_or_none()
            if not plan or plan.is_free:
                await query.edit_message_text(
                    "Plano inválido ou gratuito\\.", parse_mode=ParseMode.MARKDOWN_V2
                )
                return

            checkout = await payments_service.create_checkout(session, user_id=user.id, plan=plan)

        if not checkout or not checkout.get("checkout_url"):
            await query.edit_message_text(
                "⚠️ Falha ao gerar link de pagamento\\. Tente novamente em instantes\\.",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        url = checkout["checkout_url"]
        msg = (
            f"💳 *Pagamento — {escape_markdown_v2(plan.name)}*\n\n"
            f"Valor: *{escape_markdown_v2(_format_price(plan.price_brl_cents))}*\n"
            f"Créditos: `{plan.monthly_credits}` \\(válidos por {plan.validity_days} dias\\)\n\n"
            f"👇 Clique abaixo para concluir o pagamento via PIX, cartão ou boleto\\."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Pagar agora", url=url)]])
        await query.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb)

    except Exception as e:
        log.exception("plan_callback_error", error=str(e))
        await query.edit_message_text(
            "Erro ao processar pagamento\\. Tente novamente\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
