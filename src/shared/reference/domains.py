"""Unit code and portal to admissible government domain suffix resolver (spec 016).

Maps target portals, country codes (ISO alpha-2), and city units to their
admissible domain suffixes (e.g. GB -> {"uk"}, US -> {"gov", "mil"},
LON -> {"uk"}).
"""

from __future__ import annotations

import json
import pathlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.state.entities import TargetPortal

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_UN_MEMBER_STATES_PATH = _REPO_ROOT / "data" / "reference" / "un_member_states.json"

# Known ISO alpha-2 code to ccTLD overrides where ccTLD != lower(code)
_ISO_TO_CCTLD_OVERRIDES: dict[str, set[str]] = {
    "GB": {"uk"},
    "UK": {"uk"},
    "US": {"gov", "mil"},
}

# Known city unit codes in the platform to parent country code
_CITY_CODE_TO_PARENT: dict[str, str] = {
    "LON": "GB",
    "MCR": "GB",
    "EDI": "GB",
}


def _load_city_to_country_map() -> dict[str, str]:
    """Build a case-insensitive city-name-to-country-code map from un_member_states.json."""
    if not _UN_MEMBER_STATES_PATH.exists():
        return {}
    try:
        data = json.loads(_UN_MEMBER_STATES_PATH.read_text(encoding="utf-8"))
        mapping = {}
        for c in data.get("countries", []):
            city = c.get("most_populous_city")
            code = c.get("code")
            if city and code:
                mapping[city.lower()] = code
        return mapping
    except Exception:
        return {}


def _load_country_names() -> dict[str, str]:
    """Build an ISO alpha-2 code to country name map from un_member_states.json."""
    if not _UN_MEMBER_STATES_PATH.exists():
        return {}
    try:
        data = json.loads(_UN_MEMBER_STATES_PATH.read_text(encoding="utf-8"))
        return {
            c["code"].upper(): c["name"]
            for c in data.get("countries", [])
            if c.get("code") and c.get("name")
        }
    except Exception:
        return {}


_CITY_NAME_TO_COUNTRY = _load_city_to_country_map()
_COUNTRY_NAMES = _load_country_names()


def jurisdiction_hint(country_id: str | None) -> str:
    """Build a short instruction telling a relevance judge what jurisdiction
    level a candidate link must belong to (spec 016 follow-up, 2026-09).

    Government-domain admissibility (gov/mil-style suffixes) accepts any
    matching page regardless of level of government -- a US state DMV page
    (pa.gov) is just as admissible as the national aggregator
    (usa.gov/state-motor-vehicle-services). The semantic judge never learns
    which level the question actually needs, so a topically-matching but
    jurisdictionally-wrong page can win outright. This hint is appended to
    every relevance-judge prompt so the class of error (not any one
    question) is addressed generically across all countries and indicators.
    """
    if not country_id:
        return ""

    code = country_id.strip().upper()

    if code in _CITY_CODE_TO_PARENT:
        return (
            "Jurisdiction requirement: this assessment targets a LOCAL/city "
            "government. The winning candidate must belong to that city's "
            "own government -- a national/federal page, or another city's "
            "page, does not satisfy this even if it is topically relevant."
        )

    if len(code) == 2:
        name = _COUNTRY_NAMES.get(code, code)
        return (
            f"Jurisdiction requirement: this assessment targets the NATIONAL "
            f"(central/federal) government of {name}. A page belonging to a "
            "state, provincial, regional, county, or municipal government -- "
            "even on a matching domain suffix -- does NOT satisfy a "
            "national-level indicator unless it is explicitly the country's "
            "own designated national aggregator or portal for this service."
        )

    return ""


def resolve_admissible_domain_suffixes(
    portal_or_code: TargetPortal | str | set[str] | list[str] | None = None,
    country_id: str | None = None,
    unit_type: str | None = None,
) -> set[str]:
    """Resolve the set of admissible top-level / ccTLD domain suffixes for a portal or country code.

    Examples:
        - "US" -> {"gov", "mil"}
        - "GB" -> {"uk"}
        - "LON" -> {"uk"}
        - "DK" -> {"dk"}
        - TargetPortal(country_id="LON", unit_type="city") -> {"uk"}
    """
    if portal_or_code is None and country_id is None:
        return set()

    # If already a set/list of suffixes
    if isinstance(portal_or_code, (set, frozenset)):
        return set(portal_or_code)
    if isinstance(portal_or_code, list) and not country_id and all(isinstance(x, str) and len(x) <= 5 for x in portal_or_code):
        return set(portal_or_code)

    # If a TargetPortal object is passed
    target_portal: TargetPortal | None = None
    if hasattr(portal_or_code, "country_id"):
        target_portal = portal_or_code  # type: ignore[assignment]
        if getattr(target_portal, "admissible_domain_suffixes", None):
            return set(target_portal.admissible_domain_suffixes)
        country_id = target_portal.country_id
        if unit_type is None:
            unit_type = getattr(target_portal, "unit_type", None)
    elif isinstance(portal_or_code, str):
        if country_id is None:
            country_id = portal_or_code

    if not country_id:
        return set()

    code = country_id.strip().upper()

    # Direct override check (US, GB, UK)
    if code in _ISO_TO_CCTLD_OVERRIDES:
        return set(_ISO_TO_CCTLD_OVERRIDES[code])

    # City unit check
    if code in _CITY_CODE_TO_PARENT:
        parent_iso = _CITY_CODE_TO_PARENT[code]
        return set(_ISO_TO_CCTLD_OVERRIDES.get(parent_iso, {parent_iso.lower()}))

    if unit_type == "city":
        # Try resolving via display_name or city name
        display_name = getattr(target_portal, "display_name", None) if target_portal else None
        if display_name and display_name.lower() in _CITY_NAME_TO_COUNTRY:
            parent_iso = _CITY_NAME_TO_COUNTRY[display_name.lower()]
            return set(_ISO_TO_CCTLD_OVERRIDES.get(parent_iso, {parent_iso.lower()}))
        # Default city unit without known parent: if in UK context or 3-char code matching city map
        if len(code) == 3:
            return {"uk"}

    # Standard ISO alpha-2 country code: ccTLD matches code lowercase
    if len(code) == 2:
        return {code.lower()}

    # Unknown or non-standard code fallback: return lowercase code
    return {code.lower()}
