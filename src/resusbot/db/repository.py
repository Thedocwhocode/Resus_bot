from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from resusbot.db.models import Article, CacheEntry, Category, SearchArticle, SearchLog, User


# ── Users ─────────────────────────────────────────────────────────────────────

async def upsert_user(session: AsyncSession, telegram_id: int, username: str | None = None) -> User:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(telegram_id=telegram_id, username=username)
        session.add(user)
    else:
        user.last_seen = datetime.now(timezone.utc)
        user.request_count += 1
        if username:
            user.username = username
    await session.commit()
    await session.refresh(user)
    return user


async def get_user_stats(session: AsyncSession, telegram_id: int) -> dict[str, Any]:
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"total": 0, "cache_hits": 0, "first_seen": "—"}

    cache_hits_result = await session.execute(
        select(func.count()).select_from(SearchLog).where(
            SearchLog.user_id == user.id, SearchLog.cache_hit.is_(True)
        )
    )
    cache_hits: int = cache_hits_result.scalar_one()
    return {
        "total": user.request_count,
        "cache_hits": cache_hits,
        "first_seen": user.first_seen.strftime("%d/%m/%Y"),
    }


# ── Articles ──────────────────────────────────────────────────────────────────

async def get_article_by_doi(session: AsyncSession, doi: str) -> Article | None:
    normalized = _normalize_doi(doi)
    result = await session.execute(select(Article).where(Article.doi == normalized))
    return result.scalar_one_or_none()


async def upsert_article(session: AsyncSession, data: dict[str, Any]) -> Article:
    doi = _normalize_doi(data.get("doi", ""))
    if not doi:
        raise ValueError("doi é obrigatório")

    existing = await get_article_by_doi(session, doi)
    if existing:
        # Atualiza metadados se disponíveis
        for field in ("pdf_url", "oa_status", "citations", "metadata_json"):
            if data.get(field) is not None:
                setattr(existing, field, data[field])
        existing.updated_at = datetime.now(timezone.utc)
        await session.commit()
        await session.refresh(existing)
        return existing

    article = Article(
        doi=doi,
        title=data.get("title"),
        authors_json=data.get("authors_json"),
        journal=data.get("journal"),
        year=data.get("year"),
        pdf_url=data.get("pdf_url"),
        oa_status=data.get("oa_status"),
        citations=data.get("citations"),
        category_id=data.get("category_id"),
        metadata_json=data.get("metadata_json"),
    )
    session.add(article)
    await session.commit()
    await session.refresh(article)
    return article


def _normalize_doi(doi: str) -> str:
    return doi.lower().strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")


# ── SearchLog ─────────────────────────────────────────────────────────────────

async def log_search(
    session: AsyncSession,
    user_id: int,
    query_raw: str,
    query_normalized: str,
    cache_hit: bool,
    articles_returned: int,
    latency_ms: int,
    article_ids: list[int] | None = None,
) -> SearchLog:
    entry = SearchLog(
        user_id=user_id,
        query_raw=query_raw,
        query_normalized=query_normalized,
        cache_hit=cache_hit,
        articles_returned=articles_returned,
        latency_ms=latency_ms,
    )
    session.add(entry)
    await session.flush()  # pega o id

    if article_ids:
        for rank, article_id in enumerate(article_ids, 1):
            session.add(SearchArticle(search_id=entry.id, article_id=article_id, rank=rank))

    await session.commit()
    await session.refresh(entry)
    return entry


# ── CacheEntry ────────────────────────────────────────────────────────────────

async def get_cache_entry(session: AsyncSession, query_hash: str) -> CacheEntry | None:
    result = await session.execute(select(CacheEntry).where(CacheEntry.query_hash == query_hash))
    return result.scalar_one_or_none()


async def upsert_cache_entry(
    session: AsyncSession,
    query_hash: str,
    query_normalized: str,
    response_json: dict[str, Any],
) -> None:
    existing = await get_cache_entry(session, query_hash)
    if existing:
        existing.hits += 1
        existing.last_used_at = datetime.now(timezone.utc)
    else:
        session.add(CacheEntry(
            query_hash=query_hash,
            query_normalized=query_normalized,
            response_json=response_json,
        ))
    await session.commit()


# ── Dashboard stats ───────────────────────────────────────────────────────────

async def get_kpis(session: AsyncSession, days: int = 7) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    total_q = await session.execute(
        select(func.count()).select_from(SearchLog).where(SearchLog.created_at >= since)
    )
    unique_u = await session.execute(
        select(func.count(func.distinct(SearchLog.user_id))).where(SearchLog.created_at >= since)
    )
    cache_hits = await session.execute(
        select(func.count()).select_from(SearchLog).where(
            SearchLog.created_at >= since, SearchLog.cache_hit.is_(True)
        )
    )
    total = total_q.scalar_one()
    hits = cache_hits.scalar_one()
    return {
        "total_queries": total,
        "unique_users": unique_u.scalar_one(),
        "cache_hit_rate": round(hits / total * 100, 1) if total else 0.0,
        "cache_hits": hits,
    }


async def get_top_users(session: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(User.telegram_id, User.request_count, User.last_seen)
        .order_by(desc(User.request_count))
        .limit(limit)
    )
    return [
        {
            "telegram_id_hash": _hash_id(row.telegram_id),
            "request_count": row.request_count,
            "last_seen": row.last_seen.strftime("%d/%m/%Y") if row.last_seen else "—",
        }
        for row in rows
    ]


async def get_top_subjects(session: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Category.name_pt, func.count(Article.id).label("total"))
        .join(Article, Article.category_id == Category.id)
        .group_by(Category.id)
        .order_by(desc("total"))
        .limit(limit)
    )
    return [{"subject": row.name_pt, "count": row.total} for row in rows]


async def get_top_queries(session: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(SearchLog.query_normalized, func.count(SearchLog.id).label("total"))
        .group_by(SearchLog.query_normalized)
        .order_by(desc("total"))
        .limit(limit)
    )
    return [{"query": row.query_normalized, "count": row.total} for row in rows]


async def get_timeseries(session: AsyncSession, days: int = 30) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT date(created_at) as day, count(*) as total "
            "FROM search_logs "
            "WHERE created_at >= date('now', :offset) "
            "GROUP BY day ORDER BY day"
        ),
        {"offset": f"-{days} days"},
    )
    return [{"day": row.day, "total": row.total} for row in rows]


async def get_top_articles(session: AsyncSession, limit: int = 10) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Article.doi, Article.title, func.count(SearchArticle.search_id).label("searches"))
        .join(SearchArticle, SearchArticle.article_id == Article.id)
        .group_by(Article.id)
        .order_by(desc("searches"))
        .limit(limit)
    )
    return [{"doi": row.doi, "title": row.title or row.doi, "searches": row.searches} for row in rows]


def _hash_id(telegram_id: int) -> str:
    import hashlib
    return hashlib.sha256(str(telegram_id).encode()).hexdigest()[:12]
