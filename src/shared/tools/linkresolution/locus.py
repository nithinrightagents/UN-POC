"""Evidence-locus enforcement (FR-129–FR-133, spec 010 US2).

`national_portal_only` is a *preference*, not a lock: portal and subdomains
pass first as preferred, and any government domain of the same country passes as
well (T030). The question is about the country, and the portal is only where we
look first.

`any_government_domain` questions may draw evidence from any government
top-level domain reached from the portal (FR-131), subject to the same
rate limits and access policies as the portal itself (FR-132).
"""

from __future__ import annotations

from urllib.parse import urlparse

from shared.tools.linkresolution.sources.search import is_government_domain, is_subdomain_of


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def evidence_permitted(
    evidence_locus: str,
    evidence_url: str,
    portal_url: str,
    country_id: str | None = None,
    **kwargs,
) -> tuple[bool, str | None]:
    """Returns (permitted, reason_if_not).

    T030: national_portal_only is a preference, not a lock: portal and subdomains
    pass first, and any government domain of the same country passes as well.
    """
    evidence_domain = _domain(evidence_url)
    portal_domain = _domain(portal_url)

    if is_subdomain_of(evidence_domain, portal_domain):
        return True, None

    if not is_government_domain(evidence_url, country_id):
        return False, f"{evidence_domain} is not a recognized government domain"

    return True, None
