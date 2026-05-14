import pytest
import pytest_asyncio

from resusbot.scripts.seed_categories import seed_categories
from resusbot.scripts.seed_plans import seed_plans
from resusbot.services import credits_service


@pytest_asyncio.fixture(autouse=True)
async def seed(db_session):
    await seed_categories()
    await seed_plans()


async def _create_user(session, telegram_id=12345):
    from resusbot.db.repository import upsert_user

    user = await upsert_user(session, telegram_id=telegram_id)
    return user.id


@pytest.mark.asyncio
async def test_has_credits_new_user(db_session):
    user_id = await _create_user(db_session, telegram_id=10001)
    assert await credits_service.has_credits(db_session, user_id) is True


@pytest.mark.asyncio
async def test_check_balance_initial_state(db_session):
    user_id = await _create_user(db_session, telegram_id=10002)
    info = await credits_service.check_balance(db_session, user_id)
    assert info.balance == 0
    assert info.monthly_quota == 10  # default free
    assert info.monthly_quota_remaining == 10


@pytest.mark.asyncio
async def test_consume_uses_free_quota_first(db_session):
    user_id = await _create_user(db_session, telegram_id=10003)
    for _ in range(5):
        assert await credits_service.consume(db_session, user_id) is True
    info = await credits_service.check_balance(db_session, user_id)
    assert info.monthly_quota_used == 5
    assert info.balance == 0


@pytest.mark.asyncio
async def test_consume_blocks_when_no_credits(db_session):
    user_id = await _create_user(db_session, telegram_id=10004)
    # consome toda quota grátis (10)
    for _ in range(10):
        assert await credits_service.consume(db_session, user_id) is True
    # 11ª deve falhar
    assert await credits_service.has_credits(db_session, user_id) is False
    assert await credits_service.consume(db_session, user_id) is False


@pytest.mark.asyncio
async def test_credit_adds_balance(db_session):
    user_id = await _create_user(db_session, telegram_id=10005)
    await credits_service.credit(db_session, user_id, amount=50, reason="purchase")
    info = await credits_service.check_balance(db_session, user_id)
    assert info.balance == 50


@pytest.mark.asyncio
async def test_consume_uses_paid_after_free_exhausted(db_session):
    user_id = await _create_user(db_session, telegram_id=10006)
    await credits_service.credit(db_session, user_id, amount=5, reason="purchase")
    # Exaure quota grátis
    for _ in range(10):
        await credits_service.consume(db_session, user_id)
    # Próximos consomem do balance pago
    assert await credits_service.consume(db_session, user_id) is True
    info = await credits_service.check_balance(db_session, user_id)
    assert info.balance == 4
    assert info.monthly_quota_remaining == 0


def test_is_billable_with_pdf():
    payload = {"articles_count": 1, "has_pdf": True, "response": "..."}
    assert credits_service.is_billable(payload) is True


def test_is_billable_without_pdf():
    payload = {"articles_count": 1, "has_pdf": False, "response": "Apenas metadata"}
    assert credits_service.is_billable(payload) is False


def test_is_billable_empty():
    assert credits_service.is_billable({"articles_count": 0}) is False


def test_is_billable_heuristic_pdf_in_text():
    payload = {
        "articles_count": 1,
        "response": "📄 Title\n📥 PDF: https://example.com/article.pdf",
    }
    assert credits_service.is_billable(payload) is True


def test_is_billable_cache_hit_with_pdf():
    """Cache hit COM PDF deve ser billable (margem máxima — custo Groq zero)."""
    payload = {"articles_count": 1, "has_pdf": True, "cache_hit": True}
    assert credits_service.is_billable(payload) is True
