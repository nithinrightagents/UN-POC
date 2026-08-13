"""Per-domain rate limiting (token-bucket based)."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlparse


class RateLimiter:
    """Per-domain token-bucket rate limiter."""

    def __init__(self, rate_per_sec: float = 1.0, capacity: float = 5.0):
        self.rate_per_sec = rate_per_sec
        self.capacity = capacity
        self._tokens: dict[str, float] = {}
        self._last_update: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def domain_of(url: str) -> str:
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path.split("/")[0]
        return netloc.lower().split(":")[0]

    async def acquire(self, url: str, caller: str = "") -> float:
        domain = self.domain_of(url)
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()

        async with self._locks[domain]:
            now = time.monotonic()
            last = self._last_update.get(domain, now)
            elapsed = now - last
            self._last_update[domain] = now

            tokens = self._tokens.get(domain, self.capacity)
            tokens = min(self.capacity, tokens + elapsed * self.rate_per_sec)

            if tokens >= 1.0:
                self._tokens[domain] = tokens - 1.0
                return 0.0

            needed = 1.0 - tokens
            wait_time = needed / self.rate_per_sec
            self._tokens[domain] = 0.0
            await asyncio.sleep(wait_time)
            return wait_time
