# Implementation Plan: Headless Assessment REST API

**Feature Directory**: `specs/007-headless-rest-api`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-18
**Status**: Phase 1 complete — design artifacts generated
**Branch**: `main` (see Notes)

## Summary

Every capability this feature must expose already runs behind the portal: `portal/admin.py` creates cycles, indicators, and units and triggers the pipeline; `portal/assessor.py` records blind A/B submissions; `portal/public.py` reads publications; `review/query.py` already assembles per-question answers with confidence, justification, evidence, and spec 004's blank-field reason tag. What is missing is not capability but a *machine-readable contract*: the portal's handlers answer with `TemplateResponse` and `RedirectResponse(303)`, which is why nothing outside a browser can use them.

So the work is a new `src/api/` package that projects existing entities and existing view builders as JSON, plus three pieces of genuinely new machinery:

1. **A durable job record** (`assessment_jobs`) replacing `portal/admin.py`'s in-memory `_RUNNING_PORTALS` set, with a partial unique index making "one running job per unit" a storage invariant and a startup sweep turning a restart-orphaned run into a definite `failed` state.
2. **A shared `AIRuntime` in the app lifespan** — model provider, rate limiter, browser, HTTP client — replacing the per-run construction in `portal/live_prefill.py`. This is a correctness fix as much as plumbing: each run currently builds its *own* `RateLimiter`, so two concurrent runs against one government domain each get the full per-domain budget.
3. **API-key access control** on `/api/v1/**` only, with the secret masked out of `Settings.as_dict()` because that dict is persisted into `configuration_snapshots` and printed by `aiq config show`.

**Primary technical challenge**: this is an *idempotency and identity* problem, not a serialization problem. The existing repository writes are all deliberately forgiving — `insert_portal` is `ON CONFLICT DO NOTHING`, `insert_cycle` is used as a superseding write to update a cycle in place, `question_id` is a global primary key the portal cycle-prefixes by hand. Each is correct for a human clicking a form and wrong for a client that retries. Every create in this API therefore reads before it writes ([research.md](./research.md) R9), and the trigger's idempotency and capacity checks share one `BEGIN IMMEDIATE` transaction ([contracts/assessment-job.md](./contracts/assessment-job.md)).

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / runtime** | Python 3.11+, unchanged | existing `pyproject.toml` |
| **New dependencies** | **None.** FastAPI ≥0.112, pydantic ≥2.7, httpx, uvicorn, pytest, pytest-asyncio are all already declared | `pyproject.toml` |
| **New package** | `src/api/` — `app.py`, `deps.py`, `schemas.py`, `jobs.py`, `runner.py`, `runtime.py`, and four routers | [research.md](./research.md) R1 |
| **Surface shape** | `APIRouter` included at `prefix="/api/v1"` on the existing app — *not* `app.mount()`, whose lifespan Starlette never runs | [research.md](./research.md) R1 |
| **Modified modules** | `portal/webapp.py` (lifespan + router), `portal/admin.py` (job store replaces `_RUNNING_PORTALS`; `_final_answer` extracted), `shared/config/settings.py` (2 params + masked `as_dict`), `shared/config/validation.py` (cap ≥ 1), `shared/persistence/schema.py` (+1 table), `shared/persistence/repositories.py` (+job methods) | [data-model.md](./data-model.md) |
| **Unchanged (deliberately)** | `orchestration/scheduler.py`, `orchestration/workflow.py`, `shared/state/unit_state.py`, `shared/state/entities.py`, all of `agents/`, `review/`, `portal/assessor.py`, `portal/public.py`, every template | [research.md](./research.md) R7, R10 |
| **New configuration** | `api_key` (`AIQ_API_KEY`, default empty = access not configured), `max_concurrent_assessment_runs` (`AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS`, default 2) | [contracts/auth-and-limits.md](./contracts/auth-and-limits.md) |
| **Persistence** | One new table `assessment_jobs`, deliberately mutable for live state, following the documented `units` precedent. No migration tooling needed — `init_db` runs `CREATE TABLE IF NOT EXISTS` on every serve | [data-model.md](./data-model.md) §1, [research.md](./research.md) R3 |
| **Auth** | `X-API-Key` header, `hmac.compare_digest`, router-level dependency so no endpoint can be added unprotected | [contracts/auth-and-limits.md](./contracts/auth-and-limits.md) |
| **Concurrency** | Per unit: partial unique index. Globally: counted cap inside `BEGIN IMMEDIATE`. Both surfaces share one service | [contracts/assessment-job.md](./contracts/assessment-job.md) |
| **Testing** | `pytest` + FastAPI `TestClient` against temp-file SQLite, background runner patched — five new `tests/unit/test_api_*.py` files, no credentials or network required | [quickstart.md](./quickstart.md) |
| **Target scale** | Same pipeline volume per run; the cap bounds concurrent runs at 2 by default (~2 × `batch_size` × `assessor_agent_count` in-flight model calls) | [contracts/auth-and-limits.md](./contracts/auth-and-limits.md) §3 |

**No unresolved NEEDS CLARIFICATION.** The `/speckit-clarify` session (2026-08-18) settled seven spec-level questions; Phase 0 resolved the remaining implementation unknowns as R1–R10, including the item clarify explicitly deferred to planning (interrupted-run detection → startup sweep, R5). One clarify answer had to be **narrowed against the schema** — see "Spec amendment" below.

### Spec amendment made during planning

FR-API-010 originally said that registering the same country with a *different* portal URL creates a distinct unit. It cannot: `target_portals` declares `UNIQUE(cycle_id, country_id)` (`schema.py:37-45`) and `insert_portal` resolves conflicts with `ON CONFLICT(cycle_id, country_id) DO NOTHING` (`repositories.py:128-134`), so today that registration is **silently discarded while the portal redirects as though it succeeded**. Relaxing the constraint would break `get_portal_by_country` and `find_msq_document(cycle_id, country_id)`, both of which assume one unit per country per cycle.

[spec.md](./spec.md) was amended: the unit conflict key is `(cycle_id, country_id)` alone, independent of URL; the clarification bullet records the narrowing and why; and unit *updates* were added to Out of Scope, since changing a URL is the operation a caller would actually want here and this feature is creates-and-reads only. Full reasoning in [research.md](./research.md) R9.

### Where this fits relative to specs 001, 004, and 005

- **Spec 005** built the admin/assessor/public workflow surfaces this feature exposes headlessly, and its background-run trigger with a status view (`portal/live_prefill.py`) is what this feature makes durable and queryable. Nothing in 005's rendered behavior changes.
- **Spec 004**'s `reason_tag` on `QuestionReviewView` is exactly what FR-API-023 returns for a blocked question — reused unchanged, which is why AI results project `build_question_review()` instead of re-deriving answers (R10).
- **Spec 001**'s pipeline, resumability (`process_unit`'s "already terminal" skip), telemetry, and cost ledger are all reused verbatim; FR-API-021's resume-on-re-trigger *is* 001's resumability, exposed rather than reimplemented.

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md`, as with specs 001, 003, and 004. Following those plans' precedent, the design is gated against the spec's own non-negotiables and this codebase's tested invariants.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **Portal untouched functionally** (FR-API-002, SC-009) | Every existing portal flow behaves identically | Only `admin.py`'s run-tracking mechanism and one extracted helper change; routes, templates, and rendered states are unchanged. Full `pytest` run is the gate | PASS |
| **Append-only persistence** (spec 001 FR-062) | No UPDATE/DELETE against audit tables | `assessment_jobs` is live-progress state, not audit history — the same documented exception `units` and `update_portal_resolution` already take (R3). No existing table is mutated in a new way; the run's audit trail remains append-only `stage_events`/`cost_ledger_entries` | PASS |
| **Three terminal unit states, zero outgoing edges** (spec 001 SC-009) | `unit_state.py`'s transition table is a tested invariant | Not touched. Job state is a *separate* enum on a separate record; progress is derived from unit states, never written | PASS |
| **No silent resolution** (spec 001 FR-007/FR-033, spec 004 FR-BF-002) | Never invent an answer nobody gave | Publication reuses the extracted `_final_answer` unchanged, including its "never invents an answer" property; results return `null` + reason tag for blocked questions | PASS |
| **Configuration externalized** (spec 001 FR-072–FR-075) | No operational constant hidden in code | Both new parameters go through `Settings` + `_ENV_MAP` + `validate_settings`, appearing in `aiq config show` like every other | PASS |
| **No credentials in stored records** (spec 001 FR-110) | Secrets must not reach the database or logs | `as_dict()` masks `api_key`, closing the `configuration_snapshots` and `config show` paths — a leak `verify_no_credentials` would *not* have caught, since it scans only three telemetry tables (R6) | PASS |
| **Blind A/B integrity** (spec 005, this spec FR-API-028/029) | No cross-role read | The human-answer projection takes exactly one `role` and calls the already role-scoped `latest_human_submission`; no code path merges roles, and a role-less request is refused | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

```
src/
├── api/                              # NEW package — the entire JSON surface
│   ├── __init__.py
│   ├── app.py                        # build_api_router(database_path, settings, runtime_getter)
│   ├── deps.py                       # X-API-Key dependency (503 unconfigured / 401 bad), repo dep
│   ├── schemas.py                    # pydantic request/response models + error envelope
│   ├── runtime.py                    # AIRuntime: provider, limiter, browser, http client
│   ├── jobs.py                       # AssessmentJob store, start_assessment_job,
│   │                                 #   job_status, sweep_interrupted_jobs  (cap + idempotency)
│   ├── runner.py                     # run_assessment_job — live_prefill on the shared runtime
│   ├── identity.py                   # question_id composition (moved out of admin.py)
│   ├── finalize.py                   # _final_answer extracted from admin.py (shared, unchanged)
│   └── routers/
│       ├── cycles.py                 # cycles, questions, units  (FR-API-006..011a)
│       ├── assessments.py            # trigger, status, results  (FR-API-012..024)
│       ├── human.py                  # role-scoped submit/read   (FR-API-025..030)
│       └── publication.py            # publish, published read   (FR-API-031..034)
│
├── portal/
│   ├── webapp.py                     # MODIFIED — lifespan (init_db, sweep, AIRuntime start/stop);
│   │                                 #   include_router(build_api_router(), prefix="/api/v1")
│   ├── admin.py                      # MODIFIED — _RUNNING_PORTALS deleted; trigger and
│   │                                 #   run_in_progress go through api/jobs.py; _final_answer
│   │                                 #   and question-id composition moved out (imports back)
│   └── live_prefill.py               # MODIFIED — accepts an injected AIRuntime instead of
│                                     #   building provider/limiter/browser per run
│
└── shared/
    ├── config/
    │   ├── settings.py               # MODIFIED — +api_key, +max_concurrent_assessment_runs,
    │   │                             #   _ENV_MAP entries, as_dict() masks the secret
    │   └── validation.py             # MODIFIED — cap >= 1
    └── persistence/
        ├── schema.py                 # MODIFIED — +assessment_jobs table, +3 indexes
        └── repositories.py           # MODIFIED — insert/update/latest job, count running,
                                      #   sweep; all other methods untouched

tests/unit/
├── test_api_contract.py              # NEW — envelope, status codes, identifier round-trip
├── test_api_auth.py                  # NEW — 401/503 matrix, refused calls have no side effects
├── test_api_jobs.py                  # NEW — lifecycle, sweep, cap, idempotent double trigger
├── test_api_human_blindness.py       # NEW — zero cross-role leakage across the full matrix
└── test_api_publication.py           # NEW — score parity against the portal's own helper
```

**What is explicitly NOT touched, and why that boundary matters:**

- **`orchestration/scheduler.py`** — the highest-blast-radius file for this feature (every existing run and the whole CLI go through it). Deriving progress at read time (R7) is what keeps it untouched; a progress callback would have put this feature on the hot path of `process_unit`.
- **`shared/state/unit_state.py` and `entities.py`** — no new unit state, no new enum member. Job state is a separate concept on a separate table.
- **`agents/`, `review/`** — read-only consumers. `review/query.py::build_question_review()` is *called*, not modified (R10).
- **`portal/assessor.py`, `portal/public.py`, all templates** — the API duplicates none of their rendering; it shares their repository calls.
- **`portal/msq.py`, `review/escalations.py`, `export/`, `benchmark/`** — MSQ upload, escalation dispositions, export, and benchmarks are all out of scope; no endpoint touches them.

## Phase 0 — Research

Complete. See [research.md](./research.md). Ten decisions, each with rationale and alternatives:

| # | Decision |
|---|---|
| R1 | `APIRouter` at `/api/v1` on the existing app — a mounted sub-app's lifespan never fires in Starlette |
| R2 | One shared `AIRuntime` in the lifespan; fixes the not-actually-global per-domain rate limiter and one-Chromium-per-run |
| R3 | New, deliberately mutable `assessment_jobs` table, following the documented `units` precedent |
| R4 | Partial unique index for one-running-job-per-unit; capacity counted inside `BEGIN IMMEDIATE` |
| R5 | Interrupted runs detected by a startup sweep (single-process `uvicorn.run`), not a heartbeat |
| R6 | Secret lives in `Settings` but `as_dict()` masks it — it feeds `configuration_snapshots` and `config show` |
| R7 | Progress derived at read time from `units`; never stored, so it cannot drift and is monotonic by construction |
| R8 | Both trigger paths go through one job service; `_RUNNING_PORTALS` is deleted |
| R9 | Every create reads before writing; FR-API-010 narrowed to `(cycle, country)` against the real schema |
| R10 | Reads project `build_question_review()`; `_final_answer` is extracted, not copied, so SC-007 parity holds by construction |

## Phase 1 — Design & Contracts

Complete.

- **[data-model.md](./data-model.md)** — the `AssessmentJob` entity (DDL, fields, canonical failure causes, state transitions, four validation rules), the two configuration parameters, the four read projections (`QuestionIdentity`, `AIResultView`, `HumanAnswerView`, `PublishedResultView`), and the list of entities deliberately unchanged.
- **[contracts/rest-api.md](./contracts/rest-api.md)** — all ten capabilities as concrete endpoints with request/response bodies, the shared error envelope and its seven codes, and the identifier convention. Includes portal-parity notes (e.g. the `questionnaire_ref` rewrite on indicator add) so a cycle built through either surface reads identically.
- **[contracts/assessment-job.md](./contracts/assessment-job.md)** — `start_assessment_job` preconditions *in evaluation order* (idempotency before capacity, deliberately), the atomicity argument, background execution and terminal recording, the sweep and its single-process precondition, derived status, and the exact `portal/admin.py` before/after.
- **[contracts/auth-and-limits.md](./contracts/auth-and-limits.md)** — the key contract and its no-side-effect guarantee, `AIRuntime` composition, what is shared versus per-run and why, the lifespan sequence, and the concurrency cap with its default's justification.
- **[quickstart.md](./quickstart.md)** — eight validation scenarios mapped to the five user stories and SC-001…011; scenarios 1–6 need no credentials and no network, and only scenario 7 spends model budget.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **The startup sweep is only correct for a single serving process.** It fails *every* `running` job it finds, so a second worker's live runs would be marked `service_stopped_mid_run` while still executing | A multi-worker deployment would report healthy runs as failed and let a re-trigger race the still-running original. `aiq serve` is single-process today (`cli.py:136`, no `workers` argument), so the risk is latent, not present | Documented as a precondition in [contracts/assessment-job.md](./contracts/assessment-job.md) and R5. `tasks.md` should have the sweep log what it swept and assert single-worker operation at that point, so introducing replicas fails loudly rather than silently corrupting job state |
| **Deleting `_RUNNING_PORTALS` changes portal behavior in one visible way**: a run in progress is now derived from the database rather than process memory | Strictly an improvement (a run survives a restart in the admin view instead of appearing idle), but it is a behavior change inside the "portal unchanged" boundary of FR-API-002 | Called out here and in [contracts/assessment-job.md](./contracts/assessment-job.md)'s before/after table rather than left as a silent side effect. Sequence it as its own reviewable task so it is not buried inside the API work, and keep the admin template untouched |
| **Sharing one `BrowserSession` across concurrent runs is new usage.** Its per-fetch fresh-context isolation is documented and implemented, but it has never been exercised by two runs at once | A shared-state bug would surface as cross-unit evidence contamination — the exact thing spec 001's independence verification exists to catch | Default cap of 2 keeps concurrency low; `aiq verify independence --session …` already asserts no cross-contamination and should be run against a two-concurrent-run session as an acceptance step. Falling back to a browser-per-run is a one-line change to `AIRuntime` if needed |
| **`assessment_jobs` is a mutable table in an append-only schema** | Future readers may take it as licence to mutate audit tables | The DDL carries a comment stating the exception and pointing at the `units` precedent, matching how `upsert_unit` and `update_portal_resolution` already document themselves |
| **Masking `api_key` in `as_dict()` touches a method used by `config show`, `ConfigurationSnapshot`, and `Settings.defaults()`** | A careless mask could break the "default vs configured" source column or snapshot comparisons | Masking is value-preserving in shape (`"***"` for any non-empty secret, `""` when unset), so the effective-vs-default comparison still works; covered by a test asserting the literal secret appears in neither `config show` output nor a `configuration_snapshots` row |
| **FR-API-024's partial-results read has no natural test oracle** for "clearly marked as incomplete" | A client could mistake a partial set for a final one | The contract fixes it as an explicit `complete: bool` plus the progress pair in the envelope, and `assessed: false` per unreached question — three independent signals, each directly assertable |

## Notes

- **Branch**: work continues on `main`, matching specs 001/003/004 — no `before_plan` git hook is configured (`.specify/extensions.yml` does not exist).
- **No setup script found**: `.specify/scripts/` does not exist in this repo, so `FEATURE_SPEC`/`IMPL_PLAN`/`SPECS_DIR` were resolved from `.specify/feature.json` (`specs/007-headless-rest-api`) and the source tree was read directly, as spec 004's plan also recorded.
- **Graphify skipped.** The CLI is installed, but running it would write a `graphify-out/` artifact directory into the user's repository, and this feature's affected surface — one new package plus seven modified files — was established by targeted reads of the exact call sites (`portal/webapp.py`, `portal/admin.py`, `portal/live_prefill.py`, `orchestration/scheduler.py`, `shared/persistence/{schema,repositories}.py`, `shared/config/settings.py`, `review/query.py`, `cli.py`, `core/telemetry/verify.py`). A repo-wide structural map would not have surfaced the three findings that actually shaped this plan — the `DO NOTHING` portal insert, the `as_dict()` credential path, and Starlette's mounted-lifespan gap — since all three are semantic, not structural. Same call spec 003's and 004's plans made.

## Post-Design Constitution Re-check

Re-evaluated after [data-model.md](./data-model.md) and [contracts/](./contracts/) were written. All seven gates still PASS. Three are worth recording as *verified* rather than assumed:

- **Append-only persistence** was checked against the actual DDL and repository code, not the schema docstring's claim. `units` is genuinely upserted (`repositories.py:167-190`) and `target_portals.data` genuinely updated (`repositories.py:136-144`), both with in-code justifications of the same kind this feature's job table needs. The exception is pre-existing and documented, not invented here.
- **No credentials in stored records** was checked against `verify_no_credentials`'s real scope (`core/telemetry/verify.py:63`): it scans `fetch_records`, `stage_events`, and `cost_ledger_entries` only. Adding `api_key` to `Settings` without masking would therefore have leaked the secret into `configuration_snapshots` **with no existing check catching it**. The gate passes because of the mask, not because of the verifier.
- **Three terminal unit states** was checked to confirm the design reads `units` state and never writes it: progress derivation calls `list_units_for_portal` and counts terminal membership, and no path in `api/` calls `upsert_unit`.

Two design interactions worth recording for `tasks.md` sequencing:

1. **R8 (one trigger service) and R2 (shared runtime) both land in `portal/live_prefill.py`.** R2 changes its signature to accept an injected runtime; R8 changes who calls it and what happens to the job row afterwards. They can be implemented in either order but must land together with the `portal/webapp.py` lifespan — a shared-runtime `live_prefill` called without a started `AIRuntime` fails at `BrowserSession`'s `assert self._browser is not None`, and that failure would surface only when a real run is triggered, which the credential-free test suite deliberately never does. **Sequence the lifespan wiring before, or in the same task as, the `live_prefill` signature change**, and cover the wiring with one test that asserts the runtime is started and reachable.
2. **The R9 pre-checks and the R10 extractions are independent** and can proceed in parallel: the create endpoints need `get_cycle`/`get_question`/`get_portal_by_country` reads only, while `_final_answer` and question-id composition are pure moves out of `admin.py`. But the extractions must land before the publication and human-answer endpoints, since both reference the moved helpers — and moving `_final_answer` while `admin.py` still calls it is exactly the kind of change the existing full-suite run (SC-009) is the gate for.
