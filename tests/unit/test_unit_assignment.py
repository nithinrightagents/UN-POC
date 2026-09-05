"""Unit tests for unit-level assessor auto-assignment and staffing (US1, US3, US4)."""

from __future__ import annotations

import pytest

from portal.assignment import create_units, staffing_summary
from shared.persistence.repositories import Repository
from shared.state.entities import (
    Assessor,
    ProjectType,
    SurveyCycle,
    TargetPortal,
    UnstaffedReason,
    new_id,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(conn):
    return Repository(conn)


def _create_test_cycle(
    repo: Repository,
    cycle_id: str,
    project_type: ProjectType = ProjectType.NATIONAL_OSI,
) -> SurveyCycle:
    cycle = SurveyCycle(
        cycle_id=cycle_id,
        name=f"Test Project {cycle_id}",
        questionnaire_ref="test-ref",
        country_set=[],
        project_type=project_type,
    )
    repo.insert_cycle(cycle)
    return cycle


# --- Scenario 1: Staffing Tests (T029, SC-001, FR-IN-003, FR-UA-010) ---


def test_twelve_mapped_country_units_all_auto_staffed(repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-twelve-test", ProjectType.NATIONAL_OSI)
    country_codes = ["AF", "AL", "DZ", "AD", "AO", "AG", "AR", "AM", "AU", "AT", "AZ", "BS"]
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id=code,
            resolved_url=None,
            unit_type="country",
            display_name=f"Country {code}",
        )
        for code in country_codes
    ]

    assignments = create_units(repo, cycle.cycle_id, portals)
    assert len(assignments) == 12

    # Verify every unit is fully staffed
    asmt_dict = repo.list_unit_assignments(cycle.cycle_id)
    assert len(asmt_dict) == 12
    for p in portals:
        asmt = asmt_dict.get(p.portal_id)
        assert asmt is not None
        assert asmt.is_staffed
        assert asmt.role_a is not None
        assert asmt.role_b is not None
        assert asmt.role_a.assessor_id != asmt.role_b.assessor_id

    # At least two distinct A-role assessors across the twelve (SC-001)
    a_role_assessors = {asmt.role_a.assessor_id for asmt in asmt_dict.values()}
    assert len(a_role_assessors) >= 2

    # Staffing summary reports all 12 staffed
    summary = staffing_summary(repo, cycle.cycle_id)
    assert summary.total_units == 12
    assert summary.staffed_units == 12
    assert len(summary.unstaffed) == 0


def test_thirteenth_unit_added_afterwards_staffed_on_creation(repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-thirteen-test", ProjectType.NATIONAL_OSI)
    initial_codes = ["AF", "AL", "DZ", "AD", "AO", "AG", "AR", "AM", "AU", "AT", "AZ", "BS"]
    initial_portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id=code,
            resolved_url=None,
            unit_type="country",
            display_name=code,
        )
        for code in initial_codes
    ]
    create_units(repo, cycle.cycle_id, initial_portals)

    # Add 13th unit (BH is in mapping: asr-001 and asr-003)
    portal_13 = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle.cycle_id,
        country_id="BH",
        resolved_url=None,
        unit_type="country",
        display_name="Bahrain",
    )
    asmt_13_list = create_units(repo, cycle.cycle_id, [portal_13])
    assert len(asmt_13_list) == 1

    asmt_13 = repo.get_unit_assignment(cycle.cycle_id, portal_13.portal_id)
    assert asmt_13 is not None
    assert asmt_13.is_staffed
    assert asmt_13.role_a.assessor_id == "asr-001"
    assert asmt_13.role_b.assessor_id == "asr-003"


def test_losi_city_units_auto_staffed_from_city_mapping(repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-losi-test", ProjectType.LOSI_CITY)
    city_codes = ["CD", "CR", "CI"]  # All present in mapping with unit_type="city"
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id=code,
            resolved_url=None,
            unit_type="city",
            display_name=f"City of {code}",
        )
        for code in city_codes
    ]

    create_units(repo, cycle.cycle_id, portals)
    asmt_dict = repo.list_unit_assignments(cycle.cycle_id)
    assert len(asmt_dict) == 3
    for p in portals:
        asmt = asmt_dict[p.portal_id]
        assert asmt.is_staffed


def test_two_projects_containing_same_country_start_from_same_mapped_pair(repo: Repository, ingested):
    c1 = _create_test_cycle(repo, "c-p1", ProjectType.NATIONAL_OSI)
    c2 = _create_test_cycle(repo, "c-p2", ProjectType.NATIONAL_OSI)

    p1 = TargetPortal(portal_id=new_id("portal"), cycle_id=c1.cycle_id, country_id="AF", resolved_url=None, unit_type="country", display_name="AF")
    p2 = TargetPortal(portal_id=new_id("portal"), cycle_id=c2.cycle_id, country_id="AF", resolved_url=None, unit_type="country", display_name="AF")

    create_units(repo, c1.cycle_id, [p1])
    create_units(repo, c2.cycle_id, [p2])

    asmt_1 = repo.get_unit_assignment(c1.cycle_id, p1.portal_id)
    asmt_2 = repo.get_unit_assignment(c2.cycle_id, p2.portal_id)

    assert asmt_1 is not None and asmt_2 is not None
    assert asmt_1.role_a.assessor_id == asmt_2.role_a.assessor_id == "asr-001"
    assert asmt_1.role_b.assessor_id == asmt_2.role_b.assessor_id == "asr-002"


# --- Scenario 2: Verbatim Tests (T030, SC-004, FR-DB-006) ---


def test_verbatim_mapping_ids_preserved_exactly(repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-verbatim", ProjectType.NATIONAL_OSI)
    portal = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="AU", resolved_url=None, unit_type="country", display_name="Australia")

    create_units(repo, cycle.cycle_id, [portal])
    asmt = repo.get_unit_assignment(cycle.cycle_id, portal.portal_id)

    # In mapping: AU -> asr-017, asr-018
    assert asmt is not None
    assert asmt.role_a.assessor_id == "asr-017"
    assert asmt.role_b.assessor_id == "asr-018"


def test_reingesting_roster_with_altered_descriptive_fields_produces_identical_assignments(repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-reingest", ProjectType.NATIONAL_OSI)
    portal = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="DZ", resolved_url=None, unit_type="country", display_name="Algeria")
    create_units(repo, cycle.cycle_id, [portal])

    asmt_before = repo.get_unit_assignment(cycle.cycle_id, portal.portal_id)
    assert asmt_before is not None

    # Alter assessor's descriptive fields in assessors table
    assessor_5 = repo.get_assessor("asr-005")
    assert assessor_5 is not None
    altered_5 = Assessor(
        assessor_id="asr-005",
        display_name="Altered Name",
        email=assessor_5.email,
        organisation="Nonsense Org",
        languages=["Klingon"],
        notes="Completely rewritten notes",
    )
    repo.upsert_assessor(altered_5)

    # Re-verify assignment is completely untouched
    asmt_after = repo.get_unit_assignment(cycle.cycle_id, portal.portal_id)
    assert asmt_after is not None
    assert asmt_after.role_a.assessor_id == asmt_before.role_a.assessor_id
    assert asmt_after.role_b.assessor_id == asmt_before.role_b.assessor_id


# --- Scenario 3: Defect Refusal Tests (T031, T032, FR-IN-005..009) ---


def test_deliberate_defect_entries_leave_unit_wholly_unstaffed(repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-defects", ProjectType.NATIONAL_OSI)

    # 1. IS: same assessor named twice (asr-004) -> DUPLICATE_ASSESSOR
    p_is = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="IS", resolved_url=None, unit_type="country", display_name="Iceland")
    # 2. MT: only role A named, role B is null -> INCOMPLETE_MAPPING_ENTRY
    p_mt = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="MT", resolved_url=None, unit_type="country", display_name="Malta")
    # 3. LU: assessor_b_id is asr-999 (absent) -> UNKNOWN_ASSESSOR
    p_lu = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="LU", resolved_url=None, unit_type="country", display_name="Luxembourg")

    create_units(repo, cycle.cycle_id, [p_is, p_mt, p_lu])

    asmt_is = repo.get_unit_assignment(cycle.cycle_id, p_is.portal_id)
    assert asmt_is is not None
    assert not asmt_is.is_staffed
    assert asmt_is.role_a is None
    assert asmt_is.role_b is None
    assert asmt_is.ingest_defect == UnstaffedReason.DUPLICATE_ASSESSOR

    asmt_mt = repo.get_unit_assignment(cycle.cycle_id, p_mt.portal_id)
    assert asmt_mt is not None
    assert not asmt_mt.is_staffed
    assert asmt_mt.role_a is None
    assert asmt_mt.role_b is None
    assert asmt_mt.ingest_defect == UnstaffedReason.INCOMPLETE_MAPPING_ENTRY

    asmt_lu = repo.get_unit_assignment(cycle.cycle_id, p_lu.portal_id)
    assert asmt_lu is not None
    assert not asmt_lu.is_staffed
    assert asmt_lu.role_a is None
    assert asmt_lu.role_b is None
    assert asmt_lu.ingest_defect == UnstaffedReason.UNKNOWN_ASSESSOR


def test_uncovered_unit_produces_no_assignment_row(repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-uncovered", ProjectType.NATIONAL_OSI)
    # ZZ is in mapping, but XX is not in mapping at all
    p_uncovered = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle.cycle_id,
        country_id="XX",
        resolved_url=None,
        unit_type="country",
        display_name="Uncovered Land",
    )

    create_units(repo, cycle.cycle_id, [p_uncovered])

    # Absence is meaningful: NO row created in unit_assessor_assignments
    asmt = repo.get_unit_assignment(cycle.cycle_id, p_uncovered.portal_id)
    assert asmt is None

    # Staffing summary reports NO_MAPPING_ENTRY derived from absence
    summary = staffing_summary(repo, cycle.cycle_id)
    assert summary.total_units == 1
    assert summary.staffed_units == 0
    assert summary.unstaffed[p_uncovered.portal_id] == UnstaffedReason.NO_MAPPING_ENTRY


# --- Classification & Form Enforcement Tests (T033, FR-UA-009) ---


def test_unit_type_derived_from_project_type_ignoring_form_override(client, repo: Repository, ingested):
    # Create a National OSI project
    resp = client.post(
        "/admin/projects",
        data={
            "cycle_id": "c-nat-derive",
            "name": "National Derive",
            "question_set_id": "un_osi_2024_master",
            "project_type": "national_osi",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Add a unit posting unit_type="city" -> must be saved as "country"
    resp = client.post(
        "/admin/projects/c-nat-derive/units",
        data={
            "country_id": "DK",
            "display_name": "Denmark",
            "url": "https://www.borger.dk",
            "unit_type": "city",  # Contradicting form value!
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    portal = repo.get_portal_by_country("c-nat-derive", "DK")
    assert portal is not None
    assert portal.unit_type == "country"

    # Create a LOSI project
    resp = client.post(
        "/admin/projects",
        data={
            "cycle_id": "c-losi-derive",
            "name": "LOSI Derive",
            "question_set_id": "un_osi_2024_master",
            "project_type": "losi_city",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Add a unit posting unit_type="country" -> must be saved as "city"
    resp = client.post(
        "/admin/projects/c-losi-derive/units",
        data={
            "country_id": "CD",
            "display_name": "Kinshasa",
            "url": "",
            "unit_type": "country",  # Contradicting form value!
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    portal_losi = repo.get_portal_by_country("c-losi-derive", "CD")
    assert portal_losi is not None
    assert portal_losi.unit_type == "city"


# --- US4 Reporting Tests (T058, T059, FR-SV-001..003) ---


def test_unstaffed_reasons_rendered_in_plain_words_and_counts_match(client, repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-us4-render", ProjectType.NATIONAL_OSI)
    # 1 staffed (AF), 1 no_mapping_entry (XX), 1 duplicate (IS), 1 incomplete (MT), 1 unknown (LU)
    p_af = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="AF", resolved_url=None, unit_type="country", display_name="Afghanistan")
    p_xx = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="XX", resolved_url=None, unit_type="country", display_name="Unknown Land")
    p_is = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="IS", resolved_url=None, unit_type="country", display_name="Iceland")
    p_mt = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="MT", resolved_url=None, unit_type="country", display_name="Malta")
    p_lu = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="LU", resolved_url=None, unit_type="country", display_name="Luxembourg")

    create_units(repo, cycle.cycle_id, [p_af, p_xx, p_is, p_mt, p_lu])

    summary = staffing_summary(repo, cycle.cycle_id)
    assert summary.total_units == 5
    assert summary.staffed_units == 1
    assert len(summary.unstaffed) == 4

    resp = client.get(f"/admin/projects/{cycle.cycle_id}")
    assert resp.status_code == 200
    html = resp.text

    # Assert plain wording for each reason
    assert "1 of 5 units staffed" in html
    assert "No entry in the assessor database for this unit." in html
    assert "The assessor database names the same person for both roles." in html
    assert "Only one role is named in the assessor database." in html
    assert "The assessor database names an assessor who is not on record." in html


def test_assign_unstaffed_by_hand_preserves_already_staffed(client, repo: Repository, ingested):
    cycle = _create_test_cycle(repo, "c-us4-hand", ProjectType.NATIONAL_OSI)
    p_staffed = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="AF", resolved_url=None, unit_type="country", display_name="Afghanistan")
    p_unstaffed = TargetPortal(portal_id=new_id("portal"), cycle_id=cycle.cycle_id, country_id="IS", resolved_url=None, unit_type="country", display_name="Iceland")

    create_units(repo, cycle.cycle_id, [p_staffed, p_unstaffed])
    asmt_staffed_before = repo.get_unit_assignment(cycle.cycle_id, p_staffed.portal_id)
    assert asmt_staffed_before is not None and asmt_staffed_before.is_staffed

    # Assign role A and B by hand on p_unstaffed via portal POST
    resp_a = client.post(
        f"/admin/projects/{cycle.cycle_id}/units/{p_unstaffed.portal_id}/assessors",
        data={"role": "A", "assessor_id": "asr-010", "actor_id": "senior-reviewer"},
        follow_redirects=False,
    )
    assert resp_a.status_code == 303
    assert resp_a.headers["location"] == f"/admin/projects/{cycle.cycle_id}"

    resp_b = client.post(
        f"/admin/projects/{cycle.cycle_id}/units/{p_unstaffed.portal_id}/assessors",
        data={"role": "B", "assessor_id": "asr-011", "actor_id": "senior-reviewer"},
        follow_redirects=False,
    )
    assert resp_b.status_code == 303

    # On redirect to project detail, the newly staffed unit is visible immediately (FR-SV-003)
    resp_page = client.get(f"/admin/projects/{cycle.cycle_id}")
    assert resp_page.status_code == 200
    assert "2 of 2 units staffed" in resp_page.text

    # Verify previously staffed unit is completely preserved
    asmt_staffed_after = repo.get_unit_assignment(cycle.cycle_id, p_staffed.portal_id)
    assert asmt_staffed_after == asmt_staffed_before

