"""T027: Unit tests for blocked_domains host-level exclusion in search link resolution.

Asserts that candidate URLs on hosts present in blocked_domains are rejected by _acceptable,
while URLs on unblocked government domains are accepted.
"""

from unittest.mock import AsyncMock

import pytest

from shared.tools.linkresolution.sources.search import Candidate, search_for_link

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_candidate_on_blocked_host_is_rejected():
    mock_client = AsyncMock()

    # When state.gov is blocked, candidates on state.gov should be rejected,
    # and search should return usable=False (or fall through) with rejection reason.
    blocked = {"state.gov", "www.state.gov"}

    # Mock DDG fetch to return a state.gov candidate and an epa.gov candidate
    candidates = [
        Candidate(url="https://www.state.gov/environment/", title="Environment State Dept"),
        Candidate(url="https://www.epa.gov/environment", title="EPA Environment"),
    ]

    import shared.tools.linkresolution.sources.search as search_mod
    orig_fetch_ddg = search_mod._fetch_ddg_links
    orig_fetch_bing = search_mod._fetch_bing_links
    try:
        search_mod._fetch_ddg_links = AsyncMock(return_value=(candidates, None))
        search_mod._fetch_bing_links = AsyncMock(return_value=([], None))

        # 1. With blocked_domains containing state.gov, it should skip state.gov and pick usaspending.gov
        result = await search_for_link(
            client=mock_client,
            query="environment",
            order=1,
            country_id="US",
            blocked_domains=blocked,
            relevance_text="environment",
        )

        assert result.usable is True
        assert result.returned == "https://www.epa.gov/environment"

        # 2. When both hosts are blocked, search should fail to find admissible candidates
        result_all_blocked = await search_for_link(
            client=mock_client,
            query="environment",
            order=1,
            country_id="US",
            blocked_domains={"state.gov", "www.state.gov", "epa.gov", "www.epa.gov"},
            relevance_text="environment",
        )
        assert result_all_blocked.usable is False
        assert "blocked" in (result_all_blocked.rejection_reason or "").lower()

    finally:
        search_mod._fetch_ddg_links = orig_fetch_ddg
        search_mod._fetch_bing_links = orig_fetch_bing
