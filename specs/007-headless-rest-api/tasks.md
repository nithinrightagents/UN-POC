# Tasks: Headless Assessment REST API

**Feature**: `007-headless-rest-api`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [plan.md](plan.md) | [research.md](research.md) | [data-model.md](data-model.md) | [contracts/rest-api.md](contracts/rest-api.md) | [contracts/assessment-job.md](contracts/assessment-job.md) | [contracts/auth-and-limits.md](contracts/auth-and-limits.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-08-18

## Conventions

- `[P]` = parallelizable (different file, no dependency on an incomplete task in this list). Two tasks editing the same file are never both marked `[P]`.
- `[USn]` = belongs to User Story n's phase (spec.md priorities: US1=P1, US2=P2, US3=P2, US4=P3, US5=P2). Setup, Foundational, and Polish tasks carry no story label.
- **No new dependency.** FastAPI, pydantic, httpx, uvicorn, pytest, pytest-asyncio are already declared in `pyproject.toml` ([plan.md](plan.md) Technical Context).
- **No existing table's columns change**, no new `UnitState`, and `orchestration/scheduler.py` / `orchestration/workflow.py` are untouched by every task below ([research.md](research.md) R7; [plan.md](plan.md) Constitution Check).
- Two files are added beyond [plan.md](plan.md)'s Project Structure list, both deliberate and noted at their task: `tests/unit/conftest.py` (a shared fixture module, so the five new test files never import each other) and `src/api/routers/__init__.py`.

---

## Implementation Strategy

Six increments. The first two produce no visible behavior change; each story phase after them is independently testable per its own quickstart.md scenario(s).

1. **Increment 1** (Phase 1): Scaffolding only — the `src/api/` package skeleton and the test modules.
2. **Increment 2** (Phase 2, Foundational): Everything both surfaces must share before any endpoint can exist — the two settings, the `assessment_jobs` table and its repository methods, the shared `AIRuntime` in the app lifespan, the one job service both the portal and the API trigger through (deleting `_RUNNING_PORTALS`), the router-level key check, and the two helper extractions out of `admin.py`. This is the largest phase because the feature's real machinery is shared, not per-story.
3. **Increment 3** (Phase 3, US1 — P1, the MVP): A non-browser client drives create-cycle → add-indicators → register-unit → trigger → poll → read-results end to end in JSON.
4. **Increment 4** (Phase 4, US2 — P2): A run interrupted by a restart is reported as definitely `failed`, never `running`; `never_triggered`, idempotency, and the concurrency cap are proven.
5. **Increment 5** (Phases 5–6, US3 — P2 then US4 — P3): Blind role-scoped human answers, then publication with score parity against the portal's own helper.
6. **Increment 6** (Phase 7, US5 — P2): The access-control guarantee proven across every exposed operation, plus the secret-masking check. The dependency *itself* lands in Phase 2 — see that phase's note on why it cannot be retrofitted per story.
7. **Polish** (Phase 8): Full regression, lint, the credential-free quickstart walkthrough, and one real budget-spending run.

---

## Phase 1: Setup

> Goal: Create the empty package and test modules. No behavior change, no import from `portal/` yet.

- [X] T001 Create `src/api/__init__.py` with a module docstring stating that this package is the JSON surface described in [contracts/rest-api.md](contracts/rest-api.md), that it is included as an `APIRouter` on the portal's existing app rather than mounted (research R1), and that it adds no new dependency
- [X] T002 [P] Create `src/api/routers/__init__.py` (empty package marker for the four routers)
- [X] T003 [P] Create `tests/unit/conftest.py` with the fixtures every new API test uses: a `tmp_path`-backed SQLite file passed through `shared.persistence.schema.init_db`, a `Settings(...)` built with `api_key="test-secret"`, `max_concurrent_assessment_runs=2`, `google_cloud_project="test-proj"` and `database_path` pointed at that file, an `app` fixture calling `portal.webapp.build_app(...)` inside `with TestClient(app) as client:` so the lifespan actually runs, and an `auth` fixture returning `{"X-API-Key": "test-secret"}`. Patch `api.runner.run_assessment_job` to an awaitable fake by default so no test spends model budget or needs Chromium. (One file beyond plan.md's Project Structure list — a shared fixture module so the five test files below never import each other)
- [X] T004 Create the five test modules as scaffolds, each with a `@pytest.mark.unit` module marker and the conftest fixtures imported by name only: `tests/unit/test_api_contract.py`, `tests/unit/test_api_auth.py`, `tests/unit/test_api_jobs.py`, `tests/unit/test_api_human_blindness.py`, `tests/unit/test_api_publication.py`

---

## Phase 2: Foundational — shared machinery

> Goal: The two settings, the durable job record, the shared AI runtime in the app lifespan, the single job service, the key check, and the two extractions — all in place and correct before any endpoint is written.
>
> **Must complete before Phase 3.** Every story phase depends on this one.
>
> **Why the key check lives here and not in US5's phase**: [contracts/auth-and-limits.md](contracts/auth-and-limits.md) §1 requires the check to be a *router-level* dependency "so a new endpoint cannot be added unprotected by omission". Adding it per story would leave every endpoint written in Phases 3–6 unauthenticated in the interim — the exact failure the router-level placement exists to prevent. US5's phase therefore proves the guarantee across the finished surface (including a structural test that no route escapes it) rather than introducing it.

### Configuration

### Configuration

- [X] T005 In `src/shared/config/settings.py`: add `api_key: str = ""` and `max_concurrent_assessment_runs: int = 2` to the `Settings` dataclass under a new `# --- Programmatic interface (spec 007) ---` heading, and add their `_ENV_MAP` entries `("AIQ_API_KEY", str)` and `("AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS", int)` per [data-model.md](data-model.md) §2
- [X] T006 In `src/shared/config/settings.py::as_dict`: mask the secret — return `"***"` for `api_key` when it is non-empty and `""` when unset, leaving every other field untouched. **Mandatory, not cosmetic**: `as_dict()` is persisted into `configuration_snapshots` (`cli.py:287`) and printed by `aiq config show` (`cli.py:46`), and `verify_no_credentials` scans only `fetch_records`, `stage_events`, and `cost_ledger_entries` (`core/telemetry/verify.py:63`), so nothing existing would catch the leak (research R6). Keep the mask shape-preserving so `config show`'s effective-vs-default `SOURCE` column and `Settings.defaults()` comparisons still work
- [X] T007 [P] In `src/shared/config/validation.py::validate_settings`: append an error when `settings.max_concurrent_assessment_runs < 1` (`AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS={value} must be >= 1 (FR-API-014a)`), following the existing `assessor_agent_count` pattern
- [X] T008 [P] In `specs/001-ekap-aiq-assessment/contracts/configuration.md`: add `AIQ_API_KEY` (str, default *(empty)*, "empty = programmatic access not configured", FR-API-035/039) and `AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS` (int, default `2`, "≥ 1", FR-API-014a) to the parameter table — `settings.py`'s own docstring points at that table as the full parameter reference

### Persistence

- [X] T009 In `src/shared/persistence/schema.py`: append the `assessment_jobs` table and its three indexes to `DDL` exactly as specified in [data-model.md](data-model.md) §1, including the SQL comment on `idx_assessment_jobs_one_running` explaining that the partial unique index makes FR-API-014 a storage invariant, plus a comment stating that this table is **deliberately mutable** for live run state — the same documented exception `upsert_unit` (`repositories.py:167-190`) and `update_portal_resolution` (`repositories.py:136-144`) already take (research R3). No migration tooling is needed: `init_db` runs `executescript(DDL)` with `CREATE TABLE IF NOT EXISTS` on every `aiq serve` (`schema.py:283-292`)
- [X] T010 In `src/shared/persistence/repositories.py`: add the job methods, adjacent to the publication methods and following their row-mapping style — `insert_assessment_job(job)`, `get_assessment_job(job_id)`, `latest_assessment_job(cycle_id, portal_id)` (most recent by `created_at`), `running_assessment_job(portal_id)`, `count_running_assessment_jobs()`, `update_assessment_job_state(job_id, state, failure_cause=None, data=None)` (also bumps `updated_at`), and `sweep_running_assessment_jobs() -> int` returning `cursor.rowcount`. Every other repository method is untouched
- [X] T011 In `src/shared/persistence/repositories.py`: add a `begin_immediate()` context manager that sets `self.conn.isolation_level = None` for its duration, issues `BEGIN IMMEDIATE`, and `COMMIT`s or `ROLLBACK`s on exit, restoring the previous `isolation_level`. Required because `schema.connect` leaves sqlite3 in legacy implicit-transaction mode, where a bare `BEGIN IMMEDIATE` can raise "cannot start a transaction within a transaction" — and because the write lock must be held *before* the running-job count or two callers both count `N-1` and both insert ([contracts/assessment-job.md](contracts/assessment-job.md) §Atomicity)

### Shared runtime and the app lifespan

- [X] T012 Create `src/api/runtime.py` with `AIRuntime` per [contracts/auth-and-limits.md](contracts/auth-and-limits.md) §2 — one `ModelProvider` from `settings.google_cloud_project`/`_location`/`_use_vertexai`, **one** `RateLimiter(rate_per_sec=settings.rate_limit_per_domain_rps)` shared across all runs (today each run builds its own, so two runs against one government domain each get the full per-domain budget — research R2), one `BrowserSession(settings.user_agent, limiter)`, and one `httpx.AsyncClient(timeout=15.0)`, with `start()` / `stop()`. **Launch Chromium lazily**: `start()` must construct the provider, limiter, and HTTP client only, with an `await ensure_browser()` that launches Chromium on first use and is idempotent — otherwise a portal-only deployment with no Playwright browser installed could no longer start `aiq serve` at all, breaking FR-API-002 and FR-API-039. Record this deviation from [contracts/auth-and-limits.md](contracts/auth-and-limits.md) §2's literal `start() → browser.start()` sequence in that file
- [X] T013 In `src/portal/webapp.py`: add an `asynccontextmanager` lifespan to `build_app` and pass it to `FastAPI(lifespan=...)` — on startup call `init_db(database_path)` (idempotent; creates `assessment_jobs` if absent), construct `AIRuntime(settings)`, `await runtime.start()`, and assign `app.state.ai_runtime`; on shutdown `await runtime.stop()`. The lifespan goes on **this** app, never on a mounted sub-application: Starlette does not run a mounted app's lifespan, so a mounted API's runtime would silently never start and the first fetch would trip `BrowserSession`'s `assert self._browser is not None` at `shared/tools/browser.py:69` (research R1). Leave the existing `/review` mount, the three `include_router` calls, and the `landing` route unchanged
- [X] T014 In `tests/unit/test_api_jobs.py`: add `test_lifespan_starts_shared_runtime` — entering the `TestClient` context makes `app.state.ai_runtime` present with its provider, limiter, and HTTP client constructed, `stop()` is awaited on exit, and no Chromium launch happened at startup (T012's lazy `ensure_browser`). This is the test [plan.md](plan.md)'s Post-Design re-check calls for, because a shared-runtime `live_prefill` called without a started runtime fails only when a real run is triggered — which the credential-free suite deliberately never does
- [X] T015 In `src/portal/live_prefill.py::run_live_prefill`: accept an injected `AIRuntime` instead of building `RateLimiter`, `ModelProvider`, `BrowserSession`, and `httpx.AsyncClient` per run, and drop the `await browser.start()` / `await browser.stop()` pair (the runtime owns that lifecycle now — call `await runtime.ensure_browser()` before `run_batch`). Keep everything else exactly as it is: it still opens **its own** SQLite connection because the triggering request's connection is closed by the time the task runs, and `FetchLog`, `StageEventLog`, `CostLedger`, and the capture directory are still constructed per run on that connection — which is what keeps telemetry and cost records identical to a CLI run (SC-010). `run_batch(..., adjudicate_results=True)` is called unchanged. **Must land after T013**, per [plan.md](plan.md)'s sequencing note
- [X] T016 In `src/api/jobs.py`: define the record and the read side — `@dataclass AssessmentJob` mirroring [data-model.md](data-model.md) §1's columns, `JobStart(job, already_running)`, `JobStatus`, the canonical `failure_cause` constants (`service_stopped_mid_run`, `pipeline_error`, `ai_provider_unavailable`), and `job_status(repo, session_id, cycle_id, portal_id) -> JobStatus` reading `latest_assessment_job(...)` and **deriving** progress as the count of `repo.list_units_for_portal(session_id, portal_id)` rows whose state is in `{DELIVERED, ESCALATED, UNASSESSABLE}` against `job.questions_total` — the same computation `portal/admin.py:100-104` already performs, never a stored column, so it cannot drift and is monotonic by construction (research R7, SC-005). Return a `never_triggered` status with the live cycle question count when no row exists (FR-API-019)
- [X] T017 Create `src/api/runner.py` with `run_assessment_job(job_id, database_path, settings, runtime, session_id, cycle_id, portal_id)` — calls `run_live_prefill` on the shared runtime, then records terminal state exactly per [contracts/assessment-job.md](contracts/assessment-job.md) §Terminal recording: returned → `state='done'` with `data.outcomes = {delivered, escalated, unassessable}` from the `BatchRunSummary`; raised → `state='failed'` with `failure_cause='pipeline_error'` (or `ai_provider_unavailable` when the exception is a provider/credential failure), `data.error` holding the exception summary, and the exception logged as `portal/admin.py:53-56` does today; cancelled → best-effort `state='failed'`, `failure_cause='service_stopped_mid_run'`. A terminal job is never reopened
- [X] T018 In `src/api/jobs.py`: implement `start_assessment_job(repo, settings, runtime, *, cycle_id, portal_id, triggered_by, actor_id) -> JobStart` with the six preconditions in the **contractual evaluation order** of [contracts/assessment-job.md](contracts/assessment-job.md) — cycle exists → unit exists and belongs to that cycle → unit has a non-empty `resolved_url` → cycle has ≥ 1 indicator → **already-running job for this unit returns it with `already_running=True`** → running-job count below `settings.max_concurrent_assessment_runs`. Checks 5 and 6 and the insert run inside one `begin_immediate()` (T011), with **5 before 6** so an idempotent re-trigger succeeds at capacity because it starts nothing (FR-API-014 vs FR-API-014a). On `sqlite3.IntegrityError` from `idx_assessment_jobs_one_running`, re-read the running job and return it with `already_running=True`. On success: `ensure_session`, insert the row `state='running'` with `questions_total` snapshotted, create the `run_assessment_job` task holding a **strong reference** so asyncio cannot collect it mid-flight, and attach the completion callback. Returns before the run does any work (FR-API-013)
- [X] T019 In `src/portal/admin.py`: delete `_RUNNING_PORTALS` and `_on_prefill_done`, replace `run_prefill`'s inline guard-and-`create_task` with one `start_assessment_job(..., triggered_by="portal")` call (exceptions swallowed into the same 303 redirect as today), and replace `"run_in_progress": u.portal_id in _RUNNING_PORTALS or bool(states_seen - terminal)` with `job_status(...).state == "running" or bool(states_seen - terminal)` — the before/after table in [contracts/assessment-job.md](contracts/assessment-job.md) §Portal integration. Keep `admin_project_detail.html` and every rendered state untouched. **Land this as its own reviewable commit, not buried inside the API work** ([plan.md](plan.md) Risks): it is the one place where portal behavior genuinely changes — a run in progress is now derived from the database, so it is still reported as running after a restart instead of appearing idle

### API scaffolding shared by every endpoint

- [X] T020 In `src/api/schemas.py`: define the error envelope `{"error": {"code", "message", "details"}}` as a pydantic model plus the exception types the service and routers raise — `ApiError` base carrying `code`/`http_status`/`message`/`details`, and `NotFound`, `Conflict`, `PreconditionFailed`, `CapacityReached(retry_after_seconds)`, `Unauthorized`, `NotConfigured` — mapped to the seven codes and statuses in [contracts/rest-api.md](contracts/rest-api.md) §Error envelope. (Exceptions live in `schemas.py` rather than a new module so plan.md's file list stands.) No error body may carry cycle, unit, question, answer, or score data beyond identifiers the caller itself supplied (FR-API-036)
- [X] T021 In `src/api/schemas.py`: add the request and response models for every endpoint body in [contracts/rest-api.md](contracts/rest-api.md) §§1–6 — cycle create/read, question create/read (including `question_id` **and** `indicator_id` side by side per FR-API-011a), unit create/read, trigger response, status response with `state` constrained to `running`/`done`/`failed`/`never_triggered`, `AIResultView` and its `complete`/progress envelope, human submission and role-scoped read, and publication create/read
- [X] T022 Create `src/api/deps.py` with the `X-API-Key` dependency and the two injection helpers per [contracts/auth-and-limits.md](contracts/auth-and-limits.md) §1 — **503 `not_configured`** when `settings.api_key` is empty (FR-API-039: a deployment that never sets a secret is a supported portal-only deployment, not a misconfiguration), **401 `unauthorized`** when the header is absent or does not match, comparison via `hmac.compare_digest` so a wrong key cannot be recovered by timing, and pass-through otherwise. The dependency must run before any handler body so a refused call has **no side effects** — no job row, no task, no model call (FR-API-037, SC-008). Add a repository dependency using `portal.common.repo_factory` and a runtime dependency reading `request.app.state.ai_runtime`
- [X] T023 Create `src/api/app.py` with `build_api_router(database_path, settings, runtime_getter) -> APIRouter` — one router carrying `dependencies=[Depends(require_api_key)]` at router level and including the four sub-routers, plus `install_api_error_handlers(app)` registering handlers for `ApiError` and for FastAPI's `RequestValidationError` (whose default body is *not* the envelope, so 422s would otherwise break the single-shape contract of [contracts/rest-api.md](contracts/rest-api.md)). Handlers register on the **app**, not the router, which is why they are a separate function. `CapacityReached` must set the `Retry-After` header
- [X] T024 In `src/portal/webapp.py`: `app.include_router(build_api_router(database_path, settings, runtime_getter), prefix="/api/v1")` and call `install_api_error_handlers(app)`, leaving the portal routers, the `/review` mount, and the landing route exactly as they are (FR-API-002)
- [X] T025 Create `src/api/identity.py` with the single question-identifier helper — `compose_question_id(cycle_id, indicator_id) -> str` returning `f"{cycle_id}:{indicator_id}"` and a `QuestionIdentity` projection exposing `question_id` plus the bare `indicator_id` as a display-only field ([data-model.md](data-model.md) §3.1). This is the FR-API-011a rule made concrete: clients round-trip the stored identifier opaquely and never construct one
- [X] T026 In `src/portal/admin.py::add_question`: replace the inline `question_id=f"{cycle_id}:{question_id}"` prefixing at `admin.py:150-154` with `compose_question_id(...)` from T025, so the API and the portal cannot diverge on how a question is addressed. Rendered behavior is unchanged
- [X] T027 Move `_final_answer` out of `src/portal/admin.py:281-311` into `src/api/finalize.py` as `final_answer(repo, session_id, question_id, portal_id)` — **verbatim**, including its arbitration → A/B agreement → lone human → adjudicated-AI precedence, its unresolved-disagreement placeholder, and its "never invents an answer nobody gave" property — and have `admin.py::publish_unit` import it back. Extracting rather than copying is what makes SC-007's portal parity a property of the design instead of a test that happens to pass (research R10). **Must land before Phases 5 and 6**, which both reference it; the full-suite run of T059 is the gate on the move itself

---

## Phase 3: US1 (P1) — An external client drives a complete AI assessment without a browser

> Goal: create cycle → add indicators → register unit → trigger → poll → read results, entirely in JSON, with every step returning the identifier the next step needs.
>
> **Independent test**: run the whole sequence as a non-browser client against a running instance and assert that every response is JSON with no redirect and no markup, that each create returns its identifier, and that the same entities are then visible in the portal (spec.md User Story 1, Acceptance Scenarios 1–7; quickstart.md Scenario 1).

- [X] T028 [US1] In `src/api/routers/cycles.py`: implement `POST /cycles` (201), `GET /cycles`, and `GET /cycles/{cycle_id}` (with `question_count` and `unit_count`) per [contracts/rest-api.md](contracts/rest-api.md) §1. The create **reads before writing**: `get_cycle` first and raise `Conflict` naming the existing cycle when present, because `insert_cycle` is used elsewhere as a superseding write and a create must never act as an update (FR-API-006, research R9). On success also `ensure_session(r, cycle_id)`, as the portal's create does
- [X] T029 [US1] In `src/api/routers/cycles.py`: implement `GET /cycles/{cycle_id}/questions` and `POST /cycles/{cycle_id}/questions` (201) field-for-field with the portal's form at `admin.py:130-141` — `text` composed as `f"{title} — {what}"`, `how` expanded into the four-key guidance dict, `question_id` from `compose_question_id` (T025), `is_custom=True`, and **the same `cycle.questionnaire_ref` rewrite** to `"<name> Custom Questionnaire Set (N indicators)"` that `admin.py:170-177` performs, so a cycle built through either surface reads identically. Raise `Conflict` when that `indicator_id` already exists in this cycle; the same code under a different cycle is accepted (FR-API-009)
- [X] T030 [US1] In `src/api/routers/cycles.py`: implement `GET /cycles/{cycle_id}/units` and `POST /cycles/{cycle_id}/units` (201, returning the generated `portal_id`) per [contracts/rest-api.md](contracts/rest-api.md) §3. Pre-check with `get_portal_by_country(cycle_id, country_id)` and raise `Conflict` **regardless of the URL supplied** — `target_portals` declares `UNIQUE(cycle_id, country_id)` (`schema.py:37-45`) and `insert_portal` is `ON CONFLICT ... DO NOTHING` (`repositories.py:128-134`), so today a differing URL is silently discarded while the portal redirects as though it succeeded (amended FR-API-010, research R9). Append `country_id` to `cycle.country_set` exactly as `admin.py:193-196` does. The unit list carries `latest_job_state` from `latest_assessment_job` and `published` from `latest_publication`
- [X] T031 [US1] In `src/api/routers/assessments.py`: implement `POST /cycles/{cycle_id}/units/{portal_id}/assessment` → **202** with `job_id`, `state`, `questions_total`, `questions_completed`, `already_running`, and `created_at`, delegating entirely to `start_assessment_job` (T018) with `triggered_by="api"` and the optional body's `actor_id`. Map its raised errors to the contract's statuses: `NotFound` → 404, `PreconditionFailed` → 409 (`unit_has_no_url`, `cycle_has_no_questions`), `CapacityReached` → 429 with `Retry-After`. The idempotent case returns 202, never 429
- [X] T032 [US1] In `src/api/routers/assessments.py`: implement `GET /cycles/{cycle_id}/units/{portal_id}/assessment` → 200 from `job_status` (T016), returning `state`, `job_id`, `questions_total`, `questions_completed`, `failure_cause`, `triggered_by`, `created_at`, `updated_at`, and `outcomes` (populated once terminal), reporting the **latest** job for the unit
- [X] T033 [US1] In `src/api/routers/assessments.py`: implement `GET /cycles/{cycle_id}/units/{portal_id}/results` → 200, projecting `review/query.py::build_question_review(repo, session_id, question_id, portal_id, settings.confidence_acceptance_threshold)` per question into `AIResultView` exactly as mapped in [data-model.md](data-model.md) §3.2 — `answer` from `delivered_answer`, `confidence` from `consensus_confidence`, `justification`, `evidence_url` from `evidence.url` else `resolved_url` with `evidence_missing` alongside, and `blocked`/`blank_reason` from `escalated`/`reason_tag` (spec 004's tag verbatim, FR-API-023). `build_question_review` is **called, not modified** (research R10). The envelope carries `complete` (true only when the latest job is `done`) plus the progress pair, and each unreached question is `assessed: false` with a null answer — three independent signals so a mid-run read cannot be mistaken for a final one (FR-API-024)
- [X] T034 [P] [US1] In `tests/unit/test_api_contract.py`: add `test_full_lifecycle_returns_json_and_chains_identifiers` — POST cycle → POST question → POST unit → POST assessment → GET status → GET results, asserting every response is `application/json` with no 3xx anywhere, each create returns the identifier the next call consumes, `question_id` is `"<cycle>:<indicator>"` with `indicator_id` alongside, and a question identifier returned by the interface is accepted back unchanged (FR-API-011a, SC-001)
- [X] T035 [US1] In `tests/unit/test_api_contract.py`: add `test_duplicate_creates_are_conflicts` — re-running each of the three creates verbatim returns **409** `conflict` naming the existing entity with nothing modified (re-read and assert `name` and `questionnaire_ref` unchanged), and registering the same `country_id` with a *different* URL is also **409** with the original unit's URL intact (quickstart.md Scenario 2)
- [X] T036 [US1] In `tests/unit/test_api_contract.py`: add `test_results_partial_and_blocked` — with some of a unit's questions seeded terminal and one seeded `ESCALATED`, the results read while the job is `running` returns `complete: false` with the finished questions only, the blocked question carries `answer: null`, `blocked: true`, and a non-empty `blank_reason`, and an unreached question is `assessed: false` — distinct from the blocked one (FR-API-023, FR-API-024)
- [X] T037 [US1] In `tests/unit/test_api_contract.py`: add `test_portal_and_api_share_one_dataset` — a cycle, indicator, and unit created through the API are returned by `repo.list_cycles()`/`list_questions()`/`list_portals()` and appear in a `GET /admin` response body, and a cycle created through the portal's own `POST /admin/projects` form appears in `GET /api/v1/cycles` (FR-API-003, User Story 1 Acceptance Scenario 7)

---

## Phase 4: US2 (P2) — Job status survives a restart and is always answerable

> Goal: a run in flight when the service stopped is reported as definitely `failed` with a service-stop cause once it is back up — never `running`, never missing — and "never triggered", idempotency, and the concurrency cap all have provable answers.
>
> **Independent test**: trigger, stop the service mid-run, restart, and poll — a definite non-ambiguous state and the progress reached before the interruption come back with no reliance on the previous process's memory (spec.md User Story 2, Acceptance Scenarios 1–5; quickstart.md Scenarios 5–6).

- [X] T038 [US2] In `src/api/jobs.py`: add `sweep_interrupted_jobs(conn) -> int` — wraps `Repository(conn).sweep_running_assessment_jobs()`, setting every `state='running'` row to `state='failed'`, `failure_cause='service_stopped_mid_run'`, `updated_at=datetime('now')`, and returning the count. This is the guarantee behind FR-API-018 (a run is never reported `running` after a restart) and it is also what releases stale rows from the concurrency budget and from `idx_assessment_jobs_one_running`
- [X] T039 [US2] In `src/portal/webapp.py`: call `sweep_interrupted_jobs` in the T013 lifespan **after `init_db` and before serving traffic**, log the result as `swept N interrupted assessment job(s)` at INFO (so a clean start logs `N=0`, per quickstart.md Setup), and guard the sweep's single-process precondition: it fails *every* running job it finds, so under multiple workers it would mark another worker's live runs as stopped. Raise a clear startup error when `WEB_CONCURRENCY` or `UVICORN_WORKERS` is set above 1, referencing [contracts/assessment-job.md](contracts/assessment-job.md)'s correctness precondition — `cli.py:136` calls `uvicorn.run(app, ...)` with no `workers` argument today, so introducing replicas must fail loudly rather than silently corrupt job state ([plan.md](plan.md) Risks)
- [X] T040 [P] [US2] In `tests/unit/test_api_jobs.py`: add `test_sweep_fails_interrupted_runs` — insert a `running` job row directly, call `sweep_interrupted_jobs(conn)`, assert it returns 1 and the row is now `failed` with `failure_cause="service_stopped_mid_run"`, that a `done` and a `failed` row are untouched, and that a subsequent status read reports `failed` with the progress reached (spec.md US2 Acceptance Scenario 1, SC-004)
- [X] T041 [US2] In `tests/unit/test_api_jobs.py`: add `test_status_states_are_exactly_three_plus_never_triggered` — a unit with no job returns **200** with `state="never_triggered"` and `job_id: null` (not 404: the unit exists, the run does not, FR-API-019); a freshly triggered unit returns `running` with `0` of `N` completed; a failed job returns `failure_cause` and the progress reached (FR-API-020); and across a sequence of polls `questions_completed` never exceeds `questions_total` and never decreases (SC-005)
- [X] T042 [US2] In `tests/unit/test_api_jobs.py`: add `test_double_trigger_is_idempotent` — two triggers for the same unit both return **202** with the **same `job_id`** and the second carrying `already_running: true`, and exactly one `assessment_jobs` row exists for that unit; then assert the `IntegrityError` path directly by calling `start_assessment_job` twice with the running-job pre-read stubbed out, proving the partial unique index resolves the "two clients trigger at the same moment" edge case atomically (FR-API-014)
- [X] T043 [US2] In `tests/unit/test_api_jobs.py`: add `test_capacity_cap_bounds_concurrent_runs` — with `max_concurrent_assessment_runs=1`, triggering a second *different* unit returns **429** `capacity_reached` with `Retry-After` and inserts no row, while re-triggering the *already-running* unit still returns **202** because it starts nothing (the contractual 5-before-6 ordering, FR-API-014a and SC-011); also assert `validate_settings` rejects a cap of `0` (T007)
- [X] T044 [US2] In `tests/unit/test_api_jobs.py`: add `test_retrigger_and_precondition_refusals` — re-triggering a unit whose previous job is `failed` inserts a **new** `job_id` while the previous row remains readable (FR-API-021), and triggering a unit with no `resolved_url` or in a cycle with no indicators returns **409** `precondition_failed` with the stated reason and **no job row** (FR-API-015; quickstart.md Scenario 6)

---

## Phase 5: US3 (P2) — Human answers submitted and read programmatically without breaking blindness

> Goal: role A and role B each submit and re-read their own answers over JSON, and no response ever mentions the other role.
>
> **Independent test**: submit as both roles for the same question on the same unit, read each role back separately, and confirm each read contains only its own role's submissions with no operation returning both (spec.md User Story 3, Acceptance Scenarios 1–6; quickstart.md Scenario 4).

- [X] T045 [US3] In `src/api/routers/human.py`: implement `POST /cycles/{cycle_id}/units/{portal_id}/human-answers` → 201 per [contracts/rest-api.md](contracts/rest-api.md) §5, recording the submission on **exactly the same terms as `portal/assessor.py:70-104`** — the same `HumanAssessorSubmission` dataclass, the same `agent_index == -1` AI-suggestion lookup feeding `ai_suggested_answer` and `ai_suggestion_accepted`, and the same `recompute_portal_discrepancy(..., settings.human_discrepancy_rate_threshold)` call afterwards, so a submission is indistinguishable by origin (FR-API-027). `question_id`, `role`, `actor_id`, and `answer` are required (422 otherwise); `evidence_url` and `notes` are optional and absent is accepted, not rejected (FR-API-026)
- [X] T046 [US3] In `src/api/routers/human.py`: implement `GET /cycles/{cycle_id}/units/{portal_id}/human-answers?role=A` → 200, with **`role` required** — omitting it is **422 `invalid_request`**, never a both-roles default (FR-API-029). Build the response from a single `latest_human_submission(session_id, question_id, portal_id, role)` call per question, listing every question in the cycle with an `answered` flag separating answered from unanswered (FR-API-030) and returning the role's current answer where it has revised. No code path in this module may read or merge a second role ([data-model.md](data-model.md) §3.3)
- [X] T047 [P] [US3] In `tests/unit/test_api_human_blindness.py`: add `test_no_cross_role_leakage` — parametrized across the full unit × question × role matrix with both roles having submitted *different* answers, assert each role-scoped read returns only its own submission and that the other role's `actor_id`, notes, and evidence URL appear **nowhere in the raw response body** (a substring assertion on the serialized JSON, not only on parsed fields) — SC-006's "zero submissions belonging to the other role"
- [X] T048 [US3] In `tests/unit/test_api_human_blindness.py`: add `test_submission_and_read_rules` — a role-less read is **422** and returns neither role's data; a submission with no `evidence_url` and no `notes` is accepted (201) with those fields null; a submission missing `role`, `actor_id`, or `answer` is **422**; a revised answer is what the subsequent read returns; and a role that answered some questions and not others gets `answered` true/false accordingly (FR-API-026, FR-API-029, FR-API-030)
- [X] T049 [US3] In `tests/unit/test_api_human_blindness.py`: add `test_api_submission_matches_portal` — a submission made through the API is the one `GET /assessor/{cycle_id}/{portal_id}?role=A` renders for that role, its stored `ai_suggested_answer`/`ai_suggestion_accepted` match what the portal's own form would have stored for the same input, and the unit's A/B discrepancy case is recomputed by the API path exactly as by the portal path (FR-API-027)

---

## Phase 6: US4 (P3) — Publication and published results reachable programmatically

> Goal: publish a unit over JSON and read the score and per-question breakdown back, with the score identical to the portal's.
>
> **Independent test**: for a unit mixing agreeing human answers, differing human answers, and AI-only answers, publish through the interface and confirm the score and breakdown match what the portal's publish action produces for the same unit (spec.md User Story 4, Acceptance Scenarios 1–5; quickstart.md Scenario 8).

- [X] T050 [US4] In `src/api/routers/publication.py`: implement `POST /cycles/{cycle_id}/units/{portal_id}/publication` → 201, computing the breakdown by calling the **extracted** `api.finalize.final_answer` (T027) per question and the score as affirmative/total exactly as `admin.py::publish_unit` does, then writing a `PublicationRecord` through `insert_publication`. The response carries `publication_id`, `score`, `published_by`, `published_at`, and the `breakdown` mapped to `{question_id, indicator_id, final_answer}`. Both surfaces calling one helper is what makes SC-007 a design property (FR-API-032)
- [X] T051 [US4] In `src/api/routers/publication.py`: implement `GET /cycles/{cycle_id}/units/{portal_id}/publication` → 200 from `latest_publication(cycle_id, portal_id)`, projected per [data-model.md](data-model.md) §3.4. A never-published unit returns **200** with `published: false`, `score: null`, and an empty breakdown — explicitly not a zero score (FR-API-034); a unit published more than once returns the most recent record (FR-API-033)
- [X] T052 [P] [US4] In `tests/unit/test_api_publication.py`: add `test_publication_parity_with_portal` — seed one unit whose three questions are respectively A/B-agreeing, A/B-differing, and AI-only (a `DELIVERED` unit with `consensus_answer`), publish via the API, publish an identically seeded twin via `portal.admin`'s own publish path, and assert the two scores and per-question breakdowns are equal value-for-value (SC-007, FR-API-032)
- [X] T053 [US4] In `tests/unit/test_api_publication.py`: add `test_never_published_and_republish` — the read for an unpublished unit is **200** with `published: false` and `score: null` (not `0.0`), and after two publications the read returns the second record's `publication_id`, score, and breakdown (FR-API-033, FR-API-034)

---

## Phase 7: US5 (P2) — Access restricted to holders of a configured key

> Goal: every programmatic operation is refused without the configured secret, discloses nothing, leaves no side effect, and the secret never reaches the database or the console. The portal is unaffected either way.
>
> **Independent test**: call every programmatic operation with a valid key, a wrong key, and no key, confirming the first succeeds and the latter two are refused without disclosing any project, unit, question, or answer data (spec.md User Story 5, Acceptance Scenarios 1–5; quickstart.md Scenario 3).
>
> The dependency itself is T022 in Phase 2 — see that phase's note. These tasks prove the guarantee across the finished surface.

- [X] T054 [US5] In `tests/unit/test_api_auth.py`: add `test_every_api_route_requires_the_key` — enumerate `app.routes` for every path starting `/api/v1` and assert each one's dependant chain includes `require_api_key`, so an endpoint added later cannot escape the check by omission. This is the structural counterpart to the router-level placement in [contracts/auth-and-limits.md](contracts/auth-and-limits.md) §1
- [X] T055 [US5] In `tests/unit/test_api_auth.py`: add `test_missing_or_wrong_key_is_refused` — parametrized over every exposed operation (all four routers, reads and writes), each returns **401** `unauthorized` with no key and with a wrong key, and the response body contains no cycle name, unit display name, question text, answer, or score (assert against the raw body, using entities seeded beforehand so a leak would be detectable) — SC-008
- [X] T056 [US5] In `tests/unit/test_api_auth.py`: add `test_unconfigured_secret_keeps_portal_usable` — with `api_key=""`, the app **starts normally**, `GET /` and `GET /admin` return 200, and every `/api/v1/**` operation returns **503** `not_configured` — a portal-only deployment is supported, and the interface is never reachable unauthenticated (FR-API-038, FR-API-039)
- [X] T057 [US5] In `tests/unit/test_api_auth.py`: add `test_refused_trigger_has_no_side_effect` — a trigger with a wrong key inserts **no** `assessment_jobs` row, leaves the status read at `never_triggered`, and creates no background task (assert with the `run_assessment_job` fake never called), proving the dependency runs before any handler body (FR-API-037, SC-008)
- [X] T058 [P] [US5] In `tests/unit/test_settings.py`: add `test_api_key_is_masked_everywhere` — `Settings(api_key="super-secret").as_dict()["api_key"] == "***"`, `Settings().as_dict()["api_key"] == ""`, the literal secret appears in neither `aiq config show`'s output nor a `configuration_snapshots` row written from `as_dict()`, and `config show`'s effective-vs-default `SOURCE` column still reports `api_key` as configured rather than default (T006; [plan.md](plan.md) Risks)

---

## Phase 8: Polish & Cross-Cutting Concerns

> Goal: no regression anywhere in the existing suite, and a manual walkthrough of every quickstart scenario — including the one that spends real budget.

- [X] T059 Run `pytest tests/unit tests/contract tests/integration -q` and confirm every test outside the files this feature adds passes unmodified — in particular `tests/unit/domain/test_unit_state.py`'s terminal-state coverage, `tests/unit/test_settings.py`, `tests/unit/test_modular_structure.py`, and `tests/unit/test_blank_field_fallback.py`, whose `build_question_review` this feature calls but does not change (SC-009; [plan.md](plan.md) Constitution Check). This run is also the gate on T027's `_final_answer` move
- [X] T060 [P] Run `ruff check src tests` and fix any violation the new `src/api/` package introduces (line-length 100 per `pyproject.toml`)
- [X] T061 Walk quickstart.md Scenarios 1–6 manually via `aiq db init` + `aiq serve` with `AIQ_API_KEY=local-dev-secret` — no credentials and no network needed. Confirm `aiq config show` masks `api_key` as `***`, the startup log reports the interrupted-job sweep, the duplicate creates 409, the access matrix behaves, a real Ctrl-C mid-run then restart reports `failed`/`service_stopped_mid_run`, and a trigger against a 111-indicator cycle returns in under two seconds (`curl -w '%{time_total}'`, SC-003)
- [X] T062 Walk quickstart.md Scenarios 7–8 with Vertex AI credentials and Chromium installed — **this spends real model budget**. Confirm `questions_completed` climbs monotonically without exceeding `questions_total`, that `aiq telemetry cost --session <cycle>-workflow-session` and `aiq telemetry fetches --session …` show entries identical in kind to a portal- or CLI-triggered run (SC-010), that publication through the API matches `/public/<cycle>/<portal_id>`, and run `aiq verify independence --session …` against a session with **two concurrent runs** to confirm the shared `BrowserSession` causes no cross-unit evidence contamination ([plan.md](plan.md) Risks)
- [X] T063 [P] Update `README.md`'s `aiq serve` line and Project layout section to name the `/api/v1` JSON surface and the `src/api/` package, and record the two new environment variables where the README documents configuration — so the interface is discoverable without reading `specs/007-headless-rest-api/`

---

## Dependency Graph

```
T001 → T002, T003, T004 (scaffolds; T003 before T004's fixture use)

Config:       T005 → T006;  T007, T008 independent of both
Persistence:  T009 → T010 → T011

Runtime/lifespan (strict order — plan.md sequencing note 1):
T012 (AIRuntime) → T013 (lifespan) → T014 (wiring test)
T013 → T015 (live_prefill signature)         # NEVER before T013
T010, T011 → T016 (job store + job_status)
T015, T016 → T017 (runner)
T011, T016, T017 → T018 (start_assessment_job)
T016, T018 → T019 (delete _RUNNING_PORTALS)  # own commit

Scaffolding:  T020 → T021;  T005, T006 → T022;  T020, T021, T022 → T023 → T024
              T025 → T026                       # identity extraction
              T027 (finalize extraction, independent of T025/T026)

Foundational complete (T005–T027) → all of Phases 3–7

US1:  T023, T024, T028 → T029 → T030           # same file, sequential
      T018 → T031;  T016 → T032;  T033 needs T032's session plumbing
      T028–T033 → T034 → T035 → T036 → T037    # all test_api_contract.py

US2:  T010, T016 → T038 → T039 → T040
      T032 → T041;  T018 → T042 → T043 → T044  # all test_api_jobs.py

US3:  T021, T022 → T045 → T046 → T047 → T048 → T049

US4:  T027 → T050 → T051 → T052 → T053

US5:  T023 → T054 → T055 → T056 → T057;  T006 → T058 (independent file)

Polish: every story phase → T059 → T060, T061 → T062;  T063 anytime after T024
```

---

## Parallel Execution Opportunities

| Group | Tasks | Can run in parallel after |
|---|---|---|
| Setup | T002, T003 | T001 |
| Config vs. persistence | T007, T008 alongside T009/T010 | T005 |
| Docs vs. code | T008 | nothing — pure documentation |
| Runtime vs. scaffolding | T020–T023 alongside T012–T019 | T005, T006 (different files entirely) |
| Extractions | T025 and T027 in parallel | T001 |
| US1 first test | T034 | T028–T033 |
| US2 sweep test | T040 | T038, T039 |
| US3 blindness matrix | T047 | T045, T046 |
| US4 parity test | T052 | T027, T050, T051 |
| US5 masking test | T058 | T006 (needs none of the API work) |
| Polish | T060, T063 | T059 |

Note: the four router files (`cycles.py`, `assessments.py`, `human.py`, `publication.py`) are genuinely independent of each other and could be built by four workers in parallel once Phase 2 is complete — the story ordering below is a *priority* ordering, not a technical dependency. Within each story, though, the router file and its test file are each edited sequentially, so cross-task parallelism inside a phase is limited to the first test task.

---

## Story → Task Mapping

| Story | Priority | Requirements | Tasks | Independent test criteria |
|---|---|---|---|---|
| US1 | P1 (MVP) | FR-API-001, 003, 005–013, 011a, 015, 022–024 | T028–T037 | The full create→trigger→poll→read sequence completes in JSON with no redirect and no markup; each create returns the identifier the next step consumes; duplicates are 409; the same entities are visible in the portal |
| US2 | P2 | FR-API-014, 014a, 016–021, SC-004, SC-005, SC-011 | T038–T044 | After a mid-run restart the run reports `failed`/`service_stopped_mid_run` with the progress reached; `never_triggered` is distinct from every run state; a double trigger returns one job; the cap refuses the (N+1)th run but never an idempotent re-trigger |
| US3 | P2 | FR-API-025–030, SC-006 | T045–T049 | Each role-scoped read returns only its own role's submissions across the whole matrix, with the other role absent from the raw body; a role-less read is refused; optional fields may be absent; revisions return current |
| US4 | P3 | FR-API-031–034, SC-007 | T050–T053 | For a unit mixing agreeing, differing, and AI-only answers, the API's score and breakdown equal the portal's for the same unit; a never-published unit reports `published: false`, not a zero score |
| US5 | P2 | FR-API-035–039, SC-008 | T054–T058 | Every operation is 401 without a valid key and 503 when no secret is configured; refusals disclose no data and leave no job row; the portal is unaffected; the secret never appears in `config show` or `configuration_snapshots` |

---

## MVP Scope

**Minimum viable feature**: T001–T037 (Setup + Foundational + US1). At this point an external client can drive the entire AI half of the lifecycle over JSON — create a project, define indicators, register a unit, trigger the multi-agent pipeline, poll its progress, and read per-question answers with confidence, justification, evidence, and spec 004's blank reasons — with the portal still working exactly as it does today and the secret already enforced (T022 lands in Phase 2). This alone satisfies SC-001's AI path and SC-002's first six capabilities.

**Full feature**: T001–T063 — adds durable status across restarts and the concurrency cap (US2), the blind human-answer surface (US3), publication and published reads (US4), the proven access-control matrix (US5), and the regression plus real-run validation.

**Recommended sequencing notes** (carried from [plan.md](plan.md)'s Post-Design Constitution Re-check and Risks):

1. **T013 must land before T015.** A shared-runtime `live_prefill` called without a started `AIRuntime` fails at `BrowserSession`'s `assert self._browser is not None`, and that failure surfaces only when a real run is triggered — which the credential-free suite deliberately never does. T014 is the test that covers the wiring.
2. **T027 must land before Phases 5 and 6**, which both reference the moved `_final_answer`; moving it while `admin.py` still calls it is exactly what T059's full-suite run is the gate for.
3. **T019 (deleting `_RUNNING_PORTALS`) belongs in its own commit.** It is the single place where portal behavior genuinely changes inside FR-API-002's "unchanged" boundary — an improvement (a run survives a restart in the admin view instead of appearing idle), but it should be reviewable on its own rather than buried in the API work.
4. **T039's single-worker guard is deliberate loudness.** The sweep is only correct for one serving process; making replicas fail at startup is what keeps a latent risk from becoming silent job-state corruption.
5. **T012's lazy Chromium launch is a deviation from the contract's literal `start()` sequence**, recorded in that contract by the same task. Launching Chromium eagerly in the lifespan would make `aiq serve` unstartable on a deployment with no Playwright browser installed — a portal-only deployment that works today and that FR-API-039 requires to keep working.

---

## Format Validation

All 63 tasks follow `- [ ] T0NN [P?] [USn?] Description with exact file path(s)`. Setup (T001–T004), Foundational (T005–T027), and Polish (T059–T063) carry no story label. Every task in Phases 3–7 (T028–T058) carries exactly one story label. Every task names at least one concrete file path, and no two tasks marked `[P]` edit the same file.
