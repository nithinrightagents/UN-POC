"""Interstitial, challenge-page, and authentication-boundary detection.

Three signals for an authentication boundary, per research R9 -- any one
routes the pair to escalation rather than producing an answer (FR-108,
FR-109). Detection has to bias toward escalation: a false escalation costs
one human review; a false "feature absent" enters delivered results with a
clean, verifiable, and wrong audit trail (the exact failure mode FR-107
through FR-111 exist to prevent).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_LOGIN_URL_MARKERS = re.compile(
    r"(login|signin|sign-in|auth|sso|oauth|identity|account/login)", re.I
)
_LOGIN_CONTENT_MARKERS = [
    re.compile(r"\bsign in\b", re.I),
    re.compile(r"\blog ?in\b", re.I),
    re.compile(r"\bpassword\b", re.I),
    re.compile(r"\busername\b", re.I),
    re.compile(r"forgot.{0,15}password", re.I),
]
_LOGGED_OUT_STATE_MARKERS = [
    re.compile(r"sign in to continue", re.I),
    re.compile(r"please log in", re.I),
    re.compile(r"account required", re.I),
    re.compile(r"members? only", re.I),
]


@dataclass
class BoundaryCheck:
    is_authentication_boundary: bool
    signal: str | None = None  # "navigational" | "structural"
    detail: str | None = None


def check_navigational_boundary(final_url: str) -> BoundaryCheck:
    """Signal 1: the path to the evidence crosses a sign-in form or identity
    provider redirect."""
    if _LOGIN_URL_MARKERS.search(final_url):
        return BoundaryCheck(True, "navigational", f"URL matched login pattern: {final_url}")
    return BoundaryCheck(False)


def check_structural_boundary(html: str) -> BoundaryCheck:
    """Signal 2: the page renders a login form or a logged-out-state notice
    even though the URL itself looked benign."""
    soup = BeautifulSoup(html, "html.parser")

    password_fields = soup.find_all("input", {"type": "password"})
    if password_fields:
        return BoundaryCheck(True, "structural", "page contains a password input field")

    text = soup.get_text(" ", strip=True)
    for pattern in _LOGGED_OUT_STATE_MARKERS:
        if pattern.search(text):
            return BoundaryCheck(True, "structural", f"logged-out marker: {pattern.pattern}")

    login_hits = sum(1 for p in _LOGIN_CONTENT_MARKERS if p.search(text))
    if login_hits >= 2:
        return BoundaryCheck(True, "structural", "multiple login-form content markers present")

    return BoundaryCheck(False)


def check_authentication_boundary(final_url: str, html: str) -> BoundaryCheck:
    nav = check_navigational_boundary(final_url)
    if nav.is_authentication_boundary:
        return nav
    return check_structural_boundary(html)
