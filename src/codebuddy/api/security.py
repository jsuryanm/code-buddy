"""API key authentication, rate limiting, and pending-approval bookkeeping."""

from __future__ import annotations

import hashlib
import secrets
import time

from fastapi import HTTPException, Request

from codebuddy.cache.base import Cache
from codebuddy.config import Settings
from codebuddy.metrics import Metrics

PENDING_TTL = 15 * 60


def parse_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def extract_key(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("x-api-key")


def check_api_key(request: Request, settings: Settings) -> str | None:
    """Returns the caller's key (or None when auth is off). Raises 401 on a bad key."""
    valid = parse_keys(settings.api_keys)
    if not valid:
        return None
    given = extract_key(request) or ""
    # Compare against every key so timing does not reveal which one is close.
    matches = [secrets.compare_digest(given.encode(), k.encode()) for k in valid]
    if not any(matches):
        raise HTTPException(
            401, "Missing or invalid API key", headers={"WWW-Authenticate": "Bearer"}
        )
    return given


async def enforce_rate_limit(
    request: Request, settings: Settings, cache: Cache, metrics: Metrics, key: str | None
) -> None:
    """Fixed one-minute window per caller (API key, else client address)."""
    limit = settings.rate_limit_per_minute
    if limit <= 0:
        return
    caller = key or (request.client.host if request.client else "unknown")
    now = int(time.time())
    bucket = f"cb:rl:{hashlib.sha256(caller.encode()).hexdigest()[:16]}:{now // 60}"
    if await cache.incr(bucket, ttl=70) > limit:
        await metrics.incr("rate_limited")
        raise HTTPException(429, "Too many requests", headers={"Retry-After": str(60 - now % 60)})


class PendingApprovals:
    """Remembers which session owns a paused turn, so only that session can resume it."""

    def __init__(self, cache: Cache):
        self._cache = cache

    @staticmethod
    def _key(turn_id: str) -> str:
        return f"cb:pending:{turn_id}"

    async def add(self, turn_id: str, session_id: str) -> None:
        await self._cache.set(self._key(turn_id), session_id, PENDING_TTL)

    async def take(self, turn_id: str, session_id: str) -> bool:
        """True once, for the owning session. The entry is consumed."""
        owner = await self._cache.get(self._key(turn_id))
        if owner is None or not secrets.compare_digest(owner.encode(), session_id.encode()):
            return False
        await self._cache.delete(self._key(turn_id))
        return True
