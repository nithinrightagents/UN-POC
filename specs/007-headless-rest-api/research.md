# Phase 0 Research: Headless Assessment REST API

**Feature Directory**: `specs/007-headless-rest-api`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-18

Ten decisions. Each was reached by reading the running code rather than from the spec's prose, because this feature is almost entirely an integration against existing machinery — the risk is not "can it be built" but "does the thing I assume exists actually behave that way".

---

## R1 — The interface is an `APIRouter` on the existing app, not a mounted sub-application

**Decision**: Build `build_api_router(database_path, settings, runtime) -> APIRouter` and include it in `portal/webapp.py`'s existing `build_app()` with `prefix="/api/v1"`, alongside the three routers already included there.

**Rationale**: FR-API-004 requires the AI dependencies to be established through "the same running service's startup and shutdown". Starlette does **not** propagate lifespan events into applications attached with `app.mount()` — a mounted sub-app's `lifespan` never fires. `review/web/app.py` is mounted at `/review` today and gets away with it because it has no startup work at all. If the API were mounted the same way, its lifespan-created `ModelProvider`/`BrowserSession` would silently never start, and the first triggered assessment would fail on `assert self._browser is not None` inside `BrowserSession.fetch` (`shared/tools/browser.py:69`). Including a router on the parent app puts the lifespan where it actually runs.

**Alternatives considered**:
- *Mounted sub-app at `/api/v1`* — attractive for its separate OpenAPI document, rejected for the lifespan gap above. (A sub-app could still work if the parent owned the lifespan and passed the runtime down, but then the mount buys nothing over a router while adding an indirection.)
- *A separate deployable service* — explicitly excluded by the spec's Out of Scope and by FR-API-003's shared-configuration/shared-data requirement.
- *Adding JSON responses to the existing portal routes via content negotiation* — rejected: FR-API-002 requires the portal's behavior to be unchanged, and the portal's handlers return `RedirectResponse(303)` as their success signal, which is exactly what makes them unusable headlessly.

---

## R2 — One shared `AIRuntime` created in the app lifespan, replacing per-run construction

**Decision**: A small `AIRuntime` container (`ModelProvider`, `RateLimiter`, `BrowserSession`, `httpx.AsyncClient`) is constructed once in the app's lifespan and torn down on shutdown. Both the API's trigger and the portal's existing trigger use it.

**Rationale**: `portal/live_prefill.py:50-57` builds a *fresh* `RateLimiter`, `ModelProvider`, and `BrowserSession` per run, and `BrowserSession.start()` launches a whole Chromium via Playwright (`shared/tools/browser.py:43-45`). Two consequences, both fixed by sharing:
1. **The per-domain rate limit is not actually global today.** Each run owning its own `RateLimiter` means two concurrent runs against the same government domain each get the full `rate_limit_per_domain_rps` budget, silently doubling the request rate at that domain. FR-API-004's "same rate limiter" wiring is therefore a correctness fix, not just plumbing.
2. **One Chromium per concurrent run** is the dominant fixed cost of a run; with a concurrency cap (R8) of N, sharing takes it from N browsers to 1.

Sharing the browser is safe: `BrowserSession` documents and implements a fresh browser *context* per fetch, so "no cookies or state leak between question-portal units" (`shared/tools/browser.py:33-35`) already holds for concurrent callers.

**Alternatives considered**:
- *Keep per-run construction and only wire the settings through* — satisfies the letter of FR-API-004's "same settings" but not its intent (the named dependencies), and leaves the rate-limit defect in place.
- *Lazily construct the runtime on first trigger* — avoids paying for Chromium in portal-only deployments, but makes the first API trigger pay a multi-second browser launch inside a request that FR-API-013/SC-003 require to return in under two seconds. Rejected. (Deployments that never trigger an assessment can still avoid the cost — see R10's note on lazy browser start being an acceptable later optimization, since `BrowserSession.start()` is separable from construction.)

---

## R3 — Job status is a new, deliberately mutable `assessment_jobs` table

**Decision**: One new table. Rows are updated in place for `state` and `failure_cause`; a re-trigger inserts a new row rather than reusing the old one, so history is preserved per attempt.

**Rationale**: The schema's own doctrine is append-only (`shared/persistence/schema.py:1-7`: "no UPDATE or DELETE statement exists anywhere in this codebase against these tables"), but that doctrine already carries an explicit, documented exception for live progress tracking. `units` is upserted (`repositories.py:167-190`) with the reasoning that "Units track live pipeline progress, not audit history", and `update_portal_resolution` (`repositories.py:136`) mutates resolution state for the same reason. A job record is the same category of thing: current state of an in-flight process, not an audit record. The audit trail for what a run *did* remains the append-only `stage_events` and `cost_ledger_entries` rows the run writes anyway.

Adding the table needs no migration machinery: `init_db()` runs `executescript(DDL)` with `CREATE TABLE IF NOT EXISTS` on every `aiq serve` and `aiq db init` (`schema.py:283-289`), so appending the DDL is sufficient for both fresh and existing databases including the live `data/aiq.db`.

**Alternatives considered**:
- *Reuse `assessment_sessions`* — rejected: there is exactly one long-lived session per cycle (`portal/common.py:17-21`, `session_id_for_cycle`), shared by every unit and every human submission in that cycle. It cannot represent per-unit run attempts.
- *Derive job state entirely from `units` with no job table* — tempting since progress is derived that way (R7), but it cannot distinguish "never triggered" from "triggered and failed before any unit moved" (FR-API-019/020), and it has nowhere to record a failure cause.
- *A separate job-status file or in-process registry with periodic flush* — rejected: FR-API-017 wants it queryable and durable, and the database is already the single shared store both surfaces read (FR-API-003).

---

## R4 — One running job per unit is enforced by a partial unique index; capacity by a counted insert

**Decision**:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_jobs_one_running
    ON assessment_jobs(portal_id) WHERE state = 'running';
```

The trigger performs its capacity count and its insert inside a single `BEGIN IMMEDIATE` transaction.

**Rationale**: FR-API-014 (idempotent duplicate trigger) and the spec's "two clients trigger at the same moment" edge case are a race, and today's guard is a plain in-memory `set` membership test (`portal/admin.py:50,204`) that is not atomic even within one process. A partial unique index — supported by SQLite since 3.8.0 — makes "at most one running job per unit" a storage invariant: the loser of the race gets an `IntegrityError`, catches it, re-reads the running row, and returns that job reference, which is exactly the specified idempotent behavior. The same transaction boundary makes the FR-API-014a capacity check (`COUNT(*) WHERE state='running' < max_concurrent_assessment_runs`) non-racy; `BEGIN IMMEDIATE` is required because SQLite's default deferred transactions upgrade to a write lock only at the first write, which is after the count.

**Alternatives considered**:
- *Application-level lock (`asyncio.Lock`)* — sufficient for one process but re-introduces exactly the in-memory coupling the spec asks to remove, and buys nothing over an index the database enforces.
- *Advisory check-then-insert without a transaction* — the current bug, restated. Rejected.

---

## R5 — Interrupted runs are detected by a startup sweep, not a heartbeat

**Decision**: The lifespan runs, before serving traffic:

```sql
UPDATE assessment_jobs SET state='failed', failure_cause='service_stopped_mid_run', updated_at=... WHERE state='running'
```

**Rationale**: This resolves the item `/speckit-clarify` deferred to planning. Any row still marked `running` at startup is, by definition, owned by a process that no longer exists — `aiq serve` calls `uvicorn.run(app, ...)` with no `workers` argument (`cli.py:136`), so exactly one process serves the app and there is no second worker whose live jobs a sweep could wrongly kill. That single-process fact is what makes the sweep sound and a heartbeat unnecessary; the sweep is also what keeps stale rows from permanently consuming the R4 concurrency budget.

**Constraint this creates** (recorded here because it is easy to violate later): if the service is ever run with `--workers > 1` or behind a process manager that starts replicas, this sweep becomes wrong. It is listed in the plan's Risks with the mitigation of asserting single-worker operation at the point the sweep runs.

**Alternatives considered**:
- *Heartbeat column + staleness threshold* — survives multi-worker deployment, but needs a periodic writer, a tunable threshold, and makes status a function of clock skew. Disproportionate for a single-process app, and it would leave a genuinely dead job reported `running` until the threshold elapsed, which FR-API-018 forbids.
- *Sweep lazily at read time* — a read that mutates state, and it leaves stale rows counting against the capacity cap until someone happens to poll them.

---

## R6 — The secret lives in `Settings` but must be redacted from `as_dict()`

**Decision**: Add `api_key: str = ""` and `max_concurrent_assessment_runs: int = 2` to `Settings` with `AIQ_API_KEY` / `AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS` entries in `_ENV_MAP`, and change `Settings.as_dict()` to mask secret-valued fields (returning `"***"` when non-empty), with `Settings.defaults()` unaffected in shape.

**Rationale**: `as_dict()` is not an internal convenience — it has two outward paths that would leak the key in plaintext the moment it is set:
1. `cli.py:287` persists `values=settings.as_dict()` into a `ConfigurationSnapshot` row, so the secret would be written into `configuration_snapshots` in the database.
2. `aiq config show` prints every parameter's effective value to the terminal (`cli.py:44-53`).

Worth stating precisely, because it changes where the fix belongs: `verify_no_credentials` would **not** catch this. It scans only `fetch_records`, `stage_events`, and `cost_ledger_entries` (`core/telemetry/verify.py:63`) — not `configuration_snapshots`. So there is no existing safety net for this leak, which is why redaction has to happen at the source in `as_dict()` rather than being left to a verifier. (Its `CREDENTIAL_PATTERNS` does include the literal `"api_key"` (`verify.py:12`), so if the key ever reached a telemetry table the check would fire on the field name alone — a useful backstop for the tables it does cover.)

`config show`'s "default vs configured" source column keeps working with masking, since it compares effective to default and both sides mask identically.

**Alternatives considered**:
- *Read the secret from the environment directly at request time, bypassing `Settings`* — avoids the leak but violates the spec's requirement (FR-API-035) that it be configured alongside the platform's other settings, and loses `validate_settings` coverage.
- *Keep `as_dict()` and redact at each call site* — two call sites today, unbounded tomorrow; wrong default.

---

## R7 — Progress is derived at read time from `units`, never stored on the job

**Decision**: `questions_completed` is not a column. Status responses compute it as the number of that unit's questions in a terminal state, from `repo.list_units_for_portal(session_id, portal_id)`. Only `questions_total` is snapshotted on the job row at trigger time.

**Rationale**: `run_batch` offers no progress callback — it collects `UnitOutcome`s into a summary and returns once its `TaskGroup` completes (`orchestration/scheduler.py:99-133`). Storing progress would therefore mean either adding a callback parameter to `run_batch`/`process_unit` (the highest-blast-radius file for this feature, on the hot path of every existing run and the CLI) or writing progress from a second source of truth that can drift from `units`. Deriving instead:
- needs zero change to `orchestration/`;
- is exactly the computation `portal/admin.py:100-104` already performs for the admin table, so the two surfaces cannot disagree;
- satisfies SC-005's monotonicity for free, because a unit only ever moves *into* a terminal state (`unit_state.py`'s terminal states have no outgoing transitions);
- keeps working for a `failed` job, giving FR-API-020's "progress reached before it failed" with no extra bookkeeping.

The denominator is snapshotted rather than derived so that adding an indicator to the cycle mid-run cannot make a running job's total move underneath a polling client; the dispatched set was fixed when the run started.

**Alternatives considered**: a `progress_callback` parameter on `run_batch` (rejected as above); incrementing a counter from `process_unit` (same objection, plus write amplification per unit).

---

## R8 — Both trigger paths go through one job service; the portal's in-memory set is removed

**Decision**: A single `start_assessment_job(...)` service owns validation, the capacity/idempotency transaction, task creation, and terminal-state recording. `portal/admin.py` calls it and drops `_RUNNING_PORTALS`; its `run_in_progress` flag is read from the job store instead.

**Rationale**: The user's brief requires the in-memory tracking to be *replaced*, and correctness requires it: if the portal kept its own path, the FR-API-014a cap would bound only API-triggered runs, two surfaces could start concurrent runs for the same unit (each guard blind to the other), and a portal-triggered run would be invisible to `GET .../assessment`. FR-API-002 asks that the portal be *functionally* unchanged, which this preserves — the admin page still shows a run-in-progress state and still refuses to double-fire — while the mechanism behind it becomes the durable one.

This is the one place where this feature deliberately edits portal code, and the plan's Project Structure marks it as such.

**Alternatives considered**:
- *Leave the portal untouched, accept two mechanisms* — rejected for the three defects above.
- *Have the portal call the HTTP API internally* — a service calling itself over the loopback, needing the API key to talk to itself. Rejected.

---

## R9 — Identity and uniqueness: every create must pre-check, and one spec requirement had to narrow

**Decision**: All three create operations read before writing and return a conflict when the entity exists. The unit conflict key is `(cycle_id, country_id)` — **not** including the URL. [spec.md](./spec.md) FR-API-010 and its clarification bullet were amended accordingly during planning.

**Rationale**: The existing repository writes are all forgiving in ways an API must not be:
- `insert_portal` is `INSERT ... ON CONFLICT(cycle_id, country_id) DO NOTHING` (`repositories.py:128-134`) against a table declaring `UNIQUE(cycle_id, country_id)` (`schema.py:37-45`). So registering a second unit for a country **silently does nothing today** — and `portal/admin.py:197` still returns a 303 as though it had worked. The clarify session's answer (same country + different URL creates a distinct unit) is not representable in this schema, and changing the constraint would break `get_portal_by_country`, which every caller relies on being single-valued.
- `insert_cycle` is used deliberately as a *superseding* write — `portal/admin.py:177` re-inserts a cycle to update `questionnaire_ref`, and `:196` to append to `country_set`. A create-by-POST that reused it would silently overwrite a live project's name and questionnaire reference.
- `question_id` is a global primary key, which is why the portal cycle-prefixes it (`admin.py:150-154`); an unprefixed collision across cycles would clobber another project's indicator.

So the read-before-write is not defensive padding; each of the three writes has a specific silent-overwrite or silent-no-op failure mode that FR-API-006/009/010 exist to close.

**Alternatives considered**: relaxing `UNIQUE(cycle_id, country_id)` to admit multiple portals per country (rejected — `get_portal_by_country` and the MSQ lookup `find_msq_document(cycle_id, country_id)` both assume one); treating a differing URL as an update to the existing unit (rejected — updates are out of scope for this feature, and a silent update is precisely the surprise FR-API-006 forbids for cycles).

---

## R10 — Reads project existing view builders instead of new queries

**Decision**: AI results reuse `review/query.py::build_question_review()`; the published breakdown and its precedence reuse the publish path already in `portal/admin.py::_final_answer`, extracted to a shared module so both surfaces call one implementation.

**Rationale**: `QuestionReviewView` (`review/query.py:47-69`) already carries every field FR-API-022 asks for — `delivered_answer`, `system_proposed_answer`, `consensus_confidence`, `justification`, `resolved_url`, `evidence`, `escalated`, `escalation_reason` — plus `reason_tag`, which is exactly what FR-API-023 needs for a blocked question and which spec 004 built. Re-deriving any of this from `assessor_agent_runs` and `adjudication_results` would duplicate spec 001's and 004's logic and drift from the review UI.

`_final_answer` must be extracted rather than copied: SC-007 requires the API's published score to be *identical* to the portal's, which is only guaranteed by one implementation. Extraction is a pure move (no behavior change) and the portal keeps calling it.

**Alternatives considered**: a fresh SQL projection per endpoint (rejected — duplicates two prior specs' precedence rules and would silently diverge, breaking SC-007); returning the raw `units.data` blob (rejected — leaks internal state-machine shape into a public contract).
