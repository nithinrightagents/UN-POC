"""Live internet search discovery, restricted to government TLDs (FR-004, FR-121).

Uses a lightweight HTML search endpoint (no paid API key required for the
PoC) and filters candidates to domains that look like official government
domains before returning any of them as usable. An injectable httpx client
keeps this testable without live network access.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from shared.state.entities import LinkSource, ResolutionAttempt

# Deliberately conservative: only TLD/second-level *labels* widely recognized
# as government-restricted namespaces. A production build would source this
# from an authoritative registry rather than a fixed list. Matched against
# whole dot-separated labels, not substrings -- "gov" must be its own label
# (as in example.gov.uk), not just a fragment of a longer word, or an
# unrelated vanity domain like "govdirectory.org" would false-positive since
# "gov" appears as a substring right after a "." from "www.".
_GOV_LABELS = frozenset({"gov", "gob", "gouv", "govt", "go", "mil", "government"})


def is_government_domain(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    host = host.split("@")[-1].split(":")[0]  # strip userinfo@ and :port if present
    labels = host.split(".")
    return any(label in _GOV_LABELS for label in labels)


def _unwrap_ddg_redirect(href: str) -> str:
    """DuckDuckGo's HTML endpoint returns result links as /l/?uddg=<encoded
    target>&rut=... redirect wrappers, not the target URL itself -- checking
    is_government_domain() against the wrapper always sees duckduckgo.com,
    never the actual result site. Unwraps uddg back to the real target;
    returns href unchanged if it isn't one of these wrapper links."""
    parsed = urlparse(href, scheme="https")
    if "duckduckgo.com" not in parsed.netloc and parsed.netloc != "":
        return href
    if parsed.path != "/l/":
        return href
    target = parse_qs(parsed.query).get("uddg")
    return target[0] if target else href


async def search_for_link(
    client: httpx.AsyncClient, query: str, order: int, max_results: int = 10
) -> ResolutionAttempt:
    """FR-004: only government-TLD candidates are considered at all -- a
    non-government top result is not "returned but rejected", it is never
    surfaced as a candidate in the first place."""
    try:
        response = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (EKAP-AIQ-PoC research tool)"},
            timeout=10.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return ResolutionAttempt(
            source=LinkSource.SEARCH, order=order, returned=None, usable=False,
            rejection_reason=f"search request failed: {exc}",
        )

    soup = BeautifulSoup(response.text, "html.parser")
    raw_links = [a.get("href") for a in soup.select("a.result__a")][:max_results]
    links = [_unwrap_ddg_redirect(link) for link in raw_links if link]

    for link in links:
        if is_government_domain(link):
            return ResolutionAttempt(source=LinkSource.SEARCH, order=order, returned=link, usable=True)

    return ResolutionAttempt(
        source=LinkSource.SEARCH, order=order,
        returned=links[0] if links else None,
        usable=False,
        rejection_reason="no result among the top candidates was on a government domain"
        if links
        else "search returned no results",
    )
