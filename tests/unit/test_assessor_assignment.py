"""Unit tests for assign-assessors / unassign-assessors and the resulting lock.

Once an admin assigns both assessor emails, SurveyCycle.status flips to
"locked" and the unit/question mutation routes must refuse to change
anything (units + questions only -- tolerance, MSQ upload, publish, and
project deletion stay editable per user direction).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


def _make_cycle(repo: Repository, cycle_id: str) -> SurveyCycle:
    cycle = SurveyCycle(
        cycle_id=cycle_id,
        name="Assign Assessors Cycle",
        questionnaire_ref="ref",
        country_set=["DK"],
        project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)
    return cycle


def test_assign_assessors_with_valid_emails_locks_project(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-assign-assessors-valid"
    _make_cycle(repo, cycle_id)

    resp = client.post(
        f"/admin/projects/{cycle_id}/assign-assessors",
        data={
            "assessor_a_email": "assessor.a@example.org",
            "assessor_b_email": "assessor.b@example.org",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}"

    cycle = repo.get_cycle(cycle_id)
    assert cycle.status == "locked"
    assert cycle.assessor_a_email == "assessor.a@example.org"
    assert cycle.assessor_b_email == "assessor.b@example.org"


def test_assign_assessors_with_invalid_email_redirects_with_error_and_stays_active(
    client: TestClient, conn
):
    repo = Repository(conn)
    cycle_id = "test-assign-assessors-invalid"
    _make_cycle(repo, cycle_id)

    resp = client.post(
        f"/admin/projects/{cycle_id}/assign-assessors",
        data={
            "assessor_a_email": "not-an-email",
            "assessor_b_email": "assessor.b@example.org",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}?assign_error=1"

    cycle = repo.get_cycle(cycle_id)
    assert cycle.status == "active"
    assert cycle.assessor_a_email is None
    assert cycle.assessor_b_email is None


def test_locked_project_blocks_unit_and_question_mutations(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-locked-blocks-mutations"
    _make_cycle(repo, cycle_id)

    portal = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="DK",
        resolved_url=None, unit_type="country", display_name="Denmark",
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

    client.post(
        f"/admin/projects/{cycle_id}/assign-assessors",
        data={
            "assessor_a_email": "assessor.a@example.org",
            "assessor_b_email": "assessor.b@example.org",
        },
        follow_redirects=False,
    )

    portals_before = repo.list_portals(cycle_id)
    questions_before = repo.list_questions(cycle_id)

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
    assert "lock_error=1" in resp.headers["location"]

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-add",
        data={"country_codes": ["SE"], "unit_type": "country"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" in resp.headers["location"]

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
    assert "lock_error=1" in resp.headers["location"]

    resp = client.post(
        f"/admin/projects/{cycle_id}/questions/bulk-retire",
        data={"question_ids": [question.question_id], "actor_id": "senior-reviewer"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "lock_error=1" in resp.headers["location"]

    assert repo.list_portals(cycle_id) == portals_before
    assert repo.list_questions(cycle_id) == questions_before


def test_unassign_assessors_reopens_project_for_editing(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-unassign-reopens"
    _make_cycle(repo, cycle_id)

    client.post(
        f"/admin/projects/{cycle_id}/assign-assessors",
        data={
            "assessor_a_email": "assessor.a@example.org",
            "assessor_b_email": "assessor.b@example.org",
        },
        follow_redirects=False,
    )
    assert repo.get_cycle(cycle_id).status == "locked"

    resp = client.post(
        f"/admin/projects/{cycle_id}/unassign-assessors",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}"

    cycle = repo.get_cycle(cycle_id)
    assert cycle.status == "active"
    assert cycle.assessor_a_email is None
    assert cycle.assessor_b_email is None

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-add",
        data={"country_codes": ["SE"], "unit_type": "country"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}"
    assert any(p.country_id == "SE" for p in repo.list_portals(cycle_id))
