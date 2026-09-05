"""Unit tests for the assessment-started freeze (Scenario 8).

Replaces the retired project-level lock. Units and questions freeze once
assessment has actually begun (any human submission or completion declared),
not when assessors are named. Staffed projects with no submissions remain
editable, and assessor override remains available mid-assessment.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portal.assignment import (
    create_units,
    set_role_assignment,
)
from portal.common import session_id_for_cycle
from shared.persistence.repositories import Repository
from shared.questionnaires.registry import delete_questionnaire
from shared.state.entities import (
    AnswerType,
    AssessorRole,
    AssignmentSource,
    EvidenceLocus,
    HumanAssessorSubmission,
    ProjectType,
    Question,
    RoleAssignment,
    SurveyCycle,
    TargetPortal,
    UnitAssessorAssignment,
    UnstaffedReason,
    new_id,
    utcnow,
)

pytestmark = pytest.mark.unit


def _make_cycle(repo: Repository, cycle_id: str) -> SurveyCycle:
    cycle = SurveyCycle(
        cycle_id=cycle_id,
        name="Freeze Test Cycle",
        questionnaire_ref="ref",
        country_set=["DK"],
        project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)
    return cycle


def test_freeze_fully_staffed_project_with_no_submissions_is_editable(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-freeze-unstarted-editable"
    _make_cycle(repo, cycle_id)

    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    repo.insert_portal(portal)
    assignment = UnitAssessorAssignment(
        assignment_id=new_id("asmt"),
        cycle_id=cycle_id,
        portal_id=portal.portal_id,
        role_a=RoleAssignment(assessor_id="asr-001", source=AssignmentSource.MAPPING, set_at=utcnow()),
        role_b=RoleAssignment(assessor_id="asr-007", source=AssignmentSource.MAPPING, set_at=utcnow()),
    )
    repo.upsert_unit_assignment(assignment)

    # Adding a unit works
    resp = client.post(
        f"/admin/projects/{cycle_id}/units",
        data={
            "country_id": "SE",
            "display_name": "Sweden",
            "unit_type": "country",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" not in resp.headers["location"]
    assert any(p.country_id == "SE" for p in repo.list_portals(cycle_id))

    # Adding a question works
    try:
        resp = client.post(
            f"/admin/projects/{cycle_id}/questions",
            data={
                "question_id": "CUST-001",
                "title": "New Indicator",
                "module": "Custom Dimension",
                "evidence_locus": "national_portal_only",
                "what": "what",
                "why": "why",
                "how": "how",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "lock_error=1" not in resp.headers["location"]

        cycle = repo.get_cycle(cycle_id)
        assert cycle.status == "active"
    finally:
        try:
            delete_questionnaire(f"custom_{cycle_id}")
        except Exception:
            pass


def test_freeze_after_human_submission_guarded_routes_redirect_with_lock_error(
    client: TestClient, conn
):
    repo = Repository(conn)
    cycle_id = "test-freeze-work-started"
    _make_cycle(repo, cycle_id)

    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    repo.insert_portal(portal)
    question = Question(
        question_id=new_id("q"),
        cycle_id=cycle_id,
        text="Test indicator",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(question)

    session_id = session_id_for_cycle(cycle_id)
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=question.question_id,
            portal_id=portal.portal_id,
            role=AssessorRole.A,
            assessor_actor_id="asr-001",
            answer=True,
        )
    )

    portals_before = repo.list_portals(cycle_id)
    questions_before = repo.list_questions(cycle_id)

    # Adding unit blocked
    resp = client.post(
        f"/admin/projects/{cycle_id}/units",
        data={"country_id": "NO", "display_name": "Norway", "unit_type": "country"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" in resp.headers["location"]

    # Bulk add units blocked
    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-add",
        data={"country_codes": ["NO"], "unit_type": "country"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" in resp.headers["location"]

    # Adding question blocked
    resp = client.post(
        f"/admin/projects/{cycle_id}/questions",
        data={
            "question_id": "CUST-002",
            "title": "Blocked Indicator",
            "module": "Custom",
            "evidence_locus": "national_portal_only",
            "what": "what",
            "why": "why",
            "how": "how",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" in resp.headers["location"]

    # Retiring question blocked
    resp = client.post(
        f"/admin/projects/{cycle_id}/questions/{question.question_id}/retire",
        data={"actor_id": "senior-reviewer"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" in resp.headers["location"]

    # Removing unit blocked
    resp = client.post(
        f"/admin/projects/{cycle_id}/units/{portal.portal_id}/remove",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" in resp.headers["location"]

    assert repo.list_portals(cycle_id) == portals_before
    assert repo.list_questions(cycle_id) == questions_before


def test_freeze_no_survey_cycle_ever_locked(conn):
    repo = Repository(conn)
    cycle = _make_cycle(repo, "test-never-locked")
    assert cycle.status == "active"
    assert not hasattr(cycle, "assessor_a_email")
    assert not hasattr(cycle, "assessor_b_email")


# --- Scenario 4: Override Tests (T052, SC-005, SC-006, FR-UA-011, FR-MO-004, FR-MO-005, FR-IN-010) ---


def test_override_leaves_siblings_unchanged(client: TestClient, conn, ingested):
    repo = Repository(conn)
    cycle = _make_cycle(repo, "c-override-siblings")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url="https://borger.dk",
            unit_type="country",
            display_name="Denmark",
        ),
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="AF",
            resolved_url="https://gov.af",
            unit_type="country",
            display_name="Afghanistan",
        ),
    ]
    create_units(repo, cycle.cycle_id, portals)

    portal_dk = portals[0]
    portal_af = portals[1]

    # Override Role A on DK to asr-003
    resp = client.post(
        f"/admin/projects/{cycle.cycle_id}/units/{portal_dk.portal_id}/assessors",
        data={"role": "A", "assessor_id": "asr-003", "actor_id": "admin-1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "assign_error" not in resp.headers["location"]

    asmt_dk = repo.get_unit_assignment(cycle.cycle_id, portal_dk.portal_id)
    assert asmt_dk.role_a.assessor_id == "asr-003"
    assert asmt_dk.role_a.source == AssignmentSource.ADMINISTRATOR
    assert asmt_dk.role_b.assessor_id == "asr-007"

    # Sibling AF is untouched
    asmt_af = repo.get_unit_assignment(cycle.cycle_id, portal_af.portal_id)
    assert asmt_af.role_a.assessor_id == "asr-001"
    assert asmt_af.role_a.source == AssignmentSource.MAPPING
    assert asmt_af.role_b.assessor_id == "asr-002"


def test_override_two_projects_same_country_isolated(client: TestClient, conn, ingested):
    repo = Repository(conn)
    cycle_1 = _make_cycle(repo, "c-iso-1")
    cycle_2 = _make_cycle(repo, "c-iso-2")

    portal_1 = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle_1.cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    portal_2 = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle_2.cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    create_units(repo, cycle_1.cycle_id, [portal_1])
    create_units(repo, cycle_2.cycle_id, [portal_2])

    # Override in project 1
    resp = client.post(
        f"/admin/projects/{cycle_1.cycle_id}/units/{portal_1.portal_id}/assessors",
        data={"role": "A", "assessor_id": "asr-003", "actor_id": "admin-1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Project 2 remains untouched
    asmt_2 = repo.get_unit_assignment(cycle_2.cycle_id, portal_2.portal_id)
    assert asmt_2.role_a.assessor_id == "asr-001"
    assert asmt_2.role_a.source == AssignmentSource.MAPPING


def test_override_naming_duplicate_assessor_refused(client: TestClient, conn, ingested):
    repo = Repository(conn)
    cycle = _make_cycle(repo, "c-dup-refuse")
    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle.cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    create_units(repo, cycle.cycle_id, [portal])

    # On DK, Role B is asr-007. Attempting to assign Role A = asr-007 is duplicate
    resp = client.post(
        f"/admin/projects/{cycle.cycle_id}/units/{portal.portal_id}/assessors",
        data={"role": "A", "assessor_id": "asr-007", "actor_id": "admin-1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "assign_error=duplicate" in resp.headers["location"]

    # Assignment row is completely unchanged
    asmt = repo.get_unit_assignment(cycle.cycle_id, portal.portal_id)
    assert asmt.role_a.assessor_id == "asr-001"
    assert asmt.role_b.assessor_id == "asr-007"


def test_override_unknown_assessor_refused(client: TestClient, conn, ingested):
    repo = Repository(conn)
    cycle = _make_cycle(repo, "c-unk-refuse")
    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle.cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    create_units(repo, cycle.cycle_id, [portal])

    resp = client.post(
        f"/admin/projects/{cycle.cycle_id}/units/{portal.portal_id}/assessors",
        data={"role": "A", "assessor_id": "asr-99999", "actor_id": "admin-1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "assign_error=unknown" in resp.headers["location"]

    asmt = repo.get_unit_assignment(cycle.cycle_id, portal.portal_id)
    assert asmt.role_a.assessor_id == "asr-001"


def test_override_clearing_returns_unit_to_unstaffed(client: TestClient, conn, ingested):
    repo = Repository(conn)
    cycle = _make_cycle(repo, "c-clear-unstaffed")
    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle.cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    create_units(repo, cycle.cycle_id, [portal])

    # Clearing Role A with empty assessor_id
    resp = client.post(
        f"/admin/projects/{cycle.cycle_id}/units/{portal.portal_id}/assessors",
        data={"role": "A", "assessor_id": "", "actor_id": "admin-1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "assign_error" not in resp.headers["location"]

    asmt = repo.get_unit_assignment(cycle.cycle_id, portal.portal_id)
    assert asmt.role_a is None
    assert asmt.role_b.assessor_id == "asr-007"
    assert asmt.ingest_defect == UnstaffedReason.CLEARED_BY_ADMINISTRATOR
    assert asmt.is_staffed is False


def test_rerunning_mapping_application_leaves_override_in_place(conn, ingested):
    repo = Repository(conn)
    cycle = _make_cycle(repo, "c-rerun-preserve")
    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle.cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    create_units(repo, cycle.cycle_id, [portal])

    # Administrator sets Role A to asr-003
    set_role_assignment(repo, cycle.cycle_id, portal.portal_id, AssessorRole.A, "asr-003", "admin-1")

    # Re-apply creation/mapping logic
    create_units(repo, cycle.cycle_id, [portal])

    asmt = repo.get_unit_assignment(cycle.cycle_id, portal.portal_id)
    assert asmt.role_a.assessor_id == "asr-003"
    assert asmt.role_a.source == AssignmentSource.ADMINISTRATOR


# --- Scenario 5: Preservation Tests (T053, SC-008, SC-009, FR-MO-006..009, US3 §7, §8) ---


def test_reassignment_preserves_submitted_work_and_incoming_sees_it(client: TestClient, conn, ingested):
    repo = Repository(conn)
    cycle_id = "c-reassign-preservation"
    _make_cycle(repo, cycle_id)
    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle_id,
        country_id="DK",
        resolved_url="https://borger.dk",
        unit_type="country",
        display_name="Denmark",
    )
    question = Question(
        question_id=new_id("q"),
        cycle_id=cycle_id,
        text="Does the digital portal feature public tax returns?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(question)
    create_units(repo, cycle_id, [portal])

    # 1. asr-001 (Role A) submits an answer
    sub_resp = client.post(
        f"/assessor/{cycle_id}/{portal.portal_id}/question/{question.question_id}/submit",
        data={
            "actor_id": "asr-001",
            "answer": "true",
            "evidence_url": "https://borger.dk/tax",
            "notes": "Verified on official tax subpage",
        },
        follow_redirects=False,
    )
    assert sub_resp.status_code == 303

    session_id = session_id_for_cycle(cycle_id)
    sub_before = repo.latest_human_submission(session_id, question.question_id, portal.portal_id, AssessorRole.A)
    assert sub_before is not None
    assert sub_before.answer is True
    assert sub_before.assessor_actor_id == "asr-001"

    # 2. Administrator reassigns Role A to asr-003
    reassign_resp = client.post(
        f"/admin/projects/{cycle_id}/units/{portal.portal_id}/assessors",
        data={"role": "A", "assessor_id": "asr-003", "actor_id": "admin-super"},
        follow_redirects=False,
    )
    assert reassign_resp.status_code == 303

    # 3. Assert submission is still retrievable, unaltered, still attributed to asr-001 (FR-MO-006)
    sub_after = repo.latest_human_submission(session_id, question.question_id, portal.portal_id, AssessorRole.A)
    assert sub_after is not None
    assert sub_after.submission_id == sub_before.submission_id
    assert sub_after.answer == sub_before.answer
    assert sub_after.assessor_actor_id == "asr-001"
    assert sub_after.evidence_url == "https://borger.dk/tax"

    # 4. Incoming assessor (asr-003) sees prior work in Role A (FR-MO-007, SC-008)
    view_resp = client.get(f"/assessor/{cycle_id}/{portal.portal_id}?actor_id=asr-003")
    assert view_resp.status_code == 200
    assert "Active Role: Assessor A" in view_resp.text
    assert "Verified on official tax subpage" in view_resp.text

    # 5. Outgoing assessor (asr-001) is refused with 403 (US3 §7)
    outgoing_resp = client.get(f"/assessor/{cycle_id}/{portal.portal_id}?actor_id=asr-001")
    assert outgoing_resp.status_code == 403
    assert outgoing_resp.text == "You are not assigned to this unit."

    # 6. assignment_changes recorded row with outgoing, incoming, actor, time (FR-MO-008, SC-009)
    changes = repo.list_assignment_changes(cycle_id, portal.portal_id)
    # create_units recorded 2 changes (MAPPING for A and B), override added 1
    admin_changes = [c for c in changes if c.source == "administrator"]
    assert len(admin_changes) == 1
    chg = admin_changes[0]
    assert chg.role == "A"
    assert chg.previous_assessor_id == "asr-001"
    assert chg.new_assessor_id == "asr-003"
    assert chg.changed_by_actor_id == "admin-super"

