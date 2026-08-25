"""Tests for prefill run budget enforcement (spec 008 US6, FR-PF-041)."""

import json
import sqlite3

import pytest

from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from orchestration.budget import RunBudget
from orchestration.scheduler import run_batch
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    AnswerType,
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
    def __init__(self, text: str, model_identity: str = "vertexai/gemini-2.5-flash"):
        self.text = text
        self.model_identity = model_identity
        self.input_tokens = 500
        self.output_tokens = 500


class CostingModelProvider:
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
            "answer": True,
            "confidence": 90,
            "justification": "Clear evidence found on portal.",
            "evidence_quote": "Official verification service.",
            "auth_boundary_observed": False,
            "detected_language": "en",
        }
        return FakeModelResponse(json.dumps(payload), f"vertexai/{model}")


class FakePage:
    async def evaluate(self, script, *args):
        return {"cssPath": "#serv", "text": "Official verification service."}

    async def close(self):
        pass


class FakeBrowserSession:
    async def fetch(self, url, caller_class, fetch_log=None, timeout_ms=15000):
        return PageResult(
            url=url,
            final_url=url,
            html="<div id='serv'>Official verification service.</div>",
            status=200,
            reachable=True,
        ), FakePage()

    async def close_page(self, page):
        pass


def test_run_budget_unit_semantics():
    uncapped = RunBudget(limit=0.0)
    assert not uncapped.exhausted()
    uncapped.record(10.0)
    assert not uncapped.exhausted()
    assert uncapped.spent == 10.0

    capped = RunBudget(limit=0.01)
    assert not capped.exhausted()
    capped.record(0.005)
    assert not capped.exhausted()
    capped.record(0.006)
    assert capped.exhausted()


@pytest.mark.asyncio
async def test_budget_exhaustion_stops_undispatched_and_completes_inflight():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-bdg",
        name="Budget Cycle",
        questionnaire_ref="Test Ref",
        country_set=["FI"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-bdg",
        cycle_id="c-bdg",
        country_id="FI",
        resolved_url="https://suomi.fi",
    )
    repo.insert_portal(portal)

    questions = [
        Question(
            question_id=f"c-bdg:q{i}",
            cycle_id="c-bdg",
            indicator_id=f"q{i}",
            text=f"Indicator question {i}?",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
        for i in range(1, 4)
    ]
    for q in questions:
        repo.insert_question(q)
        repo.upsert_unit(
            "s-bdg",
            q.question_id,
            portal.portal_id,
            UnitState.RESOLVED.value,
            {"resolved_url": portal.resolved_url},
        )

    settings = Settings(
        assessor_agent_count=2,
        batch_size=1,  # Sequential execution to cleanly observe inflight vs undispatched
        supported_languages=["en"],
        prefill_run_budget=0.0001,  # Very small budget so first call exceeds it
    )

    budget = RunBudget(limit=settings.prefill_run_budget)
    fetch_log = FetchLog(conn, "s-bdg")
    stage_log = StageEventLog(conn, "s-bdg")
    cost_ledger = CostLedger(conn, "s-bdg", budget=budget)
    provider = CostingModelProvider()
    browser = FakeBrowserSession()

    await run_batch(
        repo=repo,
        settings=settings,
        session_id="s-bdg",
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        questions=questions,
        portals=[portal],
        adjudicate_results=True,
        run_id="run-bdg-1",
    )

    assert budget.exhausted()
    prefills = repo.list_prefills_for_run("run-bdg-1")
    print("ALL PREFILLS:", [(p.question_id, p.suggested, p.reason, p.answer) for p in prefills])
    assert len(prefills) == 3

    # At least one indicator delivered (the in-flight one)
    delivered = [p for p in prefills if p.suggested]
    assert len(delivered) >= 1

    # Undispatched indicators stopped with BUDGET_REACHED
    budget_stopped = [p for p in prefills if p.reason == PrefillReason.BUDGET_REACHED.value or p.reason == PrefillReason.BUDGET_REACHED]
    assert len(budget_stopped) >= 1


@pytest.mark.asyncio
async def test_concurrent_units_track_independent_run_budgets():
    """Two concurrent unit runs sharing a session_id track independent RunBudget limits."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-conc",
        name="Concurrent Cycle",
        questionnaire_ref="Test Ref",
        country_set=["FI", "SE"],
    )
    repo.insert_cycle(cycle)

    p1 = TargetPortal(portal_id="p1", cycle_id="c-conc", country_id="FI", resolved_url="https://fi.gov")
    p2 = TargetPortal(portal_id="p2", cycle_id="c-conc", country_id="SE", resolved_url="https://se.gov")
    repo.insert_portal(p1)
    repo.insert_portal(p2)

    q = Question(
        question_id="c-conc:q1",
        cycle_id="c-conc",
        indicator_id="q1",
        text="Digital service?",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-conc", q.question_id, p1.portal_id, UnitState.RESOLVED.value, {"resolved_url": p1.resolved_url})
    repo.upsert_unit("s-conc", q.question_id, p2.portal_id, UnitState.RESOLVED.value, {"resolved_url": p2.resolved_url})

    b1 = RunBudget(limit=1.0)
    b2 = RunBudget(limit=2.0)

    cl1 = CostLedger(conn, "s-conc", budget=b1)
    cl2 = CostLedger(conn, "s-conc", budget=b2)

    cl1.record("assessor_run", "gemini", 100, 100, 0.05)
    assert b1.spent == 0.05
    assert b2.spent == 0.0  # b2 is independent and untouched

    cl2.record("assessor_run", "gemini", 100, 100, 0.10)
    assert b1.spent == 0.05
    assert b2.spent == 0.10
