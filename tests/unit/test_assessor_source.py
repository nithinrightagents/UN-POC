"""Unit tests for assessor source loading and ingestion (Scenario 0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from portal.assignment import create_units, ingest_assessor_source, staffing_summary
from shared.persistence.repositories import Repository
from shared.reference.assessors import list_source_assessors, list_source_mapping
from shared.state.entities import ProjectType, SurveyCycle, TargetPortal, UnstaffedReason, new_id

pytestmark = pytest.mark.unit


def test_fresh_database_ingests_24_assessors_and_84_mapping_entries(conn):
    repo = Repository(conn)
    summary = ingest_assessor_source(repo)

    assert summary.assessors_written == 24
    assert summary.mapping_entries_written == 84

    assessors = repo.list_assessors()
    assert len(assessors) == 24
    assert any(a.assessor_id == "asr-001" for a in assessors)

    mapping = repo.load_mapping_index()
    assert len(mapping) == 84
    assert ("country", "DK") in mapping
    assert ("city", "KE") in mapping


def test_ingestion_is_idempotent(conn):
    repo = Repository(conn)
    summary1 = ingest_assessor_source(repo)
    assert summary1.assessors_written == 24
    assert summary1.mapping_entries_written == 84

    summary2 = ingest_assessor_source(repo)
    assert summary2.assessors_written == 24
    assert summary2.mapping_entries_written == 84

    assert len(repo.list_assessors()) == 24
    assert len(repo.load_mapping_index()) == 84


def test_mapping_with_duplicate_unit_raises_at_load(tmp_path: Path):
    dup_file = tmp_path / "dup_mapping.json"
    dup_data = [
        {"unit_type": "country", "unit_code": "DK", "assessor_a_id": "asr-001", "assessor_b_id": "asr-002"},
        {"unit_type": "country", "unit_code": "DK", "assessor_a_id": "asr-003", "assessor_b_id": "asr-004"},
    ]
    dup_file.write_text(json.dumps(dup_data), encoding="utf-8")

    list_source_mapping.cache_clear()
    with pytest.raises(ValueError, match="Duplicate mapping entry"):
        list_source_mapping(dup_file)
    list_source_mapping.cache_clear()


def test_mapping_with_unknown_unit_type_raises_at_load(tmp_path: Path):
    bad_file = tmp_path / "bad_unit_type.json"
    bad_data = [
        {"unit_type": "regional", "unit_code": "DK", "assessor_a_id": "asr-001", "assessor_b_id": "asr-002"}
    ]
    bad_file.write_text(json.dumps(bad_data), encoding="utf-8")

    list_source_mapping.cache_clear()
    with pytest.raises(ValueError, match="Unknown unit_type"):
        list_source_mapping(bad_file)
    list_source_mapping.cache_clear()


def test_mapping_missing_required_key_raises_at_load(tmp_path: Path):
    bad_file = tmp_path / "missing_key.json"
    bad_data = [
        {"unit_type": "country", "assessor_a_id": "asr-001", "assessor_b_id": "asr-002"}
    ]
    bad_file.write_text(json.dumps(bad_data), encoding="utf-8")

    list_source_mapping.cache_clear()
    with pytest.raises(ValueError, match="Missing required key"):
        list_source_mapping(bad_file)
    list_source_mapping.cache_clear()


def test_assessors_missing_required_key_raises_at_load(tmp_path: Path):
    bad_file = tmp_path / "bad_assessors.json"
    bad_data = [
        {"display_name": "Ghost", "email": "ghost@example.org"}
    ]
    bad_file.write_text(json.dumps(bad_data), encoding="utf-8")

    list_source_assessors.cache_clear()
    with pytest.raises(ValueError, match="Missing required key"):
        list_source_assessors(bad_file)
    list_source_assessors.cache_clear()


def test_admin_assessors_page_renders_readonly_roster(client, ingested):
    res = client.get("/admin/assessors")
    assert res.status_code == 200
    assert "Assessor Directory" in res.text
    assert "asr-001" in res.text
    assert "Amara Okonkwo" in res.text
    # Read-only confirmation: no edit or delete controls
    assert 'action="/admin/assessors' not in res.text
    assert "Delete" not in res.text
    assert "Edit" not in res.text
    assert "Create" not in res.text


def test_source_swap_preserves_staffing_and_reasons_only_people_differ(conn, tmp_path: Path):
    """Scenario 2 (SC-013): Pointing at a different assessors.json + mapping with identical unit coverage
    yields the exact same staffed/unstaffed units and reasons -- only the people differ."""
    repo = Repository(conn)

    # Initial data
    assessors_v1 = [
        {"assessor_id": "v1-001", "display_name": "Alice One", "email": "alice1@example.org"},
        {"assessor_id": "v1-002", "display_name": "Bob One", "email": "bob1@example.org"},
        {"assessor_id": "v1-003", "display_name": "Charlie One", "email": "charlie1@example.org"},
    ]
    mapping_v1 = [
        {"unit_type": "country", "unit_code": "DK", "assessor_a_id": "v1-001", "assessor_b_id": "v1-002"},
        {"unit_type": "country", "unit_code": "KE", "assessor_a_id": "v1-002", "assessor_b_id": "v1-003"},
        {"unit_type": "country", "unit_code": "FR", "assessor_a_id": "v1-001", "assessor_b_id": "v1-001"},
        {"unit_type": "country", "unit_code": "DE", "assessor_a_id": "v1-999", "assessor_b_id": "v1-002"},
    ]

    f_asr_1 = tmp_path / "assessors_v1.json"
    f_map_1 = tmp_path / "mapping_v1.json"
    f_asr_1.write_text(json.dumps(assessors_v1), encoding="utf-8")
    f_map_1.write_text(json.dumps(mapping_v1), encoding="utf-8")

    list_source_assessors.cache_clear()
    list_source_mapping.cache_clear()
    ingest_assessor_source(repo, assessors_path=f_asr_1, mapping_path=f_map_1)

    cycle_1 = SurveyCycle("c1", "Cycle 1", "ref", [], ProjectType.NATIONAL_OSI)
    repo.insert_cycle(cycle_1)
    portals_1 = [
        TargetPortal(portal_id=new_id("portal"), cycle_id="c1", country_id="DK", resolved_url="url", unit_type="country", display_name="Denmark"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c1", country_id="KE", resolved_url="url", unit_type="country", display_name="Kenya"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c1", country_id="FR", resolved_url="url", unit_type="country", display_name="France"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c1", country_id="DE", resolved_url="url", unit_type="country", display_name="Germany"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c1", country_id="JP", resolved_url="url", unit_type="country", display_name="Japan"),
    ]
    create_units(repo, "c1", portals_1)
    summary_1 = staffing_summary(repo, "c1")
    assignments_1 = {p.country_id: repo.get_unit_assignment("c1", p.portal_id) for p in portals_1}

    # Swapped data (same coverage, different people)
    assessors_v2 = [
        {"assessor_id": "v2-101", "display_name": "Zara Two", "email": "zara2@example.org"},
        {"assessor_id": "v2-102", "display_name": "Yann Two", "email": "yann2@example.org"},
        {"assessor_id": "v2-103", "display_name": "Xavier Two", "email": "xavier2@example.org"},
    ]
    mapping_v2 = [
        {"unit_type": "country", "unit_code": "DK", "assessor_a_id": "v2-101", "assessor_b_id": "v2-102"},
        {"unit_type": "country", "unit_code": "KE", "assessor_a_id": "v2-102", "assessor_b_id": "v2-103"},
        {"unit_type": "country", "unit_code": "FR", "assessor_a_id": "v2-101", "assessor_b_id": "v2-101"},
        {"unit_type": "country", "unit_code": "DE", "assessor_a_id": "v2-999", "assessor_b_id": "v2-102"},
    ]

    f_asr_2 = tmp_path / "assessors_v2.json"
    f_map_2 = tmp_path / "mapping_v2.json"
    f_asr_2.write_text(json.dumps(assessors_v2), encoding="utf-8")
    f_map_2.write_text(json.dumps(mapping_v2), encoding="utf-8")

    list_source_assessors.cache_clear()
    list_source_mapping.cache_clear()
    ingest_assessor_source(repo, assessors_path=f_asr_2, mapping_path=f_map_2)

    cycle_2 = SurveyCycle("c2", "Cycle 2", "ref", [], ProjectType.NATIONAL_OSI)
    repo.insert_cycle(cycle_2)
    portals_2 = [
        TargetPortal(portal_id=new_id("portal"), cycle_id="c2", country_id="DK", resolved_url="url", unit_type="country", display_name="Denmark"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c2", country_id="KE", resolved_url="url", unit_type="country", display_name="Kenya"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c2", country_id="FR", resolved_url="url", unit_type="country", display_name="France"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c2", country_id="DE", resolved_url="url", unit_type="country", display_name="Germany"),
        TargetPortal(portal_id=new_id("portal"), cycle_id="c2", country_id="JP", resolved_url="url", unit_type="country", display_name="Japan"),
    ]
    create_units(repo, "c2", portals_2)
    summary_2 = staffing_summary(repo, "c2")
    assignments_2 = {p.country_id: repo.get_unit_assignment("c2", p.portal_id) for p in portals_2}

    # Verify staffing counts match exactly
    assert summary_1.total_units == summary_2.total_units == 5
    assert summary_1.staffed_units == summary_2.staffed_units == 2
    assert len(summary_1.unstaffed) == len(summary_2.unstaffed) == 3

    # For every unit: staffing status and reasons are identical
    for code in ["DK", "KE"]:
        assert assignments_1[code] is not None and assignments_1[code].is_staffed is True
        assert assignments_2[code] is not None and assignments_2[code].is_staffed is True
        # Only the people differ:
        assert assignments_1[code].role_a.assessor_id.startswith("v1-")
        assert assignments_2[code].role_a.assessor_id.startswith("v2-")
        assert assignments_1[code].role_b.assessor_id.startswith("v1-")
        assert assignments_2[code].role_b.assessor_id.startswith("v2-")

    # FR: DUPLICATE_ASSESSOR
    assert assignments_1["FR"].ingest_defect == UnstaffedReason.DUPLICATE_ASSESSOR
    assert assignments_2["FR"].ingest_defect == UnstaffedReason.DUPLICATE_ASSESSOR

    # DE: UNKNOWN_ASSESSOR
    assert assignments_1["DE"].ingest_defect == UnstaffedReason.UNKNOWN_ASSESSOR
    assert assignments_2["DE"].ingest_defect == UnstaffedReason.UNKNOWN_ASSESSOR

    # JP: None (no assignment row, NO_MAPPING_ENTRY in summary)
    assert assignments_1["JP"] is None
    assert assignments_2["JP"] is None

    p1_jp = next(p.portal_id for p in portals_1 if p.country_id == "JP")
    p2_jp = next(p.portal_id for p in portals_2 if p.country_id == "JP")
    assert summary_1.unstaffed[p1_jp] == UnstaffedReason.NO_MAPPING_ENTRY
    assert summary_2.unstaffed[p2_jp] == UnstaffedReason.NO_MAPPING_ENTRY

    list_source_assessors.cache_clear()
    list_source_mapping.cache_clear()

