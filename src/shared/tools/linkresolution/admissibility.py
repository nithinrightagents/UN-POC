"""Evidence-page admissibility (2026-08-21 validation pass, spec 010 US3).

Performs mechanical admissibility checks: dead shorteners, non-content subdomains,
and check_usable extension checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from shared.tools.linkresolution.usability import check_usable


@dataclass(frozen=True)
class AdmissibilityCheck:
    admissible: bool
    reason: str | None = None


# Subdomains that serve machinery rather than citizen-facing content.
_NON_CONTENT_SUBDOMAIN_LABELS = frozenset(
    {"analytics", "api", "cdn", "static", "assets", "files", "downloads", "s3"}
)

# Retired shorteners.
_DEAD_SHORTENER_HOSTS = frozenset({"go.usa.gov", "1.usa.gov", "go.dhs.gov"})


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().split("@")[-1].split(":")[0]


def _path(url: str) -> str:
    return urlparse(url).path.lower()


def path_depth(url: str) -> int:
    """Number of non-empty path segments. 0 for a site root."""
    return len([seg for seg in _path(url).split("/") if seg])


def is_site_root(url: str) -> bool:
    return path_depth(url) == 0


def check_admissible(url: str | None) -> AdmissibilityCheck:
    """Page-KIND admissibility, layered on top of `check_usable()`."""
    if not url:
        return AdmissibilityCheck(False, check_usable(url).reason)

    host = _host(url)
    if host in _DEAD_SHORTENER_HOSTS:
        return AdmissibilityCheck(
            False, f"{host} is a retired URL shortener, not a content page"
        )

    labels = host.split(".")
    non_content = _NON_CONTENT_SUBDOMAIN_LABELS.intersection(labels)
    if non_content:
        label = sorted(non_content)[0]
        return AdmissibilityCheck(
            False, f"{label!r} subdomain serves data/assets, not browsable content"
        )

    # Frozen web archives and historical snapshots (e.g. 19january2021snapshot.epa.gov).
    if any("snapshot" in part or "archive" in part for part in labels):
        return AdmissibilityCheck(
            False, f"{host} is a frozen archive/snapshot, not live content"
        )

    usability = check_usable(url)
    if not usability.usable:
        return AdmissibilityCheck(False, usability.reason)

    return AdmissibilityCheck(True)
