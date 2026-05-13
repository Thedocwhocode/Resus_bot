"""Rate limiting por telegram_id usando sliding window no Redis."""
import time

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_WINDOW_SECONDS = 60


async def check_rate_limit(telegram_id: int, max_per_window: int = 20) -> bool:
    """
    Retorna True se o usuário ainda está dentro do limite.
    Usa Redis com sliding window; em caso de falha do Redis, permite a requisição.
    """
    try:
        from resusbot.cache.redis_client import get_redis
        redis = await get_redis()
        key = f"rl:user:{telegram_id}"
        now = time.time()
        window_start = now - _WINDOW_SECONDS

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, _WINDOW_SECONDS * 2)
        results = await pipe.execute()

        count: int = results[2]
        if count > max_per_window:
            log.warning("rate_limit_exceeded", telegram_id=telegram_id, count=count)
            return False
        return True
    except Exception:
        return True  # fail open
