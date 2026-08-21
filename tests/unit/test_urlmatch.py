import pytest
from benchmark.urlmatch import normalize_url, urls_equivalent


@pytest.mark.parametrize(
    "url_a,url_b",
    [
        # Scheme equivalence
        ("http://usa.gov/health", "https://usa.gov/health"),
        # www prefix
        ("https://www.usa.gov/health", "https://usa.gov/health"),
        ("http://www.usa.gov/health/", "https://usa.gov/health"),
        # Trailing slash
        ("https://usa.gov/health/", "https://usa.gov/health"),
        ("https://usa.gov/", "https://usa.gov"),
        # Default ports
        ("http://usa.gov:80/health", "https://usa.gov/health"),
        ("https://usa.gov:443/health", "https://usa.gov/health"),
        # Fragments
        ("https://usa.gov/health#section1", "https://usa.gov/health"),
        ("https://usa.gov/health#overview", "https://usa.gov/health#details"),
        # Tracking parameters (utm_*, gclid, fbclid)
        (
            "https://usa.gov/health?utm_source=google&utm_medium=cpc&utm_campaign=test",
            "https://usa.gov/health",
        ),
        (
            "https://www.usa.gov/health/?gclid=12345&fbclid=abcde#top",
            "http://usa.gov/health",
        ),
        # Real query parameters preserved and sorted
        (
            "https://usa.gov/search?q=taxes&page=1&utm_source=test",
            "https://www.usa.gov/search/?page=1&q=taxes",
        ),
    ],
)
def test_urls_equivalent_positive_cases(url_a, url_b):
    assert urls_equivalent(url_a, url_b) is True
    assert urls_equivalent(url_b, url_a) is True


@pytest.mark.parametrize(
    "url_a,url_b",
    [
        # Differing hosts
        ("https://usa.gov/health", "https://irs.gov/health"),
        # Differing paths
        ("https://usa.gov/health", "https://usa.gov/education"),
        ("https://usa.gov/health", "https://usa.gov/"),
        # Differing substantive query parameters
        ("https://usa.gov/search?q=taxes", "https://usa.gov/search?q=health"),
        ("https://usa.gov/search?page=1", "https://usa.gov/search?page=2"),
        # One is None
        ("https://usa.gov/health", None),
        (None, "https://usa.gov/health"),
    ],
)
def test_urls_equivalent_negative_cases(url_a, url_b):
    assert urls_equivalent(url_a, url_b) is False
    assert urls_equivalent(url_b, url_a) is False


def test_urls_equivalent_both_none():
    assert urls_equivalent(None, None) is True
    assert urls_equivalent("", "") is True
    assert urls_equivalent(None, "") is True
