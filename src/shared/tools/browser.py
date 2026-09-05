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
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from core.telemetry.fetch_log import FetchLog
from shared.ratelimit.token_bucket import RateLimiter


@dataclass
class PageResult:
    url: str
    final_url: str
    html: str
    status: int | None
    reachable: bool
    reason: str | None = None  # "timeout" | "interstitial" | "stale_stub" | "challenge" | "http_NNN" | "error: <detail>"


# Best-effort cookie-consent dismissal (2026-08-20 debugging pass): several
# live Danish government sites (skat.dk among them, via Cookiebot) render an
# interstitial consent banner that intercepts the visible page content until
# accepted -- the assessor agent was then reading and confidently reporting
# on the BANNER TEXT ITSELF ("Vi bruger cookies") as if it were the page.
# Each selector is tried with a short timeout and swallowed on failure --
# most pages have no banner at all, so this must never slow down or fail an
# otherwise-successful fetch.
_COOKIE_CONSENT_SELECTORS = (
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",  # Cookiebot -- the most common EU/DK consent widget
    "#CybotCookiebotDialogBodyButtonAccept",
    "#onetrust-accept-btn-handler",  # OneTrust
    "button.coi-banner__accept",  # "Cookie Information" (coi-consent.dk) -- used by skat.dk among others
    "button#accept-cookies",
    "text=Accepter alle",
    "text=Acceptér",
    "text=Tillad alle",
    "text=Godkend alle",
    "text=Accept all",
    "text=Accept all cookies",
)

# Container elements to strip from the DOM after a successful accept-click
# (2026-08-20 debugging pass, part 2). Clicking "accept" only sets these to
# display:none -- confirmed live on skat.dk (getComputedStyle(...).display
# == "none" after click) -- it never removes the node. That's invisible to a
# human but invisible does NOT mean absent: page_text is built by running
# BeautifulSoup over the raw page.content() HTML (see agent.py), which has
# no notion of CSS visibility and extracts hidden text exactly like visible
# text. Result: the assessor kept reading and quoting the (now-hidden)
# banner copy ("Vi bruger cookies") as if it were live page content. Removing
# the container outright, rather than trusting the vendor's own hide
# behaviour, is what actually keeps it out of the extracted text.
_COOKIE_CONSENT_CONTAINERS = (
    "#CybotCookiebotDialog",
    "#onetrust-banner-sdk",
    "#onetrust-consent-sdk",
    "#coiOverlay",
    "[class*='coi-banner']",
)


async def _dismiss_cookie_banner(page: Page) -> None:
    for selector in _COOKIE_CONSENT_SELECTORS:
        try:
            element = await page.wait_for_selector(selector, timeout=800, state="visible")
        except Exception:  # noqa: BLE001 -- selector absent on this page, try the next
            continue
        if element is None:
            continue
        try:
            await element.click(timeout=800)
            await page.wait_for_timeout(300)
        except Exception:  # noqa: BLE001 -- best-effort only
            pass
        try:
            await page.evaluate(
                """(selectors) => {
                    for (const sel of selectors) {
                        document.querySelectorAll(sel).forEach(el => el.remove());
                    }
                }""",
                list(_COOKIE_CONSENT_CONTAINERS),
            )
        except Exception:  # noqa: BLE001 -- best-effort only
            pass
        return


class BrowserSession:
    """One browser instance, reused across fetches within a run for
    efficiency. Pages are isolated per-fetch via fresh browser contexts, so
    no cookies or state leak between question-portal units."""

    def __init__(self, user_agent: str, limiter: RateLimiter, search_limiter: RateLimiter | None = None):
        self._user_agent = user_agent
        self._limiter = limiter
        # Deliberately a SEPARATE bucket from `_limiter`, not shared: the
        # general limiter's default capacity (5) is a burst allowance meant
        # for occasional concurrent hits to distinct portal domains, but the
        # search source funnels every unit's search fallback through the
        # SAME single external host -- confirmed live that a burst of just
        # ~5 concurrent requests to it gets a fraction of responses swapped
        # for a content-free HTTP 202 anti-bot interstitial (zero parseable
        # results) instead of the real result page, and that the resulting
        # cooldown outlasts a single resolve attempt's retry budget by a
        # wide margin. capacity=1.0 means no burst is ever possible here --
        # every search request, even the very first one in a run, waits its
        # full turn -- which is what actually avoids tripping the throttle,
        # as opposed to retrying harder after the fact.
        self._search_limiter = search_limiter or RateLimiter(rate_per_sec=limiter.rate_per_sec, capacity=1.0)
        self._playwright = None
        self._browser: Browser | None = None

    @property
    def limiter(self) -> RateLimiter:
        """Exposes the shared per-domain limiter so other fetchers sharing
        this session's network budget (e.g. link-resolution search) can
        acquire from the same token buckets rather than hitting external
        hosts unthrottled."""
        return self._limiter

    @property
    def search_limiter(self) -> RateLimiter:
        """A stricter, no-burst limiter dedicated to the search link-
        resolution source -- see the constructor comment for why this must
        not share the general limiter's burst-tolerant capacity."""
        return self._search_limiter

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
        timeout_ms: int = 45000,
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
            # "networkidle" waits for 500ms of zero in-flight requests, which
            # never happens on real-world sites carrying analytics beacons,
            # chat widgets, or polling scripts -- confirmed in practice: several
            # ordinary, reachable government-adjacent .dk sites timed out at
            # 15s under it while loading fully in under 4s. "domcontentloaded"
            # is what actually reflects whether the page rendered; a short,
            # best-effort networkidle grace period after that lets slower
            # dynamic content catch up without failing the whole fetch if it
            # doesn't settle in time.
            response = await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            await _dismiss_cookie_banner(page)
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except PlaywrightTimeoutError:
                pass
            status = response.status if response else None
            final_url = page.url
            html = await page.content()

            reason = None
            reachable = True
            if status is not None and status >= 400:
                reachable = False
                reason = f"http_{status}"
            if _looks_like_interstitial(html):
                reachable = False
                reason = "interstitial"
            if reachable and _looks_like_stale_stub(html):
                reachable = False
                reason = "stale_stub"

            return (
                PageResult(
                    url=url, final_url=final_url, html=html, status=status,
                    reachable=reachable, reason=reason,
                ),
                page if reachable else None,
            )
        except Exception as exc:  # noqa: BLE001 -- timeouts, DNS failures, etc.
            await context.close()
            # The exception's own message is kept (truncated) rather than
            # collapsed to the bare word "error" (2026-08-20 debugging pass):
            # that string was the ONLY thing persisted for every non-timeout
            # fetch failure, so a "portal unreachable" run could never be
            # distinguished afterwards from DNS failure vs. connection reset
            # vs. TLS error vs. anything else without re-running it live.
            detail = str(exc).splitlines()[0][:200]
            reason = "timeout" if "Timeout" in str(exc) else f"error: {detail}"
            return (
                PageResult(url=url, final_url=url, html="", status=None,
                           reachable=False, reason=reason),
                None,
            )

    async def close_page(self, page: Page) -> None:
        await page.context.close()


def _looks_like_interstitial(html: str) -> bool:
    lowered = html.lower()
    markers = ("checking your browser", "cloudflare", "captcha", "access denied", "just a moment")
    return any(m in lowered for m in markers) and len(html) < 5000


# Stale-stub detection (2026-08-20 debugging pass, phase 2): a page can
# return HTTP 200 while its entire content is a redirect/moved notice --
# confirmed live on data.gov.dk ("Grunddatamodellen er flyttet" / "this has
# moved", 1282 bytes of HTML total) -- which nothing else in this module
# catches, since it isn't an error status and doesn't match the interstitial
# markers above. Two separate questions in one run both silently landed
# here and were scored as genuine negatives against a dead end. Treated the
# same as any other unreachable page so it flows into the existing
# link-retry path in orchestration/scheduler.py instead of being assessed.
def _looks_like_stale_stub(html: str) -> bool:
    lowered = html.lower()
    markers = (
        "er flyttet",  # Danish: "has moved"
        "siden findes ikke",  # Danish: "the page doesn't exist"
        "findes ikke længere",  # Danish: "no longer exists"
        "has moved",
        "page has been moved",
        "no longer exists",
        "page not found",
    )
    return any(m in lowered for m in markers) and len(html) < 3000
