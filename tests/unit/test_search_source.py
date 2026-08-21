"""Search link source (2026-08-21 validation pass).

Covers the three defects the live replay of the USA 50-question run
exposed -- discarded result metadata, a blanket `site:` operator, and a
DuckDuckGo branch that short-circuited the stages below it -- plus the
cross-country domain leak found while validating the fix.
"""

from __future__ import annotations

import json

import httpx
import pytest

from shared.tools.linkresolution.sources.search import (
    is_government_domain,
    search_for_link,
)

_FIRECRAWL = "https://api.firecrawl.dev/v1/search"


def _ddg_html(results: list[tuple[str, str, str]]) -> str:
    blocks = "".join(
        f'<div class="result"><a class="result__a" href="{url}">{title}</a>'
        f'<a class="result__snippet">{snippet}</a></div>'
        for url, title, snippet in results
    )
    return f"<html><body>{blocks}</body></html>"


def _bing_html(results: list[tuple[str, str, str]]) -> str:
    blocks = "".join(
        f'<li class="b_algo"><h2><a href="{url}">{title}</a></h2>'
        f'<div class="b_caption"><p>{snippet}</p></div></li>'
        for url, title, snippet in results
    )
    return f"<html><body><ol>{blocks}</ol></body></html>"


class _Recorder:
    """Captures every outbound request so the tests can assert on the
    queries actually issued, not just on the result."""

    def __init__(self, firecrawl=None, ddg: str = "", bing: str = ""):
        self.firecrawl = firecrawl or []
        self.ddg = ddg
        self.bing = bing
        self.queries: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(_FIRECRAWL):
            body = json.loads(request.content)
            self.queries.append(body["query"])
            return httpx.Response(200, json={"data": self.firecrawl})
        self.queries.append(request.url.params.get("q", ""))
        if "duckduckgo" in request.url.host:
            return httpx.Response(200, text=self.ddg)
        return httpx.Response(200, text=self.bing)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ranks_on_result_metadata_rather_than_engine_order() -> None:
    """Firecrawl returns title and description on every result. Discarding
    them is what let #337 "National CIO" resolve to the National Park
    Service page purely because it ranked first."""
    recorder = _Recorder(
        firecrawl=[
            {
                "url": "https://www.usa.gov/agencies/national-park-service",
                "title": "National Park Service | USAGov",
                "description": "Information about national parks.",
            },
            {
                "url": "https://www.usa.gov/agencies/chief-information-officers-council",
                "title": "Chief Information Officers Council | USAGov",
                "description": "The principal interagency forum for federal CIOs.",
            },
        ]
    )
    from unittest.mock import AsyncMock, MagicMock
    mock_provider = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = '{"index": 1}'
    mock_provider.generate = AsyncMock(return_value=mock_resp)

    async with recorder.client() as client:
        attempt = await search_for_link(
            client,
            "National CIO or equivalent",
            order=1,
            country_id="us",
            firecrawl_api_key="test-key",
            relevance_text="National Chief Information Officer or equivalent",
            provider=mock_provider,
            model="gemini-2.5-flash",
        )

    assert attempt.usable is True
    assert attempt.returned.endswith("chief-information-officers-council")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_does_not_lead_with_a_site_operator_when_restricted() -> None:
    """`site:usa.gov <topic>` returns analytics CSVs and dead shorteners
    where the same topic queried plainly returns the real deep link, so the
    operator is a fallback variant, never the first thing tried."""
    recorder = _Recorder(
        firecrawl=[{"url": "https://www.usa.gov/health", "title": "Health | USAGov"}]
    )
    async with recorder.client() as client:
        attempt = await search_for_link(
            client,
            "Health services",
            order=1,
            country_id="us",
            firecrawl_api_key="test-key",
            restrict_domain="www.usa.gov",
            relevance_text="Health services",
        )

    assert attempt.returned == "https://www.usa.gov/health"
    assert "site:" not in recorder.queries[0]
    # The domain still steers the query, just as a term rather than a filter.
    assert "usa.gov" in recorder.queries[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_falls_back_to_the_site_operator_when_nothing_lands_on_domain() -> None:
    recorder = _Recorder(firecrawl=[{"url": "https://example.com/health"}])
    async with recorder.client() as client:
        await search_for_link(
            client,
            "Health services",
            order=1,
            country_id="us",
            firecrawl_api_key="test-key",
            restrict_domain="www.usa.gov",
            relevance_text="Health services",
        )

    assert any(q.startswith("site:usa.gov") for q in recorder.queries)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_fruitless_duckduckgo_page_does_not_block_the_bing_fallback() -> None:
    """DDG used to return a non-usable attempt on any non-empty result
    page, making the LLM resolver and Bing stages below it unreachable."""
    recorder = _Recorder(
        ddg=_ddg_html([("https://example.com/health", "Health", "not a government site")]),
        bing=_bing_html([("https://www.usa.gov/health", "Health | USAGov", "Health topics")]),
    )
    async with recorder.client() as client:
        attempt = await search_for_link(
            client, "Health services", order=1, country_id="us", relevance_text="Health services"
        )

    assert attempt.usable is True
    assert attempt.returned == "https://www.usa.gov/health"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_walks_past_an_inadmissible_top_result() -> None:
    """One bad candidate used to decide the whole source's outcome."""
    recorder = _Recorder(
        firecrawl=[
            {"url": "https://go.usa.gov/xsb6a", "title": "Dead shortener"},
            {"url": "https://analytics.usa.gov/data/health.csv", "title": "Health data"},
            {"url": "https://www.usa.gov/health", "title": "Health | USAGov"},
        ]
    )
    async with recorder.client() as client:
        attempt = await search_for_link(
            client,
            "Health services",
            order=1,
            country_id="us",
            firecrawl_api_key="test-key",
            relevance_text="Health services",
        )

    assert attempt.returned == "https://www.usa.gov/health"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reports_what_it_rejected_rather_than_just_no_results() -> None:
    """"Nothing came back" and "everything that came back was unusable"
    need different fixes and used to share a rejection reason."""
    recorder = _Recorder(firecrawl=[{"url": "https://go.usa.gov/xsb6a", "title": "Health"}])
    async with recorder.client() as client:
        attempt = await search_for_link(
            client,
            "Health services",
            order=1,
            country_id="us",
            firecrawl_api_key="test-key",
            relevance_text="Health services",
        )

    assert attempt.usable is False
    assert "go.usa.gov" in (attempt.rejection_reason or "")


@pytest.mark.unit
@pytest.mark.parametrize(
    "url,country,expected",
    [
        # India's tax portal was returned as evidence for a US income-tax
        # question: "gov" is a label there too, just under .in.
        ("https://www.incometax.gov.in/iec/foportal/", "us", False),
        ("https://www.gov.uk/vat-rates", "us", False),
        ("https://www.dhs.gov.ph/", "us", False),
        ("https://www.irs.gov/payments", "us", True),
        ("https://dmv.ny.gov/driver-license", "us", True),
        ("https://www.marines.mil/", "us", True),
        # Non-US countries keep the ccTLD rule: Denmark publishes official
        # content on ordinary .dk domains with no gov label at all.
        ("https://digst.dk/strategi", "dk", True),
        ("https://www.irs.gov/payments", "dk", False),
    ],
)
def test_government_domain_is_scoped_to_the_country_being_assessed(
    url: str, country: str, expected: bool
) -> None:
    assert is_government_domain(url, country) is expected
