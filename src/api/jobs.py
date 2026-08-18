"""Assessment job service and store (spec 007).

Provides start_assessment_job, job_status, and sweep_interrupted_jobs,
enforcing concurrency limits, partial unique index idempotency, and
status derivation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import sqlite3
from typing import TYPE_CHECKING

from api.runner import run_assessment_job
from api.schemas import CapacityReached, NotFound, PreconditionFailed
from portal.common import ensure_session
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import TERMINAL_UNIT_STATES, UnitState, new_id

if TYPE_CHECKING:
    from api.runtime import AIRuntime


# Strong references to background tasks to prevent garbage collection
_BACKGROUND_TASKS: set[asyncio.Task] = set()

# Canonical failure causes
FAILURE_SERVICE_STOPPED = "service_stopped_mid_run"
FAILURE_PIPELINE_ERROR = "pipeline_error"
FAILURE_AI_PROVIDER_UNAVAILABLE = "ai_provider_unavailable"


@dataclass
class AssessmentJob:
    job_id: str
    session_id: str
    cycle_id: str
    portal_id: str
    state: str  # 'running' | 'done' | 'failed'
    questions_total: int
    failure_cause: str | None = None
    triggered_by: str = "api"  # 'api' | 'portal'
    data: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class JobStart:
    job: AssessmentJob
    already_running: bool


@dataclass(frozen=True)
class PrefillRunSummary:
    run_id: str
    total_indicators: int
    suggested_count: int
    no_suggestion_count: int
    by_reason: dict[str, int]
    by_agreement_outcome: dict[str, int]
    total_cost_usd: float


@dataclass
class JobStatus:
    state: str  # 'running' | 'done' | 'failed' | 'never_triggered'
    job_id: str | None = None
    questions_total: int = 0
    questions_completed: int = 0
    failure_cause: str | None = None
    triggered_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    outcomes: dict | None = None
    summary: PrefillRunSummary | None = None


def prefill_run_summary(repo: Repository, run_id: str) -> PrefillRunSummary:
    prefills = repo.list_prefills_for_run(run_id)
    total = len(prefills)
    suggested = sum(1 for p in prefills if p.suggested)
    no_suggestion = total - suggested
    by_reason: dict[str, int] = {}
    by_agreement_outcome: dict[str, int] = {}
    for p in prefills:
        if p.reason:
            r_str = p.reason.value if hasattr(p.reason, "value") else str(p.reason)
            by_reason[r_str] = by_reason.get(r_str, 0) + 1
        if p.agreement_outcome:
            ao_str = (
                p.agreement_outcome.value
                if hasattr(p.agreement_outcome, "value")
                else str(p.agreement_outcome)
            )
            by_agreement_outcome[ao_str] = by_agreement_outcome.get(ao_str, 0) + 1

    total_cost_usd = 0.0
    try:
        cursor = repo.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cost_ledger_entries'")
        if cursor.fetchone():
            cursor.execute(
                "SELECT data FROM cost_ledger_entries WHERE session_id = ?",
                (run_id,),
            )
            rows = cursor.fetchall()
            import json
            total_cost_usd = sum(json.loads(r[0]).get("cost", 0.0) for r in rows if r[0])
    except Exception:
        total_cost_usd = 0.0

    return PrefillRunSummary(
        run_id=run_id,
        total_indicators=total,
        suggested_count=suggested,
        no_suggestion_count=no_suggestion,
        by_reason=by_reason,
        by_agreement_outcome=by_agreement_outcome,
        total_cost_usd=total_cost_usd,
    )


def job_status(
    repo: Repository, session_id: str, cycle_id: str, portal_id: str
) -> JobStatus:
    """Reads latest assessment job for the unit and derives progress monotonically."""
    job = repo.latest_assessment_job(cycle_id, portal_id)
    if job is None:
        questions = repo.list_questions(cycle_id)
        return JobStatus(
            state="never_triggered",
            job_id=None,
            questions_total=len(questions),
            questions_completed=0,
        )

    unit_states = repo.list_units_for_portal(session_id, portal_id)
    terminal = {s.value for s in TERMINAL_UNIT_STATES}
    completed = sum(1 for row in unit_states if row.get("state") in terminal)
    outcomes = job.data.get("outcomes") if isinstance(job.data, dict) else None
    summary = prefill_run_summary(repo, job.job_id) if job.job_id else None

    return JobStatus(
        state=job.state,
        job_id=job.job_id,
        questions_total=job.questions_total,
        questions_completed=completed,
        failure_cause=job.failure_cause,
        triggered_by=job.triggered_by,
        created_at=job.created_at,
        updated_at=job.updated_at,
        outcomes=outcomes,
        summary=summary,
    )


def start_assessment_job(
    repo: Repository,
    settings: Settings,
    runtime: AIRuntime,
    *,
    cycle_id: str,
    portal_id: str,
    triggered_by: str = "api",
    actor_id: str | None = None,
) -> JobStart:
    """Starts an assessment job subject to contractual preconditions and concurrency limits.

    Preconditions evaluation order:
    1. Cycle exists (404)
    2. Unit exists in cycle (404)
    3. Unit has resolved_url (409 PreconditionFailed: unit_has_no_url)
    4. Cycle has >= 1 question (409 PreconditionFailed: cycle_has_no_questions)
    5. Already running job returns with already_running=True
    6. Running job count < max_concurrent_assessment_runs (429 CapacityReached)
    """
    # 1. Cycle exists
    cycle = repo.get_cycle(cycle_id)
    if cycle is None:
        raise NotFound(f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id})

    # 2. Unit exists and belongs to that cycle
    portal = repo.get_portal(portal_id)
    if portal is None or portal.cycle_id != cycle_id:
        raise NotFound(
            f"Unit '{portal_id}' not found in cycle '{cycle_id}'.",
            details={"portal_id": portal_id, "cycle_id": cycle_id},
        )

    # 3. Unit has a non-empty resolved_url
    if not portal.resolved_url:
        raise PreconditionFailed(
            f"Unit '{portal_id}' has no target portal URL configured.",
            details={"reason": "unit_has_no_url", "portal_id": portal_id},
        )

    # 4. Cycle has >= 1 indicator
    questions = repo.list_questions(cycle_id)
    if not questions:
        raise PreconditionFailed(
            f"Cycle '{cycle_id}' has no indicator questions configured.",
            details={"reason": "cycle_has_no_questions", "cycle_id": cycle_id},
        )

    session_id = ensure_session(repo, cycle_id)

    # 5 & 6 and insert inside BEGIN IMMEDIATE
    with repo.begin_immediate():
        running_job = repo.running_assessment_job(portal_id)
        if running_job is not None:
            return JobStart(job=running_job, already_running=True)

        running_count = repo.count_running_assessment_jobs()
        if running_count >= settings.max_concurrent_assessment_runs:
            raise CapacityReached(
                retry_after_seconds=30,
                message=f"Concurrent assessment run capacity reached ({running_count}/{settings.max_concurrent_assessment_runs}).",
                details={
                    "running_count": running_count,
                    "max_concurrent": settings.max_concurrent_assessment_runs,
                },
            )

        job_id = new_id("job")
        job = AssessmentJob(
            job_id=job_id,
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            state="running",
            questions_total=len(questions),
            failure_cause=None,
            triggered_by=triggered_by,
            data={"actor_id": actor_id or triggered_by},
        )

        try:
            repo.insert_assessment_job(job)
        except sqlite3.IntegrityError:
            # Fallback if race condition hit the partial unique index
            running_job = repo.running_assessment_job(portal_id)
            if running_job is not None:
                return JobStart(job=running_job, already_running=True)
            raise

    # Create background task and hold a strong reference if in event loop
    try:
        task = asyncio.create_task(
            run_assessment_job(
                job.job_id,
                settings.database_path,
                settings,
                runtime,
                session_id,
                cycle_id,
                portal_id,
            )
        )
        _BACKGROUND_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_TASKS.discard)
    except RuntimeError:
        pass

    return JobStart(job=job, already_running=False)


def sweep_interrupted_jobs(conn: sqlite3.Connection) -> int:
    """Marks any running jobs as failed with failure_cause='service_stopped_mid_run'."""
    return Repository(conn).sweep_running_assessment_jobs()
