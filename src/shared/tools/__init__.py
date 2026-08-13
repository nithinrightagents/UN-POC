"""Shared cross-agent tools."""

from shared.tools.boundaries import BoundaryCheck, check_authentication_boundary
from shared.tools.browser import BrowserSession, PageResult
from shared.tools.capture import capture_region
from shared.tools.element_ref import build_reference, search_by_text
from shared.tools.language import detect_language

__all__ = [
    "BrowserSession",
    "PageResult",
    "check_authentication_boundary",
    "BoundaryCheck",
    "capture_region",
    "search_by_text",
    "build_reference",
    "detect_language",
]
