"""Tests for agreement classification, ResolverAgent, and dispute resolution (spec 008 US4)."""

import json
import sqlite3
import pytest

from agents.adjudicator.agreement import classify_agreement
from agents.resolver.agent import ResolverAgent
from agents.resolver.schema import ResolverDecision
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
    EvidenceLocus,
    PrefillReason,
    Question,
    SurveyCycle,
    TargetPortal,
    UnitState,
)
from shared.tools.browser import PageResult

pytestmark = pytest.mark.unit


class FakeModelResponse:
    def __init__(self, text: str, model_identity: str = "vertexai/gemini-pro"):
        self.text = text
        self.model_identity = model_identity
        self.input_tokens = 20
        self.output_tokens = 30


class FakeResolverProvider:
    def __init__(self, selected_run_id: str | None, undetermined: bool = False):
        self.selected_run_id = selected_run_id
        self.undetermined = undetermined

    async def generate(self, *, model, system_instruction, prompt, temperature, response_schema=None):
        if response_schema and "evidence_supports_answer" in response_schema.get("properties", {}):
            payload = {
                "evidence_supports_answer": True,
                "justification_consistent": True,
                "confidence_proportionate": True,
                "gaps": [],
            }
            return FakeModelResponse(json.dumps(payload), f"vertexai/{model}")

        payload = {
            "disagreement_characterization": "Dispute over whether feature is active or informational only.",
            "selected_run_id": self.selected_run_id,
            "reasoning": "Position A cited verifiable interactive portal flow, while Position B missed the link.",
            "confidence": 88 if self.selected_run_id else None,
            "undetermined": self.undetermined,
        }
        return FakeModelResponse(json.dumps(payload), f"vertexai/{model}")


class FakePage:
    def __init__(self, text: str = "Interactive portal exists."):
        self.text = text

    async def evaluate(self, script, *args):
        return {"cssPath": "#feat", "text": self.text}

    async def close(self):
        pass


class FakeBrowserSession:
    def __init__(self, text: str = "Interactive portal exists."):
        self.text = text

    async def fetch(self, url, caller_class, fetch_log=None, timeout_ms=15000):
        return PageResult(url=url, final_url=url, html=f"<div>{self.text}</div>", status=200, reachable=True), FakePage(self.text)

    async def close_page(self, page):
        pass


def _setup_env():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-res",
        name="Resolver Test Cycle",
        questionnaire_ref="Test Ref",
        country_set=["NO"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-res",
        cycle_id="c-res",
        country_id="NO",
        resolved_url="https://norge.no",
    )
    repo.insert_portal(portal)

    settings = Settings(
        assessor_agent_count=2,
        supported_languages=["en", "no"],
        prefill_confidence_gap_tolerance=10,
    )

    fetch_log = FetchLog(conn, "s-res")
    stage_log = StageEventLog(conn, "s-res")
    cost_ledger = CostLedger(conn, "s-res")

    return repo, conn, settings, fetch_log, stage_log, cost_ledger, portal


from shared.tools.element_ref import text_hash
from shared.state.entities import ElementReference, EvidenceArtifact


def _insert_run(
    repo: Repository,
    session_id: str,
    question_id: str,
    portal_id: str,
    run_id: str,
    agent_index: int,
    answer: bool,
    confidence: int,
    justification: str = "Verified position.",
) -> AssessorAgentRun:
    evidence = EvidenceArtifact(
        artifact_id=f"art-{run_id}",
        resolved_url="https://norge.no",
        element_reference=ElementReference(css_path="#feat", text_hash=text_hash(justification)),
        element_text=justification,
    )
    repo.insert_evidence(evidence)

    run = AssessorAgentRun(
        run_id=run_id,
        session_id=session_id,
        question_id=question_id,
        portal_id=portal_id,
        agent_index=agent_index,
        round_number=1,
        answer=answer,
        confidence=confidence,
        justification=justification,
        evidence_artifact_id=evidence.artifact_id,
        state=AgentRunState.VALIDATED_PASS,
        detected_language="en",
    )
    repo.insert_agent_run(run)
    return run


def test_classify_agreement_scenarios():
    # Uncontested agreement
    r1 = AssessorAgentRun(
        run_id="r1", session_id="s", question_id="q", portal_id="p",
        agent_index=0, round_number=1, answer=True, confidence=90, justification="J1",
        state=AgentRunState.VALIDATED_PASS,
    )
    r2 = AssessorAgentRun(
        run_id="r2", session_id="s", question_id="q", portal_id="p",
        agent_index=1, round_number=1, answer=True, confidence=85, justification="J2",
        state=AgentRunState.VALIDATED_PASS,
    )
    outcome = classify_agreement([r1, r2], gap_tolerance=10)
    assert outcome.kind == "uncontested"
    assert outcome.answer is True
    assert outcome.confidence_gap == 5

    # Agreed with gap (Scenario 4)
    r3 = AssessorAgentRun(
        run_id="r3", session_id="s", question_id="q", portal_id="p",
        agent_index=1, round_number=1, answer=True, confidence=65, justification="J3",
        state=AgentRunState.VALIDATED_PASS,
    )
    outcome_gap = classify_agreement([r1, r3], gap_tolerance=10)
    assert outcome_gap.kind == "agreed_with_gap"
    assert outcome_gap.answer is True
    assert outcome_gap.confidence_gap == 25
    # Penalized confidence: consensus confidence minus gap
    assert outcome_gap.confidence < 90

    # Disputed (different answers)
    r4 = AssessorAgentRun(
        run_id="r4", session_id="s", question_id="q", portal_id="p",
        agent_index=1, round_number=1, answer=False, confidence=90, justification="J4",
        state=AgentRunState.VALIDATED_PASS,
    )
    outcome_dispute = classify_agreement([r1, r4], gap_tolerance=10)
    assert outcome_dispute.kind == "disputed"
    assert outcome_dispute.answer is None


@pytest.mark.asyncio
async def test_scenario_2_resolver_settles_dispute():
    """Scenario 2: Assessor A and B disagree -> resolver selects Position A -> prefill suggested=True, resolved_dispute."""
    repo, conn, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    provider = FakeResolverProvider(selected_run_id="run-a", undetermined=False)
    browser = FakeBrowserSession()

    q = Question(
        question_id="c-res:q-s2",
        cycle_id="c-res",
        indicator_id="q-s2",
        text="Disputed digital ID service?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-res", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    _insert_run(repo, "s-res", q.question_id, portal.portal_id, "run-a", 0, True, 90, justification="Interactive portal exists.")
    _insert_run(repo, "s-res", q.question_id, portal.portal_id, "run-b", 1, False, 85, justification="No link found on home page.")

    outcome = await process_unit(
        repo=repo,
        settings=settings,
        session_id="s-res",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        question=q,
        portal=portal,
        run_id="run-s2-job",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-res", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is True
    assert prefill.answer is True
    assert prefill.agreement_outcome == "resolved_dispute"
    assert prefill.reason is None
    assert prefill.resolver_decision is not None
    assert prefill.resolver_decision["selected_run_id"] == "run-a"
    assert prefill.unselected_position is not None
    assert prefill.unselected_position["run_id"] == "run-b"
    assert prefill.unselected_position["answer"] is False


@pytest.mark.asyncio
async def test_scenario_3_resolver_undetermined():
    """Scenario 3: Assessor A and B disagree -> resolver finds evidence weak -> undetermined -> prefill suggested=False, unresolved_disagreement."""
    repo, conn, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    provider = FakeResolverProvider(selected_run_id=None, undetermined=True)
    browser = FakeBrowserSession()

    q = Question(
        question_id="c-res:q-s3",
        cycle_id="c-res",
        indicator_id="q-s3",
        text="Ambiguous portal indicator?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-res", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    _insert_run(repo, "s-res", q.question_id, portal.portal_id, "run-3a", 0, True, 60)
    _insert_run(repo, "s-res", q.question_id, portal.portal_id, "run-3b", 1, False, 60)

    outcome = await process_unit(
        repo=repo,
        settings=settings,
        session_id="s-res",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        question=q,
        portal=portal,
        run_id="run-s3-job",
    )

    assert outcome.final_state == UnitState.NO_SUGGESTION
    assert outcome.detail == PrefillReason.UNRESOLVED_DISAGREEMENT.value
    prefill = repo.latest_prefill("s-res", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is False
    assert prefill.answer is None
    assert prefill.reason == PrefillReason.UNRESOLVED_DISAGREEMENT.value or prefill.reason == PrefillReason.UNRESOLVED_DISAGREEMENT


@pytest.mark.asyncio
async def test_resolver_coercion_on_invalid_selection_or_error():
    """If resolver returns unknown run_id or raises, decision coerces to undetermined."""
    agent = ResolverAgent()
    settings = Settings()
    r1 = AssessorAgentRun(
        run_id="run-x", session_id="s", question_id="q", portal_id="p",
        agent_index=0, round_number=1, answer=True, confidence=90, justification="J",
        state=AgentRunState.VALIDATED_PASS,
    )
    r2 = AssessorAgentRun(
        run_id="run-y", session_id="s", question_id="q", portal_id="p",
        agent_index=1, round_number=1, answer=False, confidence=90, justification="J",
        state=AgentRunState.VALIDATED_PASS,
    )

    # Provider returning invalid run ID
    bad_provider = FakeResolverProvider(selected_run_id="unknown-run-z")
    decision = await agent.resolve(
        question_text="Q?",
        portal_url="https://test.gov",
        runs=[r1, r2],
        disagreement_points=["Disagreement"],
        settings=settings,
        provider=bad_provider,
    )
    assert decision.undetermined is True
    assert decision.selected_run_id is None
