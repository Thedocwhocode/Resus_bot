import pytest
import pytest_asyncio

from resusbot.scripts.seed_categories import seed_categories
from resusbot.services.dedup_service import normalize_doi, upsert_article_safe


@pytest_asyncio.fixture(autouse=True)
async def seed(db_session):
    await seed_categories()


def test_normalize_doi_removes_prefix():
    assert normalize_doi("https://doi.org/10.1056/NEJMoa") == "10.1056/nejmoa"
    assert normalize_doi("http://doi.org/10.1056/NEJMoa") == "10.1056/nejmoa"


def test_normalize_doi_lowercases():
    assert normalize_doi("10.1056/NEJMoa2001017") == "10.1056/nejmoa2001017"


def test_normalize_doi_empty():
    assert normalize_doi("") == ""


@pytest.mark.asyncio
async def test_upsert_article_no_doi(db_session):
    result = await upsert_article_safe(db_session, {"title": "No DOI article"})
    assert result is None


@pytest.mark.asyncio
async def test_upsert_article_creates(db_session):
    data = {"doi": "10.9999/test.001", "title": "Test Article"}
    art_id = await upsert_article_safe(db_session, data)
    assert art_id is not None
    assert isinstance(art_id, int)


@pytest.mark.asyncio
async def test_upsert_article_dedup(db_session):
    data = {"doi": "10.9999/test.002", "title": "Dup Article"}
    id1 = await upsert_article_safe(db_session, data)
    id2 = await upsert_article_safe(db_session, data)
    assert id1 == id2
