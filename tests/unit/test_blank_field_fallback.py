"""Prefilled questionnaire blank-field fallback for escalated/unverified
questions (spec.md User Stories 1-3). See
specs/004-blank-field-fallback/quickstart.md for the scenario mapping.
"""

from __future__ import annotations

import sqlite3

import pytest

from review.query import build_question_review
from review.unlock import portal_review_status
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    AdjudicationResult,
    AgentRunState,
    AnswerType,
    AssessmentSession,
    AssessorAgentRun,
    EscalationReason,
    EvidenceLocus,
    Question,
    SessionMode,
    SessionStatus,
    SurveyCycle,
    TargetPortal,
    UnitState,
    new_id,
)

pytestmark = pytest.mark.unit

# Every blocking condition, mapped to the unit state orchestration/scheduler.py
# actually escalates it to (NO_USABLE_URL -> UNASSESSABLE, the rest -> ESCALATED).
BLOCKING_CONDITIONS: list[tuple[EscalationReason, UnitState, dict]] = [
    (EscalationReason.NO_USABLE_URL, UnitState.UNASSESSABLE, {
        "resolution_history": [
            {"source": "search", "order": 1, "returned": None, "usable": False,
             "rejection_reason": "no candidate link"},
        ],
    }),
    (EscalationReason.REQUIRES_AUTHENTICATED_ACCESS, UnitState.ESCALATED, {
        "reason": "every independent agent observed an authentication boundary",
    }),
    (EscalationReason.UNRESOLVED_DISAGREEMENT, UnitState.ESCALATED, {
        "flag_reason": "agents split True/False with no majority",
    }),
    (EscalationReason.LANGUAGE_NOT_SUPPORTED, UnitState.ESCALATED, {
        "detected_language": "fr",
        "reported_languages": {"fr": 2},
        "supported_languages": ["en"],
    }),
    (EscalationReason.LANGUAGE_DECLINED, UnitState.ESCALATED, {
        "detected_language": "de",
    }),
    (EscalationReason.UNREACHABLE_PORTAL, UnitState.ESCALATED, {
        "attempts": 3,
    }),
    (EscalationReason.UNVERIFIABLE_TARGET, UnitState.ESCALATED, {
        "validated_run_count": 1,
        "total_run_count": 2,
    }),
]


@pytest.fixture
def repo() -> Repository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return Repository(conn)


def _seed_cycle_session_portal(repo: Repository) -> tuple[str, str]:
    cycle = SurveyCycle(cycle_id="cyc-1", name="Cycle", questionnaire_ref="ref", country_set=["EE"])
    repo.insert_cycle(cycle)
    session = AssessmentSession(
        session_id="sess-1", cycle_id=cycle.cycle_id, mode=SessionMode.PRODUCTION,
        config_snapshot_id="cfg-1", status=SessionStatus.COMPLETE,
    )
    repo.insert_session(session)
    portal = TargetPortal(portal_id="portal-1", cycle_id=cycle.cycle_id, country_id="EE",
                           resolved_url="https://example.gov")
    repo.insert_portal(portal)
    return session.session_id, portal.portal_id


def _seed_question(repo: Repository, cycle_id: str, question_id: str) -> Question:
    q = Question(
        question_id=question_id, cycle_id=cycle_id, text=f"Question {question_id}",
        answer_type=AnswerType.BINARY, evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    return q


def test_coverage(repo):
    session_id, portal_id = _seed_cycle_session_portal(repo)

    for reason, state, context in BLOCKING_CONDITIONS:
        qid = f"Q-{reason.value}"
        _seed_question(repo, "cyc-1", qid)
        repo.upsert_unit(session_id, qid, portal_id, state.value,
                          {"escalation_reason": reason.value, **context})

        view = build_question_review(repo, session_id, qid, portal_id, confidence_threshold=70)

        assert view.escalated is True, reason
        assert view.delivered_answer is None, reason
        assert view.system_proposed_answer is None, reason
        assert view.reason_tag is not None, reason
        assert view.reason_tag.text, reason

    # A sibling DELIVERED unit is unaffected by any of the above.
    _seed_question(repo, "cyc-1", "Q-delivered")
    repo.upsert_unit(session_id, "Q-delivered", portal_id, UnitState.DELIVERED.value,
                      {"consensus_answer": True, "consensus_confidence": 90})
    delivered_view = build_question_review(repo, session_id, "Q-delivered", portal_id, confidence_threshold=70)
    assert delivered_view.escalated is False
    assert delivered_view.reason_tag is None


def test_portal_unlock_includes_unassessable(repo):
    session_id, portal_id = _seed_cycle_session_portal(repo)
    _seed_question(repo, "cyc-1", "Q-delivered")
    _seed_question(repo, "cyc-1", "Q-escalated")
    _seed_question(repo, "cyc-1", "Q-unassessable")

    repo.upsert_unit(session_id, "Q-delivered", portal_id, UnitState.DELIVERED.value, {})
    repo.upsert_unit(session_id, "Q-escalated", portal_id, UnitState.ESCALATED.value,
                      {"escalation_reason": EscalationReason.UNRESOLVED_DISAGREEMENT.value})
    repo.upsert_unit(session_id, "Q-unassessable", portal_id, UnitState.UNASSESSABLE.value,
                      {"escalation_reason": EscalationReason.NO_USABLE_URL.value})

    status = portal_review_status(
        repo, session_id, portal_id, ["Q-delivered", "Q-escalated", "Q-unassessable"]
    )

    assert status.unlocked is True
    assert set(status.escalated_question_ids) == {"Q-escalated", "Q-unassessable"}


def test_attempt_history(repo):
    session_id, portal_id = _seed_cycle_session_portal(repo)

    # Disagreement-blocked unit with two rounds of agent runs.
    _seed_question(repo, "cyc-1", "Q-disagreement")
    for round_number in (1, 2):
        for idx, (answer, confidence) in enumerate([(True, 60), (False, 55)]):
            repo.insert_agent_run(AssessorAgentRun(
                run_id=new_id("run"), session_id=session_id, question_id="Q-disagreement",
                portal_id=portal_id, agent_index=idx, round_number=round_number,
                answer=answer, confidence=confidence, justification="disagree",
                state=AgentRunState.VALIDATED_PASS,
            ))
        repo.insert_adjudication_result(AdjudicationResult(
            adjudication_id=new_id("adj"), session_id=session_id, question_id="Q-disagreement",
            portal_id=portal_id, round_number=round_number, input_run_ids=[],
            discrepancy_flagged=True, flag_reason=f"round {round_number} split",
            max_pairwise_confidence_delta=5, consensus_answer=None, consensus_confidence=None,
            below_acceptance_threshold=True,
        ))
    repo.upsert_unit(session_id, "Q-disagreement", portal_id, UnitState.ESCALATED.value,
                      {"escalation_reason": EscalationReason.UNRESOLVED_DISAGREEMENT.value})

    view = build_question_review(repo, session_id, "Q-disagreement", portal_id, confidence_threshold=70)
    assert view.attempt_history.points_of_disagreement
    assert len(view.agent_positions) == 4  # both rounds

    # Unreachable-portal unit.
    _seed_question(repo, "cyc-1", "Q-unreachable")
    repo.upsert_unit(session_id, "Q-unreachable", portal_id, UnitState.ESCALATED.value,
                      {"escalation_reason": EscalationReason.UNREACHABLE_PORTAL.value, "attempts": 4})
    unreachable_view = build_question_review(repo, session_id, "Q-unreachable", portal_id, confidence_threshold=70)
    assert unreachable_view.attempt_history.reachability_attempts == 4

    # NO_USABLE_URL/UNASSESSABLE unit with no evidence.
    _seed_question(repo, "cyc-1", "Q-no-url")
    repo.upsert_unit(session_id, "Q-no-url", portal_id, UnitState.UNASSESSABLE.value,
                      {"escalation_reason": EscalationReason.NO_USABLE_URL.value})
    no_url_view = build_question_review(repo, session_id, "Q-no-url", portal_id, confidence_threshold=70)
    assert no_url_view.attempt_history.has_any_evidence is False


def test_tags_mutually_distinguishable(repo):
    session_id, portal_id = _seed_cycle_session_portal(repo)
    texts = []
    for reason, state, context in BLOCKING_CONDITIONS:
        qid = f"Q2-{reason.value}"
        _seed_question(repo, "cyc-1", qid)
        repo.upsert_unit(session_id, qid, portal_id, state.value,
                          {"escalation_reason": reason.value, **context})
        view = build_question_review(repo, session_id, qid, portal_id, confidence_threshold=70)
        texts.append(view.reason_tag.text)

    assert len(set(texts)) == len(texts)
