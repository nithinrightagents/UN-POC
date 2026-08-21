import sqlite3
import pytest
from core.llm_factory import ModelProvider
from orchestration.scheduler import run_batch
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.ratelimit.token_bucket import RateLimiter
from shared.state.entities import (
    AssessmentSession,
    EvidenceLocus,
    Question,
    AnswerType,
    SessionMode,
    SessionStatus,
    TargetPortal,
    UnitState,
)
from shared.tools.browser import BrowserSession
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog


class NoCallProvider(ModelProvider):
    def __init__(self):
        super().__init__("proj", "loc", True, "key")

    async def generate(self, **kwargs):
        raise RuntimeError("Assessor agent model generate() should NOT be called in resolve_only mode!")


@pytest.mark.asyncio
async def test_resolve_only_batch_dispatches_no_assessor_agent():
    # T033: Unit test asserting resolution-only batch dispatches no assessor agent and units reach UnitState.RESOLVED
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    session_id = "sess-resolve-only-test"
    session = AssessmentSession(
        session_id=session_id,
        cycle_id=None,
        mode=SessionMode.BENCHMARK,
        config_snapshot_id="cfg-test",
        status=SessionStatus.RUNNING,
    )
    repo.insert_session(session)

    portal = TargetPortal(
        portal_id="portal-us",
        cycle_id="usa-test",
        country_id="US",
        resolved_url="https://www.usa.gov",
    )
    repo.insert_portal(portal)

    question = Question(
        question_id="Q-TEST-01",
        cycle_id="usa-test",
        title="Health Services",
        text="Does the portal provide online health services?",
        what="Health services overview",
        why="Healthcare access",
        how={"criteria_for_yes": "Evidence found", "criteria_for_no": "No evidence"},
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(question)

    settings = Settings.defaults()
    limiter = RateLimiter(rate_per_sec=settings.rate_limit_per_domain_rps)
    browser = BrowserSession(settings.user_agent, limiter)
    provider = NoCallProvider()

    summary = await run_batch(
        repo=repo,
        settings=settings,
        session_id=session_id,
        provider=provider,
        browser=browser,
        http_client=None,
        fetch_log=FetchLog(conn, session_id),
        stage_log=StageEventLog(conn, session_id),
        cost_ledger=CostLedger(conn, session_id),
        questions=[question],
        portals=[portal],
        adjudicate_results=False,
        resolve_only=True,
    )

    # Assert unit reached RESOLVED state
    units = repo.list_units(session_id)
    assert len(units) == 1
    assert units[0]["state"] == UnitState.RESOLVED.value
    assert summary.resolved == 1

    # Assert zero assessor agent runs exist in database
    runs = repo.list_all_agent_runs_for_session(session_id)
    assert len(runs) == 0
