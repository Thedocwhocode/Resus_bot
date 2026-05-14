import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from resusbot.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "development",
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine.sync_engine, "connect")
def _sqlite_pragmas(dbapi_conn, _connection_record) -> None:  # type: ignore[no-untyped-def]
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def get_session_context() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables() -> None:
    """Create tables directly from SQLAlchemy metadata. Used only in tests."""
    from resusbot.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _alembic_upgrade_head() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    migrations_dir = Path(__file__).resolve().parent / "migrations"
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir))
    cfg.set_main_option("sqlalchemy.url", settings.sync_database_url)
    command.upgrade(cfg, "head")


async def run_migrations() -> None:
    """Apply Alembic migrations to head. Called at app startup."""
    await asyncio.to_thread(_alembic_upgrade_head)
