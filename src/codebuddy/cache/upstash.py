from __future__ import annotations

from upstash_redis.asyncio import Redis


class UpstashCache:
    """Cache backed by Upstash Redis over REST (UPSTASH_REDIS_REST_URL / _TOKEN)."""

    def __init__(self, redis: Redis | None = None):
        self._redis = redis or Redis.from_env()

    async def get(self, key: str) -> str | None:
        value = await self._redis.get(key)
        return None if value is None else str(value)

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._redis.set(key, value, ex=ttl)

    async def set_nx(self, key: str, value: str, ttl: int) -> bool:
        return bool(await self._redis.set(key, value, ex=ttl, nx=True))

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        value = int(await self._redis.incr(key))
        if ttl is not None and value == 1:
            await self._redis.expire(key, ttl)
        return value
