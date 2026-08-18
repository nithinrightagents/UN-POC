# Data Model: Headless Assessment REST API

**Feature Directory**: `specs/007-headless-rest-api`
**Spec**: [spec.md](./spec.md) · **Research**: [research.md](./research.md)

One new persisted entity (`AssessmentJob`), two new configuration parameters, and four read-only projections over data that already exists. Nothing else in the schema changes, and no existing table's columns are altered.

---

## 1. New persisted entity — `AssessmentJob`

One row per *trigger attempt* against one unit. A re-trigger inserts a new row; rows are updated in place only for `state`, `failure_cause`, and `updated_at` (see [research.md](./research.md) R3 for why this documented exception to the append-only doctrine is the same category as the existing `units` upsert).

### DDL — appended to `DDL` in `src/shared/persistence/schema.py`

```sql
CREATE TABLE IF NOT EXISTS assessment_jobs (
    job_id           TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    cycle_id         TEXT NOT NULL,
    portal_id        TEXT NOT NULL,
    state            TEXT NOT NULL,            -- 'running' | 'done' | 'failed'
    questions_total  INTEGER NOT NULL,         -- snapshot at trigger time (R7)
    failure_cause    TEXT,                     -- NULL unless state='failed'
    triggered_by     TEXT NOT NULL,            -- 'api' | 'portal'
    data             TEXT NOT NULL,            -- JSON: terminal outcome counts, actor
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- At most one running job per unit: makes FR-API-014 a storage invariant, so
-- two simultaneous triggers resolve atomically rather than by a memory check.
CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_jobs_one_running
    ON assessment_jobs(portal_id) WHERE state = 'running';

CREATE INDEX IF NOT EXISTS idx_assessment_jobs_unit
    ON assessment_jobs(cycle_id, portal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_assessment_jobs_state
    ON assessment_jobs(state);
```

### Fields

| Field | Type | Rule | Source requirement |
|---|---|---|---|
| `job_id` | `str` | `new_id("job")`, returned to the client as its job reference | FR-API-013 |
| `session_id` | `str` | Always `session_id_for_cycle(cycle_id)` — the cycle's single long-lived session | existing `portal/common.py` |
| `cycle_id`, `portal_id` | `str` | Must reference an existing cycle and unit; the unit must have a non-empty `resolved_url` | FR-API-015 |
| `state` | enum | Exactly `running` \| `done` \| `failed`. No `interrupted`, no `pending` | FR-API-018, FR-API-014a |
| `questions_total` | `int` | `len(repo.list_questions(cycle_id))` at trigger; must be ≥ 1 or the trigger is refused | FR-API-015, FR-API-016 |
| `failure_cause` | `str \| None` | Non-null iff `state='failed'`. Canonical values below | FR-API-018, FR-API-020 |
| `triggered_by` | enum | `api` \| `portal` — which surface started it, so operators can attribute spend | FR-API-002, SC-010 |
| `data` | JSON | Terminal outcome counts from `BatchRunSummary` (delivered/escalated/unassessable) once finished; the acting actor id | FR-API-020 |
| `created_at`, `updated_at` | ISO ts | `updated_at` moves on every state change | FR-API-016 |

**Not a field**: `questions_completed`. Progress is derived on read (R7) so it cannot drift from `units`.

### Canonical `failure_cause` values

| Value | Meaning |
|---|---|
| `service_stopped_mid_run` | Written by the startup sweep (R5) — the process running it no longer exists |
| `pipeline_error` | `run_batch` raised; the exception summary goes in `data.error` |
| `ai_provider_unavailable` | Model provider or credentials unusable — the spec's dedicated edge case |

### State transitions

```
                    (trigger accepted)
                            │
                            ▼
                        running ──────────────► done      (run_batch returned)
                            │
                            ├──────────────────► failed    (run_batch raised)
                            │
                            └──────────────────► failed    (startup sweep: service_stopped_mid_run)

  absent  ──►  "never triggered" (FR-API-019) — distinct from every state above
```

Terminal states (`done`, `failed`) never transition again; recovery is a **new row** from a re-trigger (FR-API-021), which is why per-attempt history survives.

### Validation rules

1. A row may not be inserted in a terminal state (every job starts `running`).
2. `INSERT` is refused by `idx_assessment_jobs_one_running` when that unit already has a running job → caller catches `IntegrityError`, re-reads, and returns the existing job (FR-API-014).
3. `INSERT` is refused by the service when `COUNT(*) WHERE state='running' >= settings.max_concurrent_assessment_runs`, counted inside the same `BEGIN IMMEDIATE` transaction (FR-API-014a).
4. Rule 2 is evaluated *before* rule 3: an idempotent re-trigger of an already-running unit succeeds at capacity, because it starts nothing.

---

## 2. New configuration parameters

Added to the `Settings` dataclass and `_ENV_MAP` in `src/shared/config/settings.py`.

| Field | Env var | Default | Validation | Requirement |
|---|---|---|---|---|
| `api_key` | `AIQ_API_KEY` | `""` (empty = programmatic access not configured) | none — empty is a supported portal-only deployment | FR-API-035, FR-API-039 |
| `max_concurrent_assessment_runs` | `AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS` | `2` | must be ≥ 1; `validate_settings` raises `ConfigurationError` otherwise | FR-API-014a |

**`as_dict()` masks `api_key`** — returns `"***"` when non-empty. Mandatory, not cosmetic: `as_dict()` feeds `ConfigurationSnapshot` rows written to the database (`cli.py:287`) and the `aiq config show` table, and `verify_no_credentials` does not scan `configuration_snapshots`. See [research.md](./research.md) R6.

---

## 3. Read-only projections (no new storage)

### 3.1 `QuestionIdentity`

The single identifier rule of FR-API-011a, made concrete.

| Field | Derivation |
|---|---|
| `question_id` | The stored primary key, `f"{cycle_id}:{indicator_id}"` — *the* identifier for every question-scoped request and response |
| `indicator_id` | The bare code (`Question.indicator_id`), display only |

The prefixing currently lives inline in `portal/admin.py:150-154`. It moves to one shared helper so the API and portal cannot diverge; both then satisfy "identifiers returned by the interface are accepted back unchanged".

### 3.2 `AIResultView` — per question, projected from `review/query.py::build_question_review()`

| Field | Source on `QuestionReviewView` | Note |
|---|---|---|
| `question_id`, `indicator_id` | §3.1 | |
| `answer` | `delivered_answer` | `null` for a blocked question (FR-API-023) |
| `confidence` | `consensus_confidence` | `null` when never assessed |
| `justification` | `justification` | |
| `evidence_url` | `evidence.url` if present else `resolved_url` | `evidence_missing` reported alongside |
| `blocked` / `blank_reason` | `escalated`, `reason_tag` | spec 004's reason tag verbatim (FR-API-023) |
| `assessed` | derived from unit state | separates "not yet reached" from "answered null" |

The envelope adds `complete: bool` and the derived progress pair, so a caller reading mid-run cannot mistake a partial set for a final one (FR-API-024).

### 3.3 `HumanAnswerView` — role-scoped, one role per response

| Field | Source |
|---|---|
| `question_id`, `indicator_id` | §3.1 |
| `answered` | whether `latest_human_submission(session, question, portal, role)` exists |
| `answer`, `evidence_url`, `notes`, `actor_id`, `submitted_at` | that submission (`null` when `answered` is false) |

**Invariant**: the projection is built from a single `role` argument and no code path merges two roles (FR-API-028/029, SC-006). The repository already supports exactly this shape — `latest_human_submission(..., role)` — and the assessor portal relies on the same scoping.

### 3.4 `PublishedResultView`

| Field | Source |
|---|---|
| `published` | whether `latest_publication(cycle_id, portal_id)` exists — `false` is *not* a zero score (FR-API-034) |
| `score`, `published_by`, `published_at`, `publication_id` | `PublicationRecord` |
| `breakdown[]` | `score_breakdown` mapped to `{question_id, indicator_id, final_answer}` |

Publication itself reuses the extracted `_final_answer` precedence unchanged, which is what makes SC-007's parity with the portal a property of the design rather than a test that happens to pass.

---

## 4. Entities deliberately unchanged

| Entity | Why untouched |
|---|---|
| `units`, `assessor_agent_runs`, `validation_results`, `adjudication_results` | The pipeline's own records. This feature reads them; it never writes or reshapes them |
| `human_assessor_submissions` | New submissions use the existing `HumanAssessorSubmission` dataclass and `insert_human_submission` verbatim, including the AI-suggestion linkage fields, so a submission is indistinguishable by origin (FR-API-027) |
| `publication_records` | Written through existing `insert_publication`; append-only republish semantics already give FR-API-033's "most recent wins" |
| `survey_cycles`, `questions`, `target_portals` | Same dataclasses, same insert methods. Only the *pre-check* is new (R9) |
| `assessment_sessions` | One session per cycle via `ensure_session`; jobs reference it, never replace it |
| `unit_state.py` transition table | Untouched — spec 001's exhaustive-terminal-coverage invariant stands |
