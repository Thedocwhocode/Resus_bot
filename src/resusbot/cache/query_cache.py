import hashlib
import json
import re
import unicodedata
from typing import Any

import structlog

from resusbot.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_WHITESPACE = re.compile(r"\s+")


def normalize_query(query: str) -> str:
    """Normaliza query para uso como chave de cache."""
    q = unicodedata.normalize("NFKD", query.lower().strip())
    q = q.encode("ascii", "ignore").decode("ascii")
    q = _WHITESPACE.sub(" ", q)
    return q


def hash_query(normalized: str) -> str:
    return hashlib.sha256(normalized.encode()).hexdigest()


async def get_cached_response(query: str) -> dict[str, Any] | None:
    """Busca resposta no Redis. Retorna None em cache miss."""
    normalized = normalize_query(query)
    key = f"cache:query:{hash_query(normalized)}"
    try:
        from resusbot.cache.redis_client import get_redis
        redis = await get_redis()
        raw = await redis.get(key)
        if raw:
            log.info("cache_hit_redis", query_hash=key[-12:])
            return json.loads(raw)  # type: ignore[return-value]
    except Exception as e:
        log.warning("cache_redis_get_error", error=str(e))
    return None


async def set_cached_response(query: str, response: dict[str, Any]) -> None:
    """Armazena resposta no Redis com TTL configurável."""
    normalized = normalize_query(query)
    h = hash_query(normalized)
    key = f"cache:query:{h}"
    try:
        from resusbot.cache.redis_client import get_redis
        redis = await get_redis()
        await redis.setex(key, settings.cache_ttl_seconds, json.dumps(response))
        log.info("cache_set_redis", query_hash=h[-12:], ttl=settings.cache_ttl_seconds)

        # Persiste no SQLite como backup
        from resusbot.db.repository import upsert_cache_entry
        from resusbot.db.session import get_session_context
        async with get_session_context() as session:
            await upsert_cache_entry(session, h, normalized, response)
    except Exception as e:
        log.warning("cache_redis_set_error", error=str(e))


async def get_cached_response_fallback(query: str) -> dict[str, Any] | None:
    """Fallback: busca no SQLite quando Redis está indisponível."""
    normalized = normalize_query(query)
    h = hash_query(normalized)
    try:
        from resusbot.db.repository import get_cache_entry
        from resusbot.db.session import get_session_context
        async with get_session_context() as session:
            entry = await get_cache_entry(session, h)
            if entry:
                log.info("cache_hit_sqlite", query_hash=h[-12:])
                return entry.response_json  # type: ignore[return-value]
    except Exception as e:
        log.warning("cache_sqlite_get_error", error=str(e))
    return None
