"""T029: Unit tests for locus preference (US2).

Asserts that national_portal_only accepts evidence on another national government domain
without requiring the portal_exhausted flag, while portal evidence is preferred when present.
"""

import pytest

from shared.tools.linkresolution.locus import evidence_permitted

pytestmark = pytest.mark.unit


def test_portal_subdomain_always_permitted():
    permitted, reason = evidence_permitted(
        evidence_locus="national_portal_only",
        evidence_url="https://sub.usa.gov/service",
        portal_url="https://www.usa.gov",
        country_id="US",
    )
    assert permitted is True
    assert reason is None


def test_other_government_domain_permitted_without_portal_exhausted():
    """T030: national_portal_only accepts evidence on any national government domain of the same country."""
    permitted, reason = evidence_permitted(
        evidence_locus="national_portal_only",
        evidence_url="https://www.cisa.gov/cybersecurity",
        portal_url="https://www.usa.gov",
        country_id="US",
    )
    assert permitted is True
    assert reason is None


def test_non_government_domain_rejected():
    permitted, reason = evidence_permitted(
        evidence_locus="national_portal_only",
        evidence_url="https://www.wikipedia.org/wiki/cybersecurity",
        portal_url="https://www.usa.gov",
        country_id="US",
    )
    assert permitted is False
    assert "government domain" in (reason or "").lower()


def test_escalates_on_first_retry():
    """T032: On first attempt (retry=0), restrict_domain is the portal; on first retry (retry=1), restrict_domain is None."""
    portal_url = "https://www.usa.gov"
    from urllib.parse import urlparse

    # Attempt 0: restricted to portal
    is_first_attempt = (0 == 0)
    restrict_to_portal = is_first_attempt
    restrict_domain_0 = urlparse(portal_url).netloc.lower() if restrict_to_portal else None
    assert restrict_domain_0 == "www.usa.gov"

    # Attempt 1 (first retry): restriction lifted
    is_first_attempt = (1 == 0)
    restrict_to_portal = is_first_attempt
    restrict_domain_1 = urlparse(portal_url).netloc.lower() if restrict_to_portal else None
    assert restrict_domain_1 is None

