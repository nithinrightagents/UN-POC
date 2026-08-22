"""Runs the spec-001 pipeline -- link resolution (prior-survey KB ->
MSQ -> internet search, shared/tools/linkresolution/chain.py) into N >= 2
independent live Vertex AI assessor agents, a validator, and an adjudicator
(orchestration/scheduler.py) -- against one unit, in the background, for the
admin's "Run AI Assessment" button (spec 005).
"""


from __future__ import annotations

import pathlib
import sqlite3
from typing import TYPE_CHECKING

from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from orchestration.budget import RunBudget
from orchestration.scheduler import BatchRunSummary, run_batch
from shared.config.settings import Settings
from shared.persistence.repositories import Repository

if TYPE_CHECKING:
    from api.runtime import AIRuntime


async def run_live_prefill(
    database_path: str,
    settings: Settings,
    runtime: AIRuntime,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    run_id: str | None = None,
) -> BatchRunSummary:
    """Opens its own SQLite connection (the request's connection is closed
    by the time this runs in the background) and runs every question for
    `cycle_id` against the single `portal_id` unit. Resumable: units already
    terminal from a prior run are skipped (see process_unit), so re-clicking
    the button after a partial run only dispatches what's left."""
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    repo = Repository(conn)

    portal = repo.get_portal(portal_id)
    questions = repo.list_questions(cycle_id)
    if portal is None or not questions:
        conn.close()
        return BatchRunSummary()

    await runtime.ensure_browser()

    budget = RunBudget(limit=getattr(settings, "prefill_run_budget", 0.0))
    cost_ledger = CostLedger(conn, session_id, budget=budget)

    try:
        return await run_batch(
            repo=repo,
            settings=settings,
            session_id=session_id,
            provider=runtime.provider,
            browser=runtime.browser,
            http_client=runtime.http_client,
            fetch_log=FetchLog(conn, session_id),
            stage_log=StageEventLog(conn, session_id),
            cost_ledger=cost_ledger,
            questions=questions,
            portals=[portal],
            adjudicate_results=True,
            run_id=run_id,
        )
    finally:
        conn.close()
