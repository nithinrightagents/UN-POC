"""Unit tests for Reconciliation Workspace (User Story 2, quickstart.md Scenario 3)."""

from __future__ import annotations

import pytest

from portal.common import ensure_session
from portal.reconciliation import open_automatic_round
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    AssessorRole,
    EvidenceLocus,
    HumanAssessorSubmission,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


def _setup_workspace_unit(repo: Repository, total: int = 111, disputes: int = 4):
    cycle_id = "c-ws"
    portal_id = "DK"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Workspace Test Cycle",
            questionnaire_ref="un_osi_2024",
            country_set=["DK"],
            discrepancy_rate_threshold=0.05,
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="DK",
            resolved_url="https://dk.example.com",
            display_name="Denmark Workspace",
        )
    )
    questions = []
    for i in range(total):
        q = Question(
            question_id=f"PF-{i:03d}",
            cycle_id=cycle_id,
            text=f"Indicator {i}",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
        repo.insert_question(q)
        questions.append(q)

    session_id = ensure_session(repo, cycle_id)

    # Assessor A submits True for all questions
    for q in questions:
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=q.question_id,
                portal_id=portal_id,
                role=AssessorRole.A,
                assessor_actor_id="actor-a-distinct",
                answer=True,
                evidence_url=f"https://a.evidence.com/{q.question_id}",
                notes=f"Assessor A secret notes for {q.question_id}",
            )
        )

    # Assessor B submits False for first `disputes` questions, True for the rest
    for i, q in enumerate(questions):
        ans = False if i < disputes else True
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=q.question_id,
                portal_id=portal_id,
                role=AssessorRole.B,
                assessor_actor_id="actor-b-distinct",
                answer=ans,
                evidence_url=f"https://b.evidence.com/{q.question_id}",
                notes=f"Assessor B secret notes for {q.question_id}",
            )
        )

    disputed_ids = [q.question_id for q in questions[:disputes]]
    round_obj = open_automatic_round(
        repo,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=disputed_ids,
        rate=disputes / total,
        tolerance=0.05,
    )
    return cycle_id, portal_id, session_id, questions, round_obj


def test_workspace_get_renders_both_roles_and_labels_correctly(conn, client):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_workspace_unit(repo)

    # View as Role A
    resp_a = client.get(f"/assessor/{cycle_id}/{portal_id}/reconcile?role=A&actor_id=actor-a-distinct")
    assert resp_a.status_code == 200
    text_a = resp_a.text

    # Role A sees itself as Assessor A and peer as Assessor B
    assert "Viewing as <strong>Assessor A</strong>" in text_a
    assert "Peer: <strong>Assessor B</strong>" in text_a
    assert "Your Answer (Assessor A)" in text_a
    assert "Peer's Answer (Assessor B)" in text_a

    # Tolerance, rate, compared count, automatic round notice
    assert "5%" in text_a
    assert "111 indicators" in text_a
    assert "only automatic reconciliation round" in text_a

    # Exactly 4 disputes rendered in form action
    for i in range(4):
        qid = f"PF-{i:03d}"
        assert f'action="/assessor/{cycle_id}/{portal_id}/reconcile/{qid}/joint"' in text_a
        assert f"Assessor A secret notes for {qid}" in text_a
        assert f"Assessor B secret notes for {qid}" in text_a

    # Agreed indicator (e.g. PF-004): Peer B's notes MUST NOT appear anywhere in Role A's view (FR-DR-017)
    assert "Assessor B secret notes for PF-004" not in text_a
    assert "https://b.evidence.com/PF-004" not in text_a

    # View as Role B
    resp_b = client.get(f"/assessor/{cycle_id}/{portal_id}/reconcile?role=B&actor_id=actor-b-distinct")
    assert resp_b.status_code == 200
    text_b = resp_b.text

    # Role B sees itself as Assessor B and peer as Assessor A
    assert "Viewing as <strong>Assessor B</strong>" in text_b
    assert "Peer: <strong>Assessor A</strong>" in text_b
    assert "Your Answer (Assessor B)" in text_b
    assert "Peer's Answer (Assessor A)" in text_b

    # Agreed indicator (e.g. PF-004): Peer A's notes MUST NOT appear anywhere in Role B's view (FR-DR-017)
    assert "Assessor A secret notes for PF-004" not in text_b
    assert "https://a.evidence.com/PF-004" not in text_b


def test_joint_answer_without_justification_rejected(conn, client):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_workspace_unit(repo)

    # Empty justification
    resp = client.post(
        f"/assessor/{cycle_id}/{portal_id}/reconcile/PF-000/joint",
        data={"role": "A", "actor_id": "actor-a", "answer": "true", "justification": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "justification" in resp.headers["location"].lower()


def test_joint_answer_outside_disputed_set_rejected(conn, client):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_workspace_unit(repo)

    # PF-010 is not in disputed set (PF-000..PF-003)
    resp = client.post(
        f"/assessor/{cycle_id}/{portal_id}/reconcile/PF-010/joint",
        data={"role": "A", "actor_id": "actor-a", "answer": "true", "justification": "Valid reasoning"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_workspace_refuses_when_no_round_open(conn, client):
    repo = Repository(conn)
    cycle_id = "c-no-round"
    portal_id = "DK"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="No Round Cycle",
            questionnaire_ref="un_osi_2024",
            country_set=["DK"],
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="DK",
            resolved_url="https://dk.example.com",
            display_name="Denmark No Round",
        )
    )
    ensure_session(repo, cycle_id)

    resp = client.get(f"/assessor/{cycle_id}/{portal_id}/reconcile?role=A&actor_id=actor-a", follow_redirects=False)
    assert resp.status_code == 303
    assert f"/assessor/{cycle_id}/{portal_id}" in resp.headers["location"]
    assert "error=" in resp.headers["location"]
