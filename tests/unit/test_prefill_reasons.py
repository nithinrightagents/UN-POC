"""Tests for prefill reasons taxonomy, write_prefill seam, and terminal states (spec 008 US2)."""

import sqlite3

import pytest

from orchestration.prefill_writer import write_prefill
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    PrefillReason,
    SurveyCycle,
    TargetPortal,
    UnitState,
)

pytestmark = pytest.mark.unit


def _setup_repo():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-reason",
        name="Reason Test Cycle",
        questionnaire_ref="Test Ref",
        country_set=["DK"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-reason",
        cycle_id="c-reason",
        country_id="DK",
        resolved_url="https://borger.dk",
    )
    repo.insert_portal(portal)

    return repo, "s-reason", "c-reason", "p-reason"


@pytest.mark.parametrize("reason", list(PrefillReason))
def test_all_nine_prefill_reasons_write_valid_non_suggested_prefill(reason: PrefillReason):
    repo, session_id, cycle_id, portal_id = _setup_repo()
    qid = f"{cycle_id}:test-{reason.value}"

    terminal_state = (
        UnitState.UNASSESSABLE
        if reason == PrefillReason.NO_USABLE_EVIDENCE
        else UnitState.NO_SUGGESTION
    )

    pf = write_prefill(
        repo=repo,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_id=qid,
        run_id="run-reason-test",
        suggested=False,
        reason=reason,
        terminal_state=terminal_state,
        advance_state=True,
    )

    assert pf.suggested is False
    assert pf.answer is None
    assert pf.reason == reason
    assert pf.terminal_state == terminal_state

    # Read back from database
    latest = repo.latest_prefill(session_id, qid, portal_id)
    assert latest is not None
    assert latest.suggested is False
    assert latest.answer is None
    assert latest.reason == reason.value or latest.reason == reason

    # Unit state is properly updated
    unit = repo.get_unit(session_id, qid, portal_id)
    assert unit is not None
    assert unit["state"] == terminal_state.value


def test_suggested_prefill_invariants():
    repo, session_id, cycle_id, portal_id = _setup_repo()

    # Valid suggested prefill
    pf = write_prefill(
        repo=repo,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_id=f"{cycle_id}:valid-suggested",
        run_id="run-inv",
        suggested=True,
        answer=True,
        confidence=85,
        justification="Valid justification",
        agreement_outcome="unanimous",
    )
    assert pf.suggested is True
    assert pf.answer is True
    assert pf.reason is None

    # Suggested=True with answer=None must raise ValueError
    with pytest.raises(ValueError):
        write_prefill(
            repo=repo,
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            question_id=f"{cycle_id}:invalid-1",
            run_id="run-inv",
            suggested=True,
            answer=None,
        )

    # Suggested=True with reason non-None must raise ValueError
    with pytest.raises(ValueError):
        write_prefill(
            repo=repo,
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            question_id=f"{cycle_id}:invalid-2",
            run_id="run-inv",
            suggested=True,
            answer=True,
            reason=PrefillReason.ASSESSMENT_FAILURE,
        )

    # Suggested=False with reason=None must raise ValueError
    with pytest.raises(ValueError):
        write_prefill(
            repo=repo,
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            question_id=f"{cycle_id}:invalid-3",
            run_id="run-inv",
            suggested=False,
            reason=None,
        )


@pytest.mark.asyncio
async def test_exhausted_cascade_dispatches_neither_assessor_agent():
    """FR-PF-018: A fully exhausted link resolution chain halts before assessor dispatch and writes NO_USABLE_EVIDENCE."""
    from core.telemetry.cost_ledger import CostLedger
    from core.telemetry.fetch_log import FetchLog
    from core.telemetry.stage_events import StageEventLog
    from orchestration.scheduler import process_unit
    from shared.config.settings import Settings
    from shared.state.entities import AnswerType, EvidenceLocus, Question

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(cycle_id="c-exh", name="Exh Cycle", questionnaire_ref="Ref", country_set=["NO"])
    repo.insert_cycle(cycle)
    portal = TargetPortal(portal_id="p-exh", cycle_id="c-exh", country_id="NO", resolved_url="https://no.gov")
    repo.insert_portal(portal)

    q = Question(
        question_id="c-exh:q1", cycle_id="c-exh", indicator_id="q1",
        text="Exhausted link indicator?", answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.upsert_unit("s-exh", q.question_id, portal.portal_id, UnitState.PENDING.value, {})

    settings = Settings(url_resolution_mode="historical_first")
    fetch_log = FetchLog(conn, "s-exh")
    stage_log = StageEventLog(conn, "s-exh")
    cost_ledger = CostLedger(conn, "s-exh")

    # Tracking model provider that fails if called
    class StrictProvider:
        async def generate(self, *args, **kwargs):
            raise AssertionError("Assessor model must NEVER be dispatched when link resolution is exhausted!")

    outcome = await process_unit(
        repo=repo,
        settings=settings,
        session_id="s-exh",
        provider=StrictProvider(),
        browser=None,
        http_client=None,
        fetch_log=fetch_log,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
        question=q,
        portal=portal,
        run_id="run-exh",
    )

    assert outcome.final_state == UnitState.UNASSESSABLE
    assert outcome.detail == PrefillReason.NO_USABLE_EVIDENCE.value

    # Zero agent runs created
    runs = repo.list_agent_runs("s-exh", q.question_id, portal.portal_id)
    assert len(runs) == 0

    prefill = repo.latest_prefill("s-exh", q.question_id, portal.portal_id)
    assert prefill is not None
    assert prefill.suggested is False
    assert prefill.reason == PrefillReason.NO_USABLE_EVIDENCE.value or prefill.reason == PrefillReason.NO_USABLE_EVIDENCE

