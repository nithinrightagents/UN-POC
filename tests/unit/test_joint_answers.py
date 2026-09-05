"""Unit tests for Joint Answers and Round Resolution (User Story 2, quickstart.md Scenario 4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from portal.common import ensure_session
from portal.discrepancy import recompute_portal_discrepancy
from portal.reconciliation import open_automatic_round, unit_reconciliation_state
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    AssessorCompletion,
    AssessorRole,
    AssignmentSource,
    EvidenceLocus,
    HumanAssessorSubmission,
    JointAnswer,
    Question,
    RoleAssignment,
    SurveyCycle,
    TargetPortal,
    UnitAssessorAssignment,
    new_id,
)

pytestmark = pytest.mark.unit


def _setup_disputed_unit(repo: Repository, total: int = 100, disputes: int = 4):
    cycle_id = "c-joint"
    portal_id = "DK"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Joint Answer Test Cycle",
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
            display_name="Denmark Joint",
        )
    )
    repo.upsert_unit_assignment(
        UnitAssessorAssignment(
            assignment_id=new_id("asmt"),
            cycle_id=cycle_id,
            portal_id=portal_id,
            role_a=RoleAssignment(assessor_id="actor-a", source=AssignmentSource.MAPPING),
            role_b=RoleAssignment(assessor_id="actor-b", source=AssignmentSource.MAPPING),
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
                assessor_actor_id="actor-a",
                answer=True,
                evidence_url=f"https://a.evidence.com/{q.question_id}",
                notes=f"Assessor A notes {q.question_id}",
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
                assessor_actor_id="actor-b",
                answer=ans,
                evidence_url=f"https://b.evidence.com/{q.question_id}",
                notes=f"Assessor B notes {q.question_id}",
            )
        )

    # Both declare completion
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="A",
            actor_id="actor-a",
            indicator_count_at_declaration=total,
        )
    )
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="B",
            actor_id="actor-b",
            indicator_count_at_declaration=total,
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


def test_scenario_4_joint_answers_move_rate_and_close_resolved(conn, client, settings):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_disputed_unit(repo, total=100, disputes=4)

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM human_assessor_submissions")
    initial_sub_count = cursor.fetchone()[0]

    # Commit 1 joint answer (for PF-000)
    resp = client.post(
        f"/assessor/{cycle_id}/{portal_id}/reconcile/PF-000/joint",
        data={"role": "A", "actor_id": "actor-a", "answer": "true", "justification": "Agreed upon review"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Recomputation now reports 3 disputed (PF-001, PF-002, PF-003)
    case1 = recompute_portal_discrepancy(
        repo, session_id, portal_id, [q.question_id for q in questions], 0.05, cycle_id=cycle_id
    )
    assert case1.points_of_disagreement == ["PF-001", "PF-002", "PF-003"]
    assert pytest.approx(case1.differing_answer_rate, 0.001) == 0.03

    # Round is still open
    open_rnd = repo.open_round_for_unit(session_id, portal_id)
    assert open_rnd is not None
    assert open_rnd.state == "open"

    # Commit remaining 3 joint answers by Assessor A alone (A4)
    for qid in ["PF-001", "PF-002", "PF-003"]:
        client.post(
            f"/assessor/{cycle_id}/{portal_id}/reconcile/{qid}/joint",
            data={"role": "A", "actor_id": "actor-a", "answer": "true", "justification": "Agreed alone"},
            follow_redirects=False,
        )

    # All 4 disputes settled -> round closes 'resolved'
    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    assert len(rounds) == 1
    assert rounds[0].state == "resolved"
    assert rounds[0].closed_at is not None

    # No open round remains
    assert repo.open_round_for_unit(session_id, portal_id) is None

    # Unit reconciliation state is now full_consensus (0% remaining disagreement)
    state = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings)
    assert state.state == "full_consensus"
    assert state.rate == 0.0

    # Verify NO HumanAssessorSubmission row was created by any joint answer (audit trail preservation)
    cursor.execute("SELECT COUNT(*) FROM human_assessor_submissions")
    assert cursor.fetchone()[0] == initial_sub_count

    # Both original submissions remain readable and unchanged
    sub_a = repo.latest_human_submission(session_id, "PF-000", portal_id, AssessorRole.A)
    sub_b = repo.latest_human_submission(session_id, "PF-000", portal_id, AssessorRole.B)
    assert sub_a.answer is True
    assert sub_b.answer is False
    assert sub_a.notes == "Assessor A notes PF-000"
    assert sub_b.notes == "Assessor B notes PF-000"


def test_concurrent_joint_answers_winner_takes_first(conn):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_disputed_unit(repo, total=100, disputes=4)

    # First joint answer succeeds
    ja1 = JointAnswer(
        joint_answer_id=new_id("joint"),
        session_id=session_id,
        portal_id=portal_id,
        question_id="PF-000",
        round_id=round_obj.round_id,
        data={
            "answer": True,
            "justification": "First assessor justification",
            "submitted_by_role": "A",
            "submitted_by_actor_id": "actor-a",
        },
        created_at=datetime.now(UTC),
    )
    ok1 = repo.insert_joint_answer(ja1)
    assert ok1 is True

    # Second concurrent joint answer for same (round_id, question_id) fails via unique index
    ja2 = JointAnswer(
        joint_answer_id=new_id("joint"),
        session_id=session_id,
        portal_id=portal_id,
        question_id="PF-000",
        round_id=round_obj.round_id,
        data={
            "answer": False,
            "justification": "Second assessor concurrent attempt",
            "submitted_by_role": "B",
            "submitted_by_actor_id": "actor-b",
        },
        created_at=datetime.now(UTC),
    )
    ok2 = repo.insert_joint_answer(ja2)
    assert ok2 is False  # unique constraint idx_joint_answers_once prevented duplicate

    # Exactly 1 joint answer stored for PF-000 in this round
    latest = repo.latest_joint_answer(session_id, portal_id, "PF-000")
    assert latest.committed_by_role == "A"
    assert latest.answer is True


def test_resolved_reconciliation_cannot_be_silently_re_resolved(conn, client, settings):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_disputed_unit(repo, total=100, disputes=4)

    # Resolve all 4 disputed questions
    for i in range(4):
        qid = f"PF-{i:03d}"
        repo.insert_joint_answer(
            JointAnswer(
                joint_answer_id=new_id("joint"),
                session_id=session_id,
                portal_id=portal_id,
                question_id=qid,
                round_id=round_obj.round_id,
                data={
                    "answer": True,
                    "justification": f"Settled {qid}",
                    "submitted_by_role": "A",
                    "submitted_by_actor_id": "actor-a",
                },
                created_at=datetime.now(UTC),
            )
        )

    from portal.reconciliation import close_round_if_complete
    closed_rnd = close_round_if_complete(repo, round_obj.round_id, session_id, cycle_id, portal_id, questions, settings)
    assert closed_rnd.state == "resolved"

    # Attempting to post another joint answer via assessor endpoint to the closed round fails/redirects to normal unit
    resp = client.post(
        f"/assessor/{cycle_id}/{portal_id}/reconcile/PF-000/joint",
        data={"role": "B", "actor_id": "actor-b", "answer": "false", "justification": "Trying to alter resolved answer"},
        follow_redirects=False,
    )
    # The unique index prevents insertion of a duplicate joint answer for the round
    assert resp.status_code == 303

    # The original resolved joint answer is unchanged
    latest = repo.latest_joint_answer(session_id, portal_id, "PF-000")
    assert latest.answer is True
    assert latest.committed_by_role == "A"
    assert latest.justification == "Settled PF-000"

