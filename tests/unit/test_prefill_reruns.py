"""Tests for prefill re-run semantics and preservation of human assessor submissions (spec 008 US6)."""

import sqlite3
import pytest

from orchestration.prefill_writer import write_prefill
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    AnswerType,
    AssessorRole,
    EvidenceLocus,
    HumanAssessorSubmission,
    PrefillReason,
    Question,
    SurveyCycle,
    TargetPortal,
    UnitState,
)

pytestmark = pytest.mark.unit


def _setup_rerun_env():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-rerun",
        name="Rerun Cycle",
        questionnaire_ref="Test Ref",
        country_set=["DE"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-rerun",
        cycle_id="c-rerun",
        country_id="DE",
        resolved_url="https://bund.de",
    )
    repo.insert_portal(portal)

    q1 = Question(
        question_id="c-rerun:q1",
        cycle_id="c-rerun",
        indicator_id="q1",
        text="Open data portal?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    q2 = Question(
        question_id="c-rerun:q2",
        cycle_id="c-rerun",
        indicator_id="q2",
        text="Digital identity?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q1)
    repo.insert_question(q2)

    return repo, conn, cycle, portal, q1, q2


def test_human_submissions_untouched_by_prefill_reruns():
    """100% of human submissions preserved through multiple AI prefill re-runs (FR-PF-038, SC-010)."""
    repo, conn, cycle, portal, q1, q2 = _setup_rerun_env()
    session_id = "s-rerun"

    # 1. Initial AI prefill run 1
    write_prefill(
        repo=repo,
        session_id=session_id,
        cycle_id=cycle.cycle_id,
        portal_id=portal.portal_id,
        question_id=q1.question_id,
        run_id="run-1",
        suggested=True,
        answer=True,
        confidence=80,
        justification="Initial AI found link.",
        evidence_url="https://bund.de/data",
    )

    # 2. Human Assessor submits an answer with custom rationale and notes
    human_sub = HumanAssessorSubmission(
        submission_id="sub-1",
        session_id=session_id,
        cycle_id=cycle.cycle_id,
        portal_id=portal.portal_id,
        question_id=q1.question_id,
        role=AssessorRole.A,
        assessor_actor_id="assessor_a",
        answer=False,  # Overruled AI
        evidence_url="https://bund.de/archive",
        notes="Confirmed with ministry.",
        ai_suggested_answer=True,
        ai_suggestion_accepted=False,
    )
    repo.insert_human_submission(human_sub)

    # 3. AI prefill run 2 is triggered (re-run)
    write_prefill(
        repo=repo,
        session_id=session_id,
        cycle_id=cycle.cycle_id,
        portal_id=portal.portal_id,
        question_id=q1.question_id,
        run_id="run-2",
        suggested=True,
        answer=True,
        confidence=95,
        justification="Newer AI run with high confidence.",
        evidence_url="https://bund.de/data-new",
    )

    # Verify: Human submission is completely untouched
    subs = repo.list_human_submissions(
        session_id, portal.portal_id, q1.question_id, AssessorRole.A
    )
    assert len(subs) == 1
    saved_sub = subs[0]
    assert saved_sub.answer is False
    assert saved_sub.notes == "Confirmed with ministry."
    assert saved_sub.assessor_actor_id == "assessor_a"
    assert saved_sub.ai_suggestion_accepted is False

    # Verify: Latest prefill returned reflects run 2
    latest = repo.latest_prefill(session_id, q1.question_id, portal.portal_id)
    assert latest is not None
    assert latest.run_id == "run-2"
    assert latest.confidence == 95
    assert latest.justification == "Newer AI run with high confidence."


def test_pipeline_never_writes_to_human_assessor_submissions():
    """FR-PF-038: Structural guarantee that pipeline prefill writer only writes to prefills."""
    repo, conn, cycle, portal, q1, q2 = _setup_rerun_env()
    session_id = "s-rerun"

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM human_assessor_submissions")
    initial_count = cursor.fetchone()[0]
    assert initial_count == 0

    write_prefill(
        repo=repo,
        session_id=session_id,
        cycle_id=cycle.cycle_id,
        portal_id=portal.portal_id,
        question_id=q1.question_id,
        run_id="run-check",
        suggested=False,
        reason=PrefillReason.NO_USABLE_EVIDENCE,
    )

    cursor.execute("SELECT COUNT(*) FROM human_assessor_submissions")
    after_count = cursor.fetchone()[0]
    assert after_count == 0
