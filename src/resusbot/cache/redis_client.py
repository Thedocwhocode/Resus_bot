import structlog
from redis.asyncio import Redis, from_url

from resusbot.config import settings

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_redis: Redis | None = None  # type: ignore[type-arg]


async def get_redis() -> Redis:  # type: ignore[type-arg]
    global _redis
    if _redis is None:
        _redis = from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        log.info("redis_connection_closed")


async def ping_redis() -> bool:
    try:
        redis = await get_redis()
        return await redis.ping()  # type: ignore[return-value]
    except Exception:
        return False
