"""Tests for prefill pipeline execution (spec 008 US2, Scenario 1)."""

import json
import sqlite3
import pytest

from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from orchestration.scheduler import process_unit, run_batch
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
    def __init__(self, text: str, model_identity: str):
        self.text = text
        self.model_identity = model_identity
        self.input_tokens = 10
        self.output_tokens = 10


class FakeModelProvider:
    async def generate(self, *, model, system_instruction, prompt, temperature, response_schema=None):
        if response_schema and "evidence_supports_answer" in response_schema.get("properties", {}):
            payload = {
                "evidence_supports_answer": True,
                "justification_consistent": True,
                "confidence_proportionate": True,
                "gaps": [],
            }
            return FakeModelResponse(json.dumps(payload), f"vertexai/{model}")
        return FakeModelResponse("{}", f"vertexai/{model}")


class FakePage:
    async def evaluate(self, script, *args):
        return {"cssPath": "#feat", "text": "Found verified evidence."}

    async def close(self):
        pass


class FakeBrowserSession:
    async def fetch(self, url, caller_class, fetch_log=None):
        return PageResult(url=url, final_url=url, html="<div>Found verified evidence.</div>", status=200, reachable=True), FakePage()

    async def close_page(self, page):
        pass


def _setup_pipeline_env():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-pipe",
        name="Pipeline Test Cycle",
        questionnaire_ref="Test Ref",
        country_set=["DK"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-pipe",
        cycle_id="c-pipe",
        country_id="DK",
        resolved_url="https://borger.dk",
    )
    repo.insert_portal(portal)

    settings = Settings(
        assessor_agent_count=2,
        supported_languages=["en"],
        prefill_confidence_gap_tolerance=10,
    )

    fetch_log = FetchLog(conn, "s-pipe")
    stage_log = StageEventLog(conn, "s-pipe")
    cost_ledger = CostLedger(conn, "s-pipe")

    return repo, conn, settings, fetch_log, stage_log, cost_ledger, portal


from shared.tools.element_ref import text_hash
from shared.state.entities import ElementReference, EvidenceArtifact


def _insert_validated_run(
    repo: Repository,
    session_id: str,
    question_id: str,
    portal_id: str,
    run_id: str,
    agent_index: int,
    answer: bool,
    confidence: int,
    detected_language: str = "en",
) -> AssessorAgentRun:
    evidence = EvidenceArtifact(
        artifact_id=f"art-{run_id}",
        resolved_url="https://borger.dk",
        capture_ref="/captures/test.png",
        element_reference=ElementReference(css_path="#feat", text_hash=text_hash("Found verified evidence.")),
        element_text="Found verified evidence.",
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
        justification="Found verified evidence.",
        evidence_artifact_id=evidence.artifact_id,
        state=AgentRunState.VALIDATED_PASS,
        detected_language=detected_language,
    )
    repo.insert_agent_run(run)
    return run


@pytest.mark.asyncio
async def test_unanimous_agreement_writes_delivered_prefill():
    repo, conn, settings, fetch_log, stage_log, cost_ledger, portal = _setup_pipeline_env()
    provider = FakeModelProvider()
    browser = FakeBrowserSession()

    q = Question(
        question_id="c-pipe:1.1",
        cycle_id="c-pipe",
        indicator_id="1.1",
        text="Does feature exist?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-pipe", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    _insert_validated_run(repo, "s-pipe", q.question_id, portal.portal_id, "run-1", 0, True, 90)
    _insert_validated_run(repo, "s-pipe", q.question_id, portal.portal_id, "run-2", 1, True, 85)

    outcome = await process_unit(
        repo=repo,
        settings=settings,
        session_id="s-pipe",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        capture_dir="/tmp",
        question=q,
        portal=portal,
        run_id="run-pipe-1",
    )

    assert outcome.final_state == UnitState.DELIVERED
    prefill = repo.latest_prefill("s-pipe", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is True
    assert prefill.answer is True
    assert prefill.reason is None
    assert prefill.run_id == "run-pipe-1"
    assert prefill.agreement_outcome in ("uncontested", "agreed_with_gap")
    assert len(prefill.position_run_ids) == 2


@pytest.mark.asyncio
async def test_differing_answers_write_unresolved_disagreement():
    repo, conn, settings, fetch_log, stage_log, cost_ledger, portal = _setup_pipeline_env()
    provider = FakeModelProvider()
    browser = FakeBrowserSession()

    q = Question(
        question_id="c-pipe:1.2",
        cycle_id="c-pipe",
        indicator_id="1.2",
        text="Disputed feature?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-pipe", q.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    _insert_validated_run(repo, "s-pipe", q.question_id, portal.portal_id, "run-d1", 0, True, 90)
    _insert_validated_run(repo, "s-pipe", q.question_id, portal.portal_id, "run-d2", 1, False, 85)

    outcome = await process_unit(
        repo=repo,
        settings=settings,
        session_id="s-pipe",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        capture_dir="/tmp",
        question=q,
        portal=portal,
        run_id="run-pipe-2",
    )

    assert outcome.final_state == UnitState.NO_SUGGESTION
    assert outcome.detail == PrefillReason.UNRESOLVED_DISAGREEMENT.value
    prefill = repo.latest_prefill("s-pipe", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is False
    assert prefill.answer is None
    assert prefill.reason == PrefillReason.UNRESOLVED_DISAGREEMENT.value or prefill.reason == PrefillReason.UNRESOLVED_DISAGREEMENT


@pytest.mark.asyncio
async def test_pipeline_headless_invariants_scenario_1():
    """Scenario 1: Full headless execution produces prefill per indicator, zero escalations, no ESCALATED state."""
    repo, conn, settings, fetch_log, stage_log, cost_ledger, portal = _setup_pipeline_env()
    provider = FakeModelProvider()
    browser = FakeBrowserSession()

    q1 = Question(
        question_id="c-pipe:q1",
        cycle_id="c-pipe",
        indicator_id="q1",
        text="Normal indicator",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    q2 = Question(
        question_id="c-pipe:q2",
        cycle_id="c-pipe",
        indicator_id="q2",
        text="Auth wall indicator",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        requires_authenticated_access=True,
    )
    repo.insert_question(q1)
    repo.insert_question(q2)
    repo.upsert_unit("s-pipe", q1.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})
    repo.upsert_unit("s-pipe", q2.question_id, portal.portal_id, UnitState.RESOLVED.value, {"resolved_url": portal.resolved_url})

    _insert_validated_run(repo, "s-pipe", q1.question_id, portal.portal_id, "run-q1-1", 0, True, 90)
    _insert_validated_run(repo, "s-pipe", q1.question_id, portal.portal_id, "run-q1-2", 1, True, 85)

    summary = await run_batch(
        repo=repo,
        settings=settings,
        session_id="s-pipe",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        capture_dir="/tmp",
        questions=[q1, q2],
        portals=[portal],
        run_id="job-pipe-batch",
    )

    # 1. Zero rows in escalation_queue_items
    escalations = repo.list_escalations("s-pipe")
    assert len(escalations) == 0

    # 2. No unit is ESCALATED
    units = repo.list_units_for_portal("s-pipe", portal.portal_id)
    states = [u["state"] for u in units]
    assert UnitState.ESCALATED.value not in states

    # 3. count(prefills WHERE run_id=R) == count(questions)
    prefills = repo.list_prefills_for_run("job-pipe-batch")
    assert len(prefills) == 2
    assert {p.question_id for p in prefills} == {q1.question_id, q2.question_id}


from shared.state.entities import MSQLinkCandidate, PriorSurveyLink, new_id
from shared.tools.linkresolution.chain import resolve_link


@pytest.mark.asyncio
async def test_source_cascade_matrix_sc009():
    """Scenario 8 / SC-009: earliest usable source in resolution_order supplies link; later sources not consulted."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    # 1. KB succeeds
    repo.insert_prior_survey_link(
        PriorSurveyLink(
            link_id=new_id("link"), question_id="q-kb", country_id="EE",
            url="https://www.eesti.ee", origin_cycle_id="c0", origin_session_id="s0",
        )
    )
    # 2. MSQ succeeds when KB empty
    repo.insert_msq_link_candidate(
        MSQLinkCandidate(
            candidate_id=new_id("msq"), submission_id="sub1", question_id="q-msq",
            country_id="EE", url="https://msq.eesti.ee",
        )
    )

    settings = Settings(url_resolution_mode="historical_first")

    # Test KB resolution
    res_kb = await resolve_link(repo, None, "q-kb", "EE", "search query", settings)
    assert res_kb.resolved_url == "https://www.eesti.ee"
    assert res_kb.supplying_source.value == "prior_survey_kb"
    assert len(res_kb.history) == 1  # MSQ and search not consulted

    # Test MSQ resolution (KB has no candidate)
    res_msq = await resolve_link(repo, None, "q-msq", "EE", "search query", settings)
    assert res_msq.resolved_url == "https://msq.eesti.ee"
    assert res_msq.supplying_source.value == "msq"
    assert len(res_msq.history) == 2  # KB tried (empty), MSQ succeeded

    # Test total exhaustion (no candidates in KB or MSQ, search returns nothing)
    res_none = await resolve_link(repo, None, "q-none", "EE", "search query", settings)
    assert res_none.resolved_url is None
    assert res_none.supplying_source is None
    assert len(res_none.history) >= 2
