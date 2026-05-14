import os
from collections.abc import AsyncGenerator

import fakeredis.aioredis
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# Configura env antes de importar qualquer módulo do projeto
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake:token")
os.environ.setdefault("GROQ_API_KEY", "fake_key")
os.environ.setdefault("SQLITE_PATH", ":memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("DASHBOARD_USER", "admin")
os.environ.setdefault(
    "DASHBOARD_PASSWORD_HASH", "$2b$12$fakehashfakehashfakehashfakehashfakehashfakeha"
)

# Substitui o engine global por um StaticPool em memória antes que qualquer módulo
# do projeto importe `AsyncSessionLocal` por nome (alguns chamam get_session_context
# que resolve o engine no momento da chamada — então monkey-patch funciona).
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import resusbot.db.session as _session_module
from resusbot.db.models import Base

_test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    echo=False,
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_session_module.engine = _test_engine
_session_module.AsyncSessionLocal = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _init_schema():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await _test_engine.dispose()


@pytest_asyncio.fixture
async def db_engine():
    yield _test_engine


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    async with _session_module.AsyncSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def fake_redis():
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def client():
    from fastapi import FastAPI

    from resusbot.dashboard.routes import router

    test_app = FastAPI()
    test_app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as c:
        yield c
