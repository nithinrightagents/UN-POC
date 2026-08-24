# Implementation Plan: Automated Dynamic Discrepancy Detection and Reconciliation

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-24
**Status**: Phase 1 complete — design artifacts generated
**Branch**: `main` (see Notes)

## Summary

The comparison engine exists and runs. `_compare()` computes the rate, `recompute_portal_discrepancy` writes the case and queues the work item, `compute_portal_discrepancy` is the read-only twin for GET routes, and both are already called from every submission path — the portal ([assessor.py:184](../../src/portal/assessor.py#L184)), the REST API ([human.py:93](../../src/api/routers/human.py#L93)), and the seed script. The admin badge already renders from a live computation ([admin.py:143](../../src/portal/admin.py#L143)).

Three things are genuinely missing, and one thing the code does today is wrong.

1. **There is nowhere to reconcile.** No workspace, no joint answer, no round. Detection without a resolution surface moves the work to the Senior Reviewer rather than removing it.
2. **Nothing bounds the loop.** Nothing counts rounds, so the cap of one cannot be enforced and the persistent-discrepancy state cannot exist.
3. **The tolerance is a process-wide constant** passed as a literal at six call sites, and the badge hard-codes `≤5%` in the template.

The wrong thing is the trigger. `recompute_portal_discrepancy` queues an escalation the moment the rate exceeds the threshold ([discrepancy.py:106](../../src/portal/discrepancy.py#L106)), with no regard for whether either assessor has finished. A unit where A has answered 140 indicators and B has answered 3, differing on 1, is at 33% and flags — consuming the unit's one automatic round while B still has 137 indicators to go. Gating that on both `AssessorCompletion` declarations is the single most consequential behavioural change here.

**Primary technical challenge**: a joint answer has to change the number. [`_compare()`](../../src/portal/discrepancy.py#L23-L45) reads exactly two things per indicator — A's latest submission and B's latest submission. A joint answer stored anywhere else is invisible to it, so the rate never falls, the round never closes as resolved, and a unit where the assessors have agreed on everything still shows red and still lands in persistent discrepancy. The overlay in [research.md](./research.md) R2 is what makes the feature's core loop terminate, and it is not visible from the spec's framing that the engine is complete.

Secondary, and nearly as easy to miss: **the last submission is never the trigger any more.** `complete_unit` refuses to declare while any indicator is outstanding, so the second completion strictly follows the last answer — and `complete_unit` does not call the discrepancy engine at all today. Without a new call there, no round ever opens.

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / runtime** | Python 3.11+, unchanged | existing `pyproject.toml` |
| **New dependencies** | **None.** FastAPI + Jinja2 + SQLite, as already present | `pyproject.toml` |
| **New modules** | `src/portal/reconciliation.py` (round lifecycle + `unit_reconciliation_state`), `src/portal/tolerance.py` (`effective_tolerance`) | [research.md](./research.md) R1, R4, R6 |
| **Modified — engine** | `portal/discrepancy.py` — joint-answer overlay in `_compare`, completion gate on the opening branch | [research.md](./research.md) R2, R3 |
| **Modified — portal** | `portal/assessor.py` (+2 routes, +redirect, +recompute on completion), `portal/admin.py` (+tolerance route, five-state badge rows, dispositions), `portal/seed.py` | [contracts/](./contracts/) |
| **Modified — shared** | `api/finalize.py` (+joint-answer term, +`final_answer_detail`, +open-round gate), `api/routers/completions.py`, `api/schemas.py` | [contracts/badge-tolerance-and-api.md](./contracts/badge-tolerance-and-api.md) |
| **Modified — plumbing** | `shared/persistence/{schema,repositories}.py` (+3 tables, +3 indexes), `shared/state/entities.py` (+2 fields), `shared/config/validation.py` (+1 range check) | [data-model.md](./data-model.md) |
| **New templates** | `assessor_reconcile.html` | [contracts/reconciliation-workspace.md](./contracts/reconciliation-workspace.md) §6 |
| **Modified templates** | `admin_project_detail.html` (two-state badge → five states), `assessor_unit.html` (persistent-discrepancy notice) | FR-DR-041, FR-DR-035 |
| **Unchanged (deliberately)** | `agents/**`, `orchestration/**`, `review/escalations.py`, `review/actions.py`, `shared/state/unit_state.py`, `export/**`, `benchmark/**` | see Project Structure |
| **New configuration** | `SurveyCycle.discrepancy_rate_threshold` (per project, `None` = inherit). No new `Settings` parameter — the existing `human_discrepancy_rate_threshold` becomes the inherited default | [data-model.md](./data-model.md) §5 |
| **Persistence** | Three new tables — `reconciliation_rounds` (lifecycle), `joint_answers` (append-only), `tolerance_changes` (append-only). `init_db` runs `CREATE TABLE IF NOT EXISTS` on every serve, so no migration tooling | [data-model.md](./data-model.md) §1–3 |
| **Auth** | Nothing new, and nothing claimed. Role and `actor_id` remain unauthenticated request parameters | FR-DR-018, Known Limitations |
| **Testing** | `pytest` against temp-file SQLite. **No model calls anywhere in this feature** — the human A/B path has no AI in it, so the whole suite is offline and free | [quickstart.md](./quickstart.md) |
| **Target scale** | Unchanged per submission. The badge adds no cost beyond today's per-unit computation; the spec records its growth curve as a deliberate non-requirement | [spec.md](./spec.md) Known Limitations |

**No unresolved NEEDS CLARIFICATION.** The `/speckit-clarify` session (2026-08-24) settled five spec-level questions; Phase 0 resolved the implementation unknowns as R1–R12.

### The clarify Deferred item

One, and it stays deferred: **no performance requirement for the badge.** The user chose this explicitly over a measurable page-load target. The cost is real and recorded — the project detail view recomputes per unit per load, each walk touching every indicator — and the remedy is known (a stored per-unit summary refreshed on submission, which is exactly the alternative [research.md](./research.md) R6 rejected for correctness reasons at this stage). Nothing in this plan optimises for it, and nothing in this plan makes it harder to fix later.

### What the originating request got wrong, and why it matters here

The request named four missing pieces. Two of them already exist and have for some time:

| Claimed missing | Actual state |
|---|---|
| "The POST route that triggers recompute after each submission in assessor.py" | already wired at [assessor.py:184-190](../../src/portal/assessor.py#L184-L190), and on the REST path and in the seed script |
| "Dynamic badge rendering using `compute_portal_discrepancy()`" | already computed at [admin.py:143](../../src/portal/admin.py#L143) and already rendered — but two-state with a hard-coded `≤5%` |
| "The reconciliation workspace template" | genuinely missing |
| "A dedicated reconciliation route loading conflicting questions only" | genuinely missing |

This matters beyond bookkeeping: implementing the first two as if they were absent would produce a *second* recomputation on every submission — double-writing the audit trail and, worse, double-counting against the idempotency guard. The corrected scope is what makes the round-cap enforceable.

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md`, as with specs 001, 003, 004, 007, and 008. Following those plans' precedent, the design is gated against the spec's own non-negotiables and this codebase's tested invariants.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **Blind A/B integrity** (spec 005; [entities.py:512-517](../../src/shared/state/entities.py#L512)) | Blindness is a query shape, not a UI toggle | Exactly one route reads across roles, and only for an open round's disputed set. Every other surface — questionnaire, badge, `/human-answers`, the new discrepancy endpoint — returns no peer answer in any role | PASS |
| **Display writes nothing** (FR-DR-007, SC-010) | A GET must not create audit rows | The read-only `compute_portal_discrepancy` already exists for this and keeps both display call sites. The overlay is added inside `_compare`, which both variants share, so the read-only path cannot silently acquire a write | PASS |
| **Append-only audit** (spec 001 FR-062) | No UPDATE/DELETE against audit tables | `joint_answers` and `tolerance_changes` are append-only. Original submissions are never rewritten — the rejected R2 alternative is ruled out by an explicit test. `reconciliation_rounds` is a *lifecycle* table on the `assessment_jobs` precedent, and is declared as such rather than smuggled in | PASS — with the classification stated, see Risks |
| **No silent resolution** (spec 001 FR-007/FR-033) | Never present an answer nobody gave as agreed | Strengthened. [finalize.py:121](../../src/api/finalize.py#L121) currently returns Assessor A's answer for an unresolved disagreement with no marker; FR-DR-057 keeps the value and adds the contested marking | PASS |
| **Exactly-once dispositions** (spec 001 FR-049) | One delivered disposition under concurrency | Reuses `record_disposition`'s `UNIQUE(item_id)` rather than building a second mechanism. The two new concurrency points — round opening and joint answers — use the same technique (partial unique index, unique index), never read-then-write | PASS |
| **Configuration externalized** (spec 001 FR-072–075) | No operational constant hidden in code | The tolerance moves *out* of a hard-coded template literal and out of six inline call-site literals into one resolver. `human_discrepancy_rate_threshold` also gains the range validation it has been missing | PASS — improves on today |
| **AI and human paths stay separate** (spec 008 clarification 5) | The human A/B path must not be wired to the resolver | No file under `agents/`, `orchestration/`, or the prefill path is touched. `UnitState` and `TERMINAL_UNIT_STATES` are not modified. The AI's `scope="portal"` cases and the human `scope="portal_human"` cases remain distinct rows | PASS |
| **Parity between portal and REST** (spec 007/008) | Neither surface may bypass a rule | Every rule lands in shared code — the gate inside `recompute_portal_discrepancy`, the cap inside the table's index, the tolerance inside one resolver, the state inside one projection. The two surfaces differ only in which routes call them | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

```
src/
├── portal/
│   ├── discrepancy.py                # MODIFIED — the two changes that matter most:
│   │                                 #   _compare() gains the joint-answer overlay (R2)
│   │                                 #   the flagged branch gains a both-declared gate (R3)
│   ├── reconciliation.py             # NEW — round lifecycle: open/close/cap,
│   │                                 #   and unit_reconciliation_state() (R1, R6)
│   ├── tolerance.py                  # NEW — effective_tolerance(), the single resolver (R4)
│   ├── assessor.py                   # MODIFIED — +GET /reconcile, +POST .../joint,
│   │                                 #   redirect on open round, recompute on complete_unit
│   ├── admin.py                      # MODIFIED — +POST .../tolerance, five-state unit rows,
│   │                                 #   two dispositions, surface dispose_escalation's bool
│   ├── seed.py                       # MODIFIED — completions before final recompute;
│   │                                 #   seeds one unit per badge state
│   └── templates/
│       ├── assessor_reconcile.html   # NEW — reciprocal diff view, disputed set only
│       ├── admin_project_detail.html # MODIFIED — 2 states → 5; no hard-coded "≤5%"
│       └── assessor_unit.html        # MODIFIED — persistent-discrepancy notice
│
├── api/
│   ├── finalize.py                   # MODIFIED — joint answer enters precedence;
│   │                                 #   +final_answer_detail(); +open-round gate on readiness
│   ├── schemas.py                    # MODIFIED — +discrepancy state response model
│   └── routers/
│       ├── completions.py            # MODIFIED — recompute on programmatic completion
│       │                             #   (without this, the API path never opens a round)
│       └── discrepancy.py            # NEW — GET .../discrepancy (FR-DR-071)
│
└── shared/
    ├── state/entities.py             # MODIFIED — +SurveyCycle.discrepancy_rate_threshold,
    │                                 #   +PublicationRecord.contested_question_ids,
    │                                 #   DiscrepancyCase.scope comment corrected (R12)
    ├── config/validation.py          # MODIFIED — range-check the human threshold (R5)
    └── persistence/
        ├── schema.py                 # MODIFIED — +3 tables, +2 unique indexes, +2 indexes
        └── repositories.py           # MODIFIED — round open/close/list, joint answer
                                      #   insert/list, tolerance change insert/list

tests/unit/
├── test_portal_discrepancy.py        # NEW — characterisation, written FIRST (R10)
├── test_reconciliation_rounds.py     # NEW — the completion gate and the one-round cap
├── test_reconciliation_workspace.py  # NEW — disputed set only, both roles, refusals
├── test_joint_answers.py             # NEW — the overlay; originals untouched
├── test_reconciliation_cap.py        # NEW — exhaustion, persistence, reviewer dispositions
├── test_discrepancy_badge.py         # NEW — five states, and no writes on display
├── test_project_tolerance.py         # NEW — per-project, isolation, 0%, range, attribution
├── test_assessor_completion.py       # EXTENDED — declarations survive rounds; sign-off gate
├── test_api_human_blindness.py       # EXTENDED — SC-011 across every route, both roles
├── test_api_publication.py           # EXTENDED — contested publication; score unchanged
└── test_ui_quality_checks.py         # EXTENDED — the workspace route, deliberately (R11)
```

**What is explicitly NOT touched, and why that boundary matters:**

- **`agents/**`, `orchestration/**`, the prefill path** — the AI's disagreement handling is a separate mechanism by design, and the spec's Out of Scope says so twice. This is the boundary spec 008's terminology clarification exists to protect; wiring the human path to the resolver would collapse it.
- **`shared/state/unit_state.py`, `TERMINAL_UNIT_STATES`** — reconciliation is a human-side lifecycle running beside the AI state machine, not inside it. Adding a unit state here would drag in the five hardcoded terminal-set call sites spec 008 enumerated, for no gain.
- **`review/escalations.py`, `review/actions.py`** — the queue, its views, and its exactly-once disposition guarantee are reused unmodified. Only new `resolution` string values pass through them.
- **`export/`, `benchmark/`, `public/`** — no path touches them.
- **`final_answer`'s signature** — stays `bool | None`. Both publishers share it and spec 008's parity guarantee rests on that; the detail variant is additive.

## Phase 0 — Research

Complete. See [research.md](./research.md). Twelve decisions, each with rationale and alternatives:

| # | Decision |
|---|---|
| R1 | `reconciliation_rounds` is a lifecycle table. Counting escalation items instead would never fire the cap — the idempotency guard collapses repeated rounds into one item |
| R2 | `_compare()` gains a joint-answer overlay. Without it the rate never falls and no round can ever close as resolved |
| R3 | Round opening moves behind a both-declared gate, and `complete_unit` gains the recomputation call it has never had |
| R4 | Per-project tolerance on `SurveyCycle` + a `tolerance_changes` table. `insert_cycle` is an upsert, so two "append-only" comments in `admin.py` are false and history needs its own table |
| R5 | `human_discrepancy_rate_threshold` is missing from `validate_settings`; `=50` meaning "50%" silently disables flagging |
| R6 | The five badge states are one derived projection with three consumers, not three derivations |
| R7 | Both reviewer dispositions ride on `record_disposition`'s existing exactly-once guarantee; its discarded `bool` return must be surfaced |
| R8 | Precedence gains a joint-answer term; the A-wins fallback keeps its value and gains a contested marking |
| R9 | Programmatic parity needs the completion-route recompute and one new read endpoint |
| R10 | `portal/discrepancy.py` has **no tests at all**; characterise before modifying `_compare` |
| R11 | Three existing UI gates apply to the new template, and the enumerated route test asserts 200 on a route required to refuse |
| R12 | Two pre-existing inconsistencies noted, not fixed: `portal_discrepancy_cases` queries the wrong scope; `DiscrepancyCase.scope`'s comment is stale |

## Phase 1 — Design & Contracts

Complete.

- **[data-model.md](./data-model.md)** — the three tables with their DDL and validation rules, the round state machine, the joint-answer overlay stated as a rule, the six-state derived projection with its badge and routing table, the revised publication precedence, and the entities deliberately left alone.
- **[contracts/detection-and-rounds.md](./contracts/detection-and-rounds.md)** — every recomputation trigger with which are new, the eight-step opening decision in evaluation order, round closing, the cap stated exactly, the reviewer's two dispositions, and the one condition publication readiness gains.
- **[contracts/reconciliation-workspace.md](./contracts/reconciliation-workspace.md)** — the two new routes, what the workspace returns and refuses, the joint-answer POST including its concurrent-write outcome, the blindness boundary as a per-route table, what the contract explicitly does not promise, and the template's three inherited gates.
- **[contracts/badge-tolerance-and-api.md](./contracts/badge-tolerance-and-api.md)** — the badge's two current defects quoted from the template, the five-state replacement, the tolerance set/read/record/isolate contract with its six-site migration, the new endpoint's body, and the parity checklist.
- **[quickstart.md](./quickstart.md)** — eleven scenarios (0–10) mapped to the seven user stories and SC-001…011. All offline; scenario 0 characterises the untested engine before it is modified.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **`_compare()` is modified with no tests behind it, and four public entry points flow through it.** The overlay is a genuine semantic change to the definition of "the rate" | A regression in `compute_portal_discrepancy`, `recompute_portal_discrepancy`, `find_resolved_answer`, or the publication chain would be indistinguishable from the intended change in the diff | Scenario 0 in [quickstart.md](./quickstart.md) is a characterisation suite written against the **unchanged** engine and green before any edit. Sequence it as its own task; it is the only thing standing between this feature and a silent change to a published score |
| **The joint answer could be implemented as submissions for both roles.** It is the shortest path — the rate falls with no engine change and `final_answer` needs nothing | It forges the audit trail, showing A independently changing their mind at the instant B did, and corrupts spec 008's `ai_suggestion_accepted` measure. It would pass every test in this suite except one | Scenario 4 asserts that **no `HumanAssessorSubmission` row is created by any joint answer**. That single assertion is what rules the shortcut out; without it the temptation returns at every refactor |
| **Six call sites pass the tolerance as a literal.** A half-migration to `effective_tolerance` leaves a unit judged under one figure and displayed under another | Worse than today, where at least the wrong figure is consistent. The badge would name a tolerance the engine did not apply — precisely FR-DR-043's failure, arriving through the fix for it | Migrate all six in one task ([contracts/badge-tolerance-and-api.md](./contracts/badge-tolerance-and-api.md) §2). Completion check: `grep -rn "settings.human_discrepancy_rate_threshold" src/ \| grep -v effective_tolerance` returns nothing |
| **`reconciliation_rounds` mutates a column in a codebase that says it is append-only** | A reviewer who knows spec 001 FR-062 will read this as a violation and either block it or, worse, "fix" it into an event-pair table that every reader then has to fold | The classification is stated, not assumed: it is a lifecycle table on the `assessment_jobs` precedent, and the audit trail it needs lives in `discrepancy_cases` and `joint_answers`, both append-only. Say so in the commit message, not only in this plan |
| **Adding `/reconcile` to `test_all_portal_routes_render_successfully` asserts 200 on a route required to refuse** | The failure presents as a routing bug, and the instinctive fix is to weaken FR-DR-014's refusal until the test passes | R11 names it in advance. Either extend `seeded_client` with a unit that has both roles, both completions, and an open round — worth having regardless, since nothing else in the suite builds one — or assert the refusal as its own case |
| **`dispose_escalation` returns `bool` and `admin.py` discards it** ([admin.py:409](../../src/portal/admin.py#L409)) | With two dispositions leading to opposite outcomes, a losing concurrent reviewer sees a redirect identical to success. One reviewer believes they returned the unit; the other believes they published it; one of them is wrong and neither is told | Surface the return value as part of the disposition task, not as a follow-up. The guarantee already exists in the repository layer — only the caller throws it away |
| **The completion-route recompute is one line in one file, and nothing else fails without it** | A unit assessed entirely through the REST API silently never opens a round. No portal test catches it, and the portal path works perfectly | Scenario 10 drives a unit end-to-end through the API only. It is the single test that covers this, and it should be written when the portal call site is written, not afterwards |
| **A tolerance raised mid-round closes it as `not_required`, which looks like success** | If implemented as `resolved`, the record would claim the assessors agreed when the threshold simply moved — a false audit statement about people | `not_required` is a distinct terminal state in the round machine for exactly this reason ([data-model.md](./data-model.md) §1), and scenario 9 asserts on the state value, not merely on closure |

## Notes

- **Branch**: work continues on `main`, matching specs 001/003/004/007/008 — no `before_plan` git hook is configured (`.specify/extensions.yml` does not exist).
- **No setup script found**: `.specify/` contains only `feature.json`. There is no `scripts/`, no `templates/`, and no `memory/constitution.md`, so `FEATURE_SPEC`, `IMPL_PLAN`, and `SPECS_DIR` were resolved from `.specify/feature.json` (`specs/012-portal-discrepancy-reconciliation`) — the same fallback specs 004, 007, and 008 recorded. The plan follows spec 008's structure as the house template.
- **Graphify consulted, then set aside.** Unlike spec 008, `graphify-out/` exists here and `graphify query` was run first per the project's CLAUDE.md. It returned a 279-node BFS neighbourhood spanning the AI pipeline, the benchmark harness, and test doubles — accurate but far wider than the question, and built from a snapshot that still contains files since deleted (`tests/unit/test_agreement_and_resolver.py`). None of the findings that shaped this plan are structural: the joint-answer overlay is a semantic property of what `_compare` reads, the missing trigger is an *absent* call, the false append-only comments are prose, and the untested engine is an absence of files. A structural map surfaces none of those. Targeted reads of the exact call sites did. Worth running `graphify update .` after implementation to refresh the snapshot.
- **Corrections to make in passing**, all one-liners, all in files this feature already opens: the two false "append-only superseding" comments ([admin.py:221](../../src/portal/admin.py#L221), [admin.py:240](../../src/portal/admin.py#L240)) and `DiscrepancyCase.scope`'s stale value list ([entities.py:387](../../src/shared/state/entities.py#L387)). Each nearly misled this design.

## Post-Design Constitution Re-check

Re-evaluated after [data-model.md](./data-model.md) and [contracts/](./contracts/) were written. All eight gates still PASS. Four are worth recording as *verified* rather than assumed:

- **Blindness was re-checked against the endpoint that did not exist when the gate was written.** The new `GET .../discrepancy` returns disputed **identifiers** and never disputed values. This was the gate most at risk, because returning the two sides alongside the ids is the natural convenience and the endpoint carries no authentication beyond the router's API key. Verified by checking that the response model has no field capable of holding an answer — not by intending not to populate one.
- **The write-nothing guarantee survives the overlay.** The check was whether adding a joint-answer lookup to `_compare` could give the read-only path a write. It cannot: the overlay is a read, and the two public functions diverge *after* `_compare` returns — [discrepancy.py:56-69](../../src/portal/discrepancy.py#L56) writes nothing at all, and the writing branch is entirely inside `recompute_`. The separation the existing docstrings promise is structural, and stays structural.
- **Append-only survives the feature, with one deliberate exception that is declared.** `joint_answers` and `tolerance_changes` are append-only. No design path updates or deletes a `HumanAssessorSubmission`, an `AssessorCompletion`, or a `DiscrepancyCase`. `reconciliation_rounds` mutates `state`, and is classified as lifecycle rather than audit — the same category as `assessment_jobs`, which has had an `update_..._state` method since spec 007. Verified by confirming that every fact a future reader would need to reconstruct what happened is recorded in an append-only row, not only in that column.
- **"No silent resolution" got stronger, not weaker.** [finalize.py:110-112](../../src/api/finalize.py#L110)'s docstring claims the chain "never invents an answer nobody gave" while line 121 returns Assessor A's answer as an unmarked stand-in for agreement. The value was never invented; the *agreement* was. Recording the contested set makes the docstring true of both. It should not be re-added as a comment celebrating the fix — it was always the stated contract.

Three design interactions worth recording for `tasks.md` sequencing:

1. **R10 (characterisation tests) must land before R2 (the overlay), with nothing between them.** `_compare` feeds the publication chain through `find_resolved_answer` and `final_answer`. Modifying it without a green characterisation suite means a change to a published score would be invisible in review. This is the one ordering constraint in the feature that is not negotiable.
2. **R3 (the completion gate) and its two new call sites must land together, in one change.** The gate without the `complete_unit` call means no round ever opens — the feature appears to do nothing. The call sites without the gate mean rounds open mid-assessment, which is today's defect made more frequent. Either half alone is worse than neither; the intermediate state is not merely incomplete but actively wrong.
3. **R4 (tolerance) is independent of the round machinery and can proceed in parallel, but its six call sites cannot be split.** The engine and the badge must resolve the tolerance from the same place in the same change, or the number a reviewer reads stops being the number the unit was judged by — with no error and no test failure to announce it.
