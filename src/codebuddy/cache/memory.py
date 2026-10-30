from __future__ import annotations

import time
from collections.abc import Callable


class InMemoryCache:
    """In-process cache for tests and for running without Upstash credentials."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._data: dict[str, tuple[str, float | None]] = {}

    def _live(self, key: str) -> str | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expires = item
        if expires is not None and expires <= self._clock():
            del self._data[key]
            return None
        return value

    async def get(self, key: str) -> str | None:
        return self._live(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._data[key] = (value, self._clock() + ttl)

    async def set_nx(self, key: str, value: str, ttl: int) -> bool:
        if self._live(key) is not None:
            return False
        await self.set(key, value, ttl)
        return True

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        current = self._live(key)
        value = int(current) + 1 if current is not None else 1
        expires = self._data[key][1] if current is not None else None
        if ttl is not None and current is None:
            expires = self._clock() + ttl
        self._data[key] = (str(value), expires)
        return value
