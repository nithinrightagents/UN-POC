"""Assessor and unit-assessor mapping reference data loader.

These two functions (list_source_assessors and list_source_mapping) are the
entire replacement seam for the programme's real assessor database (FR-DB-005,
SC-013). When the programme supplies the real external assessor database, these
functions read from it instead. Nothing else in the tree may open either JSON
file.

A malformed source file must fail loudly at load, not silently produce an empty
or incomplete list.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from functools import lru_cache

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
_ASSESSORS_PATH = _REPO_ROOT / "data" / "reference" / "assessors.json"
_MAPPING_PATH = _REPO_ROOT / "data" / "reference" / "unit_assessor_mapping.json"

_VALID_UNIT_TYPES = {"country", "city"}


@dataclass(frozen=True)
class AssessorRef:
    assessor_id: str
    display_name: str
    email: str
    organisation: str = ""
    languages: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class UnitMappingRef:
    unit_type: str
    unit_code: str
    assessor_a_id: str | None = None
    assessor_b_id: str | None = None


@lru_cache(maxsize=1)
def list_source_assessors(path: pathlib.Path | None = None) -> list[AssessorRef]:
    target_path = path or _ASSESSORS_PATH
    raw = target_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"Expected list in {target_path}, got {type(data).__name__}")

    seen_ids: set[str] = set()
    seen_emails: set[str] = set()
    assessors: list[AssessorRef] = []

    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"Malformed assessor record: {item}")
        for req in ("assessor_id", "display_name", "email"):
            if req not in item or not item[req]:
                raise ValueError(f"Missing required key '{req}' in assessor record: {item}")

        assessor_id = str(item["assessor_id"]).strip()
        email = str(item["email"]).strip()
        if assessor_id in seen_ids:
            raise ValueError(f"Duplicate assessor_id: {assessor_id}")
        if email in seen_emails:
            raise ValueError(f"Duplicate assessor email: {email}")

        seen_ids.add(assessor_id)
        seen_emails.add(email)

        languages = item.get("languages", [])
        if isinstance(languages, list):
            lang_tuple = tuple(str(lang) for lang in languages)
        else:
            lang_tuple = ()

        assessors.append(
            AssessorRef(
                assessor_id=assessor_id,
                display_name=str(item["display_name"]).strip(),
                email=email,
                organisation=str(item.get("organisation", "")),
                languages=lang_tuple,
                notes=str(item.get("notes", "")),
            )
        )

    return assessors


@lru_cache(maxsize=1)
def list_source_mapping(path: pathlib.Path | None = None) -> list[UnitMappingRef]:
    target_path = path or _MAPPING_PATH
    raw = target_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"Expected list in {target_path}, got {type(data).__name__}")

    seen_keys: set[tuple[str, str]] = set()
    entries: list[UnitMappingRef] = []

    for item in data:
        if not isinstance(item, dict):
            raise ValueError(f"Malformed mapping entry: {item}")
        for req in ("unit_type", "unit_code"):
            if req not in item or not item[req]:
                raise ValueError(f"Missing required key '{req}' in mapping entry: {item}")

        unit_type = str(item["unit_type"]).strip().lower()
        if unit_type not in _VALID_UNIT_TYPES:
            raise ValueError(f"Unknown unit_type '{unit_type}', expected one of {_VALID_UNIT_TYPES}")

        unit_code = str(item["unit_code"]).strip().upper()
        key = (unit_type, unit_code)
        if key in seen_keys:
            raise ValueError(f"Duplicate mapping entry for key: {key}")
        seen_keys.add(key)

        a_id = item.get("assessor_a_id")
        b_id = item.get("assessor_b_id")

        entries.append(
            UnitMappingRef(
                unit_type=unit_type,
                unit_code=unit_code,
                assessor_a_id=str(a_id).strip() if a_id is not None else None,
                assessor_b_id=str(b_id).strip() if b_id is not None else None,
            )
        )

    return entries
