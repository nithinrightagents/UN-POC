"""Heuristic AI pre-fill checker (spec 005 Section 2).

Stands in for the Gemini/Vertex-backed assessor agent (core/llm_factory.py)
while no model credentials are available this session. This is not a fake --
it makes real HTTP requests against real government portals and answers the
handful of real UN EGDI indicators that genuinely are "verifiable, public,
findable without judgment": HTTPS enforcement (#074), sitemap (#005), privacy
policy (#014), social media presence (#007), declared/alternate language as a
proxy for foreign-language support (#015), and a mobile viewport tag as a
proxy for responsive design (#071).

Every other indicator in the real questionnaire (data/questions/
msq_indicators.json) gets a dummy placeholder result instead of nothing --
zero confidence, clearly labeled as not yet assessed -- so every question in
the assessor workflow has an AI-suggestion row to react to, even before a
real (likely LLM-based, now that Vertex AI credentials are wired up) checker
exists for the rest. Swappable behind PrefillResult: a future LLM-backed
checker for the harder, judgment-requiring indicators plugs in beside this
one without touching the callers in src/portal/admin.py and src/portal/seed.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

_SOCIAL_DOMAINS = (
    "facebook.com", "twitter.com", "x.com", "youtube.com",
    "instagram.com", "linkedin.com", "t.me", "whatsapp.com",
)

_TIMEOUT = httpx.Timeout(10.0, connect=6.0)
_HEADERS = {"User-Agent": "EKAP-AIQ-PoC/0.2 (heuristic pre-fill; +un-egovernment-survey-poc)"}


@dataclass
class PrefillResult:
    indicator_id: str
    question_id: str
    answer: bool
    confidence: int
    evidence_url: str
    snippet: str
    reasoning: str


@dataclass
class _PortalFetch:
    base_url: str
    final_url: str
    status_code: int | None
    headers: httpx.Headers | None
    html: str
    soup: BeautifulSoup | None
    robots_text: str | None
    sitemap_ok: bool
    sitemap_url: str


async def _fetch_portal(client: httpx.AsyncClient, base_url: str) -> _PortalFetch:
    html = ""
    soup: BeautifulSoup | None = None
    status_code = None
    headers = None
    final_url = base_url
    try:
        resp = await client.get(base_url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        status_code = resp.status_code
        headers = resp.headers
        final_url = str(resp.url)
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
    except httpx.HTTPError:
        pass

    robots_text: str | None = None
    try:
        robots_url = urljoin(final_url, "/robots.txt")
        r = await client.get(robots_url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        if r.status_code == 200 and "text" in r.headers.get("content-type", "text"):
            robots_text = r.text
    except httpx.HTTPError:
        pass

    sitemap_ok = False
    sitemap_url = urljoin(final_url, "/sitemap.xml")
    try:
        r = await client.get(sitemap_url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        sitemap_ok = r.status_code == 200 and (
            "xml" in r.headers.get("content-type", "") or r.text.strip().startswith("<")
        )
    except httpx.HTTPError:
        pass
    if not sitemap_ok and robots_text and "sitemap:" in robots_text.lower():
        # A robots.txt Sitemap: directive is itself acceptable evidence of a
        # published sitemap, even if /sitemap.xml 404s directly.
        for line in robots_text.splitlines():
            if line.strip().lower().startswith("sitemap:"):
                sitemap_ok = True
                sitemap_url = line.split(":", 1)[1].strip()
                break

    return _PortalFetch(
        base_url=base_url, final_url=final_url, status_code=status_code, headers=headers,
        html=html, soup=soup, robots_text=robots_text, sitemap_ok=sitemap_ok, sitemap_url=sitemap_url,
    )


def _link_text_matches(soup: BeautifulSoup, keywords: list[str]) -> tuple[bool, str]:
    for a in soup.find_all("a"):
        text = (a.get_text() or "").strip().lower()
        href = (a.get("href") or "").lower()
        if any(k in text for k in keywords) or any(k in href for k in keywords):
            snippet = (a.get_text() or "").strip()[:120] or a.get("href", "")[:120]
            return True, snippet
    return False, ""


def _check_https(fetch: _PortalFetch) -> PrefillResult:
    is_https = urlparse(fetch.final_url).scheme == "https"
    return PrefillResult(
        indicator_id="#074", question_id="#074", answer=is_https,
        confidence=95 if fetch.status_code else 40,
        evidence_url=fetch.final_url,
        snippet=f"scheme={urlparse(fetch.final_url).scheme}",
        reasoning="Final resolved URL uses HTTPS." if is_https else "Portal did not resolve to an HTTPS URL.",
    )


def _check_sitemap(fetch: _PortalFetch) -> PrefillResult:
    return PrefillResult(
        indicator_id="#005", question_id="#005", answer=fetch.sitemap_ok,
        confidence=90,
        evidence_url=fetch.sitemap_url,
        snippet="sitemap.xml reachable" if fetch.sitemap_ok else "no sitemap.xml / robots.txt Sitemap: directive found",
        reasoning="A machine-readable sitemap was found." if fetch.sitemap_ok else "No sitemap.xml and no Sitemap: directive in robots.txt.",
    )


def _check_privacy(fetch: _PortalFetch) -> PrefillResult:
    if not fetch.soup:
        return PrefillResult("#014", "#014", False, 30, fetch.final_url, "", "Page did not render.")
    ok, snippet = _link_text_matches(fetch.soup, ["privacy"])
    return PrefillResult(
        "#014", "#014", ok, 80 if ok else 65, fetch.final_url, snippet,
        "A footer/nav link mentioning privacy was found." if ok else "No link mentioning 'privacy' found on the homepage.",
    )


def _check_social(fetch: _PortalFetch) -> PrefillResult:
    if not fetch.soup:
        return PrefillResult("#007", "#007", False, 30, fetch.final_url, "", "Page did not render.")
    found = []
    for a in fetch.soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(d in href for d in _SOCIAL_DOMAINS):
            found.append(a["href"])
    ok = len(found) > 0
    return PrefillResult(
        "#007", "#007", ok, 90, fetch.final_url, ", ".join(found[:3]),
        f"Found {len(found)} social media link(s)." if ok else "No links to known social media domains found.",
    )


def _check_language(fetch: _PortalFetch) -> PrefillResult:
    """Proxy signal for #015 (foreign language support): a declared lang
    attribute plus hreflang alternates suggests multi-language support, but
    doesn't confirm translated content actually exists -- flagged as a weak
    signal in the reasoning so a human assessor knows to verify."""
    if not fetch.soup:
        return PrefillResult("#015", "#015", False, 30, fetch.final_url, "", "Page did not render.")
    html_tag = fetch.soup.find("html")
    lang = html_tag.get("lang") if html_tag else None
    hreflang_count = len(fetch.soup.find_all("link", attrs={"hreflang": True}))
    ok = hreflang_count > 1
    snippet = f"lang={lang!r} hreflang_alternates={hreflang_count}"
    return PrefillResult(
        "#015", "#015", ok, 55, fetch.final_url, snippet,
        "Weak proxy signal only: found more than one hreflang alternate, suggesting translated content may exist -- verify manually."
        if ok else
        "Weak proxy signal only: no hreflang alternates found (a single declared lang doesn't rule out other-language content elsewhere on the portal) -- verify manually.",
    )


def _check_viewport(fetch: _PortalFetch) -> PrefillResult:
    """Proxy signal for #071 (responsive web design): a viewport meta tag is
    necessary but not sufficient for genuine responsive layout, so this is
    flagged as a weak signal rather than a full compliance check."""
    if not fetch.soup:
        return PrefillResult("#071", "#071", False, 30, fetch.final_url, "", "Page did not render.")
    tag = fetch.soup.find("meta", attrs={"name": "viewport"})
    ok = tag is not None
    return PrefillResult(
        "#071", "#071", ok, 55, fetch.final_url,
        str(tag.get("content", "")) if tag else "",
        "Weak proxy signal only: a mobile viewport meta tag is present -- doesn't confirm the layout is actually responsive, verify manually."
        if ok else
        "No viewport meta tag found (page is unlikely to be responsive, but verify manually).",
    )


_CHECKS = [_check_https, _check_sitemap, _check_privacy, _check_social, _check_language, _check_viewport]
_CHECK_INDICATOR_IDS = ["#074", "#005", "#014", "#007", "#015", "#071"]

_DUMMY_REASONING = (
    "Automated pre-fill for this indicator isn't implemented yet -- it needs "
    "judgment this heuristic checker can't provide (only HTTPS, sitemap, "
    "privacy-link, social-media-link, and weak language/responsive-design "
    "proxies are automated so far). A human assessor should evaluate this "
    "one from scratch, or wait for an LLM-based pre-fill pass."
)


def _dummy_result(indicator_id: str, base_url: str) -> PrefillResult:
    return PrefillResult(
        indicator_id=indicator_id, question_id=indicator_id, answer=False,
        confidence=0, evidence_url=base_url, snippet="", reasoning=_DUMMY_REASONING,
    )


async def run_heuristic_prefill(
    client: httpx.AsyncClient, base_url: str, all_indicator_ids: list[str] | None = None,
) -> list[PrefillResult]:
    """Fetch a portal once (plus robots.txt/sitemap.xml) and run every real
    heuristic check against the same fetch, so one unreachable portal
    produces low-confidence 'unreachable' results rather than separate
    timeouts per check. `all_indicator_ids`, when given, is the full set of
    indicator_ids in the active questionnaire; every one of them not covered
    by a real check gets a dummy placeholder result (see module docstring)
    so the caller can always find *something* to key off of per question."""
    fetch = await _fetch_portal(client, base_url)
    if fetch.status_code is None:
        results = [
            PrefillResult(real_id, real_id, False, 15, base_url, "", "Portal was unreachable during the AI pre-fill scan.")
            for real_id in _CHECK_INDICATOR_IDS
        ]
    else:
        results = [check(fetch) for check in _CHECKS]

    if all_indicator_ids:
        covered = {r.indicator_id for r in results}
        results += [_dummy_result(iid, base_url) for iid in all_indicator_ids if iid not in covered]
    return results
