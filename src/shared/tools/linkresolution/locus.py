"""Evidence-locus enforcement (FR-129–FR-133).

`national_portal_only` questions may only be evidenced from the resolved
portal domain or its subdomains -- evidence found elsewhere does not
satisfy the question and the answer is negative (FR-130).
`any_government_domain` questions may draw evidence from any government
top-level domain reached from the portal (FR-131), subject to the same
rate limits and access policies as the portal itself (FR-132).
"""

from __future__ import annotations

from urllib.parse import urlparse

from shared.tools.linkresolution.sources.search import is_government_domain


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def is_subdomain_of(candidate_domain: str, portal_domain: str) -> bool:
    candidate_domain = candidate_domain.lstrip("www.")
    portal_domain = portal_domain.lstrip("www.")
    return candidate_domain == portal_domain or candidate_domain.endswith("." + portal_domain)


def evidence_permitted(evidence_locus: str, evidence_url: str, portal_url: str) -> tuple[bool, str | None]:
    """Returns (permitted, reason_if_not)."""
    evidence_domain = _domain(evidence_url)
    portal_domain = _domain(portal_url)

    if evidence_locus == "national_portal_only":
        if is_subdomain_of(evidence_domain, portal_domain):
            return True, None
        return False, (
            f"question requires evidence on the national portal ({portal_domain}) "
            f"or its subdomains; evidence was found on {evidence_domain} instead"
        )

    # any_government_domain (FR-131): must still be a government TLD (FR-004 basis).
    if is_subdomain_of(evidence_domain, portal_domain):
        return True, None
    if is_government_domain(evidence_url):
        return True, None
    return False, f"{evidence_domain} is not a recognized government domain"
