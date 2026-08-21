"""URL equivalence normalization and comparison (FR-LD-016).

Compares URLs ignoring differences in:
- Scheme (http vs https)
- www prefix (www.usa.gov vs usa.gov)
- Trailing slashes (/path/ vs /path)
- Default ports (:80, :443)
- URL fragments (#section)
- Tracking parameters (utm_*, gclid, fbclid, etc.)
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_EXACT = {
    "gclid",
    "fbclid",
    "msclkid",
    "dclid",
    "yclid",
    "twclid",
    "igshid",
    "mc_eid",
    "mc_cid",
    "_ga",
    "_gl",
}


def normalize_url(url: str | None) -> str:
    """Normalize a URL string according to FR-LD-016 rules."""
    if not url:
        return ""

    raw = url.strip()
    if not raw:
        return ""

    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+-.]*://", raw):
        raw = "https://" + raw

    parsed = urlparse(raw)

    netloc = parsed.netloc.lower()
    # Strip default ports
    if ":" in netloc:
        host, port = netloc.split(":", 1)
        if (parsed.scheme.lower() == "http" and port == "80") or (
            parsed.scheme.lower() == "https" and port == "443"
        ):
            netloc = host
    else:
        host = netloc

    # Strip www. prefix
    if host.startswith("www."):
        host = host[4:]
        if ":" in netloc:
            port = netloc.split(":", 1)[1]
            netloc = f"{host}:{port}"
        else:
            netloc = host

    # Normalize path: collapse multi-slashes, strip trailing slash except root
    path = parsed.path
    if path:
        path = re.sub(r"/+", "/", path)
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
    else:
        path = "/"

    # Normalize query parameters: strip tracking parameters and sort
    query_params = []
    if parsed.query:
        for k, v in parse_qsl(parsed.query, keep_blank_values=True):
            k_lower = k.lower()
            if any(k_lower.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES):
                continue
            if k_lower in _TRACKING_PARAM_EXACT:
                continue
            query_params.append((k, v))
        query_params.sort()

    query_str = urlencode(query_params) if query_params else ""

    # Return scheme-agnostic representation for comparison
    return f"{netloc}{path}{'?' + query_str if query_str else ''}"


def urls_equivalent(a: str | None, b: str | None) -> bool:
    """Return True if two URLs are equivalent under FR-LD-016 rules."""
    norm_a = normalize_url(a)
    norm_b = normalize_url(b)

    if not norm_a and not norm_b:
        return True
    if not norm_a or not norm_b:
        return False

    return norm_a == norm_b
