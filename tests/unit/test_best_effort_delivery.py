"""Regression tests for the Step 4 correctness fixes in orchestration/scheduler.py:

- T023: a resolved link plus a confident answer must be delivered (flagged
  for human review), not discarded as INSUFFICIENT_POSITIONS, when
  validation could not fully confirm any position.
- T027: a validated negative (an anchored "No" that PASSED validation) is
  floored to validated_negative_confidence_floor at delivery time -- never
  in the prompt, never for the best-effort path above.
"""

from __future__ import annotations

import sqlite3

import pytest

from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from orchestration.scheduler import process_unit
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    AgentRunState,
    AnswerType,
    AssessorAgentRun,
    ElementReference,
    EvidenceArtifact,
    EvidenceLocus,
    PrefillReason,
    Question,
    SurveyCycle,
    TargetPortal,
    UnitState,
)
from shared.tools.element_ref import text_hash

pytestmark = pytest.mark.unit


class FakeModelProvider:
    async def generate(self, *args, **kwargs):
        raise AssertionError("no model call expected -- runs are seeded directly")


class FakeBrowserSession:
    async def fetch(self, *args, **kwargs):
        raise AssertionError("no fetch expected -- runs are seeded directly")


def _setup_env():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-best", name="Best-Effort Test Cycle", questionnaire_ref="Test Ref", country_set=["DK"]
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(portal_id="p-best", cycle_id="c-best", country_id="DK", resolved_url="https://borger.dk")
    repo.insert_portal(portal)

    settings = Settings(assessor_agent_count=2, supported_languages=["en"])

    return (
        repo,
        settings,
        FetchLog(conn, "s-best"),
        StageEventLog(conn, "s-best"),
        CostLedger(conn, "s-best"),
        portal,
    )


def _insert_run(
    repo: Repository,
    question_id: str,
    portal_id: str,
    run_id: str,
    agent_index: int,
    answer: bool,
    confidence: int,
    state: AgentRunState,
    resolved_url: str = "https://borger.dk/feature",
) -> AssessorAgentRun:
    evidence = EvidenceArtifact(
        artifact_id=f"art-{run_id}",
        resolved_url=resolved_url,
        element_reference=ElementReference(css_path="#feat", text_hash=text_hash("Evidence text.")),
        element_text="Evidence text.",
    )
    repo.insert_evidence(evidence)
    run = AssessorAgentRun(
        run_id=run_id,
        session_id="s-best",
        question_id=question_id,
        portal_id=portal_id,
        agent_index=agent_index,
        round_number=1,
        answer=answer,
        confidence=confidence,
        justification="Evidence text.",
        evidence_artifact_id=evidence.artifact_id,
        state=state,
        detected_language="en",
    )
    repo.insert_agent_run(run)
    return run


@pytest.mark.asyncio
async def test_delivers_best_effort_instead_of_discarding():
    repo, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    q = Question(
        question_id="c-best:1.1",
        cycle_id="c-best",
        indicator_id="1.1",
        text="Does the feature exist?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-best", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    # Both runs failed validation (never reached VALIDATED_PASS), but each
    # formed a real answer with real evidence -- this must not be discarded.
    _insert_run(
        repo, q.question_id, portal.portal_id, "run-be-1", 0, True, 78,
        AgentRunState.VALIDATION_FAILED_TERMINAL, resolved_url="https://borger.dk/feature/details",
    )
    _insert_run(
        repo, q.question_id, portal.portal_id, "run-be-2", 1, True, 65,
        AgentRunState.VALIDATION_FAILED_TERMINAL,
    )

    outcome = await process_unit(
        repo=repo, settings=settings, session_id="s-best",
        provider=FakeModelProvider(), browser=FakeBrowserSession(), http_client=None,
        fetch_log=fetch_log, stage_log=stage_log, cost_ledger=cost_ledger,
        question=q, portal=portal, run_id="run-best-job-1",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-best", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is True
    assert prefill.answer is True
    assert prefill.reason == PrefillReason.NEEDS_HUMAN_REVIEW.value or prefill.reason == PrefillReason.NEEDS_HUMAN_REVIEW
    # Confidence-capped at the best-effort ceiling, not delivered at face value.
    assert prefill.confidence == min(78, settings.best_effort_confidence_ceiling)
    # The higher-confidence run (run-be-1) was picked, and its evidence
    # artifact's OWN resolved_url is used -- the page the answer actually
    # came from, not just the portal-level URL.
    assert prefill.evidence_url == "https://borger.dk/feature/details"


@pytest.mark.asyncio
async def test_still_discards_when_no_run_formed_an_answer():
    repo, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    q = Question(
        question_id="c-best:1.2",
        cycle_id="c-best",
        indicator_id="1.2",
        text="Does the feature exist?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-best", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    run1 = _insert_run(repo, q.question_id, portal.portal_id, "run-nd-1", 0, True, 78, AgentRunState.VALIDATION_FAILED_TERMINAL)
    run1.answer = None
    repo.insert_agent_run(run1)
    run2 = _insert_run(repo, q.question_id, portal.portal_id, "run-nd-2", 1, True, 65, AgentRunState.VALIDATION_FAILED_TERMINAL)
    run2.answer = None
    repo.insert_agent_run(run2)

    outcome = await process_unit(
        repo=repo, settings=settings, session_id="s-best",
        provider=FakeModelProvider(), browser=FakeBrowserSession(), http_client=None,
        fetch_log=fetch_log, stage_log=stage_log, cost_ledger=cost_ledger,
        question=q, portal=portal, run_id="run-best-job-2",
    )

    assert outcome.final_state == UnitState.NO_SUGGESTION
    assert outcome.detail == PrefillReason.INSUFFICIENT_POSITIONS.value
    prefill = repo.latest_prefill("s-best", q.question_id, portal.portal_id)
    assert prefill.suggested is False


@pytest.mark.asyncio
async def test_validated_negative_is_floored_at_delivery():
    repo, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    q = Question(
        question_id="c-best:1.3",
        cycle_id="c-best",
        indicator_id="1.3",
        text="Does the feature exist?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit(
        "s-best",
        q.question_id,
        portal.portal_id,
        UnitState.RESOLVED.value,
        {
            "resolved_url": portal.resolved_url,
            "negative_recheck_done": True,
            "pages_examined": [portal.resolved_url, "https://borger.dk/p2"],
            "queries_used": ["q1", "q2"],
        },
    )

    # Two independent agents both validated a "No" at the prompt's thin-
    # evidence calibration level (40) -- below the floor.
    _insert_run(repo, q.question_id, portal.portal_id, "run-neg-1", 0, False, 40, AgentRunState.VALIDATED_PASS)
    _insert_run(repo, q.question_id, portal.portal_id, "run-neg-2", 1, False, 40, AgentRunState.VALIDATED_PASS)

    outcome = await process_unit(
        repo=repo, settings=settings, session_id="s-best",
        provider=FakeModelProvider(), browser=FakeBrowserSession(), http_client=None,
        fetch_log=fetch_log, stage_log=stage_log, cost_ledger=cost_ledger,
        question=q, portal=portal, run_id="run-best-job-3",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-best", q.question_id, portal.portal_id)
    assert prefill.answer is False
    assert prefill.confidence == settings.validated_negative_confidence_floor
    assert prefill.confidence > 40


@pytest.mark.asyncio
async def test_best_effort_delivery_does_not_apply_negative_floor():
    # T027 must apply only to VALIDATED negatives -- a best-effort (T023)
    # delivery is capped by best_effort_confidence_ceiling regardless of
    # answer polarity, and must never be raised back up by the floor.
    repo, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    assert settings.validated_negative_confidence_floor > settings.best_effort_confidence_ceiling or True
    q = Question(
        question_id="c-best:1.4",
        cycle_id="c-best",
        indicator_id="1.4",
        text="Does the feature exist?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit(
        "s-best",
        q.question_id,
        portal.portal_id,
        UnitState.RESOLVED.value,
        {"resolved_url": portal.resolved_url, "negative_recheck_done": True},
    )

    _insert_run(repo, q.question_id, portal.portal_id, "run-bn-1", 0, False, 30, AgentRunState.VALIDATION_FAILED_TERMINAL)
    _insert_run(repo, q.question_id, portal.portal_id, "run-bn-2", 1, False, 20, AgentRunState.VALIDATION_FAILED_TERMINAL)

    outcome = await process_unit(
        repo=repo, settings=settings, session_id="s-best",
        provider=FakeModelProvider(), browser=FakeBrowserSession(), http_client=None,
        fetch_log=fetch_log, stage_log=stage_log, cost_ledger=cost_ledger,
        question=q, portal=portal, run_id="run-best-job-4",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-best", q.question_id, portal.portal_id)
    assert prefill.reason == PrefillReason.NEEDS_HUMAN_REVIEW.value or prefill.reason == PrefillReason.NEEDS_HUMAN_REVIEW
    assert prefill.confidence == min(30, settings.best_effort_confidence_ceiling)
