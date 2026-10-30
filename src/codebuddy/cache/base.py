from __future__ import annotations

from typing import Protocol


class Cache(Protocol):
    """Minimal async key-value cache. Implemented by Upstash Redis and an in-memory fake."""

    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ttl: int) -> None: ...

    async def set_nx(self, key: str, value: str, ttl: int) -> bool:
        """Set only if the key does not exist. True when this call created it."""
        ...

    async def delete(self, key: str) -> None: ...

    async def incr(self, key: str, ttl: int | None = None) -> int: ...
