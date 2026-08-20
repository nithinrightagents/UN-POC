"""UN member-state reference data for guided project creation (spec 005 admin UI).

Keeps per-country facts (name, most-populous city) in a data file rather
than branching Python, per the project's standing "no country-specific
code" constraint. Same lazy-load-once pattern as
shared.questionnaires.registry.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from functools import lru_cache

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_DATA_PATH = _REPO_ROOT / "data" / "reference" / "un_member_states.json"


@dataclass(frozen=True)
class CountryRef:
    code: str
    name: str
    most_populous_city: str


@lru_cache(maxsize=1)
def list_countries() -> list[CountryRef]:
    data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return [
        CountryRef(code=c["code"], name=c["name"], most_populous_city=c["most_populous_city"])
        for c in data["countries"]
    ]


def get_country(code: str) -> CountryRef | None:
    for country in list_countries():
        if country.code == code:
            return country
    return None
