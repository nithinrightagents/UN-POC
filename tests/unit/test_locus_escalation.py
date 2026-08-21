"""Evidence-locus enforcement after the locus preference update (spec 010 US2).

The portal is where we look first. If content sits on another recognized government
domain of the same country, evidence_permitted allows it, while non-government
domains or foreign domains are rejected.
"""

from __future__ import annotations

import pytest

from shared.tools.linkresolution.locus import evidence_permitted

_PORTAL = "https://www.usa.gov"


@pytest.mark.unit
def test_portal_evidence_is_always_permitted() -> None:
    permitted, reason = evidence_permitted(
        "national_portal_only", "https://www.usa.gov/health", _PORTAL, country_id="us"
    )

    assert permitted is True
    assert reason is None


@pytest.mark.unit
def test_off_portal_national_evidence_is_permitted() -> None:
    """T030: national_portal_only accepts evidence on other national government domains."""
    permitted, reason = evidence_permitted(
        "national_portal_only", "https://www.cisa.gov/topics/cybersecurity", _PORTAL, country_id="us"
    )

    assert permitted is True
    assert reason is None


@pytest.mark.unit
def test_other_countries_rejected() -> None:
    permitted, reason = evidence_permitted(
        "national_portal_only",
        "https://www.incometax.gov.in/iec/foportal/",
        _PORTAL,
        country_id="us",
    )

    assert permitted is False
    assert "not a recognized government domain" in (reason or "")


@pytest.mark.unit
def test_non_government_sites_rejected() -> None:
    permitted, _ = evidence_permitted(
        "national_portal_only",
        "https://en.wikipedia.org/wiki/Cybersecurity_law",
        _PORTAL,
        country_id="us",
    )

    assert permitted is False


@pytest.mark.unit
def test_any_government_domain_accepts_sibling() -> None:
    permitted, _ = evidence_permitted(
        "any_government_domain", "https://sam.gov/fpds", _PORTAL, country_id="us"
    )

    assert permitted is True
