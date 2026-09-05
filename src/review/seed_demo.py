"""Seed data for demonstrating the review surface with no pipeline running.

Independent test for US1 (spec.md): "Seed one pre-computed assessment with
a complete evidence set... [and] one where evidence capture failed" so
FR-024's confidence cap is directly observable in the UI.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from shared.persistence.repositories import Repository
from shared.state.entities import (
    AdjudicationResult,
    AgentRunState,
    AnswerType,
    AssessmentSession,
    AssessorAgentRun,
    ElementReference,
    EscalationReason,
    EvidenceArtifact,
    EvidenceLocus,
    LanguageDecision,
    LanguageDecisionOutcome,
    LinkSource,
    Question,
    ResolutionAttempt,
    SessionMode,
    SessionStatus,
    SurveyCycle,
    TargetPortal,
    UnitState,
    new_id,
)


def seed_demo_review(conn: sqlite3.Connection) -> dict:
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="demo-cycle",
        name="Demo Cycle",
        questionnaire_ref="Module 2.1",
        country_set=["EE", "US"],
    )
    repo.insert_cycle(cycle)

    session = AssessmentSession(
        session_id="demo-session",
        cycle_id=cycle.cycle_id,
        mode=SessionMode.PRODUCTION,
        config_snapshot_id="demo-snapshot",
        status=SessionStatus.COMPLETE,
    )
    repo.insert_session(session)

    portal = TargetPortal(
        portal_id="demo-portal-ee",
        cycle_id=cycle.cycle_id,
        country_id="EE",
        resolved_url="https://www.eesti.ee",
        supplying_source=LinkSource.SEARCH,
        resolution_history=[
            ResolutionAttempt(
                source=LinkSource.PRIOR_SURVEY_KB, order=1, returned=None, usable=False,
                rejection_reason="no prior-cycle link on record",
            ),
            ResolutionAttempt(
                source=LinkSource.MSQ, order=2, returned=None, usable=False,
                rejection_reason="no MSQ submission contained a link",
            ),
            ResolutionAttempt(
                source=LinkSource.SEARCH, order=3, returned="https://www.eesti.ee", usable=True,
            ),
        ],
        detected_language="en",
        language_in_supported_set=True,
    )
    repo.insert_portal(portal)

    q_complete = Question(
        question_id="IF-010",
        cycle_id=cycle.cycle_id,
        text="Organizational structure — Information available on the organizational "
             "structure and/or chart of the government.",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        indicator_id="#010",
    )
    q_broken = Question(
        question_id="IF-014",
        cycle_id=cycle.cycle_id,
        text="Privacy statement(s) — Existence of a privacy policy or statement "
             "available on the national portal.",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        indicator_id="#014",
    )
    repo.insert_question(q_complete)
    repo.insert_question(q_broken)

    now = datetime.now(UTC)

    # --- Complete assessment: two agents agree, evidence intact -----------
    evidence = EvidenceArtifact(
        artifact_id=new_id("ev"),
        resolved_url=portal.resolved_url,
        element_reference=ElementReference(
            css_path="main > section:nth-of-type(2) > div.org-chart", text_hash="abc123", sibling_index=0
        ),
        element_text="Government organizational chart — Ministries and Agencies",
        captured_at=now - timedelta(minutes=10),
        verified_at=now - timedelta(minutes=8),
        verifiability_status="verified",
    )
    repo.insert_evidence(evidence)

    runs = []
    for idx, (answer, confidence, model) in enumerate(
        [(True, 91, "vertexai/gemini-2.0-flash"), (True, 88, "vertexai/gemini-2.0-flash")]
    ):
        run = AssessorAgentRun(
            run_id=new_id("run"),
            session_id=session.session_id,
            question_id=q_complete.question_id,
            portal_id=portal.portal_id,
            agent_index=idx,
            round_number=1,
            answer=answer,
            confidence=confidence,
            justification="The government organizational chart is published under "
                           "the 'About Government' section with department listings.",
            evidence_artifact_id=evidence.artifact_id,
            state=AgentRunState.VALIDATED_PASS,
            model_identity=model,
        )
        repo.insert_agent_run(run)
        runs.append(run)

    adjudication = AdjudicationResult(
        adjudication_id=new_id("adj"),
        session_id=session.session_id,
        question_id=q_complete.question_id,
        portal_id=portal.portal_id,
        round_number=1,
        input_run_ids=[r.run_id for r in runs],
        discrepancy_flagged=False,
        flag_reason=None,
        max_pairwise_confidence_delta=3,
        consensus_answer=True,
        consensus_confidence=90,
        below_acceptance_threshold=False,
    )
    repo.insert_adjudication_result(adjudication)
    repo.upsert_unit(session.session_id, q_complete.question_id, portal.portal_id, "delivered", {})

    # --- Broken-evidence assessment: capture failed ------------------------
    runs_broken = []
    for idx, (answer, confidence) in enumerate([(False, 40), (False, 35)]):
        run = AssessorAgentRun(
            run_id=new_id("run"),
            session_id=session.session_id,
            question_id=q_broken.question_id,
            portal_id=portal.portal_id,
            agent_index=idx,
            round_number=1,
            answer=answer,
            confidence=confidence,
            justification="No privacy statement link found on the homepage or footer; "
                           "evidence capture could not resolve a specific element.",
            evidence_artifact_id=None,
            state=AgentRunState.VALIDATED_PASS,
            model_identity="vertexai/gemini-2.0-flash",
            below_acceptance_threshold=True,
        )
        repo.insert_agent_run(run)
        runs_broken.append(run)

    adjudication_broken = AdjudicationResult(
        adjudication_id=new_id("adj"),
        session_id=session.session_id,
        question_id=q_broken.question_id,
        portal_id=portal.portal_id,
        round_number=1,
        input_run_ids=[r.run_id for r in runs_broken],
        discrepancy_flagged=False,
        flag_reason=None,
        max_pairwise_confidence_delta=5,
        consensus_answer=False,
        consensus_confidence=37,
        below_acceptance_threshold=True,
    )
    repo.insert_adjudication_result(adjudication_broken)
    repo.upsert_unit(session.session_id, q_broken.question_id, portal.portal_id, "delivered", {})

    # --- One unit per blocking condition (quickstart.md Scenario 0) --------
    blocked_question_ids: list[str] = []

    def _seed_blocked_question(question_id: str, text: str, indicator_id: str) -> Question:
        q = Question(
            question_id=question_id,
            cycle_id=cycle.cycle_id,
            text=text,
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id=indicator_id,
        )
        repo.insert_question(q)
        blocked_question_ids.append(question_id)
        return q

    q_no_url = _seed_blocked_question(
        "IF-020", "No usable URL — this question has no resolvable portal link.", "#020"
    )
    repo.upsert_unit(
        session.session_id, q_no_url.question_id, portal.portal_id, UnitState.UNASSESSABLE.value,
        {
            "escalation_reason": EscalationReason.NO_USABLE_URL.value,
            "resolution_history": [
                {"source": "prior_survey_kb", "order": 1, "returned": None, "usable": False,
                 "rejection_reason": "no prior-cycle link on record"},
                {"source": "msq", "order": 2, "returned": None, "usable": False,
                 "rejection_reason": "no MSQ submission contained a link"},
                {"source": "search", "order": 3, "returned": None, "usable": False,
                 "rejection_reason": "search returned no candidate link"},
            ],
        },
    )

    q_auth = _seed_blocked_question(
        "IF-021", "Login barrier — this question's content sits behind an authentication wall.", "#021"
    )
    repo.upsert_unit(
        session.session_id, q_auth.question_id, portal.portal_id, UnitState.ESCALATED.value,
        {
            "escalation_reason": EscalationReason.REQUIRES_AUTHENTICATED_ACCESS.value,
            "reason": "every independent agent observed an authentication boundary",
        },
    )

    q_unverifiable = _seed_blocked_question(
        "IF-022", "Unverifiable target — agents could not independently validate this element.", "#022"
    )
    repo.upsert_unit(
        session.session_id, q_unverifiable.question_id, portal.portal_id, UnitState.ESCALATED.value,
        {
            "escalation_reason": EscalationReason.UNVERIFIABLE_TARGET.value,
            "validated_run_count": 1,
            "total_run_count": 2,
        },
    )

    q_lang_unsupported = _seed_blocked_question(
        "IF-023", "Unsupported language — the portal content is in a language outside the supported set.", "#023"
    )
    repo.upsert_unit(
        session.session_id, q_lang_unsupported.question_id, portal.portal_id, UnitState.ESCALATED.value,
        {
            "escalation_reason": EscalationReason.LANGUAGE_NOT_SUPPORTED.value,
            "detected_language": "fr",
            "reported_languages": {"fr": 2},
            "supported_languages": ["en"],
        },
    )

    q_unreachable = _seed_blocked_question(
        "IF-024", "Unreachable portal — the resolved URL did not respond within the retry bound.", "#024"
    )
    repo.upsert_unit(
        session.session_id, q_unreachable.question_id, portal.portal_id, UnitState.ESCALATED.value,
        {
            "escalation_reason": EscalationReason.UNREACHABLE_PORTAL.value,
            "attempts": 3,
        },
    )

    q_declined = _seed_blocked_question(
        "IF-025", "Language declined — the reviewer declined to proceed in an unsupported language.", "#025"
    )
    repo.upsert_unit(
        session.session_id, q_declined.question_id, portal.portal_id, UnitState.ESCALATED.value,
        {
            "escalation_reason": EscalationReason.LANGUAGE_DECLINED.value,
            "detected_language": "de",
        },
    )
    repo.insert_language_decision(
        LanguageDecision(
            decision_id=new_id("langdec"),
            portal_id=portal.portal_id,
            session_id=session.session_id,
            detected_language="de",
            decision=LanguageDecisionOutcome.DECLINED,
            decided_by_actor_id="demo-assessor",
            resolution_manner="explicit",
        )
    )

    q_disagreement = _seed_blocked_question(
        "IF-026", "Unresolved disagreement — independent agents could not reach consensus after retry.", "#026"
    )
    disagreement_runs = []
    for round_number in (1, 2):
        for idx, (answer, confidence) in enumerate([(True, 60), (False, 55)]):
            run = AssessorAgentRun(
                run_id=new_id("run"),
                session_id=session.session_id,
                question_id=q_disagreement.question_id,
                portal_id=portal.portal_id,
                agent_index=idx,
                round_number=round_number,
                answer=answer,
                confidence=confidence,
                justification="Agents disagree on whether the cited element satisfies the question.",
                state=AgentRunState.VALIDATED_PASS,
                model_identity="vertexai/gemini-2.0-flash",
                confidence_retry_count=round_number - 1,
            )
            repo.insert_agent_run(run)
            disagreement_runs.append(run)
        repo.insert_adjudication_result(
            AdjudicationResult(
                adjudication_id=new_id("adj"),
                session_id=session.session_id,
                question_id=q_disagreement.question_id,
                portal_id=portal.portal_id,
                round_number=round_number,
                input_run_ids=[r.run_id for r in disagreement_runs[-2:]],
                discrepancy_flagged=True,
                flag_reason=f"Round {round_number}: agents split True/False with no majority",
                max_pairwise_confidence_delta=5,
                consensus_answer=None,
                consensus_confidence=None,
                below_acceptance_threshold=True,
            )
        )
    repo.upsert_unit(
        session.session_id, q_disagreement.question_id, portal.portal_id, UnitState.ESCALATED.value,
        {
            "escalation_reason": EscalationReason.UNRESOLVED_DISAGREEMENT.value,
            "flag_reason": "Round 2: agents split True/False with no majority",
            "max_pairwise_confidence_delta": 5,
        },
    )

    return {
        "session_id": session.session_id,
        "portal_id": portal.portal_id,
        "question_ids": [q_complete.question_id, q_broken.question_id, *blocked_question_ids],
    }
