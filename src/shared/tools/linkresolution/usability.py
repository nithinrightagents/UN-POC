"""Candidate URL usability test (FR-005).

A syntactic and structural check on a candidate URL, separate from whether
the page is reachable at traversal time (FR-124 requires traversal
regardless, and a URL can be well-formed yet still fail to load -- that
failure is handled by the browser layer, not here).
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class UsabilityCheck:
    usable: bool
    reason: str | None = None


# Raw data-export formats (2026-08-21: search started surfacing
# analytics.usa.gov/**/*.csv as a "usable" resolved link) have no browsable
# page content for the Assessor to evaluate -- traversing one yields an
# empty/garbled page, silently starving the agreement step of a valid
# position. PDF is deliberately excluded: many portals legitimately publish
# their primary evidence (policies, regulations) as a PDF page.
_NON_PAGE_EXTENSIONS = (".csv", ".json", ".xml", ".zip", ".xls", ".xlsx", ".tsv")


def check_usable(url: str | None) -> UsabilityCheck:
    if not url:
        return UsabilityCheck(False, "no candidate URL")

    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001
        return UsabilityCheck(False, "URL could not be parsed")

    if parsed.scheme not in ("http", "https"):
        return UsabilityCheck(False, f"unsupported scheme: {parsed.scheme!r}")

    if not parsed.netloc:
        return UsabilityCheck(False, "URL has no host")

    if "." not in parsed.netloc:
        return UsabilityCheck(False, "host has no domain suffix")

    path = parsed.path.lower()
    if path.endswith(_NON_PAGE_EXTENSIONS):
        ext = path.rsplit(".", 1)[-1]
        return UsabilityCheck(False, f"URL points to a raw data file ({ext}), not a browsable page")

    return UsabilityCheck(True)
