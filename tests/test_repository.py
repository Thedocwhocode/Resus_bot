import pytest
import pytest_asyncio
from resusbot.db.repository import (
    get_kpis,
    get_top_queries,
    get_top_users,
    log_search,
    upsert_article,
    upsert_user,
)
from resusbot.scripts.seed_categories import seed_categories


@pytest_asyncio.fixture(autouse=True)
async def seed(db_session):
    await seed_categories()


@pytest.mark.asyncio
async def test_upsert_user_creates(db_session):
    user = await upsert_user(db_session, telegram_id=111222333, username="testuser")
    assert user.id is not None
    assert user.telegram_id == 111222333


@pytest.mark.asyncio
async def test_upsert_user_idempotent(db_session):
    u1 = await upsert_user(db_session, telegram_id=444555666)
    u2 = await upsert_user(db_session, telegram_id=444555666)
    assert u1.id == u2.id


@pytest.mark.asyncio
async def test_upsert_article_and_retrieve(db_session):
    art = await upsert_article(db_session, {"doi": "10.1234/test.repo", "title": "Repo Test"})
    assert art.doi == "10.1234/test.repo"


@pytest.mark.asyncio
async def test_log_search(db_session):
    user = await upsert_user(db_session, telegram_id=777888999)
    entry = await log_search(
        session=db_session,
        user_id=user.id,
        query_raw="cardiac arrest cooling",
        query_normalized="cardiac arrest cooling",
        cache_hit=False,
        articles_returned=1,
        latency_ms=1200,
    )
    assert entry.id is not None


@pytest.mark.asyncio
async def test_get_kpis_empty(db_session):
    kpis = await get_kpis(db_session, days=7)
    assert "total_queries" in kpis
    assert "cache_hit_rate" in kpis
