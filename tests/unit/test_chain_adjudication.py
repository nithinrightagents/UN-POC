"""Tests for chain-level candidate adjudication and domain-split resolution (T009, T010, T011).

Covers:
- T009: Adjudication with choose_best() selecting search URL (index 1) vs sitemap URL (index 0 / tie-break on None).
- T010: Short-circuit when only one source yields a usable attempt (no judge call made).
- T011: Regression test asserting search_for_link is called with restrict_domain=None while sitemap receives portal_url.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import LinkSource, ResolutionAttempt
from shared.tools.linkresolution.chain import resolve_link

pytestmark = pytest.mark.unit


def _setup_repo():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    return Repository(conn)


@pytest.mark.asyncio
async def test_choose_best_selects_search_when_search_is_better():
    """T009: When both sitemap and search return usable URLs, choose_best returning 1 picks search."""
    repo = _setup_repo()
    http_client = httpx.AsyncClient()
    settings = Settings.defaults()

    sitemap_attempt = ResolutionAttempt(
        source=LinkSource.SITEMAP,
        order=1,
        returned="https://www.usa.gov/general-portal-page",
        usable=True,
    )
    search_attempt = ResolutionAttempt(
        source=LinkSource.SEARCH,
        order=2,
        returned="https://www.cio.gov/about",
        usable=True,
    )

    mock_provider = MagicMock()
    mock_response = MagicMock()
    # Mock judge selecting candidate 1 (search attempt)
    mock_response.text = json.dumps({"index": 1})
    mock_provider.generate = AsyncMock(return_value=mock_response)

    with patch("shared.tools.linkresolution.chain.resolve_from_sitemap", AsyncMock(return_value=sitemap_attempt)), \
         patch("shared.tools.linkresolution.chain.search_for_link", AsyncMock(return_value=search_attempt)), \
         patch("shared.tools.linkresolution.chain.choose_best", AsyncMock(return_value=1)) as mock_judge:

        result = await resolve_link(
            repo=repo,
            http_client=http_client,
            question_id="IF-337",
            country_id="US",
            search_query="National CIO",
            settings=settings,
            portal_url="https://www.usa.gov",
            provider=mock_provider,
            restrict_domain="www.usa.gov",
        )

        assert result.resolved_url == "https://www.cio.gov/about"
        assert result.supplying_source == LinkSource.SEARCH
        assert mock_judge.called


@pytest.mark.asyncio
async def test_choose_best_tie_break_prefers_sitemap_when_judge_returns_none():
    """T009: When judge returns None, portal sitemap is the tie-break winner."""
    repo = _setup_repo()
    http_client = httpx.AsyncClient()
    settings = Settings.defaults()

    sitemap_attempt = ResolutionAttempt(
        source=LinkSource.SITEMAP,
        order=1,
        returned="https://www.usa.gov/health",
        usable=True,
    )
    search_attempt = ResolutionAttempt(
        source=LinkSource.SEARCH,
        order=2,
        returned="https://www.cdc.gov/health",
        usable=True,
    )

    mock_provider = MagicMock()

    with patch("shared.tools.linkresolution.chain.resolve_from_sitemap", AsyncMock(return_value=sitemap_attempt)), \
         patch("shared.tools.linkresolution.chain.search_for_link", AsyncMock(return_value=search_attempt)), \
         patch("shared.tools.linkresolution.chain.choose_best", AsyncMock(return_value=None)):

        result = await resolve_link(
            repo=repo,
            http_client=http_client,
            question_id="SP-166",
            country_id="US",
            search_query="Health services",
            settings=settings,
            portal_url="https://www.usa.gov",
            provider=mock_provider,
            restrict_domain="www.usa.gov",
        )

        assert result.resolved_url == "https://www.usa.gov/health"
        assert result.supplying_source == LinkSource.SITEMAP


@pytest.mark.asyncio
async def test_single_candidate_short_circuit_skips_judge():
    """T010: When sitemap returns nothing usable, search attempt is returned without calling choose_best."""
    repo = _setup_repo()
    http_client = httpx.AsyncClient()
    settings = Settings.defaults()

    sitemap_attempt = ResolutionAttempt(
        source=LinkSource.SITEMAP,
        order=1,
        returned=None,
        usable=False,
        rejection_reason="no_sitemap_match",
    )
    search_attempt = ResolutionAttempt(
        source=LinkSource.SEARCH,
        order=2,
        returned="https://www.login.gov",
        usable=True,
    )

    mock_provider = MagicMock()

    with patch("shared.tools.linkresolution.chain.resolve_from_sitemap", AsyncMock(return_value=sitemap_attempt)), \
         patch("shared.tools.linkresolution.chain.search_for_link", AsyncMock(return_value=search_attempt)), \
         patch("shared.tools.linkresolution.chain.choose_best", AsyncMock()) as mock_judge:

        result = await resolve_link(
            repo=repo,
            http_client=http_client,
            question_id="TECH-022",
            country_id="US",
            search_query="Personal data access",
            settings=settings,
            portal_url="https://www.usa.gov",
            provider=mock_provider,
            restrict_domain="www.usa.gov",
        )

        assert result.resolved_url == "https://www.login.gov"
        assert result.supplying_source == LinkSource.SEARCH
        assert not mock_judge.called


@pytest.mark.asyncio
async def test_search_invoked_unrestricted_when_sitemap_portal_scoped():
    """T011: search_for_link is invoked with restrict_domain=None on attempt #1 while sitemap gets portal_url."""
    repo = _setup_repo()
    http_client = httpx.AsyncClient()
    settings = Settings.defaults()

    sitemap_mock = AsyncMock(
        return_value=ResolutionAttempt(
            source=LinkSource.SITEMAP,
            order=1,
            returned=None,
            usable=False,
        )
    )
    search_mock = AsyncMock(
        return_value=ResolutionAttempt(
            source=LinkSource.SEARCH,
            order=2,
            returned="https://www.epa.gov/air",
            usable=True,
        )
    )

    with patch("shared.tools.linkresolution.chain.resolve_from_sitemap", sitemap_mock), \
         patch("shared.tools.linkresolution.chain.search_for_link", search_mock):

        await resolve_link(
            repo=repo,
            http_client=http_client,
            question_id="SP-166",
            country_id="US",
            search_query="Air quality alerts",
            settings=settings,
            portal_url="https://www.usa.gov",
            restrict_domain="www.usa.gov",
        )

        # Assert sitemap received portal_url
        assert sitemap_mock.called
        assert sitemap_mock.call_args[0][1] == "https://www.usa.gov"

        # Assert search_for_link was invoked with restrict_domain=None (unrestricted)
        assert search_mock.called
        assert search_mock.call_args[1].get("restrict_domain") is None
