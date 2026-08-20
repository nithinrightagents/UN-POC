"""Live internet search discovery, restricted to government TLDs (FR-004, FR-121).

Uses a lightweight HTML search endpoint (no paid API key required for the
PoC) and filters candidates to domains that look like official government
domains before returning any of them as usable. An injectable httpx client
keeps this testable without live network access.
"""

from __future__ import annotations

import asyncio
import random
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from shared.state.entities import LinkSource, ResolutionAttempt

DDG_SEARCH_URL = "https://html.duckduckgo.com/html/"

# Deliberately conservative: only TLD/second-level *labels* widely recognized
# as government-restricted namespaces. A production build would source this
# from an authoritative registry rather than a fixed list. Matched against
# whole dot-separated labels, not substrings -- "gov" must be its own label
# (as in example.gov.uk), not just a fragment of a longer word, or an
# unrelated vanity domain like "govdirectory.org" would false-positive since
# "gov" appears as a substring right after a "." from "www.".
_GOV_LABELS = frozenset({"gov", "gob", "gouv", "govt", "go", "mil", "government"})


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def _strip_www(domain: str) -> str:
    # str.lstrip takes a set of characters, not a prefix -- lstrip("www.")
    # would also eat a genuine leading "w" or "." from an unrelated domain
    # (e.g. "wed.gov" -> "ed.gov", "www2.example.gov" -> "2.example.gov").
    return domain[4:] if domain.startswith("www.") else domain


def is_subdomain_of(candidate_domain: str, portal_domain: str) -> bool:
    candidate_domain = _strip_www(candidate_domain)
    portal_domain = _strip_www(portal_domain)
    return candidate_domain == portal_domain or candidate_domain.endswith("." + portal_domain)


def is_government_domain(url: str, country_id: str | None = None) -> bool:
    """Without a target country, falls back to the original label-only
    check. With one, a gov-pattern label alone is not enough: a domain
    carrying "gov" as a label but hosted on a DIFFERENT country's TLD (a
    Philippines .gov.ph or US .gov result surfacing for a Denmark query)
    must not pass. Conversely, many governments (Denmark's digst.dk among
    them) publish official content on an ordinary ccTLD domain with no
    "gov"-labeled subdomain at all -- for every country except the US
    (whose government namespace is the bare .gov/.mil TLD, not a
    country-code suffix), simply being hosted on that country's own ccTLD
    is accepted on its own, gov-label or not."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001
        return False
    host = host.split("@")[-1].split(":")[0]  # strip userinfo@ and :port if present
    labels = host.split(".")
    if not labels or not labels[-1]:
        return False

    has_gov_label = any(label in _GOV_LABELS for label in labels)
    if country_id is None:
        return has_gov_label

    cctld = country_id.lower()
    if cctld == "us":
        return has_gov_label
    return labels[-1] == cctld


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


def _unwrap_bing_redirect(href: str) -> str:
    """Unwraps Bing redirect wrappers (/ck/a?!...&u=a1<base64_url>) to the real target URL."""
    import base64
    parsed = urlparse(href, scheme="https")
    if "bing.com" in parsed.netloc or parsed.netloc == "":
        u_param = parse_qs(parsed.query).get("u", [""])[0]
        if u_param.startswith("a1"):
            raw = u_param[2:]
            try:
                padded = raw + "=" * ((4 - len(raw) % 4) % 4)
                decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
                if decoded.startswith("http"):
                    return decoded
            except Exception:
                pass
    return href


async def _fetch_ddg_links(
    client: httpx.AsyncClient, query: str, max_results: int
) -> tuple[list[str], str | None]:
    """One HTTP round-trip to the DDG HTML endpoint. Returns (links, error) --
    error is set only on a request-level failure, never on a zero-result page."""
    try:
        response = await client.get(
            DDG_SEARCH_URL,
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (EKAP-AIQ-PoC research tool)"},
            timeout=3.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return [], f"search request failed: {exc}"

    soup = BeautifulSoup(response.text, "html.parser")
    raw_links = [a.get("href") for a in soup.select("a.result__a")][:max_results]
    return [_unwrap_ddg_redirect(link) for link in raw_links if link], None


async def _fetch_bing_links(
    client: httpx.AsyncClient, query: str, max_results: int
) -> tuple[list[str], str | None]:
    """Fallback search using Bing HTML endpoint when DDG is unreachable."""
    try:
        response = await client.get(
            "https://www.bing.com/search",
            params={"q": query},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            timeout=4.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return [], f"bing search failed: {exc}"

    soup = BeautifulSoup(response.text, "html.parser")
    raw_links = [a.get("href") for a in soup.select("li.b_algo h2 a")][:max_results]
    return [_unwrap_bing_redirect(link) for link in raw_links if link], None


async def _resolve_via_llm(
    provider: object, model: str, query: str, country_id: str | None, portal_url: str | None = None
) -> str | None:
    """Uses LLM knowledge / grounding to find the official government URL."""
    portal_context = f"The national government portal is {portal_url}. " if portal_url else ""
    prompt = (
        f"Find the exact official government webpage URL for country code '{country_id or ''}'. "
        f"{portal_context}Find the specific official citizen service or agency deep URL for the topic: \"{query}\".\n"
        "Return ONLY a JSON object: {\"url\": \"https://...\"} containing the official government "
        "portal or agency URL (must be an official government domain for this country), or empty string if not known."
    )
    try:
        resp = await provider.generate(
            model=model,
            system_instruction="You are an expert government web portal link resolver. Return JSON only.",
            prompt=prompt,
            temperature=0.0,
        )
        import json
        text = resp.text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        parsed = json.loads(text)
        url = (parsed.get("url") or "").strip()
        if url and is_government_domain(url, country_id):
            return url
    except Exception:
        pass
    return None


def _backoff_delay(base_delay_seconds: float, attempt: int) -> float:
    """Exponential backoff with jitter."""
    return base_delay_seconds * (2**attempt) + random.uniform(0, base_delay_seconds * 0.5)


async def _fetch_firecrawl_links(
    client: httpx.AsyncClient, api_key: str, query: str, max_results: int = 10
) -> tuple[list[str], str | None]:
    """Fetches clean search results using Firecrawl /v1/search API."""
    if not api_key:
        return [], "no firecrawl api key"
    try:
        resp = await client.post(
            "https://api.firecrawl.dev/v1/search",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "limit": max_results},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        urls = [item.get("url") for item in items if item.get("url")]
        return urls, None
    except Exception as exc:  # noqa: BLE001
        return [], f"firecrawl search failed: {exc}"


async def search_for_link(
    client: httpx.AsyncClient,
    query: str,
    order: int,
    max_results: int = 10,
    country_id: str | None = None,
    max_attempts: int = 2,
    retry_delay_seconds: float = 0.5,
    provider: object | None = None,
    model: str | None = None,
    portal_url: str | None = None,
    exclude_urls: set[str] | None = None,
    firecrawl_api_key: str | None = None,
    restrict_domain: str | None = None,
) -> ResolutionAttempt:
    """FR-004: only government-TLD candidates are considered at all -- a
    non-government top result is not "returned but rejected", it is never
    surfaced as a candidate in the first place.

    Resilient search: Tries Firecrawl search if API key configured.
    Falls back to DDG, Bing search, and LLM-assisted official portal discovery.

    `exclude_urls` (2026-08-20 goal: retry with a different candidate when
    the assessor agent flags the previously-tried link as wrong) skips any
    candidate already attempted for this question, at every stage, so a
    re-invocation surfaces a genuinely different URL instead of repeating
    the same rejected one -- each stage still only returns its single best
    remaining candidate; the caller drives the "try up to N links" loop by
    re-invoking with the growing exclude set.

    `restrict_domain` (2026-08-21 goal: strict-first-try / relaxed-retry
    resolution) narrows candidate acceptance to that domain and its
    subdomains, on top of the government-TLD check -- used to force the
    first resolution attempt onto the target national portal itself, while
    later retry attempts pass this as None to allow any government domain."""
    last_error: str | None = None
    excluded = {u for u in (exclude_urls or set())}

    def _domain_ok(link: str) -> bool:
        if not is_government_domain(link, country_id):
            return False
        if restrict_domain is None:
            return True
        return is_subdomain_of(_domain(link), restrict_domain)

    # Bias the query itself toward the required domain when restricted --
    # cuts down on wasted round-trips where every returned candidate would
    # just be filtered out by _domain_ok anyway. `site:www.example.gov`
    # measurably returns worse-ranked results than the bare apex domain on
    # live Firecrawl (2026-08-21 debugging pass, reproduced directly) --
    # acceptance itself (_domain_ok/is_subdomain_of) already treats both
    # forms as equivalent, so narrowing the query text costs nothing.
    effective_query = (
        f"site:{_strip_www(restrict_domain)} {query}" if restrict_domain else query
    )

    # 1. Primary: Firecrawl search (if API key available)
    if firecrawl_api_key:
        fc_links, fc_error = await _fetch_firecrawl_links(client, firecrawl_api_key, effective_query, max_results)
        if fc_error is None and fc_links:
            for link in fc_links:
                if link in excluded:
                    continue
                if _domain_ok(link):
                    return ResolutionAttempt(
                        source=LinkSource.SEARCH, order=order, returned=link, usable=True
                    )
            remaining = [link for link in fc_links if link not in excluded]
            if remaining:
                last_error = "no result from firecrawl among top candidates was on a government domain"
        else:
            last_error = fc_error

    # 2. Secondary: DuckDuckGo HTML search
    for attempt in range(max_attempts):
        links, error = await _fetch_ddg_links(client, effective_query, max_results)
        if error is None and links:
            for link in links:
                if link in excluded:
                    continue
                if _domain_ok(link):
                    return ResolutionAttempt(
                        source=LinkSource.SEARCH, order=order, returned=link, usable=True
                    )
            remaining = [link for link in links if link not in excluded]
            return ResolutionAttempt(
                source=LinkSource.SEARCH, order=order,
                returned=remaining[0] if remaining else None,
                usable=False,
                rejection_reason="no result among the top candidates was on a government domain",
            )

        last_error = error
        if attempt < max_attempts - 1 and error is None:
            await asyncio.sleep(_backoff_delay(retry_delay_seconds, attempt))

    # 3. Tertiary: LLM-assisted official deep link resolver (if provider available)
    if provider is not None and model:
        llm_link = await _resolve_via_llm(provider, model, query, country_id, portal_url=portal_url)
        if llm_link and llm_link not in excluded and _domain_ok(llm_link):
            return ResolutionAttempt(
                source=LinkSource.SEARCH, order=order, returned=llm_link, usable=True
            )

    # 4. Quaternary: Bing HTML search fallback
    bing_links, bing_error = await _fetch_bing_links(client, effective_query, max_results)
    if bing_links:
        for link in bing_links:
            if link in excluded:
                continue
            if _domain_ok(link):
                return ResolutionAttempt(
                    source=LinkSource.SEARCH, order=order, returned=link, usable=True
                )

    return ResolutionAttempt(
        source=LinkSource.SEARCH, order=order,
        returned=None,
        usable=False,
        rejection_reason=last_error or "search returned no results after retrying",
    )
