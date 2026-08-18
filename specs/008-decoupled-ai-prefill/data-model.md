# Data Model: Decoupled AI Prefill

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Spec**: [spec.md](./spec.md) · **Research**: [research.md](./research.md)
**Created**: 2026-08-18

Two new tables, one new enum, one widened enum, two new settings, and four read projections. Everything else in the schema is reused unchanged — including `assessment_jobs`, which *is* the Prefill Run entity ([research.md](./research.md) R12).

---

## 1. `prefills` — the Prefill entity

One row per (run, question, unit). Append-only: a re-run writes new rows and never touches old ones, which is what makes FR-PF-038 structural rather than a rule someone must remember.

```sql
-- Append-only. A re-run writes a fresh row per indicator; the "current"
-- prefill is the newest row belonging to the newest COMPLETED run
-- (FR-PF-039). Never updated, never deleted.
CREATE TABLE IF NOT EXISTS prefills (
    prefill_id   TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,        -- assessment_jobs.job_id
    session_id   TEXT NOT NULL,
    cycle_id     TEXT NOT NULL,
    question_id  TEXT NOT NULL,
    portal_id    TEXT NOT NULL,
    suggested    INTEGER NOT NULL,     -- 1 = carries a suggestion, 0 = no suggestion
    data         TEXT NOT NULL,        -- the payload below
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prefills_lookup
    ON prefills(session_id, portal_id, question_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prefills_run ON prefills(run_id);
```

`suggested` is a column rather than a JSON field because FR-PF-041's summary counts by it and SC-002's coverage check groups by it; both would otherwise scan and parse every row.

### `data` payload

| Field | Type | Present when | Requirement |
|---|---|---|---|
| `answer` | bool \| null | `suggested = 1` | FR-PF-028a — exactly one, never a pair |
| `confidence` | int 0–100 \| null | `suggested = 1` | FR-PF-022, FR-PF-027 |
| `justification` | string \| null | `suggested = 1` | FR-PF-008 |
| `evidence_url` | string \| null | `suggested = 1` | FR-PF-035 |
| `supplying_source` | `LinkSource` \| null | evidence was located | FR-PF-035 |
| `agreement_outcome` | `uncontested` \| `agreed_with_gap` \| `disputed` \| `unresolved` \| null | both positions validated | FR-PF-027 |
| `confidence_gap` | int \| null | both positions validated | FR-PF-025 |
| `resolver_decision` | object \| null | `agreement_outcome = disputed` | FR-PF-026b |
| `unselected_position` | object \| null | `agreement_outcome = disputed` | FR-PF-026c, FR-PF-013 |
| `position_run_ids` | list[str] | assessment ran | audit link to `assessor_agent_runs` |
| `reason` | `PrefillReason` \| null | `suggested = 0` | FR-PF-034, FR-PF-032c |
| `terminal_state` | `UnitState` | always | FR-PF-032a |

**`reason` lives on the prefill, not in `terminal_state`** — FR-PF-032c, so the three terminal outcomes stay stable while the taxonomy grows.

**`unselected_position` is retained even though the run selected against it** (FR-PF-026c). It is a denormalised copy of the losing `AssessorAgentRun`'s answer, confidence, and justification, not a foreign key, so the assessor screen renders a contested question in one read.

### Validation rules

1. `suggested = 1` ⟺ `answer is not null` and `reason is null`. `suggested = 0` ⟺ `answer is null` and `reason is not null`. Enforced in the constructor, asserted in tests — the invariant behind SC-008.
2. `resolver_decision` and `unselected_position` are both present or both absent, and only when `agreement_outcome = disputed` (FR-PF-026a).
3. `terminal_state ∈ {delivered, unassessable, no_suggestion}` for every row a prefill run writes. `escalated` is never written (FR-PF-032a, SC-007a).
4. `terminal_state = unassessable` ⟹ `reason = no_usable_evidence` (FR-PF-032b — the outcome keeps its narrow meaning).
5. Every question in the cycle has exactly one row per completed run (FR-PF-033, SC-002).

---

## 2. `assessor_completions` — the Assessor Completion entity

```sql
-- Append-only. One row per explicit completion declaration. Completeness is
-- NOT read from this table alone -- see "Derived completeness" below.
CREATE TABLE IF NOT EXISTS assessor_completions (
    completion_id                   TEXT PRIMARY KEY,
    session_id                      TEXT NOT NULL,
    cycle_id                        TEXT NOT NULL,
    portal_id                       TEXT NOT NULL,
    role                            TEXT NOT NULL,   -- 'A' | 'B'
    actor_id                        TEXT NOT NULL,
    indicator_count_at_declaration  INTEGER NOT NULL,
    declared_at                     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_completions_lookup
    ON assessor_completions(session_id, portal_id, role, declared_at DESC);
```

`role`, `actor_id`, and `declared_at` are exactly FR-PF-005f's three required fields. `indicator_count_at_declaration` is audit only — never consulted when deciding completeness ([research.md](./research.md) R8).

### Derived completeness

```
complete(session, cycle, unit, role) :=
      EXISTS a declaration for (session, unit, role)
  AND EVERY question currently in `cycle` has a latest submission from `role`
```

The conjunction is load-bearing:

| Situation | Declaration | Coverage | Complete | Requirement |
|---|---|---|---|---|
| Every indicator answered, never declared | ✗ | ✓ | **no** | FR-PF-005f, SC-004c |
| Declared, then an answer revised | ✓ | ✓ | **yes** | FR-PF-005g |
| Declared, then a new indicator added | ✓ | ✗ | **no** | FR-PF-005e |
| Declared, then re-declared | ✓ (newest) | ✓ | **yes** | idempotent by construction |

Nothing is ever mutated to make a unit revert. That is the whole reason for deriving rather than storing.

### Validation rules

1. A declaration is refused while any indicator lacks a submission from that role; the refusal names the outstanding `question_id`s (FR-PF-005c, FR-PF-005f, SC-004b).
2. `role` must parse as `AssessorRole` — the same `InvalidRequest` path `api/routers/human.py` already uses.
3. Re-declaring is allowed and writes a new row. The newest row wins; earlier rows stay as history.

---

## 3. `UnitState` — one new terminal member

```python
class UnitState(str, Enum):
    ...
    DELIVERED     = "delivered"       # terminal
    ESCALATED     = "escalated"       # terminal — retained, no longer reachable
    UNASSESSABLE  = "unassessable"    # terminal
    NO_SUGGESTION = "no_suggestion"   # terminal — NEW

TERMINAL_UNIT_STATES = frozenset({DELIVERED, ESCALATED, UNASSESSABLE, NO_SUGGESTION})
```

### Revised transition table

| From | To (after) | Change |
|---|---|---|
| `PENDING` | `RESOLVING_LINK` | — |
| `RESOLVING_LINK` | `RESOLVED`, `UNASSESSABLE` | — |
| `RESOLVED` | `ASSESSING`, **`NO_SUGGESTION`** | `ESCALATED` removed |
| `ASSESSING` | `ADJUDICATING`, **`NO_SUGGESTION`** | `ESCALATED` removed |
| `ADJUDICATING` | `DELIVERED`, **`NO_SUGGESTION`** | `ESCALATED` and `RETRYING` removed (R4) |
| `RETRYING` | `ADJUDICATING`, **`NO_SUGGESTION`** | `ESCALATED` removed; state now unreachable |
| `DELIVERED` / `ESCALATED` / `UNASSESSABLE` / `NO_SUGGESTION` | ∅ | terminal |

`RETRYING` becomes unreachable alongside `ESCALATED` once the adjudication retry loop is bypassed (R4). Both keep their rows in `_ALLOWED` so historical units still validate.

`assert_exhaustive_terminal_coverage()` keeps its two existing assertions and **gains a third**: each of `DELIVERED`, `UNASSESSABLE`, `NO_SUGGESTION` must be reachable from `PENDING`. Without it, "every non-terminal reaches *a* terminal" would be satisfiable by a machine that only ever delivers — which is exactly what FR-PF-032d exists to prevent.

---

## 4. `PrefillReason` — new enum

```python
class PrefillReason(str, Enum):
    NO_USABLE_EVIDENCE       = "no_usable_evidence"        # FR-PF-018 → unassessable
    EVIDENCE_UNREACHABLE     = "evidence_unreachable"      # → no_suggestion
    UNSUPPORTED_LANGUAGE     = "unsupported_language"      # → no_suggestion
    ACCESS_BOUNDARY          = "access_boundary"           # → no_suggestion
    INSUFFICIENT_POSITIONS   = "insufficient_positions"    # FR-PF-028
    UNRESOLVED_DISAGREEMENT  = "unresolved_disagreement"   # FR-PF-026d
    FAILED_FINAL_VALIDATION  = "failed_final_validation"   # FR-PF-032
    ASSESSMENT_FAILURE       = "assessment_failure"        # provider/timeout
    BUDGET_REACHED           = "budget_reached"            # FR-PF-041b
```

Nine members, exactly FR-PF-034's minimum. `prefill_reason_tag()` mirrors `reason_tag()`'s contract: one template per member, `KeyError` on anything unmapped, so an added member fails in tests rather than rendering a generic label live.

`EscalationReason` is **unchanged** — it keeps its seven members for historical rows and the human-side escalation queue ([research.md](./research.md) R11).

### Where each reason arises

| Reason | Raised by | Terminal |
|---|---|---|
| `no_usable_evidence` | cascade exhausted, `resolve_link` returns `None` | `unassessable` |
| `evidence_unreachable` | assessor cannot fetch the resolved URL | `no_suggestion` |
| `unsupported_language` | majority reported language outside the allow-list | `no_suggestion` |
| `access_boundary` | `requires_authenticated_access`, or every agent hit a login wall | `no_suggestion` |
| `insufficient_positions` | fewer than 2 `VALIDATED_PASS` runs | `no_suggestion` |
| `unresolved_disagreement` | resolver returned `undetermined`, errored, or named an unknown run | `no_suggestion` |
| `failed_final_validation` | the second gate rejected the resolved position | `no_suggestion` |
| `assessment_failure` | both agents raised | `no_suggestion` |
| `budget_reached` | never dispatched — budget exhausted first | `no_suggestion` |

---

## 5. `AgreementOutcome` and `ResolverDecision` — in-memory, persisted inside `prefills.data`

Neither gets its own table. Both are per-indicator values with exactly one prefill each, so a separate table would be a 1:1 join for no gain — the same reasoning `AdjudicationDecision` already follows in `adjudication_results.data`.

```python
@dataclass(frozen=True)
class AgreementOutcome:
    kind: str                 # uncontested | agreed_with_gap | disputed | unresolved
    answer: object | None     # None only for disputed (before the resolver) and unresolved
    confidence: int | None
    confidence_gap: int       # max pairwise delta, always recorded (FR-PF-025)
    position_run_ids: list[str]

@dataclass(frozen=True)
class ResolverDecision:
    disagreement_characterization: str   # FR-PF-026b
    selected_run_id: str | None          # None ⟺ undetermined (FR-PF-026d)
    reasoning: str
    confidence: int | None
    undetermined: bool
```

`selected_run_id` must be one of `AgreementOutcome.position_run_ids`; anything else is treated as `undetermined`, which is what makes "never falls back to picking a position arbitrarily" (FR-PF-026d) a type-level property rather than a code review note.

---

## 6. `HumanAssessorSubmission` — unchanged fields, changed source

No schema change. `ai_suggested_answer` and `ai_suggestion_accepted` (FR-PF-011) keep their columns but are now populated from `latest_prefill()` instead of the `agent_index == -1` scan ([research.md](./research.md) R10). The dataclass docstring's reference to "what the heuristic pre-fill proposed" must be corrected in the same change, or it will document the opposite of what the code does.

---

## 7. Configuration

| Parameter | Env var | Default | Validation | Requirement |
|---|---|---|---|---|
| `prefill_confidence_gap_tolerance` | `AIQ_PREFILL_CONFIDENCE_GAP_TOLERANCE` | `10` | `>= 0` | FR-PF-029 |
| `prefill_run_budget` | `AIQ_PREFILL_RUN_BUDGET` | `0.0` (uncapped) | `>= 0.0` | FR-PF-041c |

Both go through `Settings` + `_ENV_MAP` + `validate_settings`, so they appear in `aiq config show` and in `configuration_snapshots` like every other parameter (spec 001 FR-072–FR-075). Neither is a secret, so neither needs `as_dict()` masking.

`prefill_confidence_gap_tolerance` defaults to `10` to match today's `per_question_confidence_threshold`, so the gap that flags a `agreed_with_gap` outcome is the same magnitude that flags `confidence_delta` today. It is a separate parameter rather than a reuse because the two now mean different things: one decides whether to *record a gap*, the other still governs `adjudicate()`'s untouched decision table.

---

## 8. Read projections

Derived at read time, never stored ([research.md](./research.md) R12).

### `PrefillView` — one per question, for the assessor screen and the API

`question_id`, `indicator_id`, `suggested`, `answer`, `confidence`, `justification`, `evidence_url`, `supplying_source`, `agreement_outcome`, `unselected_position`, `resolver_reasoning`, `reason`, `reason_text`, `run_id`, `generated_at`.

Identical for role A and role B (FR-PF-012) — it carries no role field, which is what makes the blindness guarantee structural here rather than enforced.

### `CompletionView` — per unit

`role`, `declared` (bool), `actor_id`, `declared_at`, `answered_count`, `total_indicators`, `outstanding_question_ids`, `complete` (the derived conjunction). Serves FR-PF-005h's "before declaring, see what remains" and the refusal message of FR-PF-005c.

### `PublicationReadiness` — per unit

`ready` (bool), `roles` → `CompletionView`, `blocking_reason`. Consumed by both publishers ([research.md](./research.md) R9).

### `PrefillRunSummary` — per run

`run_id`, `state`, `total_indicators`, `suggested_count`, `by_reason` (`PrefillReason` → count), `budget_in_force`, `spend_reached`. FR-PF-041 and FR-PF-041d. Grouped from `prefills` at read time.

---

## 9. Deliberately unchanged

| Entity / table | Why |
|---|---|
| `assessment_jobs` | Already the Prefill Run (R12). No DDL change; two scalars go into `data`. |
| `assessor_agent_runs`, `validation_results` | Positions and per-agent validation are unchanged (FR-PF-019–022). |
| `adjudication_results` | `adjudicate()` is not modified (R3); its rows keep their existing meaning. |
| `discrepancy_cases`, `escalation_queue_items` | Human-side only after this feature. The AI writes neither (FR-PF-002). |
| `EscalationReason` | Frozen at seven members (R11). |
| `publication_records` | Same shape; the gate changes what can reach it, not what it stores. |
| `prior_survey_links`, `msq_link_candidates`, `fetch_records`, `stage_events`, `cost_ledger_entries` | The cascade and telemetry are reused as-is. |
