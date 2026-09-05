"""Unit tests for assignment-gated assessor access (US2).

Covers FR-AC-001..005, FR-UA-004, FR-UA-005, FR-UA-007, SC-007, SC-012,
and contracts/assignment-gated-access.md §5 (T043, T044, T045).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portal.assignment import clear_role_assignment, create_units
from portal.common import ensure_session
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    AssessorRole,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def repo(conn):
    return Repository(conn)


def _make_cycle_and_questions(repo: Repository, cycle_id: str) -> tuple[SurveyCycle, list[Question]]:
    cycle = SurveyCycle(
        cycle_id=cycle_id,
        name=f"Access Test Cycle {cycle_id}",
        questionnaire_ref="test-ref",
        country_set=[],
        project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)

    questions = [
        Question(
            question_id=f"{cycle_id}:Q.1",
            cycle_id=cycle_id,
            text="Does the classified national portal exist?",
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            answer_type=AnswerType.BINARY,
        ),
        Question(
            question_id=f"{cycle_id}:Q.2",
            cycle_id=cycle_id,
            text="Are open data standards documented?",
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            answer_type=AnswerType.BINARY,
        ),
    ]
    for q in questions:
        repo.insert_question(q)

    return cycle, questions


# --- Scenario 6: Assigned Access Tests (T043, FR-AC-002, FR-UA-004, US2 §1, §3, §4) ---


def test_assigned_assessor_opens_unit_in_assigned_role_without_supplying_role(
    client: TestClient, repo: Repository, ingested
):
    cycle, questions = _make_cycle_and_questions(repo, "c-access-role-a")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url="https://borger.dk",
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)

    # In mapping, DK has A = asr-001, B = asr-007
    portal = portals[0]
    resp = client.get(f"/assessor/{cycle.cycle_id}/{portal.portal_id}?actor_id=asr-001")
    assert resp.status_code == 200
    assert "Active Role: Assessor A" in resp.text
    assert "Active Role: Assessor B" not in resp.text


def test_b_role_assignee_passing_role_a_placed_in_b(
    client: TestClient, repo: Repository, ingested
):
    cycle, questions = _make_cycle_and_questions(repo, "c-access-role-b")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url="https://borger.dk",
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)

    portal = portals[0]
    # Caller passes role=A in query string, but is assigned as role B (asr-007)
    resp = client.get(f"/assessor/{cycle.cycle_id}/{portal.portal_id}?actor_id=asr-007&role=A")
    assert resp.status_code == 200
    assert "Active Role: Assessor B" in resp.text
    assert "Active Role: Assessor A" not in resp.text


def test_same_person_different_roles_on_different_units(
    client: TestClient, repo: Repository, ingested
):
    # In mapping:
    # AF: A = asr-001, B = asr-002
    # BD: A = asr-002, B = asr-004
    # Therefore asr-002 is Role B on AF, and Role A on BD!
    cycle, _ = _make_cycle_and_questions(repo, "c-dual-role")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="AF",
            resolved_url="https://gov.af",
            unit_type="country",
            display_name="Afghanistan",
        ),
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="BD",
            resolved_url="https://bangladesh.gov.bd",
            unit_type="country",
            display_name="Bangladesh",
        ),
    ]
    create_units(repo, cycle.cycle_id, portals)

    portal_af = portals[0]
    portal_bd = portals[1]

    # asr-002 on AF -> placed in Role B
    resp_af = client.get(f"/assessor/{cycle.cycle_id}/{portal_af.portal_id}?actor_id=asr-002")
    assert resp_af.status_code == 200
    assert "Active Role: Assessor B" in resp_af.text

    # asr-002 on BD -> placed in Role A
    resp_bd = client.get(f"/assessor/{cycle.cycle_id}/{portal_bd.portal_id}?actor_id=asr-002")
    assert resp_bd.status_code == 200
    assert "Active Role: Assessor A" in resp_bd.text


# --- Scenario 6: Refusal Tests (T044, FR-AC-001, FR-AC-003, FR-AC-005, FR-UA-005, FR-UA-007, SC-007, SC-012) ---


def test_unassigned_actor_refused_with_403_and_empty_body(
    client: TestClient, repo: Repository, ingested
):
    cycle, questions = _make_cycle_and_questions(repo, "c-refusal-stranger")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url="https://borger.dk",
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)
    portal = portals[0]

    resp = client.get(f"/assessor/{cycle.cycle_id}/{portal.portal_id}?actor_id=unassigned-person")
    assert resp.status_code == 403

    # Assert on body content: must contain no question text, no evidence URL, no submissions
    for q in questions:
        assert q.text not in resp.text
    assert "https://borger.dk" not in resp.text
    assert resp.text == "You are not assigned to this unit."


def test_assessor_on_one_unit_cannot_open_sibling_unit(
    client: TestClient, repo: Repository, ingested
):
    # DK: A = asr-001, B = asr-007
    # BR: A = asr-022, B = asr-024
    cycle, _ = _make_cycle_and_questions(repo, "c-sibling-refusal")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url=None,
            unit_type="country",
            display_name="Denmark",
        ),
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="BR",
            resolved_url=None,
            unit_type="country",
            display_name="Brazil",
        ),
    ]
    create_units(repo, cycle.cycle_id, portals)

    portal_br = portals[1]
    # asr-001 is assigned to DK, NOT to Brazil
    resp = client.get(f"/assessor/{cycle.cycle_id}/{portal_br.portal_id}?actor_id=asr-001")
    assert resp.status_code == 403
    assert resp.text == "You are not assigned to this unit."


def test_half_staffed_unit_refuses_everyone(
    client: TestClient, repo: Repository, ingested
):
    cycle, _ = _make_cycle_and_questions(repo, "c-half-staffed")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url=None,
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)
    portal = portals[0]

    # Clear Role B so unit is only half-staffed
    clear_role_assignment(repo, cycle.cycle_id, portal.portal_id, AssessorRole.B, actor_id="admin-1")

    # Neither Role A holder (asr-001) nor Role B prior holder nor a stranger can access
    resp_a = client.get(f"/assessor/{cycle.cycle_id}/{portal.portal_id}?actor_id=asr-001")
    assert resp_a.status_code == 403
    assert resp_a.text == "You are not assigned to this unit."

    resp_b = client.get(f"/assessor/{cycle.cycle_id}/{portal.portal_id}?actor_id=asr-007")
    assert resp_b.status_code == 403


def test_unstaffed_unit_refuses_everyone_including_other_units_assessor(
    client: TestClient, repo: Repository, ingested
):
    # DK is staffed (asr-001, asr-007)
    # ZZ is unmapped and thus completely unstaffed
    cycle, _ = _make_cycle_and_questions(repo, "c-unstaffed-fallback")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url=None,
            unit_type="country",
            display_name="Denmark",
        ),
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="ZZ",
            resolved_url=None,
            unit_type="country",
            display_name="Unknown Island",
        ),
    ]
    create_units(repo, cycle.cycle_id, portals)
    portal_zz = portals[1]

    # asr-001 is on DK in this cycle, but cannot open ZZ -- no project-wide fallback!
    resp = client.get(f"/assessor/{cycle.cycle_id}/{portal_zz.portal_id}?actor_id=asr-001")
    assert resp.status_code == 403
    assert resp.text == "You are not assigned to this unit."


def test_completion_declaration_requires_assigned_role(
    client: TestClient, repo: Repository, ingested
):
    cycle, _ = _make_cycle_and_questions(repo, "c-completion-auth")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url=None,
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)
    portal = portals[0]

    # Unassigned actor tries to complete assessment
    resp = client.post(
        f"/assessor/{cycle.cycle_id}/{portal.portal_id}/complete",
        data={"actor_id": "intruder"},
    )
    assert resp.status_code == 403
    assert resp.text == "You are not assigned to this unit."


# --- API Parity Tests (T045, FR-AC-001, FR-AC-002, FR-AC-003, FR-AC-005) ---


def test_api_unassigned_actor_returns_403(
    client: TestClient, repo: Repository, ingested, auth: dict[str, str]
):
    cycle, questions = _make_cycle_and_questions(repo, "c-api-unassigned")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url="https://borger.dk",
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)
    portal = portals[0]
    q = questions[0]

    # POST human submission with unassigned actor
    resp = client.post(
        f"/api/v1/cycles/{cycle.cycle_id}/units/{portal.portal_id}/human-answers",
        json={
            "question_id": q.question_id,
            "role": "A",
            "actor_id": "unassigned-actor-999",
            "answer": True,
        },
        headers=auth,
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"

    # POST completion with unassigned actor
    comp_resp = client.post(
        f"/api/v1/cycles/{cycle.cycle_id}/units/{portal.portal_id}/completions",
        json={
            "role": "A",
            "actor_id": "unassigned-actor-999",
        },
        headers=auth,
    )
    assert comp_resp.status_code == 403
    assert comp_resp.json()["error"]["code"] == "forbidden"


def test_api_contradicting_role_returns_409_naming_assigned_role(
    client: TestClient, repo: Repository, ingested, auth: dict[str, str]
):
    cycle, questions = _make_cycle_and_questions(repo, "c-api-contradict")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url="https://borger.dk",
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)
    portal = portals[0]
    q = questions[0]

    # asr-001 is assigned to Role A on DK. Submitting as Role B must return 409 naming role A.
    resp = client.post(
        f"/api/v1/cycles/{cycle.cycle_id}/units/{portal.portal_id}/human-answers",
        json={
            "question_id": q.question_id,
            "role": "B",  # contradicts assigned role A
            "actor_id": "asr-001",
            "answer": True,
        },
        headers=auth,
    )
    assert resp.status_code == 409
    body = resp.json()["error"]
    assert body["code"] == "conflict"
    assert "A" in body["message"] or body.get("details", {}).get("assigned_role") == "A"

    # Completion with contradicting role also returns 409
    comp_resp = client.post(
        f"/api/v1/cycles/{cycle.cycle_id}/units/{portal.portal_id}/completions",
        json={
            "role": "B",  # contradicts assigned role A
            "actor_id": "asr-001",
        },
        headers=auth,
    )
    assert comp_resp.status_code == 409
    comp_body = comp_resp.json()["error"]
    assert comp_body["code"] == "conflict"
    assert "A" in comp_body["message"] or comp_body.get("details", {}).get("assigned_role") == "A"


def test_api_stored_role_is_always_resolved_role(
    client: TestClient, repo: Repository, ingested, auth: dict[str, str]
):
    cycle, questions = _make_cycle_and_questions(repo, "c-api-stored-role")
    portals = [
        TargetPortal(
            portal_id=new_id("portal"),
            cycle_id=cycle.cycle_id,
            country_id="DK",
            resolved_url="https://borger.dk",
            unit_type="country",
            display_name="Denmark",
        )
    ]
    create_units(repo, cycle.cycle_id, portals)
    portal = portals[0]
    q1 = questions[0]
    q2 = questions[1]

    # Valid submission for Role A on q1 and q2
    for q in [q1, q2]:
        resp = client.post(
            f"/api/v1/cycles/{cycle.cycle_id}/units/{portal.portal_id}/human-answers",
            json={
                "question_id": q.question_id,
                "role": "A",
                "actor_id": "asr-001",
                "answer": True,
            },
            headers=auth,
        )
        assert resp.status_code == 201

    session_id = ensure_session(repo, cycle.cycle_id)
    latest = repo.latest_human_submission(session_id, q1.question_id, portal.portal_id, AssessorRole.A)
    assert latest is not None
    assert latest.role == AssessorRole.A
    assert latest.assessor_actor_id == "asr-001"

    # Declare completion
    comp_resp = client.post(
        f"/api/v1/cycles/{cycle.cycle_id}/units/{portal.portal_id}/completions",
        json={
            "role": "A",
            "actor_id": "asr-001",
        },
        headers=auth,
    )
    assert comp_resp.status_code == 201
    comp = repo.latest_assessor_completion(session_id, portal.portal_id, "A")
    assert comp is not None
    assert comp.role == "A"
    assert comp.actor_id == "asr-001"
