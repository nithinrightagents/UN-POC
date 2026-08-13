"""Live internet search discovery, restricted to government TLDs (FR-004, FR-121).

Uses a lightweight HTML search endpoint (no paid API key required for the
PoC) and filters candidates to domains that look like official government
domains before returning any of them as usable. An injectable httpx client
keeps this testable without live network access.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from shared.state.entities import LinkSource, ResolutionAttempt

# Deliberately conservative: only TLD/second-level patterns that are widely
# recognized as government-restricted namespaces. A production build would
# source this from an authoritative registry rather than a fixed list.
_GOV_TLD_PATTERNS = (
    ".gov",
    ".gov.uk",
    ".gob.",
    ".gouv.",
    ".govt.",
    ".go.",  # .go.jp, .go.kr, etc.
    ".mil",
    ".government.",
)


def is_government_domain(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    return any(pattern in f".{host}." for pattern in _GOV_TLD_PATTERNS) or host.endswith(".gov")


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
    links = [a.get("href") for a in soup.select("a.result__a")][:max_results]
    links = [link for link in links if link]

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
