"""Regression tests for the validation-retry addendum split (T025) and the
truncated-page fast-fail (T024), both in orchestration/routers/retry_loops.py.

A mechanical validation failure (evidence could not be relocated on a live
re-fetch) must never be phrased as an invitation to reconsider the answer --
that framing is what flipped a correct answer to an incorrect one in
EGL-036b during a validation retry. Only a judgment-level failure
(evidence_supports_answer / justification_consistent / confidence_proportionate)
should carry the original validator gaps verbatim.
"""

from __future__ import annotations

import sqlite3

import pytest

import orchestration.routers.retry_loops as retry_loops_module
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from shared.persistence.schema import DDL
from shared.state.entities import (
    AgentRunState,
    AssessorAgentRun,
    ValidationResult,
    VerificationOutcome,
)

pytestmark = pytest.mark.unit


def _harness():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    session_id = "s-retry-wording"
    return StageEventLog(conn, session_id), FetchLog(conn, session_id), CostLedger(conn, session_id), session_id


def _initial_run(session_id: str) -> AssessorAgentRun:
    return AssessorAgentRun(
        run_id="run-initial",
        session_id=session_id,
        question_id="q-retry-wording",
        portal_id="p-retry-wording",
        agent_index=0,
        round_number=1,
        answer=True,
        confidence=80,
        justification="The portal describes this benefit under a clear heading.",
        state=AgentRunState.ASSESSED,
    )


async def _drive_loop(monkeypatch, validation_result: ValidationResult, capture: dict):
    stage_log, fetch_log, cost_ledger, session_id = _harness()

    async def _fake_validator_node(state, agent, **kwargs):
        return validation_result

    async def _fake_assessor_node(state, agent_index, round_number, agent, **kwargs):
        capture["addendum"] = state["addendum"]
        run = _initial_run(session_id)
        run.run_id = "run-retry-1"
        run.state = AgentRunState.ASSESSED
        return run

    monkeypatch.setattr(retry_loops_module, "validator_node", _fake_validator_node)
    monkeypatch.setattr("agents.assessor.node.assessor_node", _fake_assessor_node)

    class _FakeSettings:
        validation_retry_limit = 1

    return await retry_loops_module.run_validation_retry_loop(
        session_id=session_id,
        question={
            "question_id": "q-retry-wording",
            "text": "Does the portal describe this benefit?",
            "answer_type": "binary",
            "evidence_locus": "any_government_domain",
        },
        portal_url="https://example.gov/benefits",
        agent_index=0,
        round_number=1,
        settings=_FakeSettings(),
        provider=None,
        browser=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        initial_run=_initial_run(session_id),
        initial_evidence=None,
    )


@pytest.mark.asyncio
async def test_mechanical_failure_asks_to_recite_not_reconsider(monkeypatch):
    validation = ValidationResult(
        validation_id="val-1",
        run_id="run-initial",
        session_id="s-retry-wording",
        quality_score=0.2,
        gaps=["verification element_absent: not found in re-fetched DOM"],
        passed=False,
        retry_number=0,
        verification_outcome=VerificationOutcome.ELEMENT_ABSENT,
        verification_attempts=1,
    )
    capture: dict = {}
    await _drive_loop(monkeypatch, validation, capture)

    addendum_text = " ".join(capture["addendum"].items).lower()
    assert "do not change your answer" in addendum_text
    assert "re-read the page" in addendum_text


@pytest.mark.asyncio
async def test_judgment_failure_keeps_original_gaps(monkeypatch):
    validation = ValidationResult(
        validation_id="val-2",
        run_id="run-initial",
        session_id="s-retry-wording",
        quality_score=0.667,
        gaps=["confidence not proportionate to the strength of the evidence"],
        passed=False,
        retry_number=0,
        verification_outcome=VerificationOutcome.CONFIRMED,
        verification_attempts=1,
    )
    capture: dict = {}
    await _drive_loop(monkeypatch, validation, capture)

    assert capture["addendum"].items == validation.gaps


@pytest.mark.asyncio
async def test_truncated_unverifiable_stops_immediately_without_retry(monkeypatch):
    stage_log, fetch_log, cost_ledger, session_id = _harness()

    validation = ValidationResult(
        validation_id="val-3",
        run_id="run-initial",
        session_id=session_id,
        quality_score=0.0,
        gaps=["verification element_absent on truncated page (3000 chars past cutoff)"],
        passed=False,
        retry_number=0,
        verification_outcome=VerificationOutcome.TRUNCATED_UNVERIFIABLE,
        verification_attempts=1,
    )

    calls = {"assessor": 0}

    async def _fake_validator_node(state, agent, **kwargs):
        return validation

    async def _fake_assessor_node(*args, **kwargs):
        calls["assessor"] += 1
        raise AssertionError("must not retry a deterministically-truncated page")

    monkeypatch.setattr(retry_loops_module, "validator_node", _fake_validator_node)
    monkeypatch.setattr("agents.assessor.node.assessor_node", _fake_assessor_node)

    class _FakeSettings:
        validation_retry_limit = 3  # plenty of budget left -- must not be used

    result = await retry_loops_module.run_validation_retry_loop(
        session_id=session_id,
        question={
            "question_id": "q-retry-wording",
            "text": "Does the portal describe this benefit?",
            "answer_type": "binary",
            "evidence_locus": "any_government_domain",
        },
        portal_url="https://example.gov/benefits",
        agent_index=0,
        round_number=1,
        settings=_FakeSettings(),
        provider=None,
        browser=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        initial_run=_initial_run(session_id),
        initial_evidence=None,
    )

    assert calls["assessor"] == 0
    assert result.final_run.state == AgentRunState.VALIDATION_FAILED_TERMINAL
