"""Small counters for monitoring (GET /v1/metrics). Stored in the cache, so they survive restarts
when Upstash is configured and are per-process otherwise."""

from __future__ import annotations

from codebuddy.cache.base import Cache

COUNTERS = (
    "turns", "cache_hits", "semantic_hits", "guard_stops", "degraded", "tool_runs",
    "approvals_requested", "approvals_granted", "approvals_declined",
    "judge_checked", "judge_flagged", "stt_requests", "stt_failures", "rate_limited",
    "memory_recalls", "memory_writes", "memory_failures",
)  # fmt: skip


class Metrics:
    def __init__(self, cache: Cache | None = None):
        self._cache = cache
        self._local: dict[str, int] = {}

    async def incr(self, name: str) -> None:
        assert name in COUNTERS, f"unknown counter {name}"
        if self._cache is None:
            self._local[name] = self._local.get(name, 0) + 1
        else:
            await self._cache.incr(f"cb:metric:{name}")

    async def snapshot(self) -> dict[str, int]:
        if self._cache is None:
            return {n: self._local.get(n, 0) for n in COUNTERS}
        return {n: int(await self._cache.get(f"cb:metric:{n}") or 0) for n in COUNTERS}
