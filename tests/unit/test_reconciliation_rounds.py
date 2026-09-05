"""Unit tests for User Story 1: Discrepancy detection and round opening.

Covers Scenarios 1 and 2 of quickstart.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from portal.common import ensure_session
from portal.discrepancy import recompute_portal_discrepancy
from portal.reconciliation import unit_reconciliation_state
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    AssessorCompletion,
    AssessorRole,
    AssignmentSource,
    EscalationReason,
    EvidenceLocus,
    HumanAssessorSubmission,
    Question,
    RoleAssignment,
    SurveyCycle,
    TargetPortal,
    UnitAssessorAssignment,
    new_id,
)

pytestmark = pytest.mark.unit


def _seed_cycle_and_portal(
    repo: Repository,
    cycle_id: str = "c-2024",
    portal_id: str = "DK",
    num_questions: int = 140,
    actor_a: str = "actor-a",
    actor_b: str = "actor-b",
) -> list[Question]:
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Test Cycle 2024",
            questionnaire_ref="un_osi_2024",
            country_set=["DK"],
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="DK",
            resolved_url="https://denmark.example.com",
            display_name="Denmark Portal",
        )
    )
    repo.upsert_unit_assignment(
        UnitAssessorAssignment(
            assignment_id=f"asmt-{portal_id}",
            cycle_id=cycle_id,
            portal_id=portal_id,
            role_a=RoleAssignment(assessor_id=actor_a, source=AssignmentSource.MAPPING),
            role_b=RoleAssignment(assessor_id=actor_b, source=AssignmentSource.MAPPING),
        )
    )
    questions = []
    for i in range(num_questions):
        q = Question(
            question_id=f"Q{i:03d}",
            cycle_id=cycle_id,
            text=f"Indicator {i}",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
        repo.insert_question(q)
        questions.append(q)
    return questions


def _submit(
    repo: Repository,
    session_id: str,
    portal_id: str,
    question_id: str,
    role: AssessorRole,
    answer: bool,
    cycle_id: str = "c-2024",
    actor_id: str = "test-actor",
):
    sub = HumanAssessorSubmission(
        submission_id=new_id("sub"),
        session_id=session_id,
        cycle_id=cycle_id,
        question_id=question_id,
        portal_id=portal_id,
        role=role,
        assessor_actor_id=actor_id,
        answer=answer,
        evidence_url="https://example.com",
        notes="",
        ai_suggested_answer=None,
        ai_suggestion_accepted=None,
        submitted_at=datetime.now(UTC),
    )
    repo.insert_human_submission(sub)
    return sub


def test_scenario_1_nothing_opens_mid_assessment(conn, client, settings):
    """Scenario 1: A answers 140 indicators, B answers 3 (differing on 1 -> 33%).
    Neither has declared completion.
    """
    repo = Repository(conn)
    cycle_id = "c-2024"
    portal_id = "DK"
    questions = _seed_cycle_and_portal(repo, cycle_id, portal_id, num_questions=140, actor_b="test-actor-b")
    session_id = ensure_session(repo, cycle_id)

    # Assessor A answers all 140 (all True)
    for q in questions:
        _submit(repo, session_id, portal_id, q.question_id, AssessorRole.A, True)

    # Assessor B answers 3 questions: Q000 True, Q001 True, Q002 False (differs on 1 of 3)
    _submit(repo, session_id, portal_id, "Q000", AssessorRole.B, True)
    _submit(repo, session_id, portal_id, "Q001", AssessorRole.B, True)
    _submit(repo, session_id, portal_id, "Q002", AssessorRole.B, False)

    # Recompute on B's 3rd submission
    case = recompute_portal_discrepancy(
        repo, session_id, portal_id, [q.question_id for q in questions], 0.05, cycle_id=cycle_id
    )
    assert case is not None
    assert case.points_of_disagreement == ["Q002"]
    assert pytest.approx(case.differing_answer_rate, 0.01) == 1 / 3

    # Assert count(reconciliation_rounds) == 0
    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    assert len(rounds) == 0

    # Assert no PORTAL_DISCREPANCY queue item created
    escalations = repo.list_escalations(session_id)
    assert len(escalations) == 0

    # Assert unit_reconciliation_state is above_tolerance_in_progress
    state = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings)
    assert state.state == "above_tolerance_in_progress"
    assert pytest.approx(state.rate, 0.01) == 1 / 3
    assert state.compared_count == 3
    assert state.disputed_question_ids == ["Q002"]

    # Requesting /assessor/{cycle}/{unit}?role=B renders the questionnaire (not workspace redirect)
    resp = client.get(f"/assessor/{cycle_id}/{portal_id}?role=B&actor_id=test-actor-b")
    assert resp.status_code == 200
    assert "assessor-questionnaire" in resp.text or "Questionnaire" in resp.text or "DK" in resp.text
    assert "/reconcile" not in resp.headers.get("location", "")

    # Now let B answer the remaining 137 in agreement (all True)
    for q in questions[3:]:
        _submit(repo, session_id, portal_id, q.question_id, AssessorRole.B, True)

    # Both declare completion
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="A",
            actor_id="test-actor-a",
            indicator_count_at_declaration=140,
        )
    )
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="B",
            actor_id="test-actor-b",
            indicator_count_at_declaration=140,
        )
    )

    # Recompute on completion
    case_final = recompute_portal_discrepancy(
        repo, session_id, portal_id, [q.question_id for q in questions], 0.05, cycle_id=cycle_id
    )
    assert case_final is not None
    # 1 disagreement out of 140 = 0.0071 <= 0.05 (within tolerance)
    assert case_final.outcome == "within_threshold"
    assert pytest.approx(case_final.differing_answer_rate, 0.0001) == 1 / 140

    # Still no round ever opened
    rounds_final = repo.list_rounds_for_unit(session_id, portal_id)
    assert len(rounds_final) == 0

    state_final = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings)
    assert state_final.state == "within_tolerance"


def test_scenario_2_round_opens_on_second_completion_once(conn, client, settings):
    """Scenario 2: Both answer 100 questions with 10 disagreements (10% > 5%).
    A declares -> nothing opens.
    B declares -> exactly one round opens, exactly one queue item.
    Re-declaring or resubmitting unchanged adds neither.
    """
    repo = Repository(conn)
    cycle_id = "c-2024"
    portal_id = "DK"
    questions = _seed_cycle_and_portal(repo, cycle_id, portal_id, num_questions=100)
    session_id = ensure_session(repo, cycle_id)

    # 10 disagreements: Q000..Q009 (A=True, B=False). Q010..Q099 (A=True, B=True).
    for i, q in enumerate(questions):
        _submit(repo, session_id, portal_id, q.question_id, AssessorRole.A, True)
        _submit(repo, session_id, portal_id, q.question_id, AssessorRole.B, False if i < 10 else True)

    # Assessor A completes via POST route
    resp_a = client.post(
        f"/assessor/{cycle_id}/{portal_id}/complete",
        data={"role": "A", "actor_id": "actor-a"},
        follow_redirects=False,
    )
    assert resp_a.status_code in (200, 303)

    # Only A declared -> count(rounds) == 0, count(escalations) == 0
    assert len(repo.list_rounds_for_unit(session_id, portal_id)) == 0
    assert len(repo.list_escalations(session_id)) == 0

    # Assessor B completes via POST route
    resp_b = client.post(
        f"/assessor/{cycle_id}/{portal_id}/complete",
        data={"role": "B", "actor_id": "actor-b"},
        follow_redirects=False,
    )
    assert resp_b.status_code in (200, 303)

    # Exactly one open round
    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    assert len(rounds) == 1
    rnd = rounds[0]
    assert rnd.state == "open"
    assert rnd.opened_by == "automatic"
    assert rnd.round_number == 1
    assert rnd.opened_by_actor_id is None
    assert len(rnd.data["disputed_question_ids"]) == 10

    # Exactly one escalation item carrying round_id
    escalations = repo.list_escalations(session_id)
    assert len(escalations) == 1
    esc = escalations[0]
    assert esc.reason == EscalationReason.PORTAL_DISCREPANCY
    assert esc.context["round_id"] == rnd.round_id
    assert esc.context["differing_answer_rate"] == 0.1
    assert esc.context["compared_questions"] == 100

    # Declaring completion again adds neither round nor queue item
    client.post(
        f"/assessor/{cycle_id}/{portal_id}/complete",
        data={"role": "B", "actor_id": "actor-b"},
        follow_redirects=False,
    )
    assert len(repo.list_rounds_for_unit(session_id, portal_id)) == 1
    assert len(repo.list_escalations(session_id)) == 1

    # Resubmitting unchanged answer adds neither
    _submit(repo, session_id, portal_id, "Q000", AssessorRole.B, False)
    recompute_portal_discrepancy(repo, session_id, portal_id, [q.question_id for q in questions], 0.05, cycle_id=cycle_id)
    assert len(repo.list_rounds_for_unit(session_id, portal_id)) == 1
    assert len(repo.list_escalations(session_id)) == 1

    # Concurrency guarantee: inserting a second open round directly fails under partial unique index
    rnd_duplicate = rounds[0].__class__(
        round_id=new_id("rnd"),
        session_id=session_id,
        portal_id=portal_id,
        cycle_id=cycle_id,
        round_number=2,
        opened_by="automatic",
        opened_by_actor_id=None,
        opened_reason=None,
        state="open",
        data=rnd.data,
        opened_at=datetime.now(UTC),
        closed_at=None,
    )
    ok = repo.insert_reconciliation_round(rnd_duplicate)
    assert ok is False  # Index prevented duplicate open round!
