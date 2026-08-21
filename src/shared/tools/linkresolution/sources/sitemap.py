"""Portal sitemap link source (2026-08-21 validation pass).

Exploits sitemaps to resolve canonical URLs on the portal directly.
Slug-overlap matching operates locally on sitemap URL paths.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse

import httpx

from shared.state.entities import LinkSource, ResolutionAttempt
from shared.tools.linkresolution.admissibility import check_admissible

_WORD = re.compile(r"[a-z0-9]+")

_STOP_WORDS = frozenset(
    {
        "the", "and", "for", "with", "this", "that", "from", "any", "all",
        "main", "sectors", "sector", "six", "evidence", "online", "services",
        "service", "government", "governments", "gov", "portal", "portals", "website",
        "websites", "either", "page", "section", "sections", "users", "user",
        "ability", "information", "access", "national", "provision", "related",
        "different", "such", "their", "there", "have", "has", "been", "being",
        "provided", "including", "include", "includes", "other", "others",
        "via", "per", "not", "are", "can", "its", "one", "two", "may", "must",
        "these", "those", "which", "when", "where", "what", "how", "why",
        "to", "on", "of", "in", "against", "about",
    }
)

_FRAME_WORDS = frozenset(
    {
        "legislation", "law", "laws", "policy", "policies", "regulation", "regulations",
        "act", "acts", "strategy", "strategies", "plan", "plans", "rules", "bill", "bills",
        "code", "codes", "framework", "frameworks", "names", "name", "titles", "title",
        "heads", "head", "department", "departments", "rights", "right", "citizens", "citizen",
    }
)

# Common locations, tried in order
_WELL_KNOWN_PATHS = ("/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml")
_MAX_CHILD_SITEMAPS = 5
_MAX_URLS = 50_000

_cache: dict[str, list[str]] = {}


def clear_cache() -> None:
    """Test seam -- production code has no reason to call this."""
    _cache.clear()


def _origin(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


async def _get(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        response = await client.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
    except Exception:
        return None
    return response.text


def _parse(xml_text: str) -> tuple[list[str], bool]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], False
    is_index = root.tag.endswith("sitemapindex")
    locs = [(el.text or "").strip() for el in root.findall(".//{*}loc")]
    return [loc for loc in locs if loc], is_index


async def _sitemap_urls_from_robots(client: httpx.AsyncClient, origin: str) -> list[str]:
    body = await _get(client, urljoin(origin, "/robots.txt"))
    if not body:
        return []
    return [
        line.split(":", 1)[1].strip()
        for line in body.splitlines()
        if line.lower().startswith("sitemap:") and ":" in line
    ]


async def fetch_sitemap_urls(client: httpx.AsyncClient, portal_url: str) -> list[str]:
    origin = _origin(portal_url)
    if not origin:
        return []
    if origin in _cache:
        return _cache[origin]

    candidates = await _sitemap_urls_from_robots(client, origin)
    candidates.extend(urljoin(origin, path) for path in _WELL_KNOWN_PATHS)

    collected: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        body = await _get(client, candidate)
        if not body:
            continue
        locs, is_index = _parse(body)
        if is_index:
            page_locs: list[str] = []
            for child in locs[:_MAX_CHILD_SITEMAPS]:
                child_body = await _get(client, child)
                if not child_body:
                    continue
                child_locs, _ = _parse(child_body)
                page_locs.extend(child_locs)
            locs = page_locs
        for loc in locs:
            if loc not in seen:
                seen.add(loc)
                collected.append(loc)
        if collected:
            break

    collected = collected[:_MAX_URLS]
    _cache[origin] = collected
    return collected


def _extract_terms(text: str) -> set[str]:
    words = {w.lower() for w in _WORD.findall(text.lower())}
    return {w for w in words if w not in _STOP_WORDS and len(w) > 1}


def _extract_slug_words(url: str) -> list[str]:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return []
    # Drop locale prefix e.g. /es/
    segments = [s for s in path.split("/") if s]
    if segments and len(segments[0]) == 2:
        segments = segments[1:]
    slug_text = " ".join(segments).lower()
    return [w.lower() for w in _WORD.findall(slug_text) if w not in _STOP_WORDS]


def _match_slug(url: str, terms: set[str], discriminating_terms: set[str]) -> tuple[bool, float]:
    slug_words = _extract_slug_words(url)
    if not slug_words:
        return False, 0.0

    head_word = slug_words[0]

    # Stems/plurals check for head word
    head_matched = any(
        head_word == t or head_word.rstrip("s") == t.rstrip("s")
        for t in terms
    )
    if not head_matched:
        return False, 0.0

    matched = set()
    for sw in slug_words:
        for t in terms:
            if sw == t or sw.rstrip("s") == t.rstrip("s"):
                matched.add(t)

    # Must match at least one discriminating term
    if discriminating_terms and not (matched & discriminating_terms):
        return False, 0.0

    slug_coverage = len(matched) / max(len(slug_words), 1)

    # Strong match requires either matching >= 2 terms or 100% slug coverage
    if len(matched) >= 2 or slug_coverage >= 0.9:
        score = len(matched) * 2.0 + slug_coverage
        return True, score

    return False, 0.0


async def resolve_from_sitemap(
    client: httpx.AsyncClient,
    portal_url: str | None,
    order: int,
    relevance_text: str,
    relevance_detail: str | None = None,
    exclude_urls: set[str] | None = None,
) -> ResolutionAttempt:
    """Best-matching page from the portal's own sitemap, or an unusable attempt."""
    if not portal_url:
        return ResolutionAttempt(
            source=LinkSource.SITEMAP, order=order, returned=None, usable=False,
            rejection_reason="no portal URL registered for this country",
        )

    urls = await fetch_sitemap_urls(client, portal_url)
    if not urls:
        return ResolutionAttempt(
            source=LinkSource.SITEMAP, order=order, returned=None, usable=False,
            rejection_reason=f"no reachable sitemap published at {_origin(portal_url)}",
        )

    terms = _extract_terms(relevance_text)
    if relevance_detail:
        terms |= _extract_terms(relevance_detail)

    if not terms:
        return ResolutionAttempt(
            source=LinkSource.SITEMAP, order=order, returned=None, usable=False,
            rejection_reason="question text carried no distinctive terms to match against",
        )

    discrim_terms = terms - _FRAME_WORDS
    if not discrim_terms:
        discrim_terms = terms

    excluded = exclude_urls or set()
    best_url: str | None = None
    best_score = -1.0

    for url in urls:
        if url in excluded:
            continue
        if not check_admissible(url).admissible:
            continue
        ok, score = _match_slug(url, terms, discrim_terms)
        if ok and score > best_score:
            best_score = score
            best_url = url

    if best_url is None:
        return ResolutionAttempt(
            source=LinkSource.SITEMAP, order=order, returned=None, usable=False,
            rejection_reason=f"no page among {len(urls)} sitemap URLs matched the question's terms",
        )

    return ResolutionAttempt(
        source=LinkSource.SITEMAP, order=order, returned=best_url, usable=True
    )
