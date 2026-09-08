# Data Model: Disagreement Labelling for Human Assessor Discrepancies

**Feature Directory**: `specs/017-disagreement-labelling`
**Spec**: [spec.md](./spec.md) · **Research**: [research.md](./research.md)
**Created**: 2026-09-07

Three new tables, two new enums, three new dataclasses, one new configuration group. **No existing entity gains a field, and no existing table changes.** Everything this feature knows lives in its own tables, which is what makes it removable.

---

## 1. `labelling_passes` — one row per unit, the once-guard

```sql
CREATE TABLE IF NOT EXISTS labelling_passes (
    pass_id     TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    portal_id   TEXT NOT NULL,
    cycle_id    TEXT NOT NULL,
    data        TEXT NOT NULL,   -- disputed_question_ids, compared_count, dispatched_by, model_configured
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_labelling_pass_once
    ON labelling_passes(session_id, portal_id);

CREATE INDEX IF NOT EXISTS idx_labelling_pass_cycle
    ON labelling_passes(cycle_id, created_at);
```

The unique index **is** FR-DL-007. Dispatch attempts the insert and treats `IntegrityError` as "already ran", rather than reading first and then writing — the same technique `joint_answers` and `record_disposition` use for their own once-only guarantees.

`data.disputed_question_ids` freezes the disputed set as it stood at completion. Everything downstream works from this list, not from a fresh `_compare`, so a later joint answer or amendment cannot silently change what the pass was supposed to cover.

### Validation rules

| Rule | Enforcement |
|---|---|
| At most one pass per unit | `idx_labelling_pass_once` |
| A pass is only created when both roles have declared completion | `dispatch_labelling_pass` precondition (FR-DL-006) |
| A pass is not created when there are no disputes | precondition — nothing to label |
| A pass is not created when labelling is disabled or no provider is configured | precondition (R6) — the unit stays *never labelled*, not *exhausted* |

---

## 2. `disagreement_labels` — append-only, the audit record

```sql
CREATE TABLE IF NOT EXISTS disagreement_labels (
    label_id     TEXT PRIMARY KEY,
    pass_id      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    portal_id    TEXT NOT NULL,
    question_id  TEXT NOT NULL,
    label        TEXT NOT NULL,   -- DisagreementLabel enum value
    data         TEXT NOT NULL,   -- provenance + per-side observations, see below
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_disagreement_label_once
    ON disagreement_labels(pass_id, question_id);

CREATE INDEX IF NOT EXISTS idx_disagreement_label_unit
    ON disagreement_labels(session_id, portal_id);

CREATE INDEX IF NOT EXISTS idx_disagreement_label_question
    ON disagreement_labels(question_id, label);
```

`label` is a real column rather than a JSON field because every aggregate in the feature groups by it — the ambiguity measure (FR-DL-070), the per-unit composition (FR-DL-061), the insufficient-notes proportion (FR-DL-074).

`data` carries:

| Key | Purpose | Requirement |
|---|---|---|
| `established_by` | `"deterministic"` or `"classifier"` | FR-DL-051, FR-DL-091 |
| `model_identity` | `"vertexai/gemini-2.5-flash-lite"`, or absent when deterministic | FR-DL-050, FR-DL-051 |
| `prompt_version` | e.g. `"dl-1"`, absent when deterministic | FR-DL-050 |
| `input_digest` | SHA-256 over the exact rendered classifier input | FR-DL-050, FR-DL-056 |
| `stated_reason` | one short sentence from the classifier, or the deterministic rule that fired | FR-DL-050 |
| `observations` | `{"A": [...], "B": [...]}` of `SideObservation` values | FR-DL-062 |
| `submission_ids` | `{"A": ..., "B": ...}` — which two submissions were compared | FR-DL-068 |
| `interval_seconds` | gap between the two submissions | FR-DL-036, A6 |

`submission_ids` is what makes FR-DL-068 checkable: a surface compares them against the unit's current latest submissions and, where they differ, says the submission has changed since labelling.

### Validation rules

| Rule | Enforcement |
|---|---|
| One label per dispute per pass | `idx_disagreement_label_once` |
| `label` is a member of `DisagreementLabel` | parse-time check before insert (FR-DL-035) |
| Deterministic labels name no model | invariant test — `established_by == "deterministic"` implies `model_identity` absent (FR-DL-051) |
| A classifier label is one of the four it may choose | parse-time check, narrower than the enum (FR-DL-033) |
| No UPDATE or DELETE ever issued | invariant test greps the module for `UPDATE disagreement_labels` (FR-DL-054) |

---

## 3. `labelling_attempts` — append-only, one row per failure

```sql
CREATE TABLE IF NOT EXISTS labelling_attempts (
    attempt_id   TEXT PRIMARY KEY,
    pass_id      TEXT NOT NULL,
    question_id  TEXT NOT NULL,
    failure      TEXT NOT NULL,   -- 'provider_error' | 'invalid_response' | 'schema_rejected'
    data         TEXT NOT NULL,   -- error class, truncated detail; never the raw prompt
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_labelling_attempt_dispute
    ON labelling_attempts(pass_id, question_id);
```

Only *unsuccessful* attempts are recorded. A success writes a `disagreement_labels` row and nothing here, so `COUNT(*)` on this table is exactly the attempt count FR-DL-057 caps at three.

A response naming a label outside the applicable set is `schema_rejected` and **counts as an attempt** — the spec's edge case says so explicitly, and it prevents a model stuck in a bad output mode from looping.

### Derived state (no status column anywhere)

```
never_labelled  := no labelling_passes row for (session_id, portal_id)
awaiting        := pass row ∧ no label row ∧ attempts < 3
established     := label row exists
exhausted       := pass row ∧ no label row ∧ attempts = 3
```

`unit_labelling_state(repo, session_id, portal_id)` returns this projection per disputed question. It is the single reader for every surface, so the four states cannot drift apart between templates (the `unit_reconciliation_state` pattern from spec 012).

---

## 4. Enums — added to `src/shared/state/entities.py`

```python
class DisagreementLabel(str, Enum):
    """How two assessor positions relate. Never a verdict on which is correct."""
    DIFFERENT_SOURCES  = "different_sources"    # "Used different sources"
    ONE_FOUND_NOTHING  = "one_found_nothing"    # "One found nothing"
    ONE_BLOCKED        = "one_blocked"          # "One couldn't access"
    DIFFERENT_CONTENT  = "different_content"    # "Saw different things"
    DIFFERENT_JUDGEMENT = "different_judgement" # "Judged differently"
    NOT_ENOUGH_NOTES   = "not_enough_notes"     # "Not enough notes"


class SideObservation(str, Enum):
    """An observation about one submission, attributed to that side only."""
    NOTES_CONTRADICT_ANSWER = "notes_contradict_answer"
    ACCEPTED_AI_UNCHANGED   = "accepted_ai_unchanged"
    NO_NOTES                = "no_notes"
```

Two subsets matter and are named constants, not comments:

```python
DETERMINISTIC_LABELS = {DIFFERENT_SOURCES, ONE_FOUND_NOTHING}   # FR-DL-031, FR-DL-032
CLASSIFIER_LABELS    = {ONE_BLOCKED, DIFFERENT_CONTENT,
                        DIFFERENT_JUDGEMENT, NOT_ENOUGH_NOTES}  # FR-DL-033
```

The two sets are disjoint and their union is the enum — asserted in a test, so adding a label without deciding how it is established fails immediately.

Badge text lives in one mapping beside the enum. The English string is presentation, and the stored value is the enum, so re-wording a badge never rewrites history.

---

## 5. Dataclasses

```python
@dataclass
class LabellingPass:
    pass_id: str
    session_id: str
    cycle_id: str
    portal_id: str
    disputed_question_ids: list[str]
    compared_count: int
    dispatched_by: str                    # 'portal' | 'api' | 'cli'
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class DisagreementLabelRecord:
    label_id: str
    pass_id: str
    session_id: str
    portal_id: str
    question_id: str
    label: DisagreementLabel
    established_by: str                   # 'deterministic' | 'classifier'
    input_digest: str
    stated_reason: str
    observations: dict[str, list[SideObservation]]
    submission_ids: dict[str, str]
    interval_seconds: int | None = None
    model_identity: str | None = None
    prompt_version: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class LabellingAttempt:
    attempt_id: str
    pass_id: str
    question_id: str
    failure: str                          # 'provider_error' | 'invalid_response' | 'schema_rejected'
    detail: str = ""
    created_at: datetime = field(default_factory=utcnow)
```

---

## 6. The classifier input, and its digest

The digest is taken over the rendered input, not over the source rows, so it attests to what the model actually saw (FR-DL-056). The rendered input is canonical JSON with sorted keys:

```json
{
  "prompt_version": "dl-1",
  "indicator_text": "...",
  "positions": [
    {"answer": true,  "evidence_url": "...", "notes": "...", "accepted_ai_suggestion": false},
    {"answer": false, "evidence_url": "...", "notes": "...", "accepted_ai_suggestion": null}
  ],
  "interval_seconds": 86400
}
```

**Position order is content-derived, never role-derived** (R7): sort the two positions by `(evidence_url or "", notes or "")`. Ties are impossible in practice — two positions identical in URL and notes but differing in answer would sort stably and carry no role signal either way.

**What is absent is a requirement, not an omission.** No `role`, no `assessor_actor_id`, no `Prefill.answer`, no `Prefill.justification`, no `ai_suggested_answer`. Only `ai_suggestion_accepted` survives, as a bare boolean (D3, FR-DL-037, FR-DL-038). FR-DL-039 makes this object's shape the closed definition of what leaves the platform, so widening it requires changing the spec.

---

## 7. The deterministic pre-pass

```
same_source(url_a, url_b):
    ha, hb := normalise_host(url_a), normalise_host(url_b)
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)

classify_deterministically(a, b):
    if a.evidence_url and b.evidence_url and not same_source(a, b):
        return DIFFERENT_SOURCES                    # FR-DL-031
    if bool(a.evidence_url) != bool(b.evidence_url):
        return ONE_FOUND_NOTHING                    # FR-DL-032
    return None                                     # → classifier, FR-DL-033
```

`normalise_host` lowercases, strips userinfo and port (reusing the [admissibility.py:32](../../src/shared/tools/linkresolution/admissibility.py#L32) logic), strips a leading `www.` and a trailing dot. An unparseable URL yields an empty host and is treated as no evidence cited — the spec's edge case, and the reason the `bool(...)` test comes second.

See [research.md](./research.md) R4 for why this is not eTLD+1 and why the spec's wording should be corrected.

---

## 8. Per-side observations

| Observation | Source | Model involved |
|---|---|---|
| `NO_NOTES` | `notes` is absent or whitespace | no |
| `ACCEPTED_AI_UNCHANGED` | `ai_suggestion_accepted is True` | no |
| `NOTES_CONTRADICT_ANSWER` | classifier response, per position | yes |

Two of the three are free and are recorded even when the label is deterministic or the classifier fails — a dispute that is `exhausted` still carries its `NO_NOTES` and `ACCEPTED_AI_UNCHANGED` observations, because they were never in doubt. Observations are keyed by role in storage (FR-DL-062) and mapped back from position index by the caller, which is the only party that knows the mapping.

The spec's edge case where both sides carry `ACCEPTED_AI_UNCHANGED` on one indicator is recorded as a data fault rather than labelled: `dispatch_labelling_pass` logs it and stores the observations, and the dispute proceeds to labelling normally.

---

## 9. Configuration

Added to `Settings` ([settings.py:33](../../src/shared/config/settings.py#L33) neighbourhood) and to the `AIQ_*` env mapping:

| Setting | Default | Env var |
|---|---|---|
| `disagreement_labelling_enabled` | `True` | `AIQ_DISAGREEMENT_LABELLING_ENABLED` |
| `disagreement_label_model` | `"gemini-2.5-flash-lite"` | `AIQ_DISAGREEMENT_LABEL_MODEL` |
| `disagreement_label_temperature` | `0.0` | `AIQ_DISAGREEMENT_LABEL_TEMPERATURE` |

`LABEL_PROMPT_VERSION` is a module constant, not a setting — it identifies the instruction text, so it must change with the text and cannot be an operator's choice.

Disabling labelling suppresses dispatch only. Existing labels remain readable and every surface renders them, because a stored label is history and does not depend on the feature being switched on.

---

## 10. Entities deliberately unchanged

`HumanAssessorSubmission`, `AssessorCompletion`, `DiscrepancyCase`, `EscalationQueueItem`, `JointAnswer`, `ReconciliationRound`, `SurveyCycle`, `Question`, `Prefill`, `PublicationRecord`, `UnitState`, `TERMINAL_UNIT_STATES`.

`DiscrepancyCase` in particular gains no label field. A case is the numeric record; putting a label on it would make the two travel together and invite a future reader to compute one from the other.
