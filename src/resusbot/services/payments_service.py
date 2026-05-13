"""
Serviço de pagamentos — abstração `PaymentProvider` + implementação Mercado Pago.

Fluxo:
1. `create_checkout(user, plan)` → cria `Payment(status=pending)` + retorna URL
   de checkout do MP (PIX + cartão + boleto).
2. MP envia webhook a `/payments/webhook/mercadopago` quando o pagamento muda.
3. `process_webhook_event(provider, payload, signature)` valida assinatura,
   garante idempotência via `Payment.provider_event_id`, credita o usuário e
   cria/renova `Subscription`.
"""
from __future__ import annotations

import hashlib
import hmac
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from resusbot.config import settings
from resusbot.db.models import Payment, Plan, Subscription, User
from resusbot.services import credits_service

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    async def create_preference(self, payment: Payment, plan: Plan, user: User) -> dict[str, Any]:
        ...

    @abstractmethod
    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        ...

    @abstractmethod
    def parse_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Retorna dict normalizado:
        {
            "event_id": str,
            "payment_ref": str,
            "status": "paid" | "failed" | "refunded" | "disputed" | "pending",
            "amount_brl_cents": int | None,
            "raw": dict,
        }
        """
        ...


class MercadoPagoProvider(PaymentProvider):
    name = "mercadopago"

    def __init__(self) -> None:
        self._sdk = None

    def _get_sdk(self) -> Any:
        if self._sdk is None:
            try:
                import mercadopago  # type: ignore[import-untyped]
                self._sdk = mercadopago.SDK(settings.mp_access_token)
            except Exception as e:
                log.warning("mp_sdk_init_error", error=str(e))
                self._sdk = None
        return self._sdk

    async def create_preference(self, payment: Payment, plan: Plan, user: User) -> dict[str, Any]:
        sdk = self._get_sdk()
        if sdk is None:
            return {"checkout_url": "", "preference_id": None}

        preference_data = {
            "items": [
                {
                    "title": f"ResusBot — {plan.name}",
                    "description": f"{plan.monthly_credits} créditos válidos por {plan.validity_days} dias",
                    "quantity": 1,
                    "unit_price": plan.price_brl_cents / 100,
                    "currency_id": "BRL",
                }
            ],
            "external_reference": f"payment:{payment.id}",
            "notification_url": settings.mp_notification_url or None,
            "back_urls": {
                "success": settings.mp_return_url or "https://t.me/",
                "failure": settings.mp_return_url or "https://t.me/",
                "pending": settings.mp_return_url or "https://t.me/",
            },
            "auto_return": "approved",
            "payment_methods": {
                "excluded_payment_types": [],
                "installments": 6,
            },
            "metadata": {
                "user_id": user.id,
                "telegram_id": user.telegram_id,
                "plan_slug": plan.slug,
                "payment_id": payment.id,
            },
        }
        try:
            result = sdk.preference().create(preference_data)
            response = result.get("response", {})
            checkout_url = response.get("init_point") or response.get("sandbox_init_point", "")
            preference_id = response.get("id")
            return {"checkout_url": checkout_url, "preference_id": preference_id}
        except Exception as e:
            log.exception("mp_create_preference_error", error=str(e))
            return {"checkout_url": "", "preference_id": None}

    def verify_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """
        Valida o header `x-signature` do MP usando HMAC SHA-256.
        Em sandbox/dev, permite passar se MP_WEBHOOK_SECRET=changeme.
        """
        if settings.mp_webhook_secret in ("", "changeme") and not settings.is_production:
            return True

        signature_header = headers.get("x-signature") or headers.get("X-Signature", "")
        request_id = headers.get("x-request-id") or headers.get("X-Request-Id", "")
        if not signature_header:
            return False

        parts = {}
        for item in signature_header.split(","):
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip()] = v.strip()
        ts = parts.get("ts", "")
        v1 = parts.get("v1", "")
        if not ts or not v1:
            return False

        manifest = f"id:{request_id};request-id:{request_id};ts:{ts};".encode()
        expected = hmac.new(
            settings.mp_webhook_secret.encode(), manifest, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, v1)

    def parse_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        status_raw = (payload.get("status") or "").lower()
        status_map = {
            "approved": "paid",
            "authorized": "paid",
            "in_process": "pending",
            "pending": "pending",
            "rejected": "failed",
            "cancelled": "failed",
            "refunded": "refunded",
            "charged_back": "disputed",
        }
        return {
            "event_id": str(payload.get("id") or payload.get("data", {}).get("id", "")),
            "payment_ref": str(payload.get("id", "")),
            "status": status_map.get(status_raw, status_raw or "pending"),
            "amount_brl_cents": int((payload.get("transaction_amount") or 0) * 100) or None,
            "external_reference": payload.get("external_reference"),
            "raw": payload,
        }


class PaymentsService:
    def __init__(self) -> None:
        self.providers: dict[str, PaymentProvider] = {
            "mercadopago": MercadoPagoProvider(),
        }

    def get_provider(self, name: str = "mercadopago") -> PaymentProvider:
        return self.providers[name]

    async def create_checkout(
        self, session: AsyncSession, user_id: int, plan: Plan
    ) -> dict[str, Any] | None:
        user_result = await session.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            return None

        # Cria Payment(pending) e gera preference no MP
        payment = Payment(
            user_id=user_id,
            plan_id=plan.id,
            amount_brl_cents=plan.price_brl_cents,
            currency="BRL",
            status="pending",
            provider="mercadopago",
        )
        session.add(payment)
        await session.flush()

        provider = self.get_provider("mercadopago")
        result = await provider.create_preference(payment, plan, user)
        payment.checkout_url = result.get("checkout_url")
        payment.provider_payment_ref = result.get("preference_id")
        await session.commit()
        await session.refresh(payment)

        return {
            "checkout_url": payment.checkout_url,
            "payment_id": payment.id,
            "preference_id": result.get("preference_id"),
        }

    async def process_webhook_event(
        self,
        session: AsyncSession,
        provider_name: str,
        raw_body: bytes,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Processa um webhook idempotente. Retorna dict de status."""
        provider = self.get_provider(provider_name)
        if not provider.verify_signature(raw_body, headers):
            log.warning("webhook_invalid_signature", provider=provider_name)
            return {"status": "invalid_signature"}

        # MP envia notification topic. Para 'payment', precisamos consultar a API
        topic = payload.get("type") or payload.get("topic")
        if topic == "payment":
            payment_id_raw = (payload.get("data") or {}).get("id") or payload.get("id")
            if not payment_id_raw:
                return {"status": "missing_id"}
            payment_data = await self._fetch_payment_details(provider, str(payment_id_raw))
            if not payment_data:
                return {"status": "fetch_failed"}
        else:
            payment_data = payload

        event = provider.parse_event(payment_data)
        event_id = event["event_id"]
        if not event_id:
            return {"status": "missing_event_id"}

        # Idempotência: tenta marcar payment com event_id; se já existe, ignora
        external_ref = event.get("external_reference") or ""
        payment = None
        if external_ref.startswith("payment:"):
            payment_db_id = int(external_ref.split(":", 1)[1])
            payment_result = await session.execute(
                select(Payment).where(Payment.id == payment_db_id)
            )
            payment = payment_result.scalar_one_or_none()

        if payment is None:
            log.warning("webhook_payment_not_found", external_ref=external_ref)
            return {"status": "payment_not_found"}

        if payment.provider_event_id == event_id:
            log.info("webhook_idempotent_skip", event_id=event_id)
            return {"status": "already_processed"}

        try:
            payment.provider_event_id = event_id
            payment.provider_payment_ref = event["payment_ref"]
            payment.status = event["status"]
            payment.raw_payload = event["raw"]
            if event["status"] == "paid":
                payment.paid_at = datetime.now(timezone.utc)

            await session.commit()
        except IntegrityError:
            await session.rollback()
            log.info("webhook_idempotent_db", event_id=event_id)
            return {"status": "already_processed"}

        if event["status"] == "paid":
            await self._on_payment_paid(session, payment)
        elif event["status"] == "refunded":
            await self._on_payment_refunded(session, payment)

        return {"status": "ok", "payment_status": event["status"]}

    async def _fetch_payment_details(self, provider: PaymentProvider, payment_id: str) -> dict[str, Any] | None:
        """Consulta detalhes do pagamento via API MP."""
        if not isinstance(provider, MercadoPagoProvider):
            return None
        sdk = provider._get_sdk()
        if sdk is None:
            return None
        try:
            result = sdk.payment().get(payment_id)
            return result.get("response")  # type: ignore[no-any-return]
        except Exception as e:
            log.warning("mp_fetch_payment_error", error=str(e), payment_id=payment_id)
            return None

    async def _on_payment_paid(self, session: AsyncSession, payment: Payment) -> None:
        plan_result = await session.execute(select(Plan).where(Plan.id == payment.plan_id))
        plan = plan_result.scalar_one_or_none()
        if not plan:
            return

        # Credita
        expires_at = datetime.now(timezone.utc) + timedelta(days=plan.validity_days)
        await credits_service.credit(
            session,
            user_id=payment.user_id,
            amount=plan.monthly_credits,
            reason="purchase",
            payment_id=payment.id,
            expires_at=expires_at,
        )

        # Cria/atualiza subscription
        sub_result = await session.execute(
            select(Subscription)
            .where(Subscription.user_id == payment.user_id, Subscription.status == "active")
            .order_by(Subscription.current_period_end.desc())
        )
        existing = sub_result.scalars().first()
        period_end = datetime.now(timezone.utc) + timedelta(days=plan.validity_days)
        if existing:
            existing.plan_id = plan.id
            existing.current_period_end = period_end
            existing.auto_renew = True
            existing.updated_at = datetime.now(timezone.utc)
        else:
            session.add(Subscription(
                user_id=payment.user_id,
                plan_id=plan.id,
                status="active",
                current_period_end=period_end,
                auto_renew=True,
                provider="mercadopago",
                provider_subscription_ref=payment.provider_payment_ref,
            ))

        # Atualiza user.current_plan_id
        user_result = await session.execute(select(User).where(User.id == payment.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.current_plan_id = plan.id

        await session.commit()
        log.info("payment_paid", payment_id=payment.id, user_id=payment.user_id, credits=plan.monthly_credits)

        # Notifica o usuário via Telegram (fire-and-forget)
        if user:
            await _notify_payment_confirmed(user.telegram_id, plan)

    async def _on_payment_refunded(self, session: AsyncSession, payment: Payment) -> None:
        plan_result = await session.execute(select(Plan).where(Plan.id == payment.plan_id))
        plan = plan_result.scalar_one_or_none()
        if not plan:
            return

        # Debita somente o que ainda resta (protege contra saldo negativo)
        from resusbot.services.credits_service import _get_or_create_balance
        bal = await _get_or_create_balance(session, payment.user_id)
        amount_to_debit = min(plan.monthly_credits, bal.balance)
        if amount_to_debit <= 0:
            log.info("payment_refunded_no_balance", payment_id=payment.id, user_id=payment.user_id)
            return

        await credits_service.credit(
            session,
            user_id=payment.user_id,
            amount=-amount_to_debit,
            reason="refund",
            payment_id=payment.id,
        )
        log.info("payment_refunded", payment_id=payment.id, user_id=payment.user_id, debited=amount_to_debit)


async def _notify_payment_confirmed(telegram_id: int, plan: Plan) -> None:
    """Envia push Telegram confirmando pagamento e saldo atualizado."""
    try:
        from resusbot.config import settings
        from telegram import Bot
        from telegram.constants import ParseMode

        if not settings.telegram_bot_token:
            return
        bot = Bot(token=settings.telegram_bot_token)
        msg = (
            f"✅ *Pagamento confirmado\\!*\n\n"
            f"Plano: *{plan.name}*\n"
            f"Créditos adicionados: `{plan.monthly_credits}`\n"
            f"Validade: {plan.validity_days} dias\n\n"
            f"Use /saldo para conferir seu saldo atualizado\\.\n"
            f"_Boas pesquisas\\! 🔬_"
        )
        await bot.send_message(chat_id=telegram_id, text=msg, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        log.warning("payment_notify_error", telegram_id=telegram_id, error=str(e))


payments_service = PaymentsService()
