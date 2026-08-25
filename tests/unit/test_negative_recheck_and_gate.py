"""Unit tests for negative recheck, query variant, negative delivery gate, and negative provenance (spec 011 T041, T042, T046, T047, T028)."""

from __future__ import annotations

import sqlite3

import pytest

from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from orchestration.scheduler import process_unit
from review.query import build_question_review
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


def _setup_env():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-neg", name="Negative Recheck Cycle", questionnaire_ref="Test Ref", country_set=["US"]
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-us", cycle_id="c-neg", country_id="US", resolved_url="https://www.usa.gov"
    )
    repo.insert_portal(portal)

    settings = Settings(assessor_agent_count=1, supported_languages=["en"])

    return (
        repo,
        settings,
        FetchLog(conn, "s-neg"),
        StageEventLog(conn, "s-neg"),
        CostLedger(conn, "s-neg"),
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
    resolved_url: str = "https://www.usa.gov/page1",
    navigated_to_url: str | None = None,
) -> AssessorAgentRun:
    evidence = EvidenceArtifact(
        artifact_id=f"art-{run_id}",
        resolved_url=resolved_url,
        element_reference=ElementReference(css_path="#neg", text_hash=text_hash("Negative anchor.")),
        element_text="Negative anchor.",
    )
    repo.insert_evidence(evidence)
    run = AssessorAgentRun(
        run_id=run_id,
        session_id="s-neg",
        question_id=question_id,
        portal_id=portal_id,
        agent_index=agent_index,
        round_number=1,
        answer=answer,
        confidence=confidence,
        justification="Negative anchor found on page.",
        evidence_artifact_id=evidence.artifact_id,
        state=state,
        detected_language="en",
        navigated_to_url=navigated_to_url,
    )
    repo.insert_agent_run(run)
    return run


class FakeModelProvider:
    async def generate(self, *args, **kwargs):
        raise AssertionError("no model call expected in direct delivery test")


class FakeBrowserSession:
    async def fetch(self, *args, **kwargs):
        raise AssertionError("no browser fetch expected in direct delivery test")


@pytest.mark.asyncio
async def test_negative_delivery_gate_floors_when_multiple_pages_and_queries():
    """T046 & T047: When >= 2 distinct pages and >= 2 queries are examined, negative delivers clean and floored."""
    repo, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    q = Question(
        question_id="c-neg:1.1",
        cycle_id="c-neg",
        indicator_id="1.1",
        title="Misinformation statute",
        what="laws regulating online misinformation or fake news",
        text="Does the country have legislation regulating misinformation?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.ANY_GOVERNMENT_DOMAIN,
    )
    repo.insert_question(q)
    repo.upsert_unit(
        "s-neg",
        q.question_id,
        portal.portal_id,
        UnitState.RESOLVED.value,
        {
            "resolved_url": "https://www.justice.gov/page1",
            "negative_recheck_done": True,
            "pages_examined": ["https://www.usa.gov/page0", "https://www.justice.gov/page1"],
            "queries_used": ["misinformation statute", "laws regulating online misinformation"],
            "blocked_domains": ["archive.org"],
        },
    )

    _insert_run(
        repo, q.question_id, portal.portal_id, "run-neg-multi", 0, False, 40,
        AgentRunState.VALIDATED_PASS, resolved_url="https://www.justice.gov/page1"
    )

    outcome = await process_unit(
        repo=repo, settings=settings, session_id="s-neg",
        provider=FakeModelProvider(), browser=FakeBrowserSession(), http_client=None,
        fetch_log=fetch_log, stage_log=stage_log, cost_ledger=cost_ledger,
        question=q, portal=portal, run_id="run-job-neg-1",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-neg", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is True
    assert prefill.answer is False
    assert prefill.reason is None  # Clean delivery, not flagged
    assert prefill.confidence == settings.validated_negative_confidence_floor
    assert prefill.confidence >= 55

    # T047: Negative provenance is recorded in unit context
    review_view = build_question_review(repo, "s-neg", q.question_id, portal.portal_id, 60)
    assert review_view is not None
    assert review_view.delivered_answer is False
    assert review_view.consensus_confidence == settings.validated_negative_confidence_floor


@pytest.mark.asyncio
async def test_negative_delivery_gate_flags_single_page_negative():
    """T046: When < 2 distinct pages examined, negative delivers via NEEDS_HUMAN_REVIEW capped at best_effort ceiling."""
    repo, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    q = Question(
        question_id="c-neg:1.2",
        cycle_id="c-neg",
        indicator_id="1.2",
        title="Single page check",
        text="Does feature exist?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.ANY_GOVERNMENT_DOMAIN,
    )
    repo.insert_question(q)
    repo.upsert_unit(
        "s-neg",
        q.question_id,
        portal.portal_id,
        UnitState.RESOLVED.value,
        {
            "resolved_url": "https://www.usa.gov/single-page",
            "negative_recheck_done": True,
            "pages_examined": ["https://www.usa.gov/single-page"],
            "queries_used": ["single page check"],
        },
    )

    _insert_run(
        repo, q.question_id, portal.portal_id, "run-neg-single", 0, False, 40,
        AgentRunState.VALIDATED_PASS, resolved_url="https://www.usa.gov/single-page"
    )

    outcome = await process_unit(
        repo=repo, settings=settings, session_id="s-neg",
        provider=FakeModelProvider(), browser=FakeBrowserSession(), http_client=None,
        fetch_log=fetch_log, stage_log=stage_log, cost_ledger=cost_ledger,
        question=q, portal=portal, run_id="run-job-neg-2",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-neg", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is True
    assert prefill.answer is False
    assert prefill.reason == PrefillReason.NEEDS_HUMAN_REVIEW.value or prefill.reason == PrefillReason.NEEDS_HUMAN_REVIEW
    assert prefill.confidence == min(40, settings.best_effort_confidence_ceiling)

    # Review portal displays the reason tag
    review_view = build_question_review(repo, "s-neg", q.question_id, portal.portal_id, 60)
    assert review_view is not None
    assert review_view.delivered_answer is False
    assert review_view.reason_tag is not None


@pytest.mark.asyncio
async def test_review_portal_prefill_fallback_t028():
    """T028: Review portal renders delivered_answer and confidence from latest_prefill even with zero adjudication rows."""
    repo, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    q = Question(
        question_id="c-neg:1.3",
        cycle_id="c-neg",
        indicator_id="1.3",
        text="Delivered answer check",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit(
        "s-neg", q.question_id, portal.portal_id, UnitState.DELIVERED.value, {"resolved_url": portal.resolved_url}
    )

    _insert_run(
        repo, q.question_id, portal.portal_id, "run-t028", 0, True, 85,
        AgentRunState.VALIDATED_PASS, resolved_url="https://www.usa.gov/service"
    )

    from orchestration.prefill_writer import write_prefill
    write_prefill(
        repo=repo,
        session_id="s-neg",
        cycle_id="c-neg",
        portal_id=portal.portal_id,
        question_id=q.question_id,
        run_id="run-t028",
        suggested=True,
        answer=True,
        confidence=85,
        justification="Verified service exists.",
        evidence_url="https://www.usa.gov/service",
        advance_state=False,
    )

    adjudications = repo.list_adjudication_results("s-neg", q.question_id, portal.portal_id)
    assert len(adjudications) == 0  # Verify zero adjudication rows in DB

    review_view = build_question_review(repo, "s-neg", q.question_id, portal.portal_id, 60)
    assert review_view is not None
    assert review_view.delivered_answer is True
    assert review_view.system_proposed_answer is True
    assert review_view.consensus_confidence == 85
    assert review_view.below_acceptance_threshold is False
