"""Tests for cross-domain one-hop navigation in assessor agent (spec 011 T040)."""

from __future__ import annotations

import pytest

from agents.assessor.agent import _extract_same_domain_links


class FakePage:
    def __init__(self, links: list[dict]):
        self._links = links

    async def eval_on_selector_all(self, selector: str, js_func: str):
        return self._links


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_cross_domain_government_links():
    raw_links = [
        {"text": "About USA Services", "href": "https://www.usa.gov/about"},
        {"text": "Short nav", "href": "https://www.usa.gov/nav"},
        {"text": "White House Cabinet List", "href": "https://www.whitehouse.gov/administration/cabinet"},
        {"text": "EPA Citizen Science Program Details", "href": "https://www.epa.gov/innovation/participatory-science"},
        {"text": "Commercial Spam Link", "href": "https://www.google.com/search"},
        {"text": "Retired Shortener", "href": "https://go.usa.gov/xyz123"},
        {"text": "Frozen Archive Snapshot", "href": "https://19january2021snapshot.epa.gov/details"},
    ]
    page = FakePage(raw_links)
    base_url = "https://www.usa.gov"

    candidates = await _extract_same_domain_links(page, base_url, country_id="US")

    candidate_urls = [c["href"] for c in candidates]

    # Valid same-domain and government cross-domain links are present
    assert "https://www.usa.gov/about" in candidate_urls
    assert "https://www.usa.gov/nav" in candidate_urls
    assert "https://www.whitehouse.gov/administration/cabinet" in candidate_urls
    assert "https://www.epa.gov/innovation/participatory-science" in candidate_urls

    # Inadmissible links are excluded
    assert "https://www.google.com/search" not in candidate_urls
    assert "https://go.usa.gov/xyz123" not in candidate_urls
    assert "https://19january2021snapshot.epa.gov/details" not in candidate_urls

    # Same-domain links should come before cross-domain links
    same_domain_indices = [i for i, c in enumerate(candidates) if "usa.gov" in c["href"]]
    cross_domain_indices = [i for i, c in enumerate(candidates) if "usa.gov" not in c["href"]]

    assert max(same_domain_indices) < min(cross_domain_indices)
