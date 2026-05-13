import asyncio
import os
from collections.abc import AsyncGenerator

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Configura env antes de importar qualquer módulo do projeto
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake:token")
os.environ.setdefault("GROQ_API_KEY", "fake_key")
os.environ.setdefault("SQLITE_PATH", ":memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DASHBOARD_USER", "admin")
os.environ.setdefault("DASHBOARD_PASSWORD_HASH", "$2b$12$fakehashfakehashfakehashfakehashfakehashfakeha")

from resusbot.db.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def client():
    # Importa app sem iniciar lifespan completo
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    # Usa transport direto sem lifespan
    from resusbot.dashboard.routes import router
    test_app = FastAPI()
    test_app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        yield c
