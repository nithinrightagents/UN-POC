# Contract: Detection, Round Opening, and the Cap

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](../spec.md) · **Research**: [research.md](../research.md) · **Data model**: [data-model.md](../data-model.md)

Covers FR-DR-001…009, FR-DR-030…039, FR-DR-050…059.

---

## 1. When recomputation happens

| Trigger | Call site | Exists today? | Records a comparison | May open a round |
|---|---|---|---|---|
| Portal submission | [assessor.py:184](../../../src/portal/assessor.py#L184) | **yes** | yes | no — see §2 |
| Programmatic submission | [human.py:93](../../../src/api/routers/human.py#L93) | **yes** | yes | no |
| Portal completion declaration | [assessor.py:264](../../../src/portal/assessor.py#L264) | **no — new** | yes | **yes** |
| Programmatic completion | `api/routers/completions.py` | **no — new** | yes | **yes** |
| Joint answer submitted | reconciliation route | **no — new** | yes | no (may *close* a round) |
| Seed script | [seed.py:151, :155](../../../src/portal/seed.py#L151) | **yes** | yes | yes, if it declares both completions |
| Any display | [admin.py:143](../../../src/portal/admin.py#L143), [admin.py:335](../../../src/portal/admin.py#L335) | **yes** | **never** (FR-DR-007) | never |

The two rows marked *new* are the wiring gap the originating request did not identify. The recomputation on submission was already wired everywhere; the recomputation on **completion** exists nowhere, and after this feature that is the only place a round can open. See [research.md](../research.md) R3.

Read-only display must keep calling `compute_portal_discrepancy`, never `recompute_` — SC-010 and FR-DR-007 depend on it, and the existing separation between the two functions is what makes that safe.

---

## 2. The opening decision, in evaluation order

Every recomputation records a `DiscrepancyCase`. Only some open a round.

```
1. compare → None (no overlapping answered indicators)
       → record nothing, return None                              FR-DR-003
2. record the DiscrepancyCase (rate, disputed set, compared count,
   tolerance in force)                                            FR-DR-002, 004, 005, 063
3. rate ≤ tolerance in force?
       → done. No round.                                          FR-DR-005
4. a round is already open for this unit?
       → done. Never a second concurrent round.                   FR-DR-006
5. both roles have an AssessorCompletion?
       → no  → done. Recorded and displayed, nothing opened.      FR-DR-008
6. an automatic round has already been used for this unit?
       → yes → done. Unit is in persistent discrepancy.           FR-DR-033, 036
7. open round #n, opened_by='automatic'                           FR-DR-009, 030
8. queue the EscalationQueueItem for it                           FR-DR-009
```

Step 3 uses `rate > tolerance` — strictly greater, so a rate exactly equal to the tolerance is within it (A2). This matches [discrepancy.py:44](../../../src/portal/discrepancy.py#L44) exactly and must not be "fixed" to `>=`.

Step 5 is the defect fix. Without it, steps 6–8 fire mid-assessment and consume the unit's only automatic round while an assessor still has most of the questionnaire outstanding.

Step 6 is why a disagreement appearing *after* a resolved reconciliation goes straight to persistent discrepancy rather than opening a second automatic round (FR-DR-036).

**Concurrency**: two simultaneous completion declarations can both reach step 7. The partial unique index on `(session_id, portal_id) WHERE state='open'` makes the second insert fail; the caller treats `IntegrityError` as "already open" and proceeds to step 4's outcome. Never a read-then-write check.

---

## 3. Queue-item idempotency stays, and is now belt-and-braces

The existing guard ([discrepancy.py:111-116](../../../src/portal/discrepancy.py#L111-L116)) walks unresolved escalations and suppresses a new item when `context["disagreements"]` is unchanged. Keep it. It no longer carries the whole weight — the round's open state does that — but it protects the case where a work item is disposed while a round is still open.

The queue item's `context` gains `round_id`, so the work item and the round can be correlated in both directions.

---

## 4. Closing a round

A round closes when **every indicator in the disputed set that opened it carries a joint answer** (FR-DR-026, A4). Not when both assessors have acted — either assessor may commit every joint answer, and the round completes without the peer touching it.

```
on each joint answer:
    all disputed indicators of this round now answered?
        no  → round stays open
        yes → recompute (with the overlay applied)
              rate ≤ tolerance → state = 'resolved'               FR-DR-032
              rate >  tolerance → state = 'exhausted'             FR-DR-033
              in both cases: close the work item                  FR-DR-050
```

A round also closes as `not_required` when a tolerance change brings the unit within tolerance while the round is open (FR-DR-037). It is a distinct terminal state precisely because `resolved` would claim the assessors agreed, and they did not.

`exhausted` puts the unit in persistent discrepancy. From there the system does nothing further on its own: it does not re-open, does not publish, and does not lapse (FR-DR-038). It waits.

---

## 5. The cap, stated exactly

> **At most one round per unit is ever opened by the system.** Senior Reviewer returns are unlimited and are not counted against it.

`opened_by='automatic'` may appear at most once in a unit's entire round history. `opened_by='senior_reviewer'` has no limit. `rounds_consumed` counts both, so repeated returns are visible in the record even though they are permitted (FR-DR-031, A3).

This is what makes SC-006 testable in two halves: no sequence of *submissions*, however long, produces a second automatic round; and every round after the first names a reviewer.

---

## 6. The Senior Reviewer's two dispositions

Both go through the existing `dispose_escalation` → `record_disposition` path and inherit its exactly-once guarantee ([research.md](../research.md) R7).

### `returned_for_reconciliation`

| Requirement | Behaviour |
|---|---|
| FR-DR-056 | requires a non-empty stated reason; rejected without one |
| FR-DR-056 | opens a new round, `opened_by='senior_reviewer'`, `opened_by_actor_id` = the deciding reviewer, `round_number` = prior + 1 |
| FR-DR-056 | routes both assessors back to the workspace, identically to an automatic round |
| FR-DR-039 | if that round also ends above tolerance, the unit returns to persistent discrepancy and the same two dispositions are offered again |
| Edge case | if the current disputed set is empty — the assessors have since agreed everything — there is nothing to open a round over. The return is refused with that explanation rather than creating an empty round |

### `published_unresolved`

| Requirement | Behaviour |
|---|---|
| FR-DR-057 | records who decided, when, and the still-contested indicator set |
| FR-DR-057 | each contested indicator publishes by the stated precedence rule (§8 of [data-model.md](../data-model.md)) and is marked contested, not agreed |
| A5 | the tie-break itself is unchanged. This feature makes it visible and attributable; it does not introduce a new one |

**`dispose_escalation` returns `bool` and [admin.py:409](../../../src/portal/admin.py#L409) currently discards it.** With two dispositions that lead to opposite outcomes, a `False` — meaning another reviewer already decided — must be surfaced to the caller, not redirected past as if it had succeeded.

---

## 7. Sign-off gating

Publication readiness gains exactly one condition:

> A unit with an open reconciliation round is not ready to publish, whatever its completion state. (FR-DR-059)

Everything else in [`publication_readiness`](../../../src/api/finalize.py#L35-L104) is untouched: both roles declared, none outstanding, and the same `blocking_reason` strings. The new condition adds one more reason string and is evaluated after the existing ones, so a unit blocked for both reasons reports the completion problem first — that is the one the assessors can act on.

Reconciliation never clears a completion declaration (FR-DR-058). Opening, closing, and re-opening a round leave both `AssessorCompletion` rows exactly as they were, and no assessor is asked to re-declare. This is the reason the gate is a *separate* condition rather than a revocation of readiness — revoking would have been the natural implementation and would have violated FR-DR-058 silently.
