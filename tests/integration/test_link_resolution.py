"""Link resolution chain -- US4 independent test (quickstart.md Scenario 4).

Configures each of the three named modes against fixtures where each
source independently succeeds, returns nothing, or returns an unusable
candidate. Verifies consultation order, short-circuit behaviour, and
recorded provenance. No live model or portal traversal needed -- KB/MSQ
are DB-backed fixtures and search uses an injected httpx.MockTransport.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest

from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import MSQLinkCandidate, PriorSurveyLink, new_id
from shared.tools.linkresolution.chain import resolve_link

pytestmark = pytest.mark.integration


@pytest.fixture
def repo() -> Repository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return Repository(conn)


def _gov_search_transport(url_to_return: str | None):
    """A fake DuckDuckGo HTML response containing one result link."""

    def handler(request: httpx.Request) -> httpx.Response:
        if url_to_return:
            html = f'<a class="result__a" href="{url_to_return}">Result</a>'
        else:
            html = "<html><body>no results</body></html>"
        return httpx.Response(200, text=html)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_first_priority_source_short_circuits_later_sources():
    """Given historical_first mode and a usable KB link, MSQ and search must
    never be consulted."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    repo.insert_prior_survey_link(
        PriorSurveyLink(
            link_id=new_id("link"), question_id="q1", country_id="EE",
            url="https://www.eesti.ee", origin_cycle_id="c0", origin_session_id="s0",
        )
    )
    # An MSQ candidate exists too, but must never be reached.
    repo.insert_msq_link_candidate(
        MSQLinkCandidate(
            candidate_id=new_id("msq"), submission_id="sub1", question_id="q1",
            country_id="EE", url="https://msq.example.gov",
        )
    )

    settings = Settings()
    settings.url_resolution_mode = "historical_first"

    client = httpx.AsyncClient(transport=_gov_search_transport(None))
    result = await resolve_link(repo, client, "q1", "EE", "Estonia government portal", settings)

    assert result.resolved_url == "https://www.eesti.ee"
    assert result.supplying_source.value == "prior_survey_kb"
    assert len(result.history) == 1  # search and MSQ never consulted


@pytest.mark.asyncio
async def test_falls_through_when_first_source_yields_nothing():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)
    # No prior-survey link recorded at all.
    repo.insert_msq_link_candidate(
        MSQLinkCandidate(
            candidate_id=new_id("msq"), submission_id="sub1", question_id="q1",
            country_id="EE", url="https://msq.example.gov",
        )
    )

    settings = Settings()
    settings.url_resolution_mode = "historical_first"  # KB -> MSQ -> search
    client = httpx.AsyncClient(transport=_gov_search_transport(None))

    result = await resolve_link(repo, client, "q1", "EE", "Estonia government portal", settings)

    assert result.resolved_url == "https://msq.example.gov"
    assert result.supplying_source.value == "msq"
    assert len(result.history) == 2
    assert result.history[0].source.value == "prior_survey_kb"
    assert result.history[0].usable is False
    assert result.history[1].source.value == "msq"
    assert result.history[1].usable is True


@pytest.mark.parametrize(
    "mode,expected_order",
    [
        ("historical_first", ["prior_survey_kb", "msq", "search"]),
        ("msq_first", ["msq", "prior_survey_kb", "search"]),
        ("search_first", ["search", "prior_survey_kb", "msq"]),
    ],
)
@pytest.mark.asyncio
async def test_each_named_mode_consults_sources_in_its_defined_order(mode, expected_order, repo):
    settings = Settings()
    settings.url_resolution_mode = mode
    client = httpx.AsyncClient(transport=_gov_search_transport(None))  # everything fails -> full history

    result = await resolve_link(repo, client, "q1", "ZZ", "Nowhere government portal", settings)

    assert [a.source.value for a in result.history] == expected_order
    assert result.resolved_url is None  # nothing anywhere resolves


@pytest.mark.asyncio
async def test_search_rejects_non_government_domain(repo):
    settings = Settings()
    settings.url_resolution_mode = "search_first"
    settings.kb_link_source_enabled = False
    settings.msq_link_source_enabled = False

    client = httpx.AsyncClient(transport=_gov_search_transport("https://blog.example.com/estonia-guide"))
    result = await resolve_link(repo, client, "q1", "EE", "Estonia government portal", settings)

    assert result.resolved_url is None
    assert result.history[0].usable is False
    assert "government" in result.history[0].rejection_reason.lower()


@pytest.mark.asyncio
async def test_search_accepts_government_domain(repo):
    settings = Settings()
    settings.url_resolution_mode = "search_first"
    settings.kb_link_source_enabled = False
    settings.msq_link_source_enabled = False

    client = httpx.AsyncClient(transport=_gov_search_transport("https://www.usa.gov/agencies"))
    result = await resolve_link(repo, client, "q1", "US", "USA government portal", settings)

    assert result.resolved_url == "https://www.usa.gov/agencies"
    assert result.supplying_source.value == "search"


@pytest.mark.asyncio
async def test_no_source_yields_anything_produces_full_rejected_history(repo):
    settings = Settings()
    client = httpx.AsyncClient(transport=_gov_search_transport(None))

    result = await resolve_link(repo, client, "q1", "ZZ", "nothing", settings)

    assert result.resolved_url is None
    assert result.supplying_source is None
    assert len(result.history) == 3
    assert all(not a.usable for a in result.history)
    assert all(a.rejection_reason for a in result.history)


@pytest.mark.asyncio
async def test_cross_cycle_msq_candidate_matching(repo):
    """MSQ candidate stored under a different cycle prefix (e.g. cycle1:IF-010)
    must still match a query under a new cycle (e.g. cycle2:IF-010)."""
    repo.insert_msq_link_candidate(
        MSQLinkCandidate(
            candidate_id=new_id("msq"),
            submission_id="sub-dk",
            question_id="cycle-alpha:IF-010",
            country_id="DK",
            url="https://www.borger.dk",
        )
    )

    settings = Settings()
    settings.url_resolution_mode = "historical_first"
    client = httpx.AsyncClient(transport=_gov_search_transport(None))

    result = await resolve_link(
        repo, client, "cycle-beta:IF-010", "DK", "Denmark portal", settings
    )

    assert result.resolved_url == "https://www.borger.dk"
    assert result.supplying_source.value == "msq"


@pytest.mark.asyncio
async def test_portal_default_fallback(repo):
    """When all sources fail, portal_url is used as a fallback if it is a valid government domain."""
    settings = Settings()
    client = httpx.AsyncClient(transport=_gov_search_transport(None))

    result = await resolve_link(
        repo,
        client,
        "q-unfound",
        "DK",
        "Denmark query",
        settings,
        portal_url="https://www.borger.dk",
    )

    assert result.resolved_url == "https://www.borger.dk"
    assert result.supplying_source.value == "portal_default"


def test_bing_redirect_unwrap():
    from shared.tools.linkresolution.sources.search import _unwrap_bing_redirect

    # a1aHR0cHM6Ly9kZW5tYXJrLmRrLw == https://denmark.dk/
    bing_url = "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9kZW5tYXJrLmRrLw&ntb=1"
    assert _unwrap_bing_redirect(bing_url) == "https://denmark.dk/"


def _portal_and_search_transport(sitemap: str, results: list[tuple[str, str]]):
    """A portal whose sitemap is served for real, plus a search engine that
    returns `results` regardless of the query. Lets a test drive the whole
    portal-first-then-widen sequence without live network access."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=sitemap)
        if url.endswith("/robots.txt") or "sitemap" in url:
            return httpx.Response(404, text="")
        html = "".join(
            f'<div class="result"><a class="result__a" href="{link}">{title}</a></div>'
            for link, title in results
        )
        return httpx.Response(200, text=f"<html><body>{html}</body></html>")

    return httpx.MockTransport(handler)


_EMPTY_SITEMAP = (
    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://www.usa.gov/passport</loc></url></urlset>"
)


@pytest.mark.asyncio
async def test_an_irrelevant_portal_page_is_never_returned_as_evidence(repo):
    """When neither the portal nor the open web has anything on topic, the
    answer is the portal homepage -- an honest "we found no page for this"
    -- not a deep link to whatever shared a word with the question."""
    settings = Settings(url_resolution_mode="search_first")
    transport = _portal_and_search_transport(
        _EMPTY_SITEMAP,
        [("https://www.usa.gov/register-to-vote", "How to register to vote")],
    )

    from unittest.mock import AsyncMock, MagicMock
    mock_provider = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '{"index": null}'
    mock_provider.generate = AsyncMock(return_value=mock_resp)

    async with httpx.AsyncClient(transport=transport) as client:
        result = await resolve_link(
            repo, client, "q-055", "us",
            "Online land title registration", settings,
            portal_url="https://www.usa.gov",
            restrict_domain="www.usa.gov",
            relevance_text="Online land title registration",
            provider=mock_provider,
            model="gemini-2.5-flash",
        )

    assert result.resolved_url != "https://www.usa.gov/register-to-vote"
    assert result.supplying_source.value == "portal_default"


@pytest.mark.asyncio
async def test_the_widened_search_uses_the_widened_phrasing(repo):
    """A query written for one portal is the wrong query for the open web.
    "National CIO or equivalent" is unambiguous with the domain attached and
    retrieves trade press without it, so the widened pass must use the
    country-qualified phrasing the caller supplies."""
    settings = Settings(url_resolution_mode="search_first")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=_EMPTY_SITEMAP)
        if url.endswith("/robots.txt") or "sitemap" in url:
            return httpx.Response(404, text="")
        seen.append(url)
        if "United+States" in url or "United%20States" in url:
            link, title = "https://www.councils.gov/cioc/", "Chief Information Officers Council"
        else:
            link, title = "https://www.linkedin.com/company/cio-review", "CIO Review"
        return httpx.Response(
            200,
            text=f'<html><body><div class="result">'
            f'<a class="result__a" href="{link}">{title}</a></div></body></html>',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await resolve_link(
            repo, client, "q-337", "us", "National CIO or equivalent", settings,
            portal_url="https://www.usa.gov",
            restrict_domain="www.usa.gov",
            relevance_text="National CIO or equivalent",
            relevance_detail="Name of the national Chief Information Officer (CIO).",
            widened_query="United States government National CIO or equivalent",
        )

    assert result.resolved_url == "https://www.councils.gov/cioc/"
