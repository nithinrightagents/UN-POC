# Tasks: Automated Dynamic Discrepancy Detection and Reconciliation

**Feature**: `012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [plan.md](plan.md) | [research.md](research.md) | [data-model.md](data-model.md) | [contracts/detection-and-rounds.md](contracts/detection-and-rounds.md) | [contracts/reconciliation-workspace.md](contracts/reconciliation-workspace.md) | [contracts/badge-tolerance-and-api.md](contracts/badge-tolerance-and-api.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-08-24

## Conventions

- `[P]` = parallelizable (different file, no dependency on an incomplete task in this list). Two tasks editing the same file are never both marked `[P]`.
- `[USn]` = belongs to User Story n's phase (spec.md priorities: US1–US4 = P1, US5–US7 = P2). Setup, Foundational, and Polish tasks carry no story label.
- **No new dependency.** FastAPI, Jinja2, and SQLite are already declared; nothing below adds a package ([plan.md](plan.md) Technical Context).
- **No model call anywhere in this feature.** The human A/B path has no AI in it, so every test task below runs offline and free.
- **`src/agents/**`, `src/orchestration/**`, `src/shared/state/unit_state.py`, and `TERMINAL_UNIT_STATES` are never edited by any task below.** The AI disagreement path and the human A/B path are separate by design ([spec.md](spec.md) Out of Scope, spec 008 clarification 5). A task that needs to touch one of those files has gone wrong.
- **`src/shared/tools/**`, `src/export/**`, `src/benchmark/**`, and `src/portal/public.py` are never edited by any task below.**
- Two files are added beyond the spec's Key Entities list, both deliberate: `src/portal/reconciliation.py` (round lifecycle and the shared state projection) and `src/portal/tolerance.py` (the single tolerance resolver, kept separate so the six-site migration has one destination).

---

## Implementation Strategy

Ten increments. Four ordering choices below deviate from a naive priority walk, and each is deliberate.

1. **Increment 1** (Phase 1, Setup): The baseline run, then a characterisation suite for `portal/discrepancy.py` — which has **no test file today** ([research.md](research.md) R10) — then scaffolds. Nothing else may start until the characterisation suite is green against the **unchanged** engine, because this feature modifies `_compare()` and all four public entry points flow through it. This is the single non-negotiable ordering constraint in the feature.
2. **Increment 2** (Phase 2, Foundational): Three tables, two entity changes, the repository methods, the tolerance resolver **with its six call sites**, the missing settings validation, and the shared state projection. Largest phase, because this feature's machinery is shared rather than per-story. **Nothing in Phases 3–9 can start until it lands.**
3. **Increment 3** (Phase 3, US1 — P1, the MVP): Detection corrected. The completion gate, the full eight-step opening decision including the cap check, and the two new completion-route call sites. Testable with no workspace at all — a round row appears at the right moment and never at the wrong one.
4. **Increment 4** (Phase 4, US2 — P1): The workspace, joint answers, and the overlay. **The overlay lands here rather than in US6's phase**, even though US6 is the story about joint answers reaching publication, because without it a joint answer does not move the rate, no round can close as `resolved`, and US3's cap is untestable ([research.md](research.md) R2).
5. **Increment 5** (Phase 5, US3 — P1): The consequences of exhaustion. Deliberately thin: the cap guard and the `exhausted` classification are already built by Phases 3 and 4, so this phase is mostly the surfacing and the assertions that the system does nothing further on its own. That is honest rather than padded — the cap is a property of code written earlier, and this phase proves it.
6. **Increment 6** (Phase 6, US4 — P1): The Senior Reviewer's two dispositions and the contested publication record. Closes the loop opened by Increment 5 — until it lands, a persistent-discrepancy unit has nowhere to go, which is a spec-legal waiting state (FR-DR-038) but not a shippable one.
7. **Increment 7** (Phase 7, US5 — P2): The five-state badge. Follows detection because it reports state rather than creating it.
8. **Increment 8** (Phase 8, US6 — P2): Publication precedence and the sign-off gate.
9. **Increment 9** (Phase 9, US7 — P2): Setting the tolerance from the portal, its history, and the `not_required` closure. **The resolver itself is in Phase 2, not here**, because the engine, the workspace, and the badge all name "the tolerance in force" and a half-migration would judge a unit under one figure while displaying it under another ([research.md](research.md) R4). This phase adds the way to *change* it; Phase 2 established the single place it is *read*.
10. **Polish** (Phase 10): The programmatic read endpoint, the blindness sweep across every route, seed data for each badge state, three one-line corrections to comments that nearly misled this design, and full regression.

**MVP**: Phase 3 (US1) is a coherent, shippable increment on its own — detection becomes correct, and the defect where a round opens mid-assessment is fixed. The minimum *useful* release is Phases 3 + 4 together, because a round that opens with nowhere to reconcile moves work to the Senior Reviewer rather than removing it, which is the outcome this feature exists to prevent.

---

## Phase 1: Setup and characterisation

> Goal: A green baseline, a safety net under the engine about to be modified, and empty scaffolds. No behaviour change.
>
> **T002 is a hard gate.** No task in any later phase may begin until it is green against the unchanged engine.

- [X] T001 Run `pytest -q` from the repo root over `tests/` and record the passing count; this is the baseline every later phase is compared against ([quickstart.md](quickstart.md) Prerequisites)
- [X] T002 Create `tests/unit/test_portal_discrepancy.py` with the seven characterisation cases of [quickstart.md](quickstart.md) scenario 0, written against the **unchanged** `src/portal/discrepancy.py`: no overlap returns `None` and writes nothing; the rate is computed over the intersection only (A1); `rate == threshold` is within tolerance and only `rate > threshold` flags (A2, pinning [discrepancy.py:44](../../src/portal/discrepancy.py#L44)); `compute_portal_discrepancy` leaves `discrepancy_cases` and `escalation_queue_items` row counts unchanged after 50 calls; `recompute_portal_discrepancy` writes a case on every overlapping call and a queue item only when flagged; the idempotency guard suppresses a duplicate item for an unchanged disagreement set and does not suppress a changed one; `find_resolved_answer` returns the newest covering item's arbitration ([discrepancy.py:144-149](../../src/portal/discrepancy.py#L144)). **Must be green before T003**
- [X] T003 [P] Create `src/portal/reconciliation.py` as a scaffold whose module docstring states that this is the human A/B reconciliation lifecycle, that it is deliberately not wired to `agents/resolver/` or `agents/adjudicator/` ([spec.md](spec.md) Out of Scope), and that `reconciliation_rounds` is a **lifecycle** table on the `assessment_jobs` precedent rather than an append-only audit table ([research.md](research.md) R1)
- [X] T004 [P] Create `src/portal/tolerance.py` as a scaffold whose module docstring states that it is the single place a tolerance is resolved, and lists the six call sites that must never re-inline `settings.human_discrepancy_rate_threshold` ([research.md](research.md) R4)
- [X] T005 [P] Create `src/api/routers/discrepancy.py` as an empty router scaffold returning `APIRouter()`
- [X] T006 [P] Create six test modules as scaffolds with a `@pytest.mark.unit` module marker: `tests/unit/test_reconciliation_rounds.py`, `tests/unit/test_reconciliation_workspace.py`, `tests/unit/test_joint_answers.py`, `tests/unit/test_reconciliation_cap.py`, `tests/unit/test_discrepancy_badge.py`, `tests/unit/test_project_tolerance.py`
- [X] T007 [P] In `tests/unit/conftest.py`: add the fixtures this feature's tests share — a `two_assessor_unit` factory taking a per-question `(a_answer, b_answer)` map so a controlled disagreement rate can be constructed in one line, an `open_round` factory that writes a `reconciliation_rounds` row directly (so US2 is testable with no completion flow at all), and a `both_declared` helper writing both roles' `assessor_completions` rows. Extend the existing file, reusing spec 008's `completed_unit` factory rather than duplicating it; do not replace any spec 007 or 008 fixture

---

## Phase 2: Foundational — tables, the tolerance resolver, the shared projection

> Goal: Everything every story phase depends on. **Must complete before Phase 3.**
>
> **T015–T017 are one atomic group.** The resolver and all six of its call sites land in one change. A half-migration judges a unit under one tolerance and displays it under another — worse than today, where at least the wrong figure is consistent. T017 is the completion check.

### Schema and entities

- [X] T008 In `src/shared/persistence/schema.py`: add the `reconciliation_rounds`, `joint_answers`, and `tolerance_changes` tables with their four indexes exactly as given in [data-model.md](data-model.md) §1–3. Each DDL block carries a comment stating its classification — `reconciliation_rounds` is **lifecycle** (mutable `state`, `assessment_jobs` precedent), the other two are **append-only**. The partial unique index `idx_reconciliation_one_open` and the unique `idx_joint_answers_once` are load-bearing concurrency guarantees, not optimisations; say so in the comment so neither is later "tidied" into a plain index
- [X] T009 In `src/shared/state/entities.py`: add `discrepancy_rate_threshold: float | None = None` to `SurveyCycle` (stored in the existing JSON `data` column, so no DDL change) and `contested_question_ids: list[str] = field(default_factory=list)` to `PublicationRecord`. `None` and `0.0` on the threshold are deliberately distinct — document it on the field, because a `float` defaulting to `0.0` would make a project that tolerates nothing indistinguishable from one never configured (FR-DR-065)
- [X] T010 In `src/shared/state/entities.py`: add the `ReconciliationRound`, `JointAnswer`, and `ToleranceChange` dataclasses per [data-model.md](data-model.md) §1–3, and correct `DiscrepancyCase.scope`'s inline comment at [entities.py:387](../../src/shared/state/entities.py#L387) from `# "question" | "portal"` to include `"portal_human"` — it has been wrong since that value was introduced and it nearly misled this design ([research.md](research.md) R12). Same file as T009, so not parallel with it

### Persistence

- [X] T011 In `src/shared/persistence/repositories.py`: add `insert_reconciliation_round` (returning `False` on `IntegrityError` so the partial unique index is the concurrency guarantee, never a read-then-write check), `open_round_for_unit(session_id, portal_id)`, `list_rounds_for_unit(session_id, portal_id)`, and `close_round(round_id, state, closed_at)`. `close_round` is the **only** mutator on the table and accepts only the three terminal states of [data-model.md](data-model.md) §1
- [X] T012 In `src/shared/persistence/repositories.py`: add `insert_joint_answer` (returning `False` on `IntegrityError`, mirroring `record_disposition`'s shape at [repositories.py:530-546](../../src/shared/persistence/repositories.py#L530)), `latest_joint_answer(session_id, portal_id, question_id)` returning the newest across rounds, and `list_joint_answers_for_round(round_id)`. **No update and no delete method** — the append-only property is enforced by the absence of a mutator, as spec 008 did for `prefills`
- [X] T013 In `src/shared/persistence/repositories.py`: add `insert_tolerance_change` and `list_tolerance_changes(cycle_id)`. Same file as T011–T012, so the three land in sequence
- [X] T014 In `src/shared/persistence/serialization.py`: confirm the three new dataclasses and the two changed entities round-trip through `to_json`/`from_json`; add handling only where the existing dataclass path does not already cover them

### The tolerance resolver (R4) — T015–T017 are one atomic group

- [X] T015 In `src/portal/tolerance.py`: implement `effective_tolerance(repo, cycle_id, settings) -> float` returning `SurveyCycle.discrepancy_rate_threshold` where set and `settings.human_discrepancy_rate_threshold` otherwise (FR-DR-061). Read per call — never cached at module level, which is the regression SC-009 exists to catch
- [X] T016 Migrate all six literal call sites to `effective_tolerance` in one change: [assessor.py:189](../../src/portal/assessor.py#L189), [admin.py:145](../../src/portal/admin.py#L145), [admin.py:337](../../src/portal/admin.py#L337), [human.py:98](../../src/api/routers/human.py#L98), and both of [seed.py:153, :157](../../src/portal/seed.py#L153). Four files; not parallelizable with anything, because a partial migration is the failure mode ([contracts/badge-tolerance-and-api.md](contracts/badge-tolerance-and-api.md) §2)
- [X] T017 Verify the migration is complete: `grep -rn "settings.human_discrepancy_rate_threshold" src/ | grep -v effective_tolerance` returns **zero hits**. Any survivor is a site that judges or displays a unit under the process-wide default while its project runs to something else

### Configuration validation

- [X] T018 [P] In `src/shared/config/validation.py::validate_settings`: add a `0.0 <= human_discrepancy_rate_threshold <= 1.0` range check alongside the two existing `portal_*` threshold checks at [validation.py:66-77](../../src/shared/config/validation.py#L66). It has been missing since the setting was introduced, so `AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD=50` — the natural way to write "50%" — is accepted today and silently disables flagging entirely ([research.md](research.md) R5)
- [X] T019 [P] In `tests/unit/test_config_validation.py`: add cases for the new range check, including `50` and `-0.1` as rejected and `0.0` and `1.0` as accepted

### The shared state projection (R6)

- [X] T020 In `src/portal/reconciliation.py`: implement `unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings) -> UnitReconciliationState` per [data-model.md](data-model.md) §7 — the eight-field result and the six states, **in the stated evaluation order**: `reconciliation_open` before `persistent_discrepancy`, and both before the rate bands, so a re-opened round presents as open rather than exhausted. One function, three consumers (the badge, the assessor route, publication readiness); deriving the state twice is how the badge and the router come to disagree about a unit

---

## Phase 3: User Story 1 (P1) — A disagreement is detected and acted on without anyone looking for it

> **Goal**: Recomputation stays wired on every submission as it already is, but a reconciliation round opens only when both assessors have declared completion and the rate then exceeds the tolerance in force — exactly once per unit.
>
> **Independent test**: Two assessors answer one unit with a controlled disagreement rate, one set below tolerance and one above. Below tolerance: no round, no queue item. Above tolerance but before both declarations: a recorded case, no round, no queue item, and the questionnaire still renders. After both declarations: exactly one round and exactly one queue item. No workspace is required to test any of this.
>
> **This phase is the MVP** and depends on nothing in Phases 4–9.
>
> **T024–T027 are one atomic group.** The gate without the completion call sites means no round ever opens — the feature appears to do nothing. The call sites without the gate mean rounds open mid-assessment, which is today's defect made more frequent. Either half alone is worse than neither.

### Tests

- [X] T021 [P] [US1] In `tests/unit/test_reconciliation_rounds.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 1 — A answers 140 indicators, B answers 3 and differs on 1 (a 33% rate), neither has declared. Assert a `DiscrepancyCase` **is** recorded with the rate and disputed set, `count(reconciliation_rounds) == 0`, no `PORTAL_DISCREPANCY` queue item, state `above_tolerance_in_progress`, and that `/assessor/{cycle}/{unit}?role=B` renders the questionnaire. Then let B answer the remaining 137 in agreement and assert the unit ends `within_tolerance` with nothing ever opened — the round is decided by the rate at mutual completion, not by the worst rate seen along the way
- [X] T022 [US1] In `tests/unit/test_reconciliation_rounds.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 2 — exactly one `open` row with `opened_by='automatic'` and `round_number=1` after the second declaration, exactly one queue item carrying the `round_id`, neither added by re-declaring or by resubmitting an unchanged answer, and two concurrent declarations still producing one round. Assert the concurrency case against the partial unique index directly, since that is the race the index exists for

### Round opening

- [X] T023 [US1] In `src/portal/reconciliation.py`: implement `open_automatic_round(repo, session_id, cycle_id, portal_id, disputed_question_ids, rate, tolerance)` — computes `round_number` as prior count + 1, inserts with `opened_by='automatic'` and `opened_by_actor_id=None`, and treats a `False` return from the repository as "a round is already open" rather than as an error. Refuses to open over an empty disputed set ([data-model.md](data-model.md) §1 validation rules)
- [X] T024 [US1] In `src/portal/discrepancy.py::recompute_portal_discrepancy`: restructure the flagged branch into the eight-step evaluation order of [contracts/detection-and-rounds.md](contracts/detection-and-rounds.md) §2. Step 3 keeps `rate > tolerance` **strictly greater** — it must not be "fixed" to `>=` (A2). Step 4 skips when a round is already open. **Step 5 is the defect fix**: both roles must have an `AssessorCompletion` before anything opens (FR-DR-008). Step 6 refuses when an automatic round has already been used, so the cap is enforced at the only place a round can open. Steps 7–8 open the round and queue the item, and the item's `context` gains `round_id` so the work item and the round correlate in both directions. Keep the existing idempotency guard at [discrepancy.py:111-116](../../src/portal/discrepancy.py#L111-L116) — it no longer carries the whole weight but still protects a disposed item under an open round
- [X] T025 [US1] In `src/portal/assessor.py::complete_unit`: after `insert_assessor_completion` succeeds at [assessor.py:264-274](../../src/portal/assessor.py#L264-L274), call `recompute_portal_discrepancy` with the unit's question ids and `effective_tolerance`. This route has **never** called the discrepancy engine, and after T024 it is the only place in the portal where a round can open. **Must land in the same change as T024**
- [X] T026 [US1] In `src/api/routers/completions.py`: add the identical recomputation call to the programmatic completion route. Without it a unit assessed entirely through the REST API reaches mutual completion and never opens a round, with every portal test still passing — the precise bypass FR-DR-070 forbids. **Must land in the same change as T024–T025**
- [X] T027 [US1] In `src/portal/seed.py`: reorder `seed_demo_data` so both `assessor_completions` rows are written **before** the final recomputation at [seed.py:155](../../src/portal/seed.py#L155). Left in its current order, the seeded flagged unit records its disagreement without opening a round and the demo shows a red badge with no reconciliation behind it ([contracts/badge-tolerance-and-api.md](contracts/badge-tolerance-and-api.md) §4)

**Checkpoint**: `pytest tests/unit/test_reconciliation_rounds.py tests/unit/test_portal_discrepancy.py -q` green, and the T001 baseline still green. Detection is now correct end to end with no workspace in existence.

---

## Phase 4: User Story 2 (P1) — Two assessors settle their differences in a focused diff view

> **Goal**: A unit with an open round routes both assessors to a workspace showing only the disputed indicators, each side attributed to its author; either assessor commits a joint answer with a justification; the rate falls as they accumulate and the round closes.
>
> **Independent test**: Seed a unit with an open round using T007's `open_round` factory — no completion flow needed. Open the workspace as each role in turn and verify the disputed set is exactly what is editable, that each role sees its own answers as its own and its peer's as the peer's, that agreed indicators are present but locked and their peer answers absent from the response entirely, and that a joint answer moves the rate.
>
> **T030 is the highest-risk change in the feature.** `_compare()` is modified while four public entry points flow through it, one of which feeds the published score. T002's characterisation suite is what makes a regression distinguishable from the intended change.

### Tests

- [X] T028 [P] [US2] In `tests/unit/test_reconciliation_workspace.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 3 against a 111-indicator unit with 4 disputes — the 4 are editable and the other 107 are not; **both roles are rendered** and each sees its own answers as its own (a single-role test passes while the labelling is inverted); for an agreed indicator the peer's answer does not appear in the response text at all (FR-DR-017); the response names the tolerance in force, the rate, the compared count, and that this is the unit's only automatic round; a joint answer without a justification is rejected naming the field; a joint answer outside the disputed set is rejected
- [X] T029 [P] [US2] In `tests/unit/test_joint_answers.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 4 — after one joint answer on four disputes, recomputation reports **three** disputed; after all four the rate is within tolerance and the round closes `resolved`; both originals remain readable and unchanged; **no `HumanAssessorSubmission` row is created by any joint answer**; two concurrent joint answers for one indicator leave exactly one row with the loser told the peer committed first; one assessor answering all four alone closes the round without the peer acting (A4). The `HumanAssessorSubmission` assertion is the one that rules out R2's rejected alternative — without it, an implementation that writes submissions for both roles passes every other check in this file

### The overlay and round closing

- [X] T030 [US2] In `src/portal/discrepancy.py::_compare`: apply the joint-answer overlay of [data-model.md](data-model.md) §6 — for each commonly answered indicator, a joint answer (newest wins) makes both sides take the joint value and count as agreement; otherwise the two latest submissions are compared as today. This is what makes the rate fall, the round close as `resolved`, and the badge reach green; without it FR-DR-032 can never fire and a fully-agreed unit lands in persistent discrepancy ([research.md](research.md) R2). **Do not implement this by writing submissions for both roles** — that forges the blind-independence audit trail and corrupts spec 008's `ai_suggestion_accepted` measure
- [X] T031 [US2] Re-run `pytest tests/unit/test_portal_discrepancy.py -q` after T030 and confirm every characterisation case still passes except those the overlay is specified to change. Any other movement is a regression in a function the publication chain depends on
- [X] T032 [US2] In `src/portal/reconciliation.py`: implement `close_round_if_complete(...)` per [contracts/detection-and-rounds.md](contracts/detection-and-rounds.md) §4 — when every indicator in the round's opening disputed set carries a joint answer, recompute with the overlay applied and close `resolved` when `rate <= tolerance` or `exhausted` when it does not, then close the round's work item (FR-DR-050). Completion is measured against the set that **opened** the round, not the current one, and does not require both assessors to have acted (A4)

### Routes and template

- [X] T033 [US2] In `src/portal/assessor.py`: add `GET /assessor/{cycle_id}/{portal_id}/reconcile` per [contracts/reconciliation-workspace.md](contracts/reconciliation-workspace.md) §2 — 404 for an unknown cycle or unit as `unit_form` does, then **refuse for any requester in any role** when no round is open, redirecting to the questionnaire with an explanation (FR-DR-014). For the disputed set only, return the viewing role's answer, the peer's answer, any committed joint answer, and the round's context figures. Indicators outside the disputed set are returned as settled and **without the peer's answer**
- [X] T034 [US2] In `src/portal/assessor.py`: add `POST /assessor/{cycle_id}/{portal_id}/reconcile/{question_id}/joint` per [contracts/reconciliation-workspace.md](contracts/reconciliation-workspace.md) §3, applying its five preconditions in order. A `False` return from `insert_joint_answer` is a **normal outcome**, not an error — the peer committed first, so show their answer as agreed rather than overwriting it or raising. On success call T032's closer, then redirect back to the workspace
- [X] T035 [US2] In `src/portal/assessor.py::unit_form`: redirect to `/reconcile` when `unit_reconciliation_state` is `reconciliation_open`, for both roles (FR-DR-010). Every other state — including `above_tolerance_in_progress` and `persistent_discrepancy` — renders the questionnaire exactly as today (FR-DR-008, FR-DR-035). Same file as T033–T034
- [X] T036 [US2] Create `src/portal/templates/assessor_reconcile.html` extending `base.html` (which supplies the skip link, `role="banner"`, `id="main-content"`, and `role="contentinfo"`), rendering the reciprocal side-by-side layout for the disputed set with each answer attributed to its author, the settled indicators as locked, the round's context figures, and the justification field marked as required. **Zero emoji** — use the existing SVG sprite; reuse existing `badge--*` colour tokens so the WCAG 2.2 contrast gate stays satisfiable ([contracts/reconciliation-workspace.md](contracts/reconciliation-workspace.md) §6)
- [X] T037 [US2] In `tests/unit/test_ui_quality_checks.py`: decide the workspace route's presence in `test_all_portal_routes_render_successfully`'s enumerated list **deliberately**. Its `seeded_client` fixture seeds one Assessor A submission, no B, and no round, so adding `/reconcile` to that list asserts HTTP 200 on a route required to refuse, and the failure will present as a routing bug. Either extend the fixture with a unit having both roles, both completions, and an open round — worth having regardless, since nothing else in the suite constructs one — or assert the refusal as its own case ([research.md](research.md) R11)

**Checkpoint**: two assessors can be driven from disagreement to a closed round end to end, and the rate visibly moves. This plus Phase 3 is the minimum useful release.

---

## Phase 5: User Story 3 (P1) — The system sends work back once, then stops and hands over

> **Goal**: A round that ends above tolerance leaves the unit in a persistent-discrepancy state that is distinguishable everywhere discrepancy is shown, and the system opens nothing further on its own.
>
> **Independent test**: Drive a unit through a round that leaves the rate above tolerance; verify the round closes `exhausted`, no further round opens under any number of subsequent submissions, the assessor sees the questionnaire with a handover notice rather than a workspace, and the rounds consumed and who opened each are visible.
>
> **Deliberately thin.** The cap guard (T024 step 6) and the `exhausted` classification (T032) are already built. This phase surfaces the state and proves the property; it does not re-implement it.

### Tests

- [X] T038 [P] [US3] In `tests/unit/test_reconciliation_cap.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 5's automatic half — a round ending above tolerance closes `exhausted` and the unit becomes `persistent_discrepancy`; **fifty further submissions produce no second automatic round** (SC-006); a disagreement appearing after a *resolved* round goes straight to persistent discrepancy because the automatic round is spent (FR-DR-036); leaving the unit alone changes nothing — it neither publishes, re-opens, nor lapses (FR-DR-038)

### Surfacing

- [X] T039 [US3] In `src/portal/templates/assessor_unit.html`: render the persistent-discrepancy notice when `unit_reconciliation_state` is `persistent_discrepancy` — the disagreement now sits with the Senior Reviewer, and no workspace is offered (FR-DR-035). Text and icon, never colour alone
- [X] T040 [P] [US3] In `src/portal/reconciliation.py`: add a `round_history(repo, session_id, portal_id)` helper returning each round's number, opener, actor, reason, and closure state, for the surfaces that must show how many rounds a unit has consumed and who opened each (FR-DR-031). `rounds_consumed` and `automatic_round_used` are already on T020's `UnitReconciliationState`; this is the detail behind those two counters

**Checkpoint**: `pytest tests/unit/test_reconciliation_cap.py -q` green. A persistent-discrepancy unit now waits visibly, with nowhere yet to go — which Phase 6 provides.

---

## Phase 6: User Story 4 (P1) — The Senior Reviewer decides what happens to an unresolved disagreement

> **Goal**: A persistent-discrepancy unit offers exactly two dispositions — return for another round with a stated reason, or publish with the disagreement recorded — and whichever is chosen is attributable afterwards.
>
> **Independent test**: Take a unit into persistent discrepancy, then exercise both branches: a return, verifying round 2 opens attributed to the reviewer with their reason and that the assessors are routed back; and a publish, verifying the unit publishes with the contested indicators recorded and nothing silently substituted.

### Tests

- [X] T041 [P] [US4] In `tests/unit/test_reconciliation_cap.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 5's reviewer half — a return opens round 2 with `opened_by='senior_reviewer'`, the actor, and the reason; a return without a reason is refused; a return over an **empty** current disputed set is refused with that explanation and creates no empty round; a second reviewer disposing concurrently gets the "already decided" outcome **surfaced rather than swallowed**; round 2 ending above tolerance returns the unit to persistent discrepancy with the same two options (FR-DR-039)
- [X] T042 [P] [US4] In `tests/unit/test_api_publication.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 6 — publishing over a disagreement records who decided, when, and the still-contested set; each contested indicator publishes by the stated precedence and is marked contested; and **the score is arithmetically identical** to what today's code produces for the same data. That last assertion is what keeps A5 honest — this feature makes the existing tie-break visible and attributable, and must not quietly change it

### Reviewer round

- [X] T043 [US4] In `src/portal/reconciliation.py`: implement `open_reviewer_round(repo, ..., actor_id, reason)` — requires a non-empty reason and actor, sets `opened_by='senior_reviewer'`, sets `round_number` to prior + 1, and is **not** counted against the automatic cap (A3). Refuses when the current disputed set is empty, because there is nothing to open a round over
- [X] T044 [US4] In `src/portal/admin.py::dispose`: offer the two dispositions of [contracts/detection-and-rounds.md](contracts/detection-and-rounds.md) §6 for a persistent-discrepancy item, routing each through the existing `dispose_escalation` → `record_disposition` path so both inherit its exactly-once guarantee. **Surface `dispose_escalation`'s `bool` return**, currently discarded at [admin.py:409](../../src/portal/admin.py#L409): with two dispositions leading to opposite outcomes, a losing concurrent reviewer would otherwise see a redirect identical to success, and one of the two reviewers would be wrong about what happened without being told ([research.md](research.md) R7)
- [X] T045 [US4] In `src/portal/templates/admin_escalations.html`: render the two dispositions for a persistent-discrepancy item, with the reason field marked required on the return branch, and show which round the item belongs to
- [X] T046 [US4] In `src/portal/admin.py` and `src/portal/templates/admin_project_detail.html`: for a persistent-discrepancy unit, show the still-contested indicators, both assessors' answers, any joint answers already agreed with their justification and author, and that the automatic round has been used (FR-DR-052, FR-DR-031). This is the one admin surface that reads across roles, and it is a reviewer surface rather than an assessor one — SC-011 constrains what is returned to a request made **in an assessor's role**, which this is not

### Contested publication

- [X] T047 [US4] In `src/api/finalize.py`: add `final_answer_detail(...)` returning the same value as `final_answer` plus which of the five precedence terms produced it ([data-model.md](data-model.md) §8). **`final_answer` keeps its `bool | None` signature** — both publishers depend on it and spec 008's parity guarantee rests on them sharing it
- [X] T048 [US4] In `src/portal/admin.py::publish_unit` and the REST publication path in `src/api/routers/publication.py`: fill `PublicationRecord.contested_question_ids` from `final_answer_detail`, so an indicator published over an unresolved disagreement is marked contested rather than presented as agreed (FR-DR-057). Correct [finalize.py:110-112](../../src/api/finalize.py#L110)'s docstring, which claims the chain "never invents an answer nobody gave" while [line 121](../../src/api/finalize.py#L121) returns Assessor A's answer as an unmarked stand-in for agreement — the *value* was never invented, the *agreement* was, and recording the contested set is what makes the docstring true

**Checkpoint**: the loop is closed. Every unit has a terminal path — resolved, exhausted-then-returned, or exhausted-then-published-with-the-disagreement-on-record.

---

## Phase 7: User Story 5 (P2) — A Senior Reviewer sees the true discrepancy position of every unit at a glance

> **Goal**: The project detail view distinguishes five discrepancy states plus "awaiting second assessment", names the tolerance actually in force, shows the compared count, and writes nothing.
>
> **Independent test**: Construct one unit per state, load the project page, and verify each renders distinguishably by text and icon as well as colour; then load it fifty more times and verify no row was created.

### Tests

- [X] T049 [P] [US5] In `tests/unit/test_discrepancy_badge.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 8 — six distinguishable badges; every badge names the project's tolerance and **no hard-coded `5%` remains in the template**; the awaiting-second-assessment unit shows no rate rather than 0% (FR-DR-044); every badge shows the compared count (FR-DR-045); fifty page loads leave `discrepancy_cases` and `escalation_queue_items` row counts unchanged (SC-010); and the publish-refused re-render at [admin.py:335](../../src/portal/admin.py#L335) produces the **same** badge as the normal render for the same unit

### Implementation

- [X] T050 [US5] In `src/portal/admin.py`: extract the near-duplicated `unit_rows` construction at [admin.py:143-146](../../src/portal/admin.py#L143) and [admin.py:335-338](../../src/portal/admin.py#L335) into one helper that calls `unit_reconciliation_state`. Both call sites must produce the same shape or the badge changes meaning when a publish is refused; the duplication is pre-existing, and extracting it makes the sameness structural instead of remembered
- [X] T051 [US5] In `src/portal/admin.py`: confirm both call sites still use `compute_portal_discrepancy` and **never** `recompute_` (FR-DR-007, SC-010). The read-only variant exists for exactly this and says so in its docstring at [discrepancy.py:51-55](../../src/portal/discrepancy.py#L51)
- [X] T052 [US5] In `src/portal/templates/admin_project_detail.html`: replace the two-state block at [lines 367-385](../../src/portal/templates/admin_project_detail.html#L367-L385) with the six-row state table of [contracts/badge-tolerance-and-api.md](contracts/badge-tolerance-and-api.md) §1. Delete the hard-coded `Within &le;5% Threshold` string — a project running at any other tolerance currently displays a figure that is not its tolerance, which is the exact failure FR-DR-043 forbids. Persistent discrepancy must be visually **and textually** distinct from a first-time flag (FR-DR-034)
- [X] T053 [US5] Run `pytest tests/unit/test_ui_quality_checks.py -q` and confirm the zero-emoji, WCAG 2.2 contrast, and landmark gates are all still green after T052

---

## Phase 8: User Story 6 (P2) — Agreed answers reach the Senior Reviewer as settled answers

> **Goal**: The jointly agreed answer is the value used at publication for its indicator, completion declarations survive every round, and sign-off waits while a round is open.
>
> **Independent test**: Reconcile a unit whose disputed indicators had A and B differing, then inspect the answer used at sign-off and publication for each — it is the joint value, never either original. Separately, open and close a round on a unit both assessors have declared complete and verify both declaration rows are byte-identical afterwards.

### Tests

- [X] T054 [P] [US6] In `tests/unit/test_assessor_completion.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 7 — opening, closing, and re-opening a round leave both `AssessorCompletion` rows byte-identical and neither assessor is asked to re-declare (FR-DR-058); `publication_readiness` reports not-ready while a round is open with a reason naming the reconciliation (FR-DR-059); **every pre-existing `blocking_reason` string is unchanged** and a unit blocked on outstanding indicators still reports that first; and readiness returns to its prior value once the round closes
- [X] T055 [P] [US6] In `tests/unit/test_api_publication.py`: assert `final_answer` returns the joint value for every reconciled indicator, in preference to either original (FR-DR-051, SC-005)

### Implementation

- [X] T056 [US6] In `src/api/finalize.py::final_answer`: insert the joint-answer term as position 2 of the precedence chain per [data-model.md](data-model.md) §8 — after Senior Reviewer arbitration, before the both-agree case. Positions 1, 3, 4, and 5 are unchanged
- [X] T057 [US6] In `src/api/finalize.py::publication_readiness`: add exactly one condition — a unit with an open reconciliation round is not ready, whatever its completion state (FR-DR-059). Evaluate it **after** the existing conditions so a unit blocked for both reasons reports the completion problem first; that is the one the assessors can act on. Implement it as a **separate condition, never as a revocation of a completion declaration** — revoking would be the natural implementation and would violate FR-DR-058 silently
- [X] T058 [US6] In `src/portal/reconciliation.py`: assert structurally that a resolved reconciliation cannot be silently re-resolved with different answers by a later action (FR-DR-054) — a closed round is never reopened, a new round is always a new row, and the disposition path is already covered by `record_disposition`'s `UNIQUE(item_id)`. Add the test to `tests/unit/test_joint_answers.py` rather than new production code if no gap is found

---

## Phase 9: User Story 7 (P2) — A project runs to a tolerance other than 5%

> **Goal**: A Senior Reviewer sets a project's tolerance from the portal while it runs; the next comparison uses it; other projects are unaffected; and the change is recorded with its previous value.
>
> **Independent test**: Set two projects to different tolerances and verify the same rate flags under one and not the other in the same process with no restart, that comparisons recorded under the old figure still report the old figure, and that 0% is honoured while 101% is rejected.
>
> The resolver these tasks configure was built in Phase 2 (T015–T017); this phase adds the way to change what it reads.

### Tests

- [X] T059 [P] [US7] In `tests/unit/test_project_tolerance.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 9 — an unset project uses 5%; two projects at different tolerances judge the same rate differently in one process with no restart; **changing project X does not change project Y's outcome** (assert explicitly, since a helper caching one value module-wide is the natural regression); 0% flags any disagreement and is not treated as unset; 101% and a negative value are rejected with the previous value standing; the change records who, when, and the previous value, with a first change from an inheriting project recording "inheriting" rather than 5%; and a `DiscrepancyCase` recorded under the old tolerance still reports the old tolerance

### Implementation

- [X] T060 [US7] In `src/portal/admin.py`: add `POST /admin/projects/{cycle_id}/tolerance` per [contracts/badge-tolerance-and-api.md](contracts/badge-tolerance-and-api.md) §2 — validates 0–100 inclusive and rejects anything outside it with the previous value standing (FR-DR-064), writes `SurveyCycle.discrepancy_rate_threshold`, and appends a `tolerance_changes` row carrying the previous value (FR-DR-066). `0` is valid and must **not** be coerced to "unset" — the `None`/`0.0` distinction is the entire reason the field is nullable (FR-DR-065)
- [X] T061 [US7] In `src/portal/admin.py`: correct the two false comments at [admin.py:221](../../src/portal/admin.py#L221) and [admin.py:240](../../src/portal/admin.py#L240) that read `# append-only superseding cycle record`. `insert_cycle` is an upsert on a `cycle_id PRIMARY KEY` ([repositories.py:51-57](../../src/shared/persistence/repositories.py#L51)) that destroys the previous value — which is precisely why T060 needs a separate history table ([research.md](research.md) R4). Same file as T060
- [X] T062 [US7] In `src/portal/templates/admin_project_detail.html`: add the tolerance control, showing the value in force and whether it is inherited or explicitly set
- [X] T063 [US7] In `src/portal/reconciliation.py`: on a tolerance change, close any open round whose unit now falls within the new tolerance as **`not_required`**, not as `resolved` (FR-DR-037). The distinction is not cosmetic — `resolved` would record that the assessors agreed when the threshold simply moved, which is a false audit statement about people ([data-model.md](data-model.md) §1)
- [X] T064 [US7] In `specs/001-ekap-aiq-assessment/contracts/configuration.md`: add the per-project tolerance and the now-validated `human_discrepancy_rate_threshold` to the parameter table with defaults, ranges, and requirement ids (FR-DR-060–066), following spec 008's precedent — `settings.py`'s docstring points at that table as the full parameter reference

---

## Phase 10: Polish and cross-cutting concerns

- [X] T065 [P] In `src/api/schemas.py`: add the discrepancy state response model of [contracts/badge-tolerance-and-api.md](contracts/badge-tolerance-and-api.md) §3. **No field capable of holding an answer** — disputed *identifiers* only. Verify this by reading the model's fields, not by intending not to populate one
- [X] T066 In `src/api/routers/discrepancy.py`: implement `GET /cycles/{cycle_id}/units/{portal_id}/discrepancy` under the existing router-level `X-API-Key` dependency, returning `unit_reconciliation_state`'s projection so the API and the portal cannot disagree about a unit's state (FR-DR-071). `awaiting_second_assessment` returns `null` for the rate rather than `0.0` — zero means full consensus and the two must never be conflated
- [X] T067 In `src/api/app.py`: register the new router alongside the six existing `include_router` calls at [app.py:31-36](../../src/api/app.py#L31)
- [X] T068 [P] In `tests/unit/test_api_contract.py`: assert `GET .../discrepancy` returns the same `state` value the badge shows for the same unit, and that the response contains no answer from either role
- [X] T069 [P] In `tests/unit/test_api_human_blindness.py`: extend the existing raw-response-text technique across every route in [contracts/reconciliation-workspace.md](contracts/reconciliation-workspace.md) §4's table — the questionnaire, the project detail page, `GET /human-answers`, and the new discrepancy endpoint — **in both roles**, asserting the peer's distinguishing notes and actor id are absent. Only `/reconcile` may return a peer answer, and only for an indicator in the open round's disputed set. This is SC-011 mechanised
- [X] T070 In `tests/unit/test_api_contract.py`: drive a unit end to end **through the REST API only** — submissions and both completions — and assert its round opens exactly as the portal path's does (FR-DR-070). This is the only test that catches a missing T026, and every portal test passes without it
- [X] T071 [P] In `src/portal/seed.py`: seed one unit per badge state — full consensus, within tolerance, above tolerance in progress, reconciliation open, and persistent discrepancy — since nothing else in the tree constructs them and both T049 and T028 need that fixture shape ([contracts/badge-tolerance-and-api.md](contracts/badge-tolerance-and-api.md) §4)
- [X] T072 [P] In `src/review/escalations.py`: leave `portal_discrepancy_cases()`'s `scope="portal"` query at [escalations.py:79](../../src/review/escalations.py#L79) **unchanged**, and add a comment recording that the engine writes `"portal_human"` so the two do not match. This is a pre-existing inconsistency deliberately out of scope ([research.md](research.md) R12); fixing it silently inside this feature would change what an unrelated admin view lists, in a commit nobody would think to review for that
- [X] T073 Run the full suite from the repo root: `pytest -q`. Compare against T001's baseline — the count rises by the new tests and nothing previously green has gone red
- [X] T074 Walk [quickstart.md](quickstart.md) scenarios 0–10 in order against a fresh database via `aiq serve` and the seeded demo data, confirming each expectation by hand as well as by test
- [X] T075 Run `graphify update .` from the repo root to refresh `graphify-out/graph.json`, which is stale as of this feature's planning ([plan.md](plan.md) Notes)
- [X] T076 Re-read [plan.md](plan.md)'s Constitution Check table against the implemented code and confirm all eight gates still hold — in particular that no route outside `/reconcile` reads across roles, that no display path in `src/portal/admin.py` calls `recompute_`, and that `joint_answers` and `tolerance_changes` have no mutator in `src/shared/persistence/repositories.py`

---

## Dependencies

```
Phase 1 (Setup + characterisation)
   │   T002 is a hard gate — nothing proceeds until it is green
   ▼
Phase 2 (Foundational: tables, entities, repos, tolerance resolver, projection)
   │   blocks every story phase
   ▼
Phase 3 (US1 — detection, the completion gate, round opening)   ◀── MVP
   │
   ▼
Phase 4 (US2 — workspace, joint answers, the overlay)
   │        │
   │        └──▶ Phase 8 (US6 — publication precedence, sign-off gate)
   ▼
Phase 5 (US3 — persistent discrepancy surfaced)
   │
   ▼
Phase 6 (US4 — reviewer dispositions, contested publication)
   │
   ▼
Phase 10 (Polish)

Phase 7 (US5 — badge)   depends only on Phase 2's projection; may run
                        alongside Phases 5–6 once Phase 4 has landed

Phase 9 (US7 — setting the tolerance)   depends only on Phase 2;
                        may run alongside Phases 5–8
```

**Story-level dependencies:**

| Story | Depends on | Why |
|---|---|---|
| US1 | Phase 2 | the rounds table, the projection, and the resolver |
| US2 | US1 | a round must be able to open before a workspace can show one |
| US3 | US2 | a round must be able to close before exhaustion means anything |
| US4 | US3 | the reviewer acts on a persistent-discrepancy unit |
| US5 | Phase 2 only | reads the projection; independent of the round machinery |
| US6 | US2 | joint answers must exist before they can take precedence |
| US7 | Phase 2 only | the resolver is already in place; this adds the setter |

**Cross-story note**: US6's Phase 8 could begin as soon as Phase 4 lands, in parallel with Phases 5–7. It is placed after them only to keep P1 stories ahead of P2 ones.

---

## Parallel Execution Examples

**Phase 1** — after T001 and T002 (the gate) complete, five tasks are independent:

```
T003 (src/portal/reconciliation.py)      ┐
T004 (src/portal/tolerance.py)           ├── all different files
T005 (src/api/routers/discrepancy.py)    │
T006 (six new test scaffolds)            │
T007 (tests/unit/conftest.py)            ┘
```

**Phase 2** — T018/T019 (config validation) run alongside the schema and repository work. T011–T013 all edit `repositories.py` and must sequence. T015–T017 are one atomic group and cannot be split.

**Phase 3** — T021 and T022 both edit `test_reconciliation_rounds.py`, so only T021 carries `[P]`; they cover disjoint scenarios and can be split between two people who coordinate on the file. T024–T027 are one atomic group and cannot be split.

**Phase 4** — T028 and T029 are different test files and fully parallel. T030 (the overlay) must precede T032 (the closer). T033–T035 all edit `assessor.py` and sequence; T036 (the template) is parallel with all three.

**Phase 6** — T041 and T042 are different test files and parallel. T043 (`reconciliation.py`) is parallel with T047 (`finalize.py`). T044–T046 touch `admin.py` and its templates and sequence.

**Phase 10** — T065, T068, T069, T071, and T072 are all different files and fully parallel. T066 depends on T065, and T067 on T066.

---

## Independent Test Criteria

| Story | Independently testable by |
|---|---|
| US1 | two assessors, a controlled disagreement rate, and the completion declarations — **no workspace required** |
| US2 | a hand-seeded open round via T007's factory — **no completion flow required** |
| US3 | one round driven to closure above tolerance, then fifty further submissions |
| US4 | a unit placed in persistent discrepancy, then each disposition exercised separately |
| US5 | six hand-constructed units, one per state, and repeated page loads |
| US6 | a reconciled unit inspected at `final_answer` and at `publication_readiness` |
| US7 | two projects at different tolerances, in one process, judging the same rate |

---

## Format Validation

All 76 tasks follow `- [ ] Tnnn [P?] [USn?] description with file path`. Story labels appear on Phase 3–9 tasks only; Setup, Foundational, and Polish tasks carry none. No task marked `[P]` shares a file with another `[P]` task in the same phase.
