"""Page-KIND admissibility (2026-08-21 validation pass).

Every URL in the "rejected" table below was actually delivered by the
resolver during the USA 50-question run and passed the old `check_usable`
test. They are kept verbatim rather than reduced to synthetic examples so
that a regression reproduces the original failure, not an abstraction of it.
"""

from __future__ import annotations

import pytest

from shared.tools.linkresolution.admissibility import (
    check_admissible,
    is_site_root,
    path_depth,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "url,reason_fragment",
    [
        # Data/asset subdomains. These dominated `site:usa.gov` results and
        # accounted for 16 of the run's 21 homepage fall-throughs.
        (
            "https://analytics.usa.gov/data/health-human-services/all-pages-realtime.csv",
            "analytics",
        ),
        ("https://cdn.example.gov/assets/logo-pack", "cdn"),
        # Shorteners GSA retired in 2020, still ranking in search indexes.
        ("https://go.usa.gov/xsb6a", "shortener"),
        ("http://1.usa.gov/1oZYWbv", "shortener"),
    ],
)
def test_rejects_pages_that_are_not_evidence(url: str, reason_fragment: str) -> None:
    verdict = check_admissible(url)

    assert verdict.admissible is False
    assert reason_fragment in (verdict.reason or "").lower()


@pytest.mark.unit
@pytest.mark.parametrize(
    "url",
    [
        # The deep links the run should have found and did not.
        "https://www.usa.gov/health",
        "https://www.usa.gov/education",
        "https://www.usaspending.gov/search",
        "https://sam.gov/fpds",
        "https://www.usa.gov/agency-index/e",
        # Policy/legislation indicators (#336-#341) legitimately cite these,
        # which is why "publications" and "documents" are NOT treated as
        # editorial sections.
        "https://www.gov.uk/government/publications/national-data-strategy",
        "https://digst.dk/documents/strategy",
        # A site root is admissible -- ranking demotes it, this layer does
        # not exclude it, because a handful of indicators genuinely ask
        # about the homepage itself (#003 search bar, #072 last updated).
        "https://www.usa.gov/",
    ],
)
def test_admits_real_content_pages(url: str) -> None:
    assert check_admissible(url).admissible is True


@pytest.mark.unit
def test_inherits_the_syntactic_usability_rules() -> None:
    """Admissibility layers on top of check_usable rather than replacing it,
    so a CSV or a non-http scheme is still rejected here."""
    assert check_admissible(None).admissible is False
    assert check_admissible("ftp://example.gov/file").admissible is False
    assert check_admissible("https://example.gov/data/export.csv").admissible is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.usa.gov", 0),
        ("https://www.usa.gov/", 0),
        ("https://www.usa.gov/health", 1),
        ("https://www.usa.gov/agency-index/e", 2),
        ("https://www.usa.gov/a/b/c/d", 4),
    ],
)
def test_path_depth_counts_segments(url: str, expected: int) -> None:
    assert path_depth(url) == expected
    assert is_site_root(url) is (expected == 0)
