# Data Model: Automated Dynamic Discrepancy Detection and Reconciliation

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](./spec.md) · **Research**: [research.md](./research.md)

Three new tables, two changed entities, one new configuration field, and one derived projection. `init_db` runs `CREATE TABLE IF NOT EXISTS` on every `aiq serve`, so no migration tooling is involved — the same property specs 007 and 008 relied on.

---

## 1. `reconciliation_rounds` — lifecycle

Mutable `state`, following the `assessment_jobs` precedent rather than the append-only audit convention. See [research.md](./research.md) R1 for why this is not a derived count.

```sql
CREATE TABLE IF NOT EXISTS reconciliation_rounds (
    round_id        TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    portal_id       TEXT NOT NULL,
    cycle_id        TEXT NOT NULL,
    round_number    INTEGER NOT NULL,      -- 1-based, per unit
    opened_by       TEXT NOT NULL,         -- 'automatic' | 'senior_reviewer'
    opened_by_actor_id TEXT,               -- NULL when opened_by = 'automatic'
    opened_reason   TEXT,                  -- required when opened_by = 'senior_reviewer'
    state           TEXT NOT NULL,         -- 'open' | 'resolved' | 'exhausted' | 'not_required'
    data            TEXT NOT NULL,         -- disputed_question_ids, rate_at_open, tolerance_at_open
    opened_at       TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reconciliation_one_open
    ON reconciliation_rounds(session_id, portal_id) WHERE state = 'open';

CREATE INDEX IF NOT EXISTS idx_reconciliation_unit
    ON reconciliation_rounds(session_id, portal_id, round_number);
```

**The partial unique index is the concurrency guarantee.** Two simultaneous completion declarations — A and B declaring within the same instant — would otherwise both observe "both declared, above tolerance, no open round" and both open a round. The index makes the second `INSERT` fail with `IntegrityError`, which the caller treats as "already open" rather than an error. This is the same mechanism `assessment_jobs` uses for its one-running-job-per-unit rule ([schema.py:341](../../src/shared/persistence/schema.py#L341)) and that `escalation_dispositions` uses for FR-049; a read-then-write check would be a regression against a guarantee this codebase already holds three times over.

### Validation rules

| Rule | Source |
|---|---|
| At most one `state='open'` row per `(session_id, portal_id)` | enforced by index |
| `opened_by='automatic'` is permitted at most once per unit across all history | FR-DR-030, checked before insert |
| `opened_by='senior_reviewer'` requires non-empty `opened_reason` and `opened_by_actor_id` | FR-DR-056 |
| `round_number` = count of prior rounds for the unit + 1 | FR-DR-031 |
| `data.disputed_question_ids` is non-empty at open | FR-DR-011; an empty set means nothing to reconcile (see edge case below) |
| `closed_at` set exactly when `state != 'open'` | — |

### State transitions

```
                      ┌──────────────────────────────────────┐
                      │                                      │
   (none) ──open──▶ open ──all disputed answered, rate ≤ tol──▶ resolved
                      │
                      ├──all disputed answered, rate > tol───▶ exhausted
                      │
                      └──tolerance raised, rate now ≤ tol────▶ not_required
```

`resolved` and `exhausted` and `not_required` are terminal. A unit re-enters `open` only through a **new row** with the next `round_number`; a closed round is never reopened. `not_required` exists for FR-DR-037 so a tolerance change closes a round as no longer needed rather than as resolved — the distinction matters because `resolved` implies the assessors agreed and `not_required` does not.

---

## 2. `joint_answers` — append-only

```sql
CREATE TABLE IF NOT EXISTS joint_answers (
    joint_answer_id TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    portal_id       TEXT NOT NULL,
    question_id     TEXT NOT NULL,
    round_id        TEXT NOT NULL,
    data            TEXT NOT NULL,   -- answer, justification, submitted_by_role, submitted_by_actor_id
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_joint_answers_once
    ON joint_answers(round_id, question_id);

CREATE INDEX IF NOT EXISTS idx_joint_answers_lookup
    ON joint_answers(session_id, portal_id, question_id);
```

**The second unique index is FR-DR-020 made structural**: exactly one joint answer per indicator per round, submitted by either assessor and binding both. It is also the resolution of the concurrent-submission edge case — both assessors opening the workspace and committing a joint answer for the same indicator at the same moment. One insert wins; the other returns `False` and the caller shows the peer's committed answer rather than overwriting it. Same shape as `record_disposition` ([repositories.py:530-546](../../src/shared/persistence/repositories.py#L530)).

It is scoped to `round_id`, not to `(session_id, portal_id, question_id)`, so a Senior Reviewer's re-opened round can settle an indicator that a previous round also settled. The overlay (§6) reads the newest.

### Validation rules

| Rule | Source |
|---|---|
| `question_id` must be in the round's `disputed_question_ids` | FR-DR-023 |
| `justification` must be present and non-empty after trimming | FR-DR-021 |
| the round must be `state='open'` | FR-DR-014 |
| originals are never updated or deleted | FR-DR-025 |

---

## 3. `tolerance_changes` — append-only

```sql
CREATE TABLE IF NOT EXISTS tolerance_changes (
    change_id       TEXT PRIMARY KEY,
    cycle_id        TEXT NOT NULL,
    previous_value  REAL,            -- NULL when the project was previously inheriting
    new_value       REAL NOT NULL,
    changed_by_actor_id TEXT NOT NULL,
    changed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tolerance_changes_cycle
    ON tolerance_changes(cycle_id, changed_at);
```

Exists because `survey_cycles` cannot hold history — `insert_cycle` is an upsert on a `cycle_id PRIMARY KEY` ([repositories.py:51-57](../../src/shared/persistence/repositories.py#L51)), destroying the previous value. FR-DR-066 requires the previous value. See [research.md](./research.md) R4.

`previous_value IS NULL` means the project was inheriting the process-wide default when the change was made, which is distinct from a previous explicit value that happened to equal the default.

---

## 4. Changed entities

### `SurveyCycle` (+1 field)

```python
discrepancy_rate_threshold: float | None = None   # None = inherit the process-wide default
```

Stored in the existing JSON `data` column, so no DDL change. `None` and `0.0` are deliberately distinct: `None` inherits, `0.0` means "any disagreement at all flags this unit" (FR-DR-065). A `float` defaulting to `0.0` would make a project that deliberately tolerates nothing indistinguishable from one that has never been configured.

### `DiscrepancyCase` (0 fields; 1 comment corrected)

No structural change. `thresholds_in_force` already carries the tolerance under which each comparison was judged ([discrepancy.py:67](../../src/portal/discrepancy.py#L67)), which is exactly FR-DR-063 — the requirement is already satisfied by the existing engine and needs only to keep being satisfied once the tolerance becomes per-project.

`scope`'s inline comment reads `# "question" | "portal"` ([entities.py:387](../../src/shared/state/entities.py#L387)) and has been wrong since `"portal_human"` was introduced. Correct it.

### `PublicationRecord` (+1 field)

```python
contested_question_ids: list[str] = field(default_factory=list)
```

FR-DR-057 requires that an indicator published over an unresolved disagreement is *marked as contested rather than presented as agreed*. `score_breakdown` records the value; this records which of those values nobody agreed on. Empty for every existing and every uncontested publication, so no backfill — consistent with spec 008's decision not to migrate an append-only public-facing table.

---

## 5. Configuration

| Parameter | Default | Scope | Env override |
|---|---|---|---|
| `human_discrepancy_rate_threshold` | `0.05` | process-wide default | `AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD` (existing) |
| `SurveyCycle.discrepancy_rate_threshold` | `None` (inherit) | per project | — (set through the portal) |

**Resolution**: `effective_tolerance(repo, cycle_id, settings)` returns the project value where set, otherwise the process-wide default. Every comparison and every display goes through it — see [research.md](./research.md) R4 for the six literal call sites that must migrate together, and why a half-migration is worse than no migration.

`human_discrepancy_rate_threshold` is added to `validate_settings`' range checks, where it has been missing since it was introduced ([research.md](./research.md) R5).

---

## 6. The joint-answer overlay

Not a table — the rule by which the three tables above combine into a rate. It belongs here because it changes what "the discrepancy rate" *means*, and every requirement about the rate depends on it.

```
for each indicator both assessors have answered:
    if a joint answer exists for this unit and indicator:
        both sides take the joint value        → counts as agreement
    else:
        compare the two latest submissions     → unchanged behaviour
```

Where multiple joint answers exist for one indicator (a Senior Reviewer's re-opened round settling it again), the newest applies.

Consequences, each of which is a spec requirement that would otherwise be unreachable:

- the rate falls as joint answers accumulate, so a round can close as `resolved` (FR-DR-032);
- the badge reaches green when every dispute is settled (FR-DR-041);
- an indicator settled jointly is no longer in the disputed set on recomputation, so a further submission does not re-open it (edge case: *an assessor changes an answer during an open reconciliation*);
- **and, deliberately, a changed original answer can put a settled indicator back into dispute** — if an assessor amends their answer after a joint answer exists, the newest submission is compared against the joint value, and if they differ the indicator disputes again. This is correct: the joint answer settled a disagreement that the amendment has re-created.

---

## 7. Derived projection: `unit_reconciliation_state`

Computed, never stored ([research.md](./research.md) R6). One function; three consumers — the badge, the assessor route, and publication readiness.

```
UnitReconciliationState:
    state                 one of the six below
    rate                  float | None          (None when not comparable)
    compared_count        int                   FR-DR-045
    disputed_question_ids list[str]
    tolerance_in_force    float                 FR-DR-043
    rounds_consumed       int                   FR-DR-031
    automatic_round_used  bool                  FR-DR-030
    open_round_id         str | None
```

| State | Condition | Badge (FR-DR-041/042) | Routes assessors to workspace? |
|---|---|---|---|
| `awaiting_second_assessment` | no overlapping answers | neutral, "awaiting second assessment", no rate (FR-DR-044) | no |
| `full_consensus` | rate == 0 | green + check icon | no |
| `within_tolerance` | 0 < rate ≤ tolerance | amber, names the tolerance in force | no |
| `above_tolerance_in_progress` | rate > tolerance, not both declared | red + "assessment in progress" | **no** (FR-DR-008) |
| `reconciliation_open` | an open round exists | red + "reconciliation open" | **yes** (FR-DR-010) |
| `persistent_discrepancy` | rate > tolerance, automatic round used, no open round | red + "reconciliation exhausted", visually and textually distinct | **no** (FR-DR-035) |

Ordering matters: `reconciliation_open` is checked before `persistent_discrepancy`, and both before the rate bands, so a re-opened round presents as open rather than exhausted.

Colour is never the only signal — each state carries text and an icon (FR-DR-042), which is also what keeps the zero-emoji and contrast gates satisfiable ([research.md](./research.md) R11).

---

## 8. Publication precedence

`final_answer`'s chain, with the new term in **bold**:

1. Senior Reviewer arbitration for this indicator (`resolved_answers` on a disposition) — unchanged, [discrepancy.py:136-160](../../src/portal/discrepancy.py#L136)
2. **joint answer for this indicator** — new (FR-DR-051)
3. A and B agree — unchanged
4. exactly one assessor answered — unchanged
5. they differ and nothing settled it — **still returns A's answer, now recorded as contested** (FR-DR-057, A5)

`final_answer` keeps its `bool | None` signature; both publishers depend on it and spec 008's parity guarantee rests on them sharing it. A new `final_answer_detail()` returns the same value plus which of the five terms produced it, and the publish path uses it to fill `contested_question_ids`. The published score is arithmetically unchanged — this is a labelling change, not a scoring one.

---

## 9. Entities deliberately unchanged

| Entity | Why it stays as it is |
|---|---|
| `HumanAssessorSubmission` | joint answers are additive; originals must stay readable (FR-DR-025) and untouched (R2's rejected alternative) |
| `AssessorCompletion` | a round never invalidates a declaration (FR-DR-058) |
| `EscalationQueueItem` / `EscalationReason` | `PORTAL_DISCREPANCY` still names the work item; the round is the state beside it, not a replacement. No new reason value |
| `escalation_dispositions` | its `UNIQUE(item_id)` guarantee is reused for both reviewer dispositions (R7) |
| `UnitState` / `TERMINAL_UNIT_STATES` | reconciliation is a human-side lifecycle and never touches the AI pipeline's state machine |
| `Prefill` | the AI path is out of scope by design |
