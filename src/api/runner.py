"""Background runner for assessment jobs (spec 007)."""

from __future__ import annotations

import asyncio
import logging
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

_log = logging.getLogger(__name__)


async def _run_headless_batch(
    database_path: str,
    settings: Settings,
    runtime: AIRuntime,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    run_id: str | None = None,
) -> BatchRunSummary:
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
            cycle_id=cycle_id,
            portal=portal,
            questions=questions,
            agent_runtime=runtime,
            cost_ledger=cost_ledger,
            stage_event_log=StageEventLog(conn, session_id),
            fetch_log=FetchLog(conn, session_id),
            run_id=run_id,
        )
    finally:
        conn.close()


async def run_assessment_job(
    job_id: str,
    database_path: str,
    settings: Settings,
    runtime: AIRuntime,
    session_id: str,
    cycle_id: str,
    portal_id: str,
) -> None:
    """Executes the live assessment run in the background and records terminal state."""
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    repo = Repository(conn)

    try:
        summary: BatchRunSummary = await _run_headless_batch(
            database_path=database_path,
            settings=settings,
            runtime=runtime,
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            run_id=job_id,
        )
        outcomes = {
            "delivered": summary.delivered,
            "escalated": summary.escalated,
            "no_suggestion": summary.no_suggestion,
            "unassessable": summary.unassessable,
        }
        job = repo.get_assessment_job(job_id)
        current_data = job.data if job else {}
        current_data["outcomes"] = outcomes
        current_data["budget_in_force"] = getattr(settings, "prefill_run_budget", 0.0)
        from api.jobs import prefill_run_summary

        summary_obj = prefill_run_summary(repo, job_id)
        current_data["spend_reached"] = summary_obj.total_cost_usd
        repo.update_assessment_job_state(
            job_id, state="done", failure_cause=None, data=current_data
        )
    except asyncio.CancelledError:
        job = repo.get_assessment_job(job_id)
        current_data = job.data if job else {}
        repo.update_assessment_job_state(
            job_id,
            state="failed",
            failure_cause="service_stopped_mid_run",
            data=current_data,
        )
        raise
    except Exception as exc:
        _log.exception(
            "Live AI assessment run failed for job %s (portal %s)",
            job_id,
            portal_id,
            exc_info=exc,
        )
        exc_summary = f"{type(exc).__name__}: {str(exc)}"
        is_provider_error = any(
            err_term in exc_summary.lower()
            for err_term in [
                "credential",
                "vertex",
                "auth",
                "google",
                "permission",
                "quota",
                "model",
                "unavailable",
            ]
        )
        failure_cause = (
            "ai_provider_unavailable" if is_provider_error else "pipeline_error"
        )
        job = repo.get_assessment_job(job_id)
        current_data = job.data if job else {}
        current_data["error"] = exc_summary
        repo.update_assessment_job_state(
            job_id,
            state="failed",
            failure_cause=failure_cause,
            data=current_data,
        )
    finally:
        conn.close()
