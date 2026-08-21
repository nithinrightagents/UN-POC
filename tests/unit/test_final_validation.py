"""Tests for the validator gate in the per-agent retry loop (spec 008 US5).

The delivery-time final validation gate (FR-PF-030) was deleted in T018 because
it re-ran validation on evidence that had already passed the per-agent loop,
meaning it could only remove answers, never add them.

These tests cover the per-agent VALIDATED_PASS loop in retry_loops.py, which is
retained and unchanged. Tests that previously asserted FAILED_FINAL_VALIDATION
from the delivery gate now assert DELIVERED — because once two agents both
VALIDATED_PASS, a prefill is produced without a second gate.
"""

import json
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
from shared.tools.browser import PageResult

pytestmark = pytest.mark.unit


class FakeModelResponse:
    def __init__(self, text: str, model_identity: str = "vertexai/gemini-pro"):
        self.text = text
        self.model_identity = model_identity
        self.input_tokens = 20
        self.output_tokens = 30


class FakeValidatorProvider:
    def __init__(self, should_pass: bool = True, raise_error: bool = False):
        self.should_pass = should_pass
        self.raise_error = raise_error

    async def generate(self, *, model, system_instruction, prompt, temperature, response_schema=None):
        if self.raise_error:
            raise RuntimeError("Validator provider error")

        if response_schema and "evidence_supports_answer" in response_schema.get("properties", {}):
            payload = {
                "evidence_supports_answer": self.should_pass,
                "justification_consistent": self.should_pass,
                "confidence_proportionate": self.should_pass,
                "gaps": [] if self.should_pass else ["Evidence does not support assertion."],
            }
            return FakeModelResponse(json.dumps(payload), f"vertexai/{model}")

        return FakeModelResponse("{}", f"vertexai/{model}")


class FakePage:
    def __init__(self, text: str = "Online Verification Tool"):
        self.text = text

    async def evaluate(self, script, *args):
        return {"cssPath": "#cert-verif", "text": self.text}

    async def close(self):
        pass


class FakeBrowserSession:
    def __init__(self, reachable: bool = True):
        self.reachable = reachable

    async def fetch(self, url, caller_class, fetch_log=None, timeout_ms=15000):
        return PageResult(
            url=url,
            final_url=url,
            html="<html><body><div id='cert-verif'>Online Verification Tool</div></body></html>",
            status=200,
            reachable=self.reachable,
        ), FakePage()

    async def close_page(self, page):
        pass


def _setup_env():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-fval",
        name="Final Val Test Cycle",
        questionnaire_ref="Test Ref",
        country_set=["EE"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-fval",
        cycle_id="c-fval",
        country_id="EE",
        resolved_url="https://eesti.ee",
    )
    repo.insert_portal(portal)

    settings = Settings(
        assessor_agent_count=2,
        supported_languages=["en", "et"],
        prefill_confidence_gap_tolerance=10,
    )

    fetch_log = FetchLog(conn, "s-fval")
    stage_log = StageEventLog(conn, "s-fval")
    cost_ledger = CostLedger(conn, "s-fval")

    return repo, conn, settings, fetch_log, stage_log, cost_ledger, portal


from shared.tools.element_ref import text_hash


def _insert_run_with_evidence(
    repo: Repository,
    session_id: str,
    question_id: str,
    portal_id: str,
    run_id: str,
    agent_index: int,
    answer: bool = True,
    confidence: int = 90,
) -> AssessorAgentRun:
    evidence = EvidenceArtifact(
        artifact_id=f"art-{run_id}",
        resolved_url="https://eesti.ee",
        element_reference=ElementReference(css_path="#cert-verif", text_hash=text_hash("Online Verification Tool")),
        element_text="Online Verification Tool",
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
        justification="Verified tool.",
        evidence_artifact_id=evidence.artifact_id,
        state=AgentRunState.VALIDATED_PASS,
        detected_language="en",
    )
    repo.insert_agent_run(run)
    return run


@pytest.mark.asyncio
async def test_two_validated_pass_runs_delivers_prefill():
    """Two VALIDATED_PASS runs agree → DELIVERED (no delivery-time gate, T018)."""
    repo, conn, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    provider = FakeValidatorProvider(should_pass=True)
    browser = FakeBrowserSession(reachable=True)

    q = Question(
        question_id="c-fval:1.1",
        cycle_id="c-fval",
        indicator_id="1.1",
        text="Digital certificate verification?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-fval", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    _insert_run_with_evidence(repo, "s-fval", q.question_id, portal.portal_id, "run-fv-1", 0)
    _insert_run_with_evidence(repo, "s-fval", q.question_id, portal.portal_id, "run-fv-2", 1)

    outcome = await process_unit(
        repo=repo,
        settings=settings,
        session_id="s-fval",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        question=q,
        portal=portal,
        run_id="run-fv-job",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-fval", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is True
    assert prefill.answer is True
    assert prefill.reason is None


@pytest.mark.asyncio
async def test_two_validated_pass_runs_delivers_even_with_failing_provider():
    """T018: delivery-time gate is gone; a provider that would have failed the old gate
    now has no effect — the two per-agent VALIDATED_PASS runs are enough to deliver."""
    repo, conn, settings, fetch_log, stage_log, cost_ledger, portal = _setup_env()
    # Provider that would have rejected at the old delivery gate
    provider = FakeValidatorProvider(should_pass=False)
    browser = FakeBrowserSession(reachable=True)

    q = Question(
        question_id="c-fval:1.2",
        cycle_id="c-fval",
        indicator_id="1.2",
        text="Feature delivers despite old gate?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-fval", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    _insert_run_with_evidence(repo, "s-fval", q.question_id, portal.portal_id, "run-fv-3", 0)
    _insert_run_with_evidence(repo, "s-fval", q.question_id, portal.portal_id, "run-fv-4", 1)

    outcome = await process_unit(
        repo=repo,
        settings=settings,
        session_id="s-fval",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        question=q,
        portal=portal,
        run_id="run-fv-job-2",
    )

    # T018: delivery gate gone → DELIVERED even when the old gate would have rejected
    assert outcome.final_state == UnitState.DELIVERED, (
        f"Expected DELIVERED after T018 removed the delivery gate, got {outcome.final_state}"
    )
