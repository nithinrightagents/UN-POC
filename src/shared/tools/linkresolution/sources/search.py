"""Live internet search discovery, restricted to government TLDs (FR-004, FR-121).

Uses a lightweight HTML search endpoint (no paid API key required for the
PoC) and filters candidates to domains that look like official government
domains before returning any of them as usable. An injectable httpx client
keeps this testable without live network access.

2026-08-21 validation pass. Three defects found by replaying the USA
50-question run against the live search APIs, all fixed here:

  * Metadata was thrown away. Firecrawl returns title + description on
    every result; `_fetch_firecrawl_links` kept only `url`. With nothing
    but a URL there was no way to tell a relevant result from an
    irrelevant one, so the resolver took whichever result happened to be
    first on an allowed domain -- which is how "National CIO" resolved to
    `usa.gov/agencies/national-park-service`.

  * A blanket `site:` operator poisoned the result set. `site:usa.gov
    <topic>` returns analytics CSV endpoints, retired go.usa.gov
    shorteners, or nothing at all, while the same topic queried normally
    returns the textbook-correct deep link (`usaspending.gov/search`,
    `sam.gov/fpds`). The operator is now a fallback variant rather than
    the only query, with the domain hint expressed as a plain keyword
    first and the restriction still enforced on acceptance.

  * DuckDuckGo short-circuited the chain. Its branch returned a
    non-usable attempt on any non-empty result page, so the LLM resolver
    and Bing fallback below it were unreachable whenever DDG answered at
    all. Stages now pool their candidates and fall through.
"""

from __future__ import annotations

import asyncio
import random
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from dataclasses import dataclass

from shared.state.entities import LinkSource, ResolutionAttempt
from shared.tools.linkresolution.admissibility import check_admissible
from shared.tools.linkresolution.relevance import choose_best


@dataclass
class Candidate:
    url: str
    title: str = ""
    snippet: str = ""
    position: int = 0


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
    is accepted on its own, gov-label or not.

    For the US the gov label must be the TLD itself. Accepting the label
    anywhere let India's incometax.gov.in through as evidence for a US
    income-tax question (2026-08-21, reproduced live) -- "gov" is a label
    there too, just under a different country's namespace."""
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
        return labels[-1] in {"gov", "mil"}
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


def _text(node: object) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


async def _fetch_ddg_links(
    client: httpx.AsyncClient, query: str, max_results: int
) -> tuple[list[Candidate], str | None]:
    """One HTTP round-trip to the DDG HTML endpoint. Returns (candidates,
    error) -- error is set only on a request-level failure, never on a
    zero-result page."""
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
    candidates: list[Candidate] = []
    for position, anchor in enumerate(soup.select("a.result__a")[:max_results], start=1):
        href = anchor.get("href")
        if not href:
            continue
        # The snippet lives in a sibling of the anchor's enclosing result
        # block; missing markup just means a weaker (not broken) ranking.
        block = anchor.find_parent(class_="result") or anchor.parent
        snippet = _text(block.select_one(".result__snippet")) if block else ""
        candidates.append(
            Candidate(
                url=_unwrap_ddg_redirect(href),
                title=_text(anchor),
                snippet=snippet,
                position=position,
            )
        )
    return candidates, None


async def _fetch_bing_links(
    client: httpx.AsyncClient, query: str, max_results: int
) -> tuple[list[Candidate], str | None]:
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
    candidates: list[Candidate] = []
    for position, block in enumerate(soup.select("li.b_algo")[:max_results], start=1):
        anchor = block.select_one("h2 a")
        href = anchor.get("href") if anchor else None
        if not href:
            continue
        candidates.append(
            Candidate(
                url=_unwrap_bing_redirect(href),
                title=_text(anchor),
                snippet=_text(block.select_one(".b_caption p")),
                position=position,
            )
        )
    return candidates, None


async def _resolve_via_llm(
    provider: object, model: str, query: str, country_id: str | None, portal_url: str | None = None
) -> str | None:
    """Uses LLM knowledge / grounding to find the official government URL."""
    portal_context = f"The national government portal is {portal_url}. " if portal_url else ""
    prompt = (
        f"Find the exact official government webpage URL for country code '{country_id or ''}'. "
        f"{portal_context}Find the specific official citizen service or agency deep URL for the topic: \"{query}\".\n"
        "Return the DEEP link to the page that actually carries the content -- not the site "
        "homepage, not a news or blog article about it.\n"
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
) -> tuple[list[Candidate], str | None]:
    """Fetches clean search results using Firecrawl /v1/search API.

    `title` and `description` are on every result the API returns and are
    what makes relevance ranking possible at all -- an earlier version
    discarded both and kept only the URL.
    """
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
        candidates = [
            Candidate(
                url=item["url"],
                title=item.get("title") or "",
                snippet=item.get("description") or "",
                position=position,
            )
            for position, item in enumerate(items, start=1)
            if item.get("url")
        ]
        return candidates, None
    except Exception as exc:  # noqa: BLE001
        return [], f"firecrawl search failed: {exc}"


def _query_variants(query: str, restrict_domain: str | None) -> list[str]:
    """Query text to try, best-first.

    When restricted, the domain goes in as a plain keyword rather than a
    `site:` operator. Search engines treat the operator as a hard filter
    over their index and fall back to whatever low-value pages on that
    domain they happen to hold -- on `site:usa.gov` that is analytics CSV
    endpoints and dead shorteners. As a keyword it is a ranking signal
    instead, and the restriction is still enforced exactly, on acceptance.
    The operator survives only as a second variant for the case where the
    keyword form surfaced nothing on-domain at all.
    """
    if not restrict_domain:
        return [query]
    apex = _strip_www(restrict_domain)
    return [f"{query} {apex}", f"site:{apex} {query}"]


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
    relevance_text: str | None = None,
    relevance_detail: str | None = None,
    blocked_domains: set[str] | None = None,
) -> ResolutionAttempt:
    """FR-004: only government-TLD candidates are considered at all -- a
    non-government top result is not "returned but rejected", it is never
    surfaced as a candidate in the first place.

    Resilient search: Tries Firecrawl search if API key configured.
    Falls back to DDG, Bing search, and LLM-assisted official portal discovery.
    Each stage pools its candidates, scores every acceptable one for
    relevance to the question, and returns the best -- so one irrelevant
    top result no longer decides the answer, and an empty-handed stage no
    longer prevents the stages below it from running.

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
    later retry attempts pass this as None to allow any government domain.

    `relevance_text` is the question's own wording, used for ranking. It is
    separate from `query` because the query may carry search operators and
    domain hints that say nothing about what the page should contain;
    ranking against those would reward every page on the domain equally.

    `relevance_detail` is the question's longer explanation. It expands the
    acronyms the title uses -- #337 asks for the "National CIO" and the page
    is titled "Chief Information Officers Council" -- but it is written in
    boilerplate shared across indicators, so it ranks at a discount.
    """
    last_error: str | None = None
    excluded = {u for u in (exclude_urls or set())}
    blocked = {b.lower() for b in (blocked_domains or set())}
    rejections: list[str] = []
    seen: set[str] = set()

    def _acceptable(candidate: Candidate) -> str | None:
        """None when admissible, else the reason it was rejected."""
        if not is_government_domain(candidate.url, country_id):
            return "not on a government domain"
        cand_host = _domain(candidate.url).lower()
        if blocked and (cand_host in blocked or any(cand_host.endswith("." + b) for b in blocked)):
            return f"on a blocked host ({cand_host})"
        if restrict_domain and not is_subdomain_of(cand_host, restrict_domain):
            return f"outside the required domain ({restrict_domain})"
        verdict = check_admissible(candidate.url)
        return None if verdict.admissible else verdict.reason

    async def _best(candidates: list[Candidate]) -> Candidate | None:
        """Highest-scoring acceptable candidate, judged semantically by model, falling back deterministically."""
        keep: list[Candidate] = []
        for candidate in candidates:
            if candidate.url in excluded or candidate.url in seen:
                continue
            seen.add(candidate.url)
            reason = _acceptable(candidate)
            if reason is None:
                keep.append(candidate)
            else:
                rejections.append(f"{candidate.url}: {reason}")
        if not keep:
            return None

        # T040/T041: Semantic relevance judge with deterministic fallback
        if provider is not None and model:
            try:
                chosen_idx = await choose_best(
                    provider=provider,
                    model=model,
                    question={"title": relevance_text or query, "what": relevance_detail or ""},
                    candidates=keep,
                )
                if chosen_idx is not None:
                    return keep[chosen_idx]
                rejections.append("no candidate judged relevant by semantic judge")
                return None
            except Exception:
                return keep[0]

        # T041: Fallback when no provider is configured
        return keep[0]

    def _hit(candidate: Candidate) -> ResolutionAttempt:
        return ResolutionAttempt(
            source=LinkSource.SEARCH, order=order, returned=candidate.url, usable=True
        )

    # 1. Primary: Firecrawl search (if API key available).
    if firecrawl_api_key:
        for variant in _query_variants(query, restrict_domain):
            fc_candidates, fc_error = await _fetch_firecrawl_links(
                client, firecrawl_api_key, variant, max_results
            )
            if fc_error is not None:
                last_error = fc_error
                break  # a request-level failure will not fix itself on a reworded query
            best = await _best(fc_candidates)
            if best is not None:
                return _hit(best)

    # 2. Secondary: DuckDuckGo HTML search.
    ddg_query = _query_variants(query, restrict_domain)[0]
    for attempt in range(max_attempts):
        candidates, error = await _fetch_ddg_links(client, ddg_query, max_results)
        if error is None:
            best = await _best(candidates)
            if best is not None:
                return _hit(best)
            break  # DDG answered; a second identical request returns the same page

        last_error = error
        if attempt < max_attempts - 1:
            await asyncio.sleep(_backoff_delay(retry_delay_seconds, attempt))

    # 3. Tertiary: LLM-assisted official deep link resolver (if provider available).
    if provider is not None and model:
        llm_link = await _resolve_via_llm(
            provider, model, relevance_text or query, country_id, portal_url=portal_url
        )
        if llm_link:
            best = await _best([Candidate(url=llm_link, title=relevance_text or query)])
            if best is not None:
                return _hit(best)

    # 4. Quaternary: Bing HTML search fallback.
    bing_candidates, bing_error = await _fetch_bing_links(client, ddg_query, max_results)
    if bing_error is not None:
        last_error = last_error or bing_error
    best = await _best(bing_candidates)
    if best is not None:
        return _hit(best)

    # Report what was actually seen and discarded, not just "no results" --
    # the two failure modes need different fixes and were indistinguishable
    # in the run logs before this.
    if rejections:
        reason = "no admissible government-domain result among the top candidates: " + "; ".join(
            rejections[:5]
        )
    else:
        reason = last_error or "search returned no results after retrying"

    return ResolutionAttempt(
        source=LinkSource.SEARCH,
        order=order,
        returned=None,
        usable=False,
        rejection_reason=reason,
    )
