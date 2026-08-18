# Contract: Assessment Job Service

The single path by which any surface starts an AI assessment run, and the single source of truth for whether one is in flight. Replaces the in-memory `_RUNNING_PORTALS` set in `portal/admin.py` ([research.md](../research.md) R8).

**Module**: `src/api/jobs.py` (store + service) · **Record**: [data-model.md](../data-model.md) §1

---

## `start_assessment_job(...) -> JobStart`

```
start_assessment_job(
    repo, settings, runtime, *, cycle_id, portal_id, triggered_by, actor_id
) -> JobStart(job: AssessmentJob, already_running: bool)
```

### Preconditions, in evaluation order

| # | Check | On failure |
|---|---|---|
| 1 | cycle exists | `NotFound("cycle")` |
| 2 | unit exists and belongs to that cycle | `NotFound("unit")` |
| 3 | unit has a non-empty `resolved_url` | `PreconditionFailed("unit_has_no_url")` |
| 4 | cycle has ≥ 1 indicator | `PreconditionFailed("cycle_has_no_questions")` |
| 5 | **a running job for this unit already exists** | return it with `already_running=True` — success, not an error |
| 6 | running-job count < `settings.max_concurrent_assessment_runs` | `CapacityReached(retry_after_seconds)` |

Order matters and is contractual: **5 before 6**, so an idempotent re-trigger succeeds even at capacity, because it starts nothing (FR-API-014 vs FR-API-014a).

### Atomicity

Checks 5–6 and the row insert happen inside one `BEGIN IMMEDIATE` transaction. `BEGIN IMMEDIATE` (not SQLite's default deferred mode) is required because the write lock must be held *before* the count, or two callers can both count `N-1` and both insert.

The unique partial index `idx_assessment_jobs_one_running` is the backstop: a caller that loses the race to insert catches `sqlite3.IntegrityError`, re-reads the running job, and returns it with `already_running=True`. Both callers therefore observe the specified idempotent outcome, and exactly one run exists (the spec's "two clients trigger at the same moment" edge case).

### Effects on success

1. Ensures the cycle's session (`ensure_session`).
2. Inserts an `AssessmentJob` row with `state='running'` and `questions_total` snapshotted.
3. Creates the background task, holding a strong reference so it is not garbage-collected mid-flight (the reason `portal/admin.py:45-50` keeps its own set today).
4. Attaches a completion callback that records the terminal state (below).

Returns before the run has done any work (FR-API-013).

---

## Background execution

```
run_assessment_job(job_id, database_path, settings, runtime, session_id, cycle_id, portal_id)
```

Behaviourally the existing `portal/live_prefill.py::run_live_prefill`, with two changes:

1. **Dependencies come from the shared `AIRuntime`** (provider, rate limiter, browser, HTTP client) rather than being constructed per run — see [research.md](../research.md) R2. It still opens **its own SQLite connection**, because the triggering request's connection is closed by the time the task runs; that part of `run_live_prefill`'s docstring remains true and is unchanged.
2. **It records terminal job state.** `FetchLog`, `StageEventLog`, and `CostLedger` are still constructed per run on that connection, so telemetry and cost accounting are identical to a portal-triggered or CLI run (FR-API-004, SC-010).

`run_batch(..., adjudicate_results=True)` is called unchanged — the pipeline itself (link resolution → N assessor agents → validator → adjudicator) is not modified by this feature, and its resumability is what makes re-triggering safe (FR-API-021).

### Terminal recording

| Outcome | Written |
|---|---|
| `run_batch` returns | `state='done'`, `data.outcomes = {delivered, escalated, unassessable}` from `BatchRunSummary` |
| `run_batch` raises | `state='failed'`, `failure_cause='pipeline_error'` (or `ai_provider_unavailable` for a provider/credential failure), `data.error` = exception summary, and the exception is logged as `portal/admin.py:53-56` does today |
| Task cancelled | `state='failed'`, `failure_cause='service_stopped_mid_run'` — best effort; the startup sweep is the guarantee |

A terminal job is never reopened. Re-triggering inserts a new row (FR-API-021).

---

## `sweep_interrupted_jobs(conn) -> int`

Called once in the app lifespan **before serving traffic**, returning the number of rows swept (logged at startup):

```sql
UPDATE assessment_jobs
   SET state = 'failed', failure_cause = 'service_stopped_mid_run', updated_at = datetime('now')
 WHERE state = 'running'
```

**Correctness precondition**: exactly one process serves the app. True today — `cli.py:136` calls `uvicorn.run(app, …)` with no `workers` argument. If replicas are ever introduced, this sweep would fail another worker's live jobs; see the plan's Risks. The sweep is also what releases stale rows from the concurrency budget and from the one-running-job-per-unit index.

Guarantees FR-API-018 (never reported `running` after a restart) and, with the never-triggered case, FR-API-019.

---

## `job_status(repo, session_id, cycle_id, portal_id) -> JobStatus`

Reads the **latest** job row for the unit and derives progress; returns a `never_triggered` status when no row exists.

```
questions_completed = count of that unit's units whose state ∈
    {DELIVERED, ESCALATED, UNASSESSABLE}        # repo.list_units_for_portal
questions_total     = job.questions_total       # snapshot, or live cycle count when never triggered
```

Progress is derived, never stored ([research.md](../research.md) R7): it is the same computation `portal/admin.py:100-104` already performs, so the API and the admin page cannot disagree, and it is monotonic because a unit only ever moves *into* a terminal state — satisfying SC-005 structurally rather than by test.

---

## Portal integration

`portal/admin.py` changes only in mechanism:

| Today | After |
|---|---|
| `_RUNNING_PORTALS: set[str]` module global | removed |
| `if portal and portal.resolved_url and portal_id not in _RUNNING_PORTALS:` then `asyncio.create_task(run_live_prefill(...))` | `start_assessment_job(..., triggered_by="portal")`, exceptions swallowed into the redirect as today |
| `"run_in_progress": u.portal_id in _RUNNING_PORTALS or bool(states_seen - terminal)` | `job_status(...).state == "running" or bool(states_seen - terminal)` |

The rendered admin page keeps the same states and the same double-click protection (FR-API-002 — *functionally* unchanged). Behaviour that genuinely improves: a run in progress is still reported as such after a restart instead of appearing idle, and a portal-triggered run is now visible over HTTP.
