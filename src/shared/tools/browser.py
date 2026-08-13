"""Headless browser page acquisition (research R4).

A headless browser, not a plain HTTP client, because FR-021 requires a
region-scoped visual capture, which needs layout, and because government
portals are heavily client-rendered -- an HTTP-only fetch would
systematically under-report features on more advanced portals.

Every fetch acquires from the shared per-domain rate limiter before
navigating (FR-069, FR-089) and is recorded to the fetch log (FR-115).
"""

from __future__ import annotations

from dataclasses import dataclass

from playwright.async_api import Browser, Page, async_playwright

from shared.ratelimit.token_bucket import RateLimiter
from core.telemetry.fetch_log import FetchLog


@dataclass
class PageResult:
    url: str
    final_url: str
    html: str
    status: int | None
    reachable: bool
    reason: str | None = None  # "timeout" | "interstitial" | "challenge" | "error"


class BrowserSession:
    """One browser instance, reused across fetches within a run for
    efficiency. Pages are isolated per-fetch via fresh browser contexts, so
    no cookies or state leak between question-portal units."""

    def __init__(self, user_agent: str, limiter: RateLimiter):
        self._user_agent = user_agent
        self._limiter = limiter
        self._playwright = None
        self._browser: Browser | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def stop(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(
        self,
        url: str,
        caller_class: str,
        fetch_log: FetchLog | None = None,
        timeout_ms: int = 15000,
    ) -> tuple[PageResult, Page | None]:
        """Fetch `url`, honouring the shared per-domain rate limit. Returns the
        page result and, on success, the live Page object (caller must close
        the owning context) so capture.py and element_ref.py can operate on
        the rendered DOM before the page is torn down."""
        domain = RateLimiter.domain_of(url)
        wait = await self._limiter.acquire(url, caller_class)
        if fetch_log:
            fetch_log.record(domain, caller_class, wait)

        assert self._browser is not None, "BrowserSession.start() was not called"
        context = await self._browser.new_context(user_agent=self._user_agent)
        page = await context.new_page()
        try:
            response = await page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            status = response.status if response else None
            final_url = page.url
            html = await page.content()

            reason = None
            reachable = True
            if status is not None and status >= 400:
                reachable = False
                reason = "error"
            if _looks_like_interstitial(html):
                reachable = False
                reason = "interstitial"

            return (
                PageResult(
                    url=url, final_url=final_url, html=html, status=status,
                    reachable=reachable, reason=reason,
                ),
                page if reachable else None,
            )
        except Exception as exc:  # noqa: BLE001 -- timeouts, DNS failures, etc.
            await context.close()
            return (
                PageResult(url=url, final_url=url, html="", status=None,
                           reachable=False, reason="timeout" if "Timeout" in str(exc) else "error"),
                None,
            )

    async def close_page(self, page: Page) -> None:
        await page.context.close()


def _looks_like_interstitial(html: str) -> bool:
    lowered = html.lower()
    markers = ("checking your browser", "cloudflare", "captcha", "access denied", "just a moment")
    return any(m in lowered for m in markers) and len(html) < 5000
