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

    return UsabilityCheck(True)
