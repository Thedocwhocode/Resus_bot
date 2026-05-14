import pytest
import pytest_asyncio

from resusbot.scripts.seed_categories import seed_categories
from resusbot.scripts.seed_plans import seed_plans
from resusbot.services.payments_service import MercadoPagoProvider, payments_service


@pytest_asyncio.fixture(autouse=True)
async def seed(db_session):
    await seed_categories()
    await seed_plans()


def test_mp_parse_event_approved():
    provider = MercadoPagoProvider()
    payload = {
        "id": "MP-123",
        "status": "approved",
        "transaction_amount": 14.90,
        "external_reference": "payment:1",
    }
    event = provider.parse_event(payload)
    assert event["status"] == "paid"
    assert event["payment_ref"] == "MP-123"
    assert event["amount_brl_cents"] == 1490
    assert event["external_reference"] == "payment:1"


def test_mp_parse_event_rejected():
    provider = MercadoPagoProvider()
    event = provider.parse_event({"id": "MP-999", "status": "rejected"})
    assert event["status"] == "failed"


def test_mp_parse_event_refunded():
    provider = MercadoPagoProvider()
    event = provider.parse_event({"id": "MP-888", "status": "refunded"})
    assert event["status"] == "refunded"


def test_mp_signature_passes_in_dev_with_default_secret(monkeypatch):
    from resusbot.config import settings

    monkeypatch.setattr(settings, "mp_webhook_secret", "changeme")
    monkeypatch.setattr(settings, "app_env", "development")
    provider = MercadoPagoProvider()
    assert provider.verify_signature(b"{}", {}) is True


def test_mp_signature_fails_in_prod_without_header(monkeypatch):
    from resusbot.config import settings

    monkeypatch.setattr(settings, "mp_webhook_secret", "real_secret")
    monkeypatch.setattr(settings, "app_env", "production")
    provider = MercadoPagoProvider()
    assert provider.verify_signature(b"{}", {}) is False


@pytest.mark.asyncio
async def test_create_checkout_creates_pending_payment(db_session):
    from sqlalchemy import select

    from resusbot.db.models import Payment, Plan
    from resusbot.db.repository import upsert_user

    user = await upsert_user(db_session, telegram_id=20001)
    result = await db_session.execute(select(Plan).where(Plan.slug == "plantao"))
    plan = result.scalar_one()

    checkout = await payments_service.create_checkout(db_session, user.id, plan)
    assert checkout is not None
    assert "payment_id" in checkout

    payment_result = await db_session.execute(
        select(Payment).where(Payment.id == checkout["payment_id"])
    )
    payment = payment_result.scalar_one()
    assert payment.status == "pending"
    assert payment.amount_brl_cents == 1490


@pytest.mark.asyncio
async def test_on_payment_paid_credits_user(db_session, monkeypatch):
    """Simula webhook 'paid' e valida creditação + criação de subscription."""
    from sqlalchemy import select

    from resusbot.db.models import Payment, Plan, Subscription
    from resusbot.db.repository import upsert_user
    from resusbot.services import credits_service
    from resusbot.services.payments_service import payments_service

    monkeypatch.setattr("resusbot.config.settings.mp_webhook_secret", "changeme")
    monkeypatch.setattr("resusbot.config.settings.app_env", "development")

    user = await upsert_user(db_session, telegram_id=20002)
    result = await db_session.execute(select(Plan).where(Plan.slug == "plantao"))
    plan = result.scalar_one()

    # Cria payment pendente
    payment = Payment(
        user_id=user.id,
        plan_id=plan.id,
        amount_brl_cents=plan.price_brl_cents,
        status="pending",
        provider="mercadopago",
    )
    db_session.add(payment)
    await db_session.commit()
    await db_session.refresh(payment)

    # Simula que o provider já processou o status
    payment.status = "paid"
    payment.provider_event_id = "EVT-001"
    await db_session.commit()

    await payments_service._on_payment_paid(db_session, payment)

    info = await credits_service.check_balance(db_session, user.id)
    assert info.balance == plan.monthly_credits

    sub_result = await db_session.execute(
        select(Subscription).where(Subscription.user_id == user.id, Subscription.status == "active")
    )
    sub = sub_result.scalar_one_or_none()
    assert sub is not None
    assert sub.plan_id == plan.id
