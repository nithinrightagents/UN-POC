"""Portal sitemap link source (2026-08-21 validation pass).

The fixture below is a trimmed copy of the shape usa.gov actually
publishes -- including the analytics CSV entries and the /health and
/education pages the 50-question run failed to find while those pages sat
in this very file.
"""

from __future__ import annotations

import httpx
import pytest

from shared.state.entities import LinkSource
from shared.tools.linkresolution.sources import sitemap as sitemap_source
from shared.tools.linkresolution.sources.sitemap import (
    fetch_sitemap_urls,
    resolve_from_sitemap,
)

_URLSET = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.usa.gov/</loc></url>
  <url><loc>https://www.usa.gov/health</loc></url>
  <url><loc>https://www.usa.gov/education</loc></url>
  <url><loc>https://www.usa.gov/blog/2016/03/opinion-piece</loc></url>
  <url><loc>https://analytics.usa.gov/data/all-pages-realtime.csv</loc></url>
</urlset>
"""

_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.usa.gov/sitemap-1.xml</loc></sitemap>
</sitemapindex>
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    sitemap_source.clear_cache()
    yield
    sitemap_source.clear_cache()


def _client(routes: dict[str, tuple[int, str]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes.get(str(request.url), (404, ""))
        return httpx.Response(status, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_returns_the_deep_link_matching_the_question() -> None:
    async with _client({"https://www.usa.gov/sitemap.xml": (200, _URLSET)}) as client:
        attempt = await resolve_from_sitemap(
            client, "https://www.usa.gov", order=1, relevance_text="Health sector services"
        )

    assert attempt.usable is True
    assert attempt.returned == "https://www.usa.gov/health"
    assert attempt.source is LinkSource.SITEMAP


@pytest.mark.unit
@pytest.mark.asyncio
async def test_skips_inadmissible_entries_even_when_they_match() -> None:
    """A blog post and a CSV both live in the sitemap; neither is evidence."""
    async with _client({"https://www.usa.gov/sitemap.xml": (200, _URLSET)}) as client:
        attempt = await resolve_from_sitemap(
            client, "https://www.usa.gov", order=1, relevance_text="opinion piece"
        )

    assert attempt.usable is False
    assert "matched the question" in (attempt.rejection_reason or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_returns_nothing_rather_than_guessing() -> None:
    """An unmatched sitemap must not fall back to an arbitrary page -- a
    confidently wrong deep link reads as evidence."""
    async with _client({"https://www.usa.gov/sitemap.xml": (200, _URLSET)}) as client:
        attempt = await resolve_from_sitemap(
            client, "https://www.usa.gov", order=1, relevance_text="Cryptocurrency licensing"
        )

    assert attempt.usable is False
    assert attempt.returned is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_expands_a_sitemap_index_one_level() -> None:
    routes = {
        "https://www.usa.gov/sitemap.xml": (200, _INDEX),
        "https://www.usa.gov/sitemap-1.xml": (200, _URLSET),
    }
    async with _client(routes) as client:
        urls = await fetch_sitemap_urls(client, "https://www.usa.gov")

    assert "https://www.usa.gov/education" in urls
    # Index entries are sitemaps, not pages, and must not survive as candidates.
    assert "https://www.usa.gov/sitemap-1.xml" not in urls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discovers_the_sitemap_through_robots_txt() -> None:
    routes = {
        "https://www.usa.gov/robots.txt": (
            200,
            "User-agent: *\nSitemap: https://www.usa.gov/custom-sitemap.xml\n",
        ),
        "https://www.usa.gov/custom-sitemap.xml": (200, _URLSET),
    }
    async with _client(routes) as client:
        urls = await fetch_sitemap_urls(client, "https://www.usa.gov")

    assert "https://www.usa.gov/health" in urls


@pytest.mark.unit
@pytest.mark.asyncio
async def test_caches_per_origin_across_questions() -> None:
    """A run resolves many questions against one portal; the sitemap is
    fetched once, not once per question."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == "https://www.usa.gov/sitemap.xml":
            return httpx.Response(200, text=_URLSET)
        return httpx.Response(404, text="")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await resolve_from_sitemap(client, "https://www.usa.gov", 1, "Health")
        first_round = len(calls)
        await resolve_from_sitemap(client, "https://www.usa.gov", 1, "Education")

    assert len(calls) == first_round


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reports_an_unreachable_sitemap_distinctly() -> None:
    """"No sitemap published" and "sitemap had no match" need different
    fixes, so they must not share a rejection reason."""
    async with _client({}) as client:
        attempt = await resolve_from_sitemap(client, "https://www.usa.gov", 1, "Health")

    assert attempt.usable is False
    assert "no reachable sitemap" in (attempt.rejection_reason or "")


_AMBIGUOUS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.usa.gov/census-data</loc></url>
  <url><loc>https://www.usa.gov/name-change</loc></url>
  <url><loc>https://www.usa.gov/agencies/office-on-violence-against-women</loc></url>
  <url><loc>https://www.usa.gov/visas</loc></url>
  <url><loc>https://www.usa.gov/search-gov</loc></url>
</urlset>
"""


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question,expected",
    [
        # Accepted: the question owns the slug's head word and covers it.
        ("Entry or Transit Visa", "https://www.usa.gov/visas"),
        ("Search feature", "https://www.usa.gov/search-gov"),
        # Rejected: tail-only match -- the page is about the census.
        ("Legislation on Open Government Data", None),
        # Rejected: head matches but the tail word contradicts the question.
        ("Names and titles of heads of department", None),
        # Rejected: a single incidental word inside a long agency slug.
        ("Legislation against misinformation disinformation", None),
    ],
)
async def test_requires_a_strong_slug_match_before_returning_evidence(
    question: str, expected: str | None
) -> None:
    """This source ranks on the URL alone, so its bar is deliberately higher
    than search's -- everything it rejects still falls through to search,
    which has titles and snippets to judge with."""
    async with _client({"https://www.usa.gov/sitemap.xml": (200, _AMBIGUOUS)}) as client:
        attempt = await resolve_from_sitemap(client, "https://www.usa.gov", 1, question)

    assert attempt.returned == expected


_RELAXED_SHAPES = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.example.gov/citizens/health/vaccination</loc></url>
  <url><loc>https://www.example.gov/en/services/tax/file</loc></url>
</urlset>
"""


@pytest.mark.unit
@pytest.mark.asyncio
async def test_relaxed_slug_matching_accepts_nested_and_locale_paths() -> None:
    """T015: Match anywhere in path without requiring head-word match."""
    async with _client({"https://www.example.gov/sitemap.xml": (200, _RELAXED_SHAPES)}) as client:
        # /citizens/health/vaccination matches health & vaccination despite 'citizens' at head
        attempt1 = await resolve_from_sitemap(
            client, "https://www.example.gov", 1, "Childhood health vaccination services"
        )
        assert attempt1.usable is True
        assert attempt1.returned == "https://www.example.gov/citizens/health/vaccination"

        # /en/services/tax/file matches tax & file
        attempt2 = await resolve_from_sitemap(
            client, "https://www.example.gov", 1, "File income tax online"
        )
        assert attempt2.usable is True
        assert attempt2.returned == "https://www.example.gov/en/services/tax/file"

