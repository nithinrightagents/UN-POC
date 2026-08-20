"""Shared AI runtime (spec 007).

One ModelProvider, one RateLimiter, one BrowserSession, and one httpx.AsyncClient
shared across all live assessment runs.

Deviation from contracts/auth-and-limits.md §2 literal start() -> browser.start():
Chromium is launched lazily via ensure_browser() on first actual use rather than
eagerly inside start(). This allows portal-only deployments and test suites
without Playwright Chromium binaries installed to start normally (FR-API-002, FR-API-039).
"""

from __future__ import annotations

import asyncio
import httpx

from core.llm_factory import ModelProvider
from shared.config.settings import Settings
from shared.ratelimit.token_bucket import RateLimiter
from shared.tools.browser import BrowserSession


class AIRuntime:
    """Shared AI runtime managed by the FastAPI app lifespan."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.provider = ModelProvider(
            settings.google_cloud_project,
            settings.google_cloud_location,
            settings.google_genai_use_vertexai,
            settings.google_api_key,
        )
        self.limiter = RateLimiter(rate_per_sec=settings.rate_limit_per_domain_rps)
        self.browser = BrowserSession(settings.user_agent, self.limiter)
        self.http_client = httpx.AsyncClient(timeout=15.0)
        self._browser_started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Starts the runtime. Browser is started lazily via ensure_browser()."""
        pass

    async def ensure_browser(self) -> None:
        """Ensures that the headless browser has started (idempotent)."""
        if not self._browser_started:
            async with self._lock:
                if not self._browser_started:
                    await self.browser.start()
                    self._browser_started = True

    async def stop(self) -> None:
        """Stops the browser session and HTTP client."""
        if self._browser_started:
            await self.browser.stop()
            self._browser_started = False
        await self.http_client.aclose()
