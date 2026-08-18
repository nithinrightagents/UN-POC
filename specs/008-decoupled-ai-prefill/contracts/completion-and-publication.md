# Contract: Mandatory Completion and Publication

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Spec**: [spec.md](../spec.md) · **Research**: [research.md](../research.md) · **Data model**: [data-model.md](../data-model.md)

The human side of the decoupling. The AI leaves the publication precedence chain; mandatory completion is what makes that safe rather than merely principled.

---

## 1. The precedence chain, before and after

```python
# BEFORE — src/api/finalize.py
a, b = latest_human_submission(A), latest_human_submission(B)
if a and b:
    if a.answer == b.answer:      return a.answer
    resolved = find_resolved_answer(...)
    if resolved is not None:      return resolved
    return a.answer                                    # placeholder
if a:                             return a.answer
if b:                             return b.answer
if unit delivered and consensus:  return consensus_answer     # ← AI fallback 1
if heuristic rows exist:          return last.answer          # ← AI fallback 2
return None
```

```python
# AFTER
a, b = latest_human_submission(A), latest_human_submission(B)
if a and b:
    if a.answer == b.answer:      return a.answer
    resolved = find_resolved_answer(...)
    if resolved is not None:      return resolved
    return a.answer                                    # placeholder, unchanged
if a:                             return a.answer
if b:                             return b.answer
return None                                            # both AI branches deleted
```

Two branches deleted, nothing else touched. This supersedes the final term of `specs/007-headless-rest-api/spec.md` FR-API-032 (FR-PF-005).

**Why removing them is safe now and was not before.** `final_answer` returning `None` used to mean "this question is silently dropped from the score's denominator". Under the completion gate a unit cannot be published while any indicator lacks an answer from a required role, so `None` is unreachable at publication time. The function keeps returning `None` — it is a real state during assessment — but no publisher can observe it.

**The function's stated property is preserved.** Its docstring's "never invents an answer nobody gave" now holds absolutely rather than nearly: previously the AI fallbacks were exactly the case where it *did*.

---

## 2. `publication_readiness`

```python
@dataclass(frozen=True)
class RoleCompletion:
    role: str                     # 'A' | 'B'
    declared: bool
    actor_id: str | None
    declared_at: str | None
    answered_count: int
    total_indicators: int
    outstanding_question_ids: list[str]
    complete: bool                # declared AND not outstanding

@dataclass(frozen=True)
class PublicationReadiness:
    ready: bool                   # every required role complete
    roles: dict[str, RoleCompletion]
    blocking_reason: str | None

def publication_readiness(repo, session_id, cycle_id, portal_id) -> PublicationReadiness
```

Lives in `src/api/finalize.py` beside `final_answer`, so both publishers import from one module ([research.md](../research.md) R9).

**Required roles are A and B**, both. The precedence chain reads both, so a unit with only one role's answers is a half-assessed unit whatever its coverage looks like.

**`blocking_reason` names what is missing**, never a generic refusal:

| Situation | `blocking_reason` |
|---|---|
| Role B never declared | `Assessor B has not declared their assessment complete.` |
| Role A declared, then an indicator was added | `Assessor A has 1 indicator outstanding: c-2024:2.3.4.` |
| Neither role declared | `Assessors A and B have not declared their assessment complete.` |

The outstanding list is truncated in the message and returned in full in `roles`, so a UI can render either.

---

## 3. Declaring completion

### Preconditions, in evaluation order

1. Cycle exists → else `404`.
2. Unit exists in that cycle → else `404`.
3. `role` parses as `AssessorRole` → else `400`.
4. **Every question currently in the cycle has a latest submission from `role`** → else refuse, naming the outstanding `question_id`s (FR-PF-005c, FR-PF-005f, SC-004b).

Order matters: identity errors are reported before completeness, so a caller with a typo'd unit id is told that rather than being handed a list of 111 outstanding indicators.

### Effect

Writes one `assessor_completions` row with `role`, `actor_id`, `declared_at`, and `indicator_count_at_declaration`. Re-declaring is permitted and writes another row; the newest wins. No existing row is ever updated or deleted.

### What it does *not* do

- It does not record any answer. A declaration over a unit where the assessor accepted every prefill without acting on it is impossible, because condition 4 requires a real submission per indicator (FR-PF-009a).
- It does not freeze the unit. Revising an answer afterwards is allowed and keeps the unit complete (FR-PF-005g) — coverage stays satisfied because the revision is itself a submission.

---

## 4. Publishing

### Preconditions

1. Cycle and unit exist → else `404`.
2. `publication_readiness(...).ready` → else refuse with `blocking_reason` (`409` on the API, a re-rendered admin page with the message on the portal).

### Effect — arithmetic unchanged

```python
breakdown = {q.question_id: final_answer(...) for q in questions}   # no None survives the gate
score = sum(breakdown.values()) / len(breakdown)
```

`len(breakdown) == len(questions)` always, once the gate passes. That is SC-004a: every published score is computed over the full indicator set, so two units are comparable in one ranking table.

**Neither publisher's formula changes.** [admin.py:224](../../../src/portal/admin.py#L224) and [publication.py](../../../src/api/routers/publication.py) keep the code they have; only what can reach them changes. SC-013's identical-score guarantee therefore holds because both call the same two shared functions, not because a test compares them ([research.md](../research.md) R9).

---

## 5. The assessor screen

| Element | Behaviour | Requirement |
|---|---|---|
| Per-question suggestion | prefill answer, confidence, justification, evidence URL, supplying source | FR-PF-008, FR-PF-035 |
| Contested question | the unselected position and the resolver's characterization shown alongside the one suggestion | FR-PF-013, FR-PF-026c |
| No-suggestion question | the reason text from `prefill_reason_tag()`, empty answer field | FR-PF-008, SC-008 |
| No prefill at all | empty suggestion area, workflow otherwise identical | FR-PF-007 |
| Departing from the suggestion | no confirmation, no justification field, no approval | FR-PF-009, SC-003 |
| Progress indicator | answered / total, with outstanding indicators listed | FR-PF-005h |
| Complete button | disabled while any indicator is outstanding; the refusal names them | FR-PF-005c, SC-004b |
| Role isolation | the prefill carries no role field and is rendered identically to A and B; neither role's submissions are read while rendering the other's | FR-PF-012, FR-PF-046 |

**No "accept all" control**, and no default acceptance on completion — both are Out of Scope and FR-PF-009a respectively. The completion action reads submissions; it never creates them.

---

## 6. Seed and demo data

The gate applies to seeded data too. [seed.py](../../../src/portal/seed.py) and [seed_demo.py](../../../src/review/seed_demo.py) publish units today; after this change those publishes refuse unless the seeds also write:

1. Submissions from **both** roles for **every** question on each unit they publish.
2. An `assessor_completions` row per role per published unit.
3. `prefills` rows in place of the `agent_index == -1` heuristic rows, or the demo assessor screen shows empty suggestions ([research.md](../research.md) R10).

This is a real task with a real chance of being discovered late, because the seeds are not part of the unit test suite. The quickstart's scenario 8 exists to catch it.

---

## 7. Existing published records

`data/aiq.db` holds 2 `publication_records` written under the old precedence chain, against 1073 human submissions. They are append-only history and are **not** rewritten: the public surface reads the latest row per (cycle, portal), so a republish under the new rules supersedes them naturally.

Whether to republish is an operational decision, not a requirements one. What matters for planning is that no migration step is required and none should be written — a backfill would be the only mutation of an append-only audit table in the codebase.
