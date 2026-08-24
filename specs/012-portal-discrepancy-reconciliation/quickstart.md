# Quickstart: Validating Discrepancy Detection and Reconciliation

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

Ten scenarios. **Every one runs offline** — no credentials, no network, no model calls. This feature touches only the human A/B path, which has no AI in it; that is the same boundary the spec draws in Out of Scope, and it makes the whole suite cheap to run.

## Prerequisites

```bash
pip install -e ".[dev]"
pytest -q                       # baseline: everything green BEFORE any change
```

The baseline matters here for a specific reason. `src/portal/discrepancy.py` has **no test file today** ([research.md](./research.md) R10), and this feature modifies `_compare()` — the function all four of its public entry points flow through. Scenario 0 exists to close that gap before the change, so a regression and a new behaviour are distinguishable in the diff.

---

## Scenario 0 — Characterise the engine before touching it

*Covers the existing behaviour this feature builds on · A1, A2*

```bash
pytest tests/unit/test_portal_discrepancy.py -q     # NEW FILE — write this first
```

Written against the **unchanged** engine, and green before any other work starts.

**Expect**

- No overlapping answered indicator → `None`, and nothing written.
- Rate is computed over the intersection only; indicators one assessor has not answered are excluded, not counted as disagreements (A1).
- `rate == threshold` is **within** tolerance; only `rate > threshold` flags (A2). Test 0.05 exactly against a 5% tolerance.
- `compute_portal_discrepancy` writes nothing: row counts in `discrepancy_cases` and `escalation_queue_items` unchanged after 50 calls.
- `recompute_portal_discrepancy` writes a case on every call with overlap, and a queue item only when flagged.
- The idempotency guard: two flagged recomputations with the same disagreement set produce one queue item, a different set produces two.
- `find_resolved_answer` returns the **newest** covering item's arbitration, not an older one ([discrepancy.py:144-149](../../src/portal/discrepancy.py#L144)).

---

## Scenario 1 — Nothing opens mid-assessment

*Covers US1 · SC-002 · FR-DR-008*

```bash
pytest tests/unit/test_reconciliation_rounds.py -k mid_assessment -q
```

The defect the clarify session found, made a test. Assessor A answers 140 indicators. Assessor B answers 3 and differs on 1 — a rate of 33%, far above any tolerance. Neither has declared completion.

**Expect**

- A `DiscrepancyCase` **is** recorded, with rate 0.33 and the disputed set (FR-DR-004).
- `count(reconciliation_rounds) == 0`.
- No `PORTAL_DISCREPANCY` queue item was created.
- `unit_reconciliation_state` reports `above_tolerance_in_progress`.
- Requesting `/assessor/{cycle}/{unit}?role=B` renders the **questionnaire**, not the workspace.

Then let B answer the remaining 137 with no further disagreement. The rate falls below tolerance; still nothing opens; the unit ends `within_tolerance`. That second half is the point — the round is decided by the rate at mutual completion, not by the worst rate ever seen.

---

## Scenario 2 — The round opens on the second completion, exactly once

*Covers US1 · SC-002 · FR-DR-009, FR-DR-006*

```bash
pytest tests/unit/test_reconciliation_rounds.py -k opens_once -q
```

Both assessors answer every indicator, differing on enough to exceed tolerance. A declares completion — nothing opens. B declares completion.

**Expect**

- Exactly one row in `reconciliation_rounds`, `state='open'`, `opened_by='automatic'`, `round_number=1`.
- Exactly one `PORTAL_DISCREPANCY` queue item, carrying the `round_id`.
- Declaring completion again, or resubmitting an unchanged answer, adds neither.
- Two concurrent completion declarations still produce one round — assert against the partial unique index directly, since this is the race the index exists for.

---

## Scenario 3 — The workspace shows the dispute and nothing else

*Covers US2 · SC-003 · FR-DR-011…017*

```bash
pytest tests/unit/test_reconciliation_workspace.py -q
```

A unit with 111 indicators and 4 in dispute, with an open round.

**Expect**

- The workspace response contains the 4 disputed indicators as editable, and none of the other 107 as editable (FR-DR-011, FR-DR-012).
- Rendered as role A: A's answers labelled as the viewer's, B's as the peer's. Rendered as role B: the reverse. **Both roles must be exercised** — a single-role test passes while the labelling is inverted (FR-DR-013).
- For an *agreed* indicator, the peer's answer does not appear in the response text at all (FR-DR-017).
- The response names the tolerance in force, the rate, the compared count, and that this is the unit's only automatic round (FR-DR-016).
- A joint answer submitted without a justification is rejected, and the message names the field (FR-DR-021).
- A joint answer for an indicator outside the disputed set is rejected (FR-DR-023).

---

## Scenario 4 — A joint answer actually moves the rate

*Covers US2, US6 · SC-005 · FR-DR-020…026, FR-DR-051*

```bash
pytest tests/unit/test_joint_answers.py -q
```

The scenario that proves [research.md](./research.md) R2. Without the overlay every assertion below fails, and the feature's core loop never closes.

**Expect**

- After a joint answer on one of four disputed indicators, recomputation reports **three** disputed, not four.
- After all four, the rate is at or below tolerance and the round closes `resolved` (FR-DR-032).
- The original submissions are still readable and unchanged — both roles, both values (FR-DR-025).
- No `HumanAssessorSubmission` row was created by any joint answer. This is the assertion that rules out the rejected alternative in R2; without it, an implementation that writes submissions for both roles passes every other check here.
- `final_answer` returns the joint value for each reconciled indicator (FR-DR-051, SC-005).
- Two concurrent joint answers for the same indicator: one wins, the other is told the peer committed first, and exactly one row exists.
- One assessor answers all four alone; the round closes without the peer acting, and the peer finds everything settled (A4).

---

## Scenario 5 — The cap holds, and only the reviewer can lift it

*Covers US3, US4 · SC-006, SC-007 · FR-DR-030…039, FR-DR-055…057*

```bash
pytest tests/unit/test_reconciliation_cap.py -q
```

**Expect**

- A round that ends above tolerance closes `exhausted`; the unit becomes `persistent_discrepancy`; **no second round opens** (FR-DR-033).
- No sequence of further submissions — try fifty — produces a second automatic round (SC-006).
- A unit in persistent discrepancy renders the questionnaire, not the workspace, and says the disagreement is with the Senior Reviewer (FR-DR-035).
- A disagreement appearing after a *resolved* round goes straight to persistent discrepancy; the automatic round is spent (FR-DR-036).
- Leaving the unit alone changes nothing: it neither publishes nor re-opens nor lapses (FR-DR-038).
- A Senior Reviewer return opens round 2 with `opened_by='senior_reviewer'`, the actor, and the reason; without a reason it is refused (FR-DR-056).
- Return with an empty current disputed set — the assessors have since agreed everything — is refused with that explanation, and no empty round is created.
- A second reviewer disposing concurrently gets the "already decided" outcome, surfaced rather than swallowed ([research.md](./research.md) R7).
- Round 2 ending above tolerance returns the unit to persistent discrepancy with the same two options (FR-DR-039).

---

## Scenario 6 — Publishing over a disagreement is recorded, not silent

*Covers US4 · SC-008 · FR-DR-057, A5*

```bash
pytest tests/unit/test_api_publication.py -k contested -q
```

**Expect**

- The publication succeeds and records who decided, when, and the still-contested indicator set.
- Each contested indicator's published value follows the stated precedence — today, Assessor A's answer ([finalize.py:121](../../src/api/finalize.py#L121)) — and is marked contested.
- The **score is arithmetically identical** to what today's code produces for the same data. This is the assertion that keeps A5 honest: the feature makes the existing rule visible and attributable, and must not quietly change it.

---

## Scenario 7 — Declarations survive, and sign-off waits

*Covers US6 · FR-DR-058, FR-DR-059*

```bash
pytest tests/unit/test_assessor_completion.py -k reconciliation -q
```

**Expect**

- Opening, closing, and re-opening a round leave both `AssessorCompletion` rows byte-identical, and neither assessor is asked to re-declare (FR-DR-058).
- `publication_readiness` reports not-ready while a round is open, with a reason naming the reconciliation (FR-DR-059).
- Its existing `blocking_reason` strings are unchanged for every pre-existing case — a unit blocked on outstanding indicators still reports that, and reports it first.
- Once the round closes, readiness returns to what it was before the round opened.

---

## Scenario 8 — Five badge states, and no writes

*Covers US5 · SC-004, SC-010 · FR-DR-040…045*

```bash
pytest tests/unit/test_discrepancy_badge.py -q
pytest tests/unit/test_ui_quality_checks.py -q
```

Construct one unit per state: full consensus, within tolerance, above tolerance in progress, reconciliation open, persistent discrepancy, and awaiting a second assessment.

**Expect**

- Each renders a distinguishable badge with text and an icon, not colour alone (FR-DR-042).
- Every badge names the tolerance **in force for that project**; no occurrence of a hard-coded `5%` remains in the template (FR-DR-043).
- The awaiting-second-assessment unit shows no rate (FR-DR-044); it is not shown as 0%.
- Every badge shows the compared count (FR-DR-045).
- Load the project page 50 times: `discrepancy_cases` and `escalation_queue_items` row counts unchanged (SC-010).
- The publish-refused re-render at [admin.py:335](../../src/portal/admin.py#L335) produces the **same** badge as the normal render for the same unit.
- `test_ui_quality_checks.py` stays green — zero emoji, contrast, landmarks — and the workspace route's presence in its route list is a deliberate decision, not an accident ([contracts/reconciliation-workspace.md](./contracts/reconciliation-workspace.md) §6).

---

## Scenario 9 — Per-project tolerance

*Covers US7 · SC-009 · FR-DR-060…066*

```bash
pytest tests/unit/test_project_tolerance.py -q
```

**Expect**

- A project with no tolerance set uses 5% (FR-DR-061).
- Two projects at different tolerances judge the same rate differently, in the same process, with no restart (FR-DR-060, FR-DR-062).
- Changing project X's tolerance does not change project Y's outcome (SC-009). Assert this explicitly — a helper caching one value module-wide is the natural regression.
- A tolerance of 0% flags any disagreement and is not treated as unset (FR-DR-065).
- 101%, or a negative value, is rejected and the previous value stands (FR-DR-064).
- The change records who, when, and the previous value; a first change from an inheriting project records the previous value as "inheriting", not as 5% (FR-DR-066).
- A `DiscrepancyCase` recorded under the old tolerance still reports the old tolerance when read back (FR-DR-063).
- Raising the tolerance closes an open round as `not_required`, not as `resolved` (FR-DR-037).
- `grep -rn "settings.human_discrepancy_rate_threshold" src/ | grep -v effective_tolerance` returns **nothing**.

---

## Scenario 10 — Programmatic parity and the blindness boundary

*Covers SC-011 · FR-DR-015, FR-DR-017, FR-DR-070, FR-DR-071*

```bash
pytest tests/unit/test_api_human_blindness.py -q
pytest tests/unit/test_api_contract.py -k discrepancy -q
```

**Expect**

- A unit driven entirely through the REST API — submissions and both completions — opens its round exactly as the portal path does (FR-DR-070). Without the new call on the completion route this fails, and it is the only test that catches it.
- `GET .../discrepancy` returns the same `state` value the badge shows for the same unit (FR-DR-071).
- That response contains **no answers from either role** — disputed identifiers only. Assert on the raw text that the peer's distinguishing notes and actor id are absent, the technique `test_api_human_blindness.py` already uses.
- Apply the same raw-text assertion to the questionnaire route, the project detail page, and `GET /human-answers`, in both roles. Only `/reconcile` may return a peer answer, and only for an indicator in the open round's disputed set (SC-011).

---

## Coverage map

| Scenario | User stories | Success criteria |
|---|---|---|
| 0 | — (characterisation) | A1, A2 |
| 1 | US1 | SC-002 |
| 2 | US1 | SC-002 |
| 3 | US2 | SC-003 |
| 4 | US2, US6 | SC-005 |
| 5 | US3, US4 | SC-006, SC-007 |
| 6 | US4 | SC-008 |
| 7 | US6 | — (FR-DR-058/059) |
| 8 | US5 | SC-004, SC-010 |
| 9 | US7 | SC-009 |
| 10 | US1, US2 | SC-011 |

SC-001 is covered incidentally throughout — every scenario that submits an answer and then reads the rate exercises it, because the recomputation is already wired on submission and always has been.
