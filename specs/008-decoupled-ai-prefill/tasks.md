# Tasks: Decoupled AI Prefill

**Feature**: `008-decoupled-ai-prefill`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [plan.md](plan.md) | [research.md](research.md) | [data-model.md](data-model.md) | [contracts/prefill-pipeline.md](contracts/prefill-pipeline.md) | [contracts/completion-and-publication.md](contracts/completion-and-publication.md) | [contracts/rest-api-additions.md](contracts/rest-api-additions.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-08-19

## Conventions

- `[P]` = parallelizable (different file, no dependency on an incomplete task in this list). Two tasks editing the same file are never both marked `[P]`.
- `[USn]` = belongs to User Story n's phase (spec.md priorities: US1=P1, US2=P1, US3=P2, US4=P2, US5=P2, US6=P3). Setup, Foundational, and Polish tasks carry no story label.
- **No new dependency.** The resolver uses the existing `ModelProvider`; everything else is stdlib or already declared in `pyproject.toml` ([plan.md](plan.md) Technical Context).
- **`agents/adjudicator/agent.py` is never edited by any task below.** Its decision table and its test file stay byte-identical ([research.md](research.md) R3) — that boundary is what makes the spec 001 FR-028 supersession safe.
- **`shared/tools/linkresolution/**` is never edited by any task below.** The cascade already satisfies FR-PF-014–016; only what happens after it returns `None` changes.
- Two files are added beyond [plan.md](plan.md)'s Project Structure list, both deliberate and noted at their task: `src/orchestration/prefill_writer.py` (extracted so `scheduler.py` has one prefill-writing seam rather than nine call sites) and `src/agents/resolver/__init__.py`.

---

## Implementation Strategy

Nine increments. Two ordering choices below deviate from a naive priority walk, and both are deliberate:

1. **Increment 1** (Phase 1): Scaffolding only — empty modules and test files. No behavior change.
2. **Increment 2** (Phase 2, Foundational): The fourth terminal state and everything it touches, the two new tables, the reason taxonomy, and the two settings. Largest phase, because this feature's machinery is shared rather than per-story. **Nothing in Phases 3–8 can start until it lands.**
3. **Increment 3** (Phase 3, US1 — P1, the MVP): The human side, end to end. Testable against hand-seeded `prefills` rows with no pipeline change at all — an assessor sees suggestions from the real table, cannot leave an indicator blank, must declare completion, and publication refuses without it.
4. **Increment 4** (Phase 4, US2 — P1): The pipeline runs to completion alone and creates no human work item. **US4's resolver is not yet built at the end of this phase**, so a disagreement terminates as a `unresolved_disagreement` no-suggestion prefill. That is a spec-legal outcome (FR-PF-026d), not a broken intermediate state — the run still completes unattended, still covers every indicator, and still queues nothing. Increment 5 upgrades those indicators from "not settled" to "settled".
5. **Increment 5** (Phase 5, US4 — P2): Agreement classification and the resolver agent. Contested indicators start producing settled answers.
6. **Increment 6** (Phase 6, US5 — P2): The second validation gate and the reason taxonomy proven end to end. **The gate is deliberately not in Increment 4**, where a resolved position reaches the prefill ungated — an intermediate state that over-delivers rather than under-delivers, and one no external surface sees, since a run is triggered by an operator rather than shipped to users.
7. **Increment 7** (Phase 7, US3 — P2): The cascade's supplying source and attempt history recorded onto the prefill. Small, because the cascade itself is already built and correct.
8. **Increment 8** (Phase 8, US6 — P3): Re-running, the latest-prefill selection rule, and the per-run spend cap.
9. **Polish** (Phase 9): Supersession annotations in the three affected specs, full regression, the seed walkthrough, one real budget-spending run, and the resolver-bias check.

---

## Phase 1: Setup

> Goal: Create empty modules and test scaffolds. No behavior change, no import from an incomplete module.

- [x] T001 Create `src/agents/resolver/__init__.py` with a module docstring stating that this package settles *answer* disagreements between two already-validated assessor positions, that it is distinct from `agents/adjudicator/` (mechanical, no model call) and from `portal/discrepancy.py` (human A/B), and that it deliberately takes no browser so a third independent opinion is inexpressible ([research.md](research.md) R5)
- [x] T002 [P] Create `src/agents/adjudicator/agreement.py` as a scaffold with the module docstring explaining that it maps `adjudicate()`'s output onto FR-PF-023–027 without modifying `adjudicate()` itself, and why (R3)
- [x] T003 [P] Create `src/orchestration/budget.py` as a scaffold with the module docstring explaining that per-run spend is accumulated in-process rather than queried from `cost_ledger`, because `ensure_session()` is per-cycle and two concurrent units of one cycle share a `session_id` (R7)
- [x] T004 [P] Create `src/orchestration/prefill_writer.py` as a scaffold — the single seam through which every pipeline exit writes a `prefills` row. (One file beyond plan.md's Project Structure list: `scheduler.py` has nine distinct exit paths and giving each its own insert would make the "every indicator ends with a prefill record" invariant unverifiable by reading)
- [x] T005 [P] Create `src/api/routers/prefills.py` and `src/api/routers/completions.py` as empty router scaffolds returning `APIRouter()`
- [x] T006 [P] In `tests/unit/conftest.py`: add fixtures this feature's tests share — a `seeded_prefills` factory that inserts `prefills` rows directly (so US1 is testable with no pipeline run), a `stub_provider` returning scripted structured outputs for the assessor/validator/resolver nodes, and a `completed_unit` factory writing both roles' submissions plus completion rows for every question on a unit. Extend the existing file; do not replace its spec 007 fixtures
- [x] T007 Create the seven new test modules as scaffolds, each with a `@pytest.mark.unit` module marker: `tests/unit/test_prefill_pipeline.py`, `tests/unit/test_prefill_reasons.py`, `tests/unit/test_agreement_and_resolver.py`, `tests/unit/test_final_validation_gate.py`, `tests/unit/test_assessor_completion.py`, `tests/unit/test_prefill_reruns.py`, `tests/unit/test_prefill_budget.py`

---

## Phase 2: Foundational — the fourth terminal, the two tables, the taxonomy

> Goal: Everything every story phase depends on. **Must complete before Phase 3.**
>
> **T008–T015 are one atomic group.** The transition table cannot permit `NO_SUGGESTION` before the enum defines it, and the five consumer sites will misreport any unit in the new state until they are widened — resume would re-dispatch it, job progress would never reach 100%, and results would report the run incomplete. Land them together, in one commit, and use T015 as the completion check.

### The fourth terminal state (R1)

- [x] T008 In `src/shared/state/entities.py`: add `NO_SUGGESTION = "no_suggestion"  # terminal` to `UnitState` and extend `TERMINAL_UNIT_STATES` to the four-member frozenset per [data-model.md](data-model.md) §3. Add a comment on `ESCALATED` recording that it is retained for historical rows and for `review/seed_demo.py`, and is no longer reachable from the pipeline
- [x] T009 In `src/shared/state/unit_state.py`: apply the revised transition table from [data-model.md](data-model.md) §3 — remove every inbound edge to `ESCALATED`, add `NO_SUGGESTION` as a successor of `RESOLVED`, `ASSESSING`, `ADJUDICATING`, and `RETRYING`, and give `NO_SUGGESTION` an empty successor set. Update the module docstring's "Exactly three terminal states" sentence to four, naming which one is unreachable and why
- [x] T010 In `src/shared/state/unit_state.py::assert_exhaustive_terminal_coverage`: keep both existing assertions and **add a third** — each of `DELIVERED`, `UNASSESSABLE`, `NO_SUGGESTION` must be reachable from `PENDING` by BFS. Without it, "every non-terminal reaches *a* terminal" would be satisfied by a delivery-only machine, which is what FR-PF-032d exists to prevent
- [x] T011 In `tests/unit/domain/test_unit_state.py`: amend `test_exactly_three_terminal_states` to the four-member set, rename it to `test_exactly_four_terminal_states`, and add `test_every_prefill_terminal_is_reachable` covering T010's new assertion. **This is a spec 001 SC-009 invariant test — the amendment must be strictly stronger than what it replaces, and the commit message must say so.** Add a test asserting `ESCALATED` has zero inbound edges, so its unreachability is pinned rather than incidental
- [x] T012 [P] In `src/shared/state/resume.py:41`: replace the inline `(DELIVERED, ESCALATED, UNASSESSABLE)` tuple with an import of `TERMINAL_UNIT_STATES`
- [x] T013 [P] In `src/review/unlock.py:23`: replace `_TERMINAL = {...}` with `TERMINAL_UNIT_STATES` imported from `shared.state.entities`
- [x] T014 [P] In `src/portal/admin.py:88`, `src/api/jobs.py:86`, and `src/api/routers/assessments.py:133`: replace each inline terminal set with the imported `TERMINAL_UNIT_STATES`. Three files, no overlap with any other task in this phase
- [x] T015 Verify the widening is complete: `grep -rn "UNASSESSABLE" src/ | grep -i "escalated"` returns zero hits outside `entities.py`, `unit_state.py`, and `seed_demo.py`. Any remaining literal triple is a site that will misreport a `no_suggestion` unit

### The reason taxonomy (R11)

- [x] T016 [P] In `src/shared/state/entities.py`: add the `PrefillReason` enum with exactly the nine members of [data-model.md](data-model.md) §4. **Do not add members to `EscalationReason`** — it stays frozen at seven so historical rows, `tests/unit/test_reason_tags.py`, and `tests/unit/test_blank_field_fallback.py` keep working
- [x] T017 In `src/shared/state/reason_tags.py`: add `PREFILL_REASON_TAGS` (one template per `PrefillReason` member) and `prefill_reason_tag(reason: str) -> ReasonTag`, mirroring `reason_tag()`'s contract including its deliberate `KeyError` on an unmapped value. Leave `reason_tag()` and `REASON_TAGS` untouched, and add `UnitState.NO_SUGGESTION.value` to `BLOCKED_UNIT_STATES`
- [x] T018 [P] In `tests/unit/test_reason_tags.py`: add a parametrized test covering all nine `PrefillReason` members and one asserting `prefill_reason_tag("not_a_reason")` raises `KeyError`. Do not modify the existing `reason_tag` tests

### Entities

- [x] T019 In `src/shared/state/entities.py`: add the `Prefill` and `AssessorCompletion` dataclasses per [data-model.md](data-model.md) §1–2. `Prefill.__post_init__` MUST enforce validation rule 1 — `suggested` true ⟺ `answer` non-null and `reason` null, and false ⟺ the reverse — so SC-008's invariant is a constructor property, not a convention
- [x] T020 [P] In `src/agents/adjudicator/agreement.py`: define the `AgreementOutcome` frozen dataclass, and in `src/agents/resolver/schema.py` define `ResolverDecision` per [data-model.md](data-model.md) §5. `ResolverDecision` MUST enforce `undetermined ⟺ selected_run_id is None`, which is what makes "never picks arbitrarily" (FR-PF-026d) a type-level property

### Persistence (R2, R8)

- [x] T021 In `src/shared/persistence/schema.py`: add the `prefills` and `assessor_completions` tables and their three indexes exactly as given in [data-model.md](data-model.md) §1–2, each with the DDL comment stating it is append-only. Place them after `publication_records` and before the index block
- [x] T022 In `src/shared/persistence/repositories.py`: add `insert_prefill`, `latest_prefill(session_id, question_id, portal_id)`, and `list_prefills_for_run(run_id)`. `latest_prefill` applies the selection rule of [contracts/prefill-pipeline.md](contracts/prefill-pipeline.md) §6 — newest row of the newest *completed* run when one exists, newest row overall when no run has completed yet, so an in-flight first run's partial output is visible while a re-run never flickers
- [x] T023 In `src/shared/persistence/repositories.py`: add `insert_assessor_completion` and `latest_assessor_completion(session_id, portal_id, role)`. Neither table gets an update or delete method — completeness is derived (R8), and adding a mutator would invite the append-only violation the derivation exists to avoid
- [x] T024 [P] In `src/shared/persistence/serialization.py`: confirm `PrefillReason` and the new dataclasses round-trip through `to_json`/`from_json` as the existing enums do; add handling only if the enum-as-`str` path does not already cover them

### Configuration

- [x] T025 In `src/shared/config/settings.py`: add `prefill_confidence_gap_tolerance: int = 10` and `prefill_run_budget: float = 0.0` under a new `# --- Prefill pipeline (spec 008) ---` heading, with `_ENV_MAP` entries `("AIQ_PREFILL_CONFIDENCE_GAP_TOLERANCE", int)` and `("AIQ_PREFILL_RUN_BUDGET", float)`. Neither is a secret, so `as_dict()` masking is unchanged
- [x] T026 [P] In `src/shared/config/validation.py::validate_settings`: append errors for `prefill_confidence_gap_tolerance < 0` and `prefill_run_budget < 0.0`, following the existing threshold-validation pattern. `0.0` is valid and means uncapped (FR-PF-041c)
- [x] T027 [P] In `specs/001-ekap-aiq-assessment/contracts/configuration.md`: add both parameters to the table with defaults, ranges, and the requirement ids (FR-PF-029, FR-PF-041c) — `settings.py`'s docstring points at that table as the full parameter reference

---

## Phase 3: User Story 1 (P1) — The assessor starts from a prefill and keeps full authority

> **Goal**: An assessor sees the real pipeline's suggestions, can take or ignore any of them freely, cannot leave an indicator blank, must explicitly declare completion, and no unit publishes without that declaration.
>
> **Independent test**: Seed `prefills` rows directly (T006's fixture) with no pipeline run at all. Accept some suggestions unchanged, modify others, answer the rest independently; confirm every recorded submission is exactly what was entered, that no untouched question acquired an answer, that completion is refused while an indicator is outstanding and names it, and that publish is refused until both roles declare.
>
> **This phase is the MVP** and depends on nothing in Phases 4–8.

### Tests

- [x] T028 [P] [US1] In `tests/unit/test_assessor_completion.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 5's six-row table — refusal names outstanding indicators, all-answered-but-undeclared is not publishable, declaring records role/actor/timestamp, revising after declaring keeps the unit complete, adding an indicator after declaring reverts it, and re-declaring writes a second row without mutating the first
- [x] T029 [P] [US1] In `tests/unit/test_api_publication.py`: extend with the failing tests for [quickstart.md](quickstart.md) scenario 6 — a fully-prefilled unit with zero human answers publishes nothing and `final_answer` returns `None` for every question; a published unit's breakdown has exactly `len(questions)` entries; portal and API publish produce identical score and breakdown

### Read the real prefill, not the heuristic rows (R10)

- [x] T030 [US1] In `src/portal/assessor.py::unit_form` (lines 51-56): replace the `agent_index == -1` scan with `r.latest_prefill(session_id, q.question_id, portal_id)` and build the `PrefillView` projection of [data-model.md](data-model.md) §8 for each row
- [x] T031 [US1] In `src/portal/assessor.py::submit` (lines 81-85): replace the same scan so `ai_suggested_answer` and `ai_suggestion_accepted` record what the assessor actually saw. **Must land in the same change as T030** — moving only the display would record acceptance against a suggestion never shown, corrupting SC-012's measure silently and retroactively (R10)
- [x] T032 [P] [US1] In `src/api/routers/human.py` (lines 70-76): apply the same replacement for the programmatic submit path. Request and response shapes are unchanged ([contracts/rest-api-additions.md](contracts/rest-api-additions.md) §5)
- [x] T033 [P] [US1] In `src/shared/state/entities.py::HumanAssessorSubmission`: correct the docstring's "records what the heuristic pre-fill proposed" to name the pipeline prefill. Left as-is it would document the opposite of what T030–T032 make the code do

### Completion declaration (R8)

- [x] T034 [US1] In `src/api/finalize.py`: add `RoleCompletion`, `PublicationReadiness`, and `publication_readiness(repo, session_id, cycle_id, portal_id)` per [contracts/completion-and-publication.md](contracts/completion-and-publication.md) §2. Completeness is the **conjunction** of a declaration row and live per-question coverage — never a stored boolean, never either half alone. `blocking_reason` names the role and the outstanding indicators; it is never a generic refusal
- [x] T035 [US1] In `src/api/finalize.py::final_answer`: delete both AI fallback branches (lines 33-45) so the chain ends `return None` after the two single-role branches. Update the docstring — its "never invents an answer nobody gave" claim was untrue in exactly the branches being removed, and is now simply true. **Sequencing: T034 must land before or with this task** — deleting the fallbacks without the readiness gate in place is the one genuinely dangerous intermediate state in this feature, silently switching published scores to partial-coverage denominators ([plan.md](plan.md) Post-Design item 2)
- [x] T036 [US1] In `src/portal/assessor.py`: add a `POST /assessor/{cycle_id}/{portal_id}/complete` route applying [contracts/completion-and-publication.md](contracts/completion-and-publication.md) §3's preconditions in evaluation order, writing one `assessor_completions` row on success and re-rendering with the outstanding indicators named on refusal. Add the answered/total progress figures to `unit_form`'s context (FR-PF-005h)
- [x] T037 [US1] In `src/portal/templates/assessor_unit.html`: render the prefill's suggestion, confidence, justification, evidence URL, and supplying source per question; render `reason_text` and an empty answer field for a no-suggestion prefill; render an empty suggestion area when no prefill exists at all; add the progress indicator and the complete button, disabled while any indicator is outstanding. **No "accept all" control and no default-accept on completion** — both are Out of Scope / FR-PF-009a

### Publication gate (R9)

- [x] T038 [US1] In `src/portal/admin.py::publish_unit`: call `publication_readiness` first and re-render the project page with `blocking_reason` when it is not ready. The score arithmetic below it is unchanged — only what can reach it changes
- [x] T039 [P] [US1] In `src/api/routers/publication.py::publish_unit`: apply the same gate, raising the new `assessment_incomplete` 409 with the per-role details body of [contracts/rest-api-additions.md](contracts/rest-api-additions.md) §3
- [x] T040 [P] [US1] In `src/portal/templates/admin_project_detail.html`: show per-role declaration state and the blocking reason on each unit row, so a reviewer sees why publish is unavailable rather than finding out by clicking

### Programmatic parity for this story (FR-PF-042–046)

- [x] T041 [P] [US1] In `src/api/schemas.py`: add the request/response models for `GET .../prefills`, `POST .../completions`, `GET .../completions`, and the two new error codes `incomplete_assessment` and `assessment_incomplete`, matching the bodies in [contracts/rest-api-additions.md](contracts/rest-api-additions.md) §1–3, §6
- [x] T042 [US1] In `src/api/routers/prefills.py`: implement `GET /cycles/{cycle_id}/units/{portal_id}/prefills` per [contracts/rest-api-additions.md](contracts/rest-api-additions.md) §1. **Deliberately takes no `role` query parameter and returns no human submission** — a prefill is identical for both roles (FR-PF-012), so accepting one would imply a scoping that does not exist. One entry per question currently in the cycle, always
- [x] T043 [US1] In `src/api/routers/completions.py`: implement `POST` and `GET /cycles/{cycle_id}/units/{portal_id}/completions` per [contracts/rest-api-additions.md](contracts/rest-api-additions.md) §2. The `GET` returns per-role *counts* and outstanding ids, never answers — a role's answers are exactly what the other role must not see
- [x] T044 [US1] In `src/api/app.py::build_api_router`: include both new routers so they inherit the existing router-level `X-API-Key` dependency. No separate authentication mechanism is introduced (FR-PF-048)

### Seeds — the demo breaks the moment T038 lands

- [x] T045 [P] [US1] In `src/portal/seed.py`: write `prefills` rows in place of the `agent_index == -1` heuristic rows for every seeded unit, and write both roles' submissions plus an `assessor_completions` row per role for every unit the seed publishes. `agents/prefill/heuristic.py` stays as the fast free generator; only its output destination changes
- [x] T046 [P] [US1] In `src/review/seed_demo.py`: write `assessor_completions` rows for every unit it publishes, and keep its six deliberate `UnitState.ESCALATED` units unchanged — they are historical-row coverage and must keep rendering through `reason_tag()`

### Verification

- [x] T047 [US1] In `tests/unit/test_api_human_blindness.py`: extend the existing matrix to cover the prefill endpoint — assert its response body contains no submission from either role and no `role` field, across a unit where A and B have submitted different answers to the same questions
- [x] T048 [US1] Run `pytest tests/unit/test_assessor_completion.py tests/unit/test_api_publication.py tests/unit/test_api_human_blindness.py -q` — T028, T029, and T047 now pass

---

## Phase 4: User Story 2 (P1) — The prefill is produced end to end with no human involvement

> **Goal**: A run over a whole questionnaire completes on its own, produces one prefill record per indicator, and adds nothing to any human queue.
>
> **Independent test**: Trigger a run for a unit whose indicators include confident answers, agent disagreement, and no usable evidence. Run it with no human interacting and confirm it terminates on its own, that every indicator has a prefill record, and that no human work item was created.
>
> **At the end of this phase a disagreement terminates as `unresolved_disagreement`** — a spec-legal outcome (FR-PF-026d), not a broken state. Phase 5 upgrades those to settled answers. Every US2 acceptance scenario except scenario 2's "settles it" half passes here.

### Tests

- [x] T049 [P] [US2] In `tests/unit/test_prefill_pipeline.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 1 — the run reaches a terminal job state alone; zero `escalation_queue_items` rows are created during it; no unit it touched is `ESCALATED`; and `count(prefills WHERE run_id=R) == count(questions)`. These are [contracts/prefill-pipeline.md](contracts/prefill-pipeline.md) §7's three properties, and one fixture proves all three for every reason at once

### The prefill-writing seam

- [x] T050 [US2] In `src/orchestration/prefill_writer.py`: implement `write_prefill(repo, run_id, session_id, cycle_id, question_id, portal_id, *, suggestion=None, reason=None, terminal_state, **payload)` — constructs a validated `Prefill`, inserts it, and advances the unit to `terminal_state`. Enforces [data-model.md](data-model.md) §1 rules 3 and 4: `terminal_state` is one of the three prefill terminals, and `unassessable` pairs only with `no_usable_evidence`

### Rewrite the pipeline's exits (R1, R4)

- [x] T051 [US2] In `src/orchestration/scheduler.py::process_unit`: replace the `escalate()` closure with a `no_suggestion()` closure calling `write_prefill`. **Delete the `repo.insert_escalation(...)` call entirely** — after this, `portal/discrepancy.py` is the only writer of `escalation_queue_items` in the codebase, which is where it belongs. Map each existing escalation site to its `PrefillReason` per [data-model.md](data-model.md) §4: `NO_USABLE_URL` → `no_usable_evidence`/`unassessable`, `REQUIRES_AUTHENTICATED_ACCESS` → `access_boundary`, `LANGUAGE_NOT_SUPPORTED` → `unsupported_language`, `UNVERIFIABLE_TARGET` → `insufficient_positions`
- [x] T052 [US2] In `src/orchestration/scheduler.py::process_unit`: remove the `run_adjudication_retry_loop` call and its escalation branch (lines 342-390), replacing it with a direct single adjudication over the validated runs. Both of the loop's triggers are settled elsewhere now (R4). Leave `run_adjudication_retry_loop` and `_describe_disagreement` in `orchestration/routers/retry_loops.py` — the latter is reused verbatim by the resolver in Phase 5, and the validation retry loop in the same module is untouched
- [x] T053 [US2] In `src/orchestration/scheduler.py::process_unit`: on a successful adjudication, write a delivered prefill carrying answer, confidence, justification, evidence URL, and `position_run_ids`; on `answers_differ`, write an `unresolved_disagreement` no-suggestion prefill (Phase 5 replaces this branch); add `assessment_failure` and `evidence_unreachable` exits for the both-agents-raised and unfetchable-evidence cases the current code does not distinguish
- [x] T054 [US2] In `src/orchestration/scheduler.py::run_batch` and `process_unit`: thread a `run_id` parameter through so every prefill row is attributed to the job that produced it. Default it to a generated id when called from the CLI, which has no job row

### Run identity and summary (R12)

- [x] T055 [P] [US2] In `src/portal/live_prefill.py` and `src/api/runner.py`: pass the `assessment_jobs.job_id` into `run_batch` as the `run_id`. No signature change beyond that parameter
- [x] T056 [US2] In `src/api/jobs.py`: add `prefill_run_summary(repo, job_id)` returning the `PrefillRunSummary` projection of [data-model.md](data-model.md) §8, grouped from `prefills` at read time and never stored (R12). Include it in the job status response
- [x] T057 [P] [US2] In `src/portal/templates/admin_project_detail.html`: show the run summary — suggested count and per-reason counts — on the unit's run status area (FR-PF-041)

### Verification

- [x] T058 [US2] Run `pytest tests/unit/test_prefill_pipeline.py -q` — T049's three properties pass. Then run the full suite and confirm no pre-existing test regressed; `tests/unit/test_adjudicator.py` in particular must still pass untouched

---

## Phase 5: User Story 4 (P2) — Two assessors in parallel, and a resolver settles what they dispute

> **Goal**: Agreement is classified, a confidence gap no longer blocks delivery, and a genuine answer disagreement is settled by a dedicated agent into exactly one suggestion.
>
> **Independent test**: For indicators engineered to produce agreement, agreement with a wide confidence gap, and outright disagreement, confirm the two agents ran concurrently and independently, that only validated positions counted, that the resolver was invoked on exactly the disagreements, and that every indicator ended with exactly one suggested answer.
>
> Ordered before US5 despite equal priority: US5's gate validates *the resolved position*, which does not exist until this phase produces one.

### Tests

- [x] T059 [P] [US4] In `tests/unit/test_agreement_and_resolver.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 3's six-row table plus the two run-level assertions — the resolver call count equals the `answers_differ` count exactly (FR-PF-026a), and every indicator producing a suggestion produced exactly one answer, never a list (SC-006a). `classify_agreement` is pure, so most of this is table-driven with no I/O

### Agreement classification (R3)

- [x] T060 [US4] In `src/agents/adjudicator/agreement.py`: implement `classify_agreement(validated_runs, per_question_confidence_threshold, gap_tolerance) -> AgreementOutcome` per [contracts/prefill-pipeline.md](contracts/prefill-pipeline.md) §2. Calls the untouched `adjudicate()` and maps its three outcomes. `agreed_with_gap` re-derives the answer itself because `adjudicate()` deliberately returns `None` there, and its confidence is `compute_consensus_confidence(...) - gap`, floored at 0. `confidence_gap` is recorded in every branch, including when zero
- [x] T061 [P] [US4] In `src/agents/adjudicator/agreement.py`: add the module-level invariant test hook asserting `classify_agreement` never returns `disputed` when the positions share an answer, and never returns `uncontested`/`agreed_with_gap` when they do not. FR-PF-026a is a property of this function, not a condition checked at the call site

### The resolver agent (R5)

- [x] T062 [P] [US4] In `src/agents/resolver/schema.py`: define the structured model output — disagreement characterization, selected run id, reasoning, confidence, and an explicit `undetermined` result. `undetermined` is first-class rather than an error path, because FR-PF-026d requires "cannot determine" to be expressible
- [x] T063 [US4] In `src/agents/resolver/agent.py`: implement `ResolverAgent(BaseAgent)` with a `provider` and **no `browser` parameter**, following `AdjudicatorAgent`'s shape. The prompt receives both positions with answer, confidence, justification, evidence URL, and element text, plus `_describe_disagreement()`'s existing anonymised description. It selects between the two supplied positions; it has no fetch tool and no path to form a third opinion
- [x] T064 [US4] In `src/agents/resolver/node.py`: implement `resolve_disagreement(...)` recording a `stage_events` row and a `cost_ledger` entry with `stage="resolution"` and `agent_index=None`, so contested-question spend is separable in `by_stage_and_agent()`. Apply the three coercions to `undetermined` from [contracts/prefill-pipeline.md](contracts/prefill-pipeline.md) §3 — unknown run id, provider error/timeout/unparseable, and explicit decline — all mapping to `unresolved_disagreement`. **There is deliberately no fourth branch that picks a position when the resolver fails**

### Wiring

- [x] T065 [US4] In `src/orchestration/scheduler.py::process_unit`: replace T053's placeholder disagreement branch — call `classify_agreement`, route `uncontested` and `agreed_with_gap` straight to a delivered prefill, and route `disputed` through the resolver. Instantiate `ResolverAgent` once per unit alongside `AssessorAgent`
- [x] T066 [US4] In `src/orchestration/prefill_writer.py`: extend the payload to carry `agreement_outcome`, `confidence_gap`, `resolver_decision`, and `unselected_position` per [data-model.md](data-model.md) §1. The unselected position is a denormalised copy of the losing run's answer, confidence, and justification — not a foreign key — so the assessor screen renders a contested question in one read (FR-PF-026c)
- [x] T067 [P] [US4] In `src/portal/templates/assessor_unit.html` and `src/api/routers/prefills.py`: surface the contested case — one suggestion, the unselected position beside it, and the resolver's characterization, so a settled dispute stays recognizable as one (FR-PF-013)

### Verification

- [x] T068 [US4] In `tests/unit/test_prefill_pipeline.py`: add the parallelism and independence assertions of SC-005 — the two assessor `stage_events` spans for one indicator overlap, and neither agent's recorded output varies with the other's. Then run `pytest tests/unit/test_agreement_and_resolver.py tests/unit/test_adjudicator.py -q`, confirming the new tests pass and the untouched adjudicator tests still do

---

## Phase 6: User Story 5 (P2) — Only a validated position is offered, and nothing is escalated

> **Goal**: The resolved position passes a second, independent validation before anyone sees it; what fails becomes a stated reason, never a queue item.
>
> **Independent test**: Construct resolved positions that pass and fail the final validation; confirm the passing ones become suggestions and the failing ones become no-suggestion prefills carrying their reason; and confirm across a whole run covering every reason that no AI-side outcome produced a human queue item.

### Tests

- [x] T069 [P] [US5] In `tests/unit/test_final_validation_gate.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 4 — the gate runs on `uncontested` positions too; a failing gate yields `failed_final_validation` at no reduced confidence; a resolver-selected position that fails the gate does **not** fall back to the position the resolver rejected; and the validator is invoked exactly once for the resolved position, proving no retry loop was entered
- [x] T070 [P] [US5] In `tests/unit/test_prefill_reasons.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 2 — all nine reasons distinguishable with non-generic labels, `no_usable_evidence` and only it terminating `unassessable`, every other reason terminating `no_suggestion`

### The second gate (R6)

- [x] T071 [US5] In `src/orchestration/scheduler.py::process_unit`: after a single resolved position exists — whether from agreement or from the resolver — call `validator_node` once with `retry_number=0`, no addendum, and no re-assessment, per [contracts/prefill-pipeline.md](contracts/prefill-pipeline.md) §4. Use `stage="final_validation"` so its cost is separable from per-agent validation. **The gate runs on uncontested positions too** — skipping it there is the natural optimisation and FR-PF-030 explicitly forbids it
- [x] T072 [US5] In `src/orchestration/scheduler.py`: on gate failure or validator exception, write a `failed_final_validation` no-suggestion prefill. No fallback to the rejected position, no delivery at reduced confidence (FR-PF-032). Persist the gate's `ValidationResult` row exactly as per-agent validation does, so the audit trail's shape is unchanged

### Programmatic reason taxonomy (FR-PF-047)

- [x] T073 [P] [US5] In `src/api/routers/assessments.py`: for a question with no suggestion, return the `PrefillReason` value as `reason` and `prefill_reason_tag()`'s label as `reason_text`, per [contracts/rest-api-additions.md](contracts/rest-api-additions.md) §4. **Historical records keep their old reasons** — a unit terminated `escalated` by a pre-feature run still renders through `reason_tag()`; the reader picks by which field the record carries (R11)
- [x] T074 [P] [US5] In `specs/007-headless-rest-api/spec.md`: annotate FR-API-023 as superseded by FR-PF-047, following the "supersede the framing, not the file" convention specs 005 and 006 already use in this repo

### Verification

- [x] T075 [US5] Run `pytest tests/unit/test_final_validation_gate.py tests/unit/test_prefill_reasons.py -q`. Then add the run-level assertion to `tests/unit/test_prefill_pipeline.py` that a run covering all nine reasons still produces zero escalation queue items and zero `ESCALATED` units (SC-007a)

---

## Phase 7: User Story 3 (P2) — Evidence is located through the ordered source cascade

> **Goal**: The cascade's ordering and its full attempt history are visible on the prefill an assessor reads, not only in the unit's internal data.
>
> **Independent test**: Run generation for indicators contrived so the first source succeeds, only the second succeeds, only the third succeeds, and none succeed; confirm the correct source supplied each link, that later sources were not consulted after an earlier success, and that the full attempt history is recorded in every case.
>
> Smallest phase in the feature: [chain.py](../../src/shared/tools/linkresolution/chain.py) already implements FR-PF-014–017 exactly and is not edited by any task here.

- [x] T076 [P] [US3] In `src/orchestration/prefill_writer.py`: carry `supplying_source` onto every prefill that had evidence located, taken from `ChainResolutionResult.supplying_source` (FR-PF-035), so an assessor sees not only what was suggested but where it came from and how that place was found
- [x] T077 [P] [US3] In `src/portal/templates/assessor_unit.html` and `src/api/routers/prefills.py`: display and return the supplying source alongside the evidence URL
- [x] T078 [US3] In `tests/unit/test_prefill_pipeline.py`: add the cascade matrix of [quickstart.md](quickstart.md) scenario 8's SC-009 check as a stubbed unit test — for each of the four contrivances, assert the recorded `supplying_source` is the earliest usable source in `settings.resolution_order`, that no later source was consulted after an earlier success, and that `resolution_history` records every attempt with its order, return, usability, and rejection reason
- [x] T079 [P] [US3] In `tests/unit/test_prefill_reasons.py`: assert that a fully-exhausted cascade dispatches **neither** assessor agent (FR-PF-018) — the cheapest failure must also be the cheapest path

---

## Phase 8: User Story 6 (P3) — Prefill is regenerated freely without disturbing human work

> **Goal**: An operator can re-run generation at any time; human submissions are untouched, the newest run's suggestions are what show, and an unattended run cannot spend without bound.
>
> **Independent test**: Run generation, submit answers to some questions, re-run, and confirm every prior submission is unchanged and still attributed, while the suggestions shown reflect the newer run.

### Re-run semantics

- [x] T080 [P] [US6] In `tests/unit/test_prefill_reruns.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 7's re-run and concurrency halves — 100% of prior submissions unchanged in answer, evidence, notes, and attribution (SC-010); the newest completed run's prefills are what a read returns (FR-PF-039); a submission during an in-flight run succeeds and is not lost (SC-011); and an assessor opening a unit mid-run sees suggestions for completed indicators and empty ones for the rest
- [x] T081 [US6] Confirm by test rather than by code that a re-run has no write path to `human_assessor_submissions` — `prefills` is append-only and the pipeline never touches the submission table, so FR-PF-038 is structural. Add the assertion explicitly so a future change that breaks it fails loudly

### Per-run budget (R7)

- [x] T082 [P] [US6] In `tests/unit/test_prefill_budget.py`: write the failing tests for [quickstart.md](quickstart.md) scenario 7's budget half. **The test must run two concurrent units of the same cycle** — that is the exact case a `total_cost()`-delta implementation gets wrong, since `ensure_session()` makes them share a `session_id`
- [x] T083 [US6] In `src/orchestration/budget.py`: implement `RunBudget` with `limit`, `spent`, `record(cost)`, and `exhausted()` per [contracts/prefill-pipeline.md](contracts/prefill-pipeline.md) §5. `limit == 0.0` short-circuits `exhausted()` to `False`, so an unconfigured deployment behaves exactly as today (FR-PF-041c)
- [x] T084 [US6] In `src/core/telemetry/cost_ledger.py`: allow `CostLedger` to accept an optional `RunBudget` and forward every `record()` cost to it. No schema change, no new column — `cost_ledger_entries` keeps its shape, and existing databases need no migration
- [x] T085 [US6] In `src/orchestration/scheduler.py::run_batch`: check `budget.exhausted()` inside `bounded()` **before acquiring the semaphore**; when exhausted, write a `budget_reached` no-suggestion prefill for that indicator and return without dispatching. Checking before dispatch is what gives FR-PF-041a's "the indicator in flight finishes" for free — there is no cancellation path to write
- [x] T086 [P] [US6] In `src/api/jobs.py`: record `budget_in_force` and `spend_reached` into the job's `data` JSON at terminal recording (FR-PF-041d), and ensure a budget-stopped run records state `completed`, not `failed` (FR-PF-041b). Two scalars written once — a JSON field, not a DDL change
- [x] T087 [US6] Run `pytest tests/unit/test_prefill_reruns.py tests/unit/test_prefill_budget.py -q`. Confirm re-running after a budget stop resumes exactly the unreached indicators (FR-PF-041e) — this needs no new code, since unreached units were never advanced past `PENDING` and resumability is spec 001's existing behaviour

---

## Phase 9: Polish & Cross-Cutting Concerns

- [x] T088 [P] In `specs/007-headless-rest-api/spec.md`: annotate FR-API-032's final term as superseded by FR-PF-005 (the AI answer leaves the publication precedence chain), matching T074's annotation style
- [x] T089 [P] In `specs/001-ekap-aiq-assessment/spec.md`: annotate FR-028 as superseded by FR-PF-025 — a confidence gap no longer blocks delivery. **This is the supersession most likely to be missed**, because it is not stated as one in spec 008 and only becomes visible when reading `adjudicate()`'s FR-028 branch ([plan.md](plan.md) Cross-spec supersessions)
- [x] T090 [P] In `src/shared/config/settings.py` and `specs/001-ekap-aiq-assessment/contracts/configuration.md`: mark `adjudication_retry_limit` as no longer governing any live path (R4). Either deprecate it with a load-time warning or remove it — leaving it looking active is the failure mode to avoid
- [x] T091 [P] In `src/cli.py` and `README.md`: state that `aiq run` now produces prefills rather than escalations, since `process_unit` is shared and this change reaches the CLI as well as the portal and API (R4's blast radius)
- [x] T092 Run the full suite: `pytest -q`. **Exactly one pre-existing test is expected to have changed rather than merely still pass** — `tests/unit/domain/test_unit_state.py`'s terminal-set assertion, amended by T011. Any other pre-existing failure is a regression
- [x] T093 Walk [quickstart.md](quickstart.md) scenario 9 against a fresh database: `aiq seed` then `aiq serve`, confirming seeded units still publish and the seeded assessor screen shows suggestions. The seeds are outside the unit suite and are the likeliest place for this feature to break something quietly
- [x] T094 Walk [quickstart.md](quickstart.md) scenario 8 — one real end-to-end run against ~5 indicators with live credentials. **Record the wall-clock time**: it is the measured baseline the spec's Outstanding performance item needs, and it should be written back into this file once known. Confirm the assessor screen shows pipeline output rather than heuristic rows, and that the admin escalation page gained nothing from the run
- [x] T095 Check the resolver for systematic bias: over the T094 run plus the stubbed contested fixtures, compare the resolver's selection rate between agent 1 and agent 2 positions. A resolver that systematically favours one index would bias every contested indicator and nothing else in the pipeline would notice ([plan.md](plan.md) Risks). `agents/verify.py` and the benchmark harness already exist for this shape of question

---

## Dependencies

```
Phase 1 (Setup)
   └─► Phase 2 (Foundational)  ── T008–T015 are one atomic group
          ├─► Phase 3 (US1, P1)  ── MVP; independent of Phases 4–8
          └─► Phase 4 (US2, P1)
                 └─► Phase 5 (US4, P2)   needs a resolved position to exist
                        └─► Phase 6 (US5, P2)   gates the resolved position
                               ├─► Phase 7 (US3, P2)   records cascade onto the prefill
                               └─► Phase 8 (US6, P3)
                                      └─► Phase 9 (Polish)
```

| Depends on | Task | Blocked by |
|---|---|---|
| Every story phase | T008–T027 | Phase 1 |
| US1 prefill reads | T030, T031, T032 | T022 |
| US1 completion | T034, T036, T043 | T023 |
| US1 publish gate | T038, T039 | T034, T035 |
| US2 pipeline exits | T051–T053 | T009, T017, T019, T050 |
| US2 summary | T056 | T054, T055 |
| US4 wiring | T065 | T060, T063, T064, T053 |
| US5 gate | T071, T072 | T065 |
| US3 supplying source | T076 | T050 |
| US6 budget | T085 | T083, T084 |
| Polish full suite | T092 | every implementation task |

**Cross-phase parallelism**: Phase 3 (US1) and Phase 4 (US2) are genuinely independent once Phase 2 lands — one is the human side reading a table, the other is the pipeline writing it, and the table is their only contact point. Two workers could take them simultaneously. Within Phase 5, T062 (schema) and T060 (classification) are independent of each other; T063 and T064 are not, since the node calls the agent.

**Sequencing constraints that are not merely ordering** (from [plan.md](plan.md)'s Post-Design Constitution Re-check):

1. **T008–T015 must land as one commit.** Between the enum change and the last consumer widening, a `no_suggestion` unit is terminal to the state machine but non-terminal to five readers — resume would re-dispatch it and job progress would never reach 100%. T015 is the completion check, not a formality.
2. **T034 must land before or with T035.** Deleting the AI fallbacks without the readiness gate is the one genuinely dangerous intermediate state in this feature: published scores would silently switch to partial-coverage denominators, which is precisely the comparability failure D1 exists to prevent, arriving unannounced.
3. **T030 and T031 cannot be split.** They read the same lookup; moving only the display would record `ai_suggestion_accepted` against a suggestion the assessor never saw, corrupting SC-012's measure silently and retroactively.
4. **T011 belongs in its own commit.** It amends a spec 001 SC-009 invariant test, and the natural instinct on seeing that test fail is to make it pass rather than to strengthen it. The commit message must state that the replacement assertion is stronger.
5. **T045/T046 must land in the same change as T038.** The moment the publish gate exists, the demo seeds publish units it refuses — a break discovered by a person clicking rather than by CI.

---

## Story → Task Mapping

| Story | Priority | Requirements | Tasks | Independent test criteria |
|---|---|---|---|---|
| US1 | P1 (MVP) | FR-PF-003–013, 005a–005h, 009a, 042–046 | T028–T048 | An assessor sees real pipeline suggestions, takes or ignores any freely with no extra step, cannot complete with an indicator outstanding (the refusal names it), and no unit publishes until both roles declare; a fully-prefilled unit with no human answers publishes nothing |
| US2 | P1 | FR-PF-001, 002, 033, 040, 041 | T049–T058 | A run over a whole questionnaire terminates alone, adds zero rows to any human queue, leaves no unit `ESCALATED`, and produces exactly one prefill record per indicator |
| US3 | P2 | FR-PF-014–018, 035 | T076–T079 | Across the four-way cascade matrix, the earliest usable source supplied the link every time, no later source was consulted after an earlier success, the full attempt history is recorded, and a fully-exhausted cascade dispatches neither agent |
| US4 | P2 | FR-PF-019–029, 013 | T059–T068 | The two agents ran concurrently and independently; only validated positions counted; the resolver was invoked on exactly the answer disagreements and nothing else; every indicator that produced a suggestion produced exactly one |
| US5 | P2 | FR-PF-030–034, 032a–032d, 047 | T069–T075 | A resolved position that fails the second gate becomes a no-suggestion prefill at no reduced confidence and never falls back to the rejected position; all nine reasons are distinguishable; the run creates no queue item |
| US6 | P3 | FR-PF-036–041e | T080–T087 | After a re-run, 100% of prior human submissions are unchanged and still attributed; the newest completed run's suggestions are what show; a budget stop leaves every indicator with a prefill record and re-running resumes the unreached ones |

---

## MVP Scope

**Minimum viable feature**: T001–T048 (Setup + Foundational + US1). At this point the decoupling's *human* half is real and complete — the assessor screen reads the pipeline's own prefills rather than demo seed rows, every indicator requires an explicit yes or no, completion is an attributed declaration rather than an inference, and the AI is out of the publication precedence chain entirely with a completeness gate making that safe. This alone satisfies SC-003, SC-004, SC-004a–c, and SC-012, and it is testable with hand-seeded prefill rows and no pipeline change at all.

It is worth being precise about what the MVP does *not* yet do: the pipeline still escalates on disagreement, so FR-PF-002 is not yet met. The MVP delivers "the human decides" without yet delivering "the AI finishes alone".

**Full feature**: T001–T095 — adds the unattended pipeline with no human work items (US2), the resolver that settles disputes into one answer (US4), the second validation gate and the reason taxonomy (US5), the cascade's provenance on the prefill (US3), re-running and the spend cap (US6), and the supersession annotations, regression, seed walkthrough, real run, and resolver-bias check.

---

## Format Validation

All 95 tasks follow `- [ ] T0NN [P?] [USn?] Description with exact file path(s)`. Setup (T001–T007), Foundational (T008–T027), and Polish (T088–T095) carry no story label. Every task in Phases 3–8 (T028–T087) carries exactly one story label. Every task names at least one concrete file path, and no two tasks marked `[P]` edit the same file — in particular, the seven tasks touching `src/orchestration/scheduler.py` (T051, T052, T053, T065, T071, T072, T085) are all unmarked and strictly sequential, as are the two touching `src/api/finalize.py` (T034, T035) and the three touching `src/portal/assessor.py` (T030, T031, T036).
