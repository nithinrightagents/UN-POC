"""Seed data for demonstrating the review surface with no pipeline running.

Independent test for US1 (spec.md): "Seed one pre-computed assessment with
a complete evidence set... [and] one where evidence capture failed" so
FR-024's confidence cap is directly observable in the UI.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from shared.state.entities import (
    AdjudicationResult,
    AssessmentSession,
    AssessorAgentRun,
    AgentRunState,
    AnswerType,
    ElementReference,
    EvidenceArtifact,
    EvidenceLocus,
    LinkSource,
    Question,
    ResolutionAttempt,
    SessionMode,
    SessionStatus,
    SurveyCycle,
    TargetPortal,
    new_id,
)
from shared.persistence.repositories import Repository


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

    now = datetime.now(timezone.utc)

    # --- Complete assessment: two agents agree, evidence intact -----------
    evidence = EvidenceArtifact(
        artifact_id=new_id("ev"),
        resolved_url=portal.resolved_url,
        capture_ref="demo-capture-010.png",
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

    return {
        "session_id": session.session_id,
        "portal_id": portal.portal_id,
        "question_ids": [q_complete.question_id, q_broken.question_id],
    }
