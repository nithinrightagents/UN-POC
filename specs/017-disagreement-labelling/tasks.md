# Tasks: Disagreement Labelling for Human Assessor Discrepancies

**Feature**: `017-disagreement-labelling`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [plan.md](plan.md) | [research.md](research.md) | [data-model.md](data-model.md) | [contracts/labelling-pass.md](contracts/labelling-pass.md) | [contracts/classifier-contract.md](contracts/classifier-contract.md) | [contracts/surfaces-and-measures.md](contracts/surfaces-and-measures.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-09-07

## Conventions

- `[P]` = parallelizable (different file, no dependency on an incomplete task in this list). Two tasks editing the same file are never both marked `[P]`.
- `[USn]` = belongs to User Story n's phase (spec.md priorities: US1–US3 = P1, US4–US5 = P2, US6 = P3). Setup, Foundational, and Polish tasks carry no story label.
- **No new dependency.** FastAPI, Jinja2, SQLite and the existing `google-genai` path are already declared; nothing below adds a package ([plan.md](plan.md) Technical Context).
- **`src/portal/discrepancy.py` is never edited by any task below.** It is imported read-only, as [admin.py:31](../../src/portal/admin.py#L31) and `cycles.py` already do. `git diff --stat -- src/portal/discrepancy.py` staying empty for the whole feature is SC-002's cheapest proof, and T002 makes it a standing check rather than an intention. **A task that needs to touch that file has gone wrong.**
- **`src/portal/templates/assessor_reconcile.html`, `src/portal/templates/assessor_unit.html`, `src/portal/reconciliation.py`, `src/api/finalize.py`, `src/core/llm_factory.py`, `src/agents/**` and `src/orchestration/**` are never edited by any task below** (FR-DL-065, FR-DL-066, [research.md](research.md) R10). Their absence from the diff is the evidence for three of the nine Constitution gates.
- **No existing table changes and no existing entity gains a field** ([data-model.md](data-model.md) §10). Everything this feature knows lives in its own three tables, which is what makes it removable.
- **Ten of the eleven quickstart scenarios run offline** against injected fake providers, on the `NoCallProvider` pattern already in `tests/unit/test_resolve_only.py`. Only T081 spends money, and it is optional.

### Two contract corrections made during task generation

Both were found by reading the routes and the CLI rather than the design docs, and both are already applied to the contract files:

| Artifact said | Corrected to | Why |
|---|---|---|
| `/admin/questionnaires/{cycle_id}/ambiguity` | `/admin/projects/{cycle_id}/ambiguity` | `/admin/questionnaires/{set_id}` ([admin.py:266](../../src/portal/admin.py#L266)) is the **indicator set**, keyed by set id. A project is a `cycle_id` and lives at [admin.py:355](../../src/portal/admin.py#L355). The ambiguity route is a sibling of the escalations route at [admin.py:1015](../../src/portal/admin.py#L1015) |
| `python -m cli label-drain` | `aiq label drain` | `src/cli.py` is `click` with groups reached through the `aiq` console script (`pyproject.toml:34`). A flat `label-drain` command would be the only one of its shape in the tree |

---

## Implementation Strategy

Nine increments. Three ordering choices below deviate from a naive priority walk, and each is deliberate.

1. **Increment 1** (Phase 1, Setup): The baseline, the isolation guard, and empty scaffolds. **T002 is the standing invariant, not a one-time gate** — unlike spec 012, which modified the engine and needed a characterisation suite under it, this feature's claim is that the engine is not touched at all. That is checked by a diff, and it is checked again in Polish.
2. **Increment 2** (Phase 2, Foundational): Two enums, three dataclasses, three tables, the repository methods, the settings, the deterministic pre-pass, and the state projection. Largest phase, because this feature's machinery is shared across every story. **Nothing in Phases 3–8 can start until it lands.** The pre-pass and the projection are pure functions with no I/O and are fully testable here, which is why Scenario 2 is satisfied before any model code exists.
3. **Increment 3** (Phase 3, US1 — P1, the MVP): The classifier, the dispatch, the runner, and the badge on the escalations page. This is the feature: a disputed indicator stops being a bare question id. **T037 and T038 are one atomic group** — the two completion call sites land together, because the portal site alone is the parity bypass FR-DL-080 forbids and every portal test would still pass.
4. **Increment 4** (Phase 4, US2 — P1): The isolation guarantees, made into assertions. Deliberately thin on implementation and heavy on tests, and that is honest rather than padded: **US2's property is created by where Phase 3's code was placed, not by code written here.** This phase proves it, and adds only the two things that cannot be proved without them — the swallowed-exception boundary at dispatch and the four distinct rendered states.
5. **Increment 5** (Phase 5, US3 — P1): Provenance, the retry cap, the exhausted state, staleness, and `aiq label drain`. **The retry machinery is here rather than in US1** because FR-DL-052 and FR-DL-057 to FR-DL-059 are one argument: a rule against re-establishing a label would also have forbidden any retry, and the three-attempt cap is what resolves that. Splitting them across phases would leave a half-stated rule in the tree.
6. **Increment 6** (Phase 6, US4 — P2): The per-unit label composition, which is what makes an access-dominated unit distinguishable from an interpretation-dominated one at the same rate.
7. **Increment 7** (Phase 7, US5 — P2): The ambiguity measure, its base, and its two routes. The durable output of the whole feature, and the last thing buildable, because it needs labels across many units before it means anything.
8. **Increment 8** (Phase 8, US6 — P3): The insufficient-notes proportion, reported on the same routes as the measure.
9. **Polish** (Phase 9): The three read endpoints, programmatic parity end to end, the blindness sweep, seed data for each state, full regression, the graph refresh, and the Constitution re-check.

**MVP**: Phase 3 (US1) is a coherent, shippable increment on its own — every disputed indicator carries a label, and a Senior Reviewer opening the escalations page reads the composition of a unit's disagreement instead of eleven pairs of free text. The minimum *safe* release is Phases 3 + 4 together, because US1 without US2's assertions ships a model output into a governance surface with nothing yet proving it cannot reach the numeric path.

---

## Phase 1: Setup and the isolation guard

> Goal: A recorded baseline, a standing check that the engine is untouched, and empty scaffolds. No behaviour change.

- [X] T001 Run `pytest -q` from the repo root over `tests/` and record the passing count; this is the baseline every later phase is compared against ([quickstart.md](quickstart.md) Prerequisites)
- [X] T002 Record the engine baseline: `pytest tests/unit/test_portal_discrepancy.py tests/unit/test_assessor_completion.py -q` green, and `git diff --stat -- src/portal/discrepancy.py` empty. **This is a standing invariant, re-checked at T079, not a one-time gate** — the file is imported read-only for `_compare` and must never appear in this feature's diff (SC-002, [research.md](research.md) R1)
- [X] T003 [P] Create `src/portal/disagreement_labels.py` as a scaffold whose module docstring states that this is the labelling pass, that it imports `_compare` from `portal/discrepancy.py` **read-only and never writes through `recompute_portal_discrepancy`**, and that it holds the seven prohibitions of [contracts/labelling-pass.md](contracts/labelling-pass.md) §7 verbatim as a comment block so a later reader finds them before adding a write
- [X] T004 [P] Create `src/portal/label_classifier.py` as a scaffold whose module docstring states that this is the sole model boundary for labelling, that it takes a provider as a parameter rather than constructing one, and that **it does not import `Prefill` and must not be made to** — the structural form of D3 and FR-DL-037 ([contracts/classifier-contract.md](contracts/classifier-contract.md) §2)
- [X] T005 [P] Create `src/api/routers/labels.py` as an empty router scaffold returning `APIRouter()`
- [X] T006 [P] Create `src/portal/templates/admin_indicator_ambiguity.html` as a scaffold extending `base.html` with an empty results table
- [X] T007 [P] Create ten test modules as scaffolds with a `@pytest.mark.unit` module marker: `tests/unit/test_disagreement_labels_isolation.py`, `test_labelling_dispatch.py`, `test_label_deterministic.py`, `test_label_classifier_input.py`, `test_label_classifier_output.py`, `test_label_retry_exhaustion.py`, `test_label_provenance.py`, `test_label_surfaces.py`, `test_indicator_ambiguity.py`, `test_label_api_parity.py`
- [X] T008 [P] In `tests/unit/conftest.py`: add the fixtures this feature's tests share — a `disputed_unit` factory building on the existing `two_assessor_unit` (`conftest.py:176`) and `both_declared` (`conftest.py:294`) fixtures, taking a per-question `(a_answer, a_url, a_notes, b_answer, b_url, b_notes)` map so a unit with one dispute of each kind is one call; a `FakeLabelProvider` returning canned JSON with a recorded call count and a captured payload; a `RaisingProvider`; and a `NoCallProvider` that fails the test if `generate` is invoked, reusing the shape at `tests/unit/test_resolve_only.py:27`. Extend the existing file; do not replace any spec 007, 008 or 012 fixture

---

## Phase 2: Foundational — enums, tables, repositories, the pre-pass, the projection

> Goal: Everything every story phase depends on. **Must complete before Phase 3.**
>
> The deterministic pre-pass and the state projection are pure functions with no repository access and no model call, so quickstart Scenario 2 is fully satisfied in this phase, before any model code exists.

### Entities

- [X] T009 In `src/shared/state/entities.py`: add the `DisagreementLabel` and `SideObservation` enums exactly as given in [data-model.md](data-model.md) §4, plus the `DETERMINISTIC_LABELS` and `CLASSIFIER_LABELS` frozensets as **named constants, not comments** — they are read by the pre-pass and by the response schema, and a comment cannot be asserted on. Add the badge-text mapping beside the enum, so re-wording a badge never rewrites a stored value
- [X] T010 In `src/shared/state/entities.py`: add the `LabellingPass`, `DisagreementLabelRecord` and `LabellingAttempt` dataclasses per [data-model.md](data-model.md) §5. Same file as T009, so not parallel with it. **No existing entity gains a field** — in particular `DiscrepancyCase` gains no label, because a case is the numeric record and pairing the two invites a future reader to compute one from the other ([data-model.md](data-model.md) §10)
- [X] T011 [P] In `tests/unit/test_label_deterministic.py`: assert `DETERMINISTIC_LABELS` and `CLASSIFIER_LABELS` are disjoint and that their union is exactly `set(DisagreementLabel)`. This fails the moment someone adds a seventh label without deciding how it is established, which is the only way the pre-pass and the response schema can silently drift apart

### Schema and persistence

- [X] T012 In `src/shared/persistence/schema.py`: add the `labelling_passes`, `disagreement_labels` and `labelling_attempts` tables with their five indexes exactly as given in [data-model.md](data-model.md) §1–3, after the `assignment_changes` block at `schema.py:457`. Each DDL block carries a comment stating that the table is **append-only** and that `idx_labelling_pass_once` and `idx_disagreement_label_once` are load-bearing once-only guarantees rather than optimisations, so neither is later "tidied" into a plain index. `label` is a real column, not a JSON field, because every aggregate in the feature groups by it
- [X] T013 In `src/shared/persistence/repositories.py`: add `insert_labelling_pass(pass_) -> bool` returning `False` on `sqlite3.IntegrityError` — the once-guard is the unique index, never a read-then-write check, mirroring `record_disposition` at [repositories.py:740](../../src/shared/persistence/repositories.py#L740) and `insert_joint_answer` at [repositories.py:1308](../../src/shared/persistence/repositories.py#L1308) — plus `get_labelling_pass(session_id, portal_id)` and `list_labelling_passes(cycle_id)`
- [X] T014 In `src/shared/persistence/repositories.py`: add `insert_disagreement_label(record) -> bool` (also `False` on `IntegrityError`), `list_labels_for_unit(session_id, portal_id)`, and `list_labels_for_cycle(cycle_id)`. **No update and no delete method** — the append-only property is enforced by the absence of a mutator, as spec 008 did for `prefills` and spec 012 for `joint_answers` (FR-DL-054)
- [X] T015 In `src/shared/persistence/repositories.py`: add `insert_labelling_attempt(attempt)` and `count_attempts(pass_id, question_id) -> int`. Only *failures* are recorded, so `COUNT(*)` is exactly the attempt count FR-DL-057 caps at three; say so in the method docstring, because a future reader who adds a success row here silently breaks the cap
- [X] T016 In `src/shared/persistence/repositories.py`: add `count_labels_by_kind(cycle_id | None)` returning established-deterministic, established-by-classifier, and pass/label/attempt totals in one query, and `count_labels_by_question(cycle_id | None)` grouping by `(question_id, label)` for the ambiguity measure (FR-DL-070, FR-DL-091, [research.md](research.md) R11). Same file as T013–T015, so the four land in sequence
- [X] T017 In `src/shared/persistence/serialization.py`: confirm the three new dataclasses round-trip through `to_json`/`from_json`, including the `DisagreementLabel` and `SideObservation` enum members and the `observations` dict-of-lists; add handling only where the existing dataclass path does not already cover them

### Configuration

- [X] T018 [P] In `src/shared/config/settings.py`: add `disagreement_labelling_enabled: bool = True`, `disagreement_label_model: str = "gemini-2.5-flash-lite"` and `disagreement_label_temperature: float = 0.0` to `Settings` (`settings.py:79` neighbourhood), and their three `AIQ_*` entries to the env mapping at `settings.py:157` ([data-model.md](data-model.md) §9). Document on the enabled flag that disabling it **suppresses dispatch only** — existing labels stay readable, because a stored label is history and does not depend on the feature being switched on
- [X] T019 [P] In `src/shared/config/validation.py::validate_settings`: add a `0.0 <= disagreement_label_temperature <= 2.0` range check alongside the existing threshold checks, and a corresponding case in `tests/unit/test_config_validation.py`

### The deterministic pre-pass (SC-009, R4)

- [X] T020 [P] In `tests/unit/test_label_deterministic.py`: write the failing tests for the six-row table in [quickstart.md](quickstart.md) Scenario 2, driven by `NoCallProvider` so an accidental model call fails the test. The two rows that matter most are `dvla.gov.uk` vs `hmrc.gov.uk` → `DIFFERENT_SOURCES` (the eTLD+1 bug the spec was amended for) and `gov.sg` vs `e-services.gov.sg` → same source, reaching the classifier. Add the unparseable-URL row: garbage normalises to an empty host and is treated as **no evidence cited**, so it is not `ONE_FOUND_NOTHING`
- [X] T021 In `src/portal/disagreement_labels.py`: implement `normalise_host(url)`, `same_source(url_a, url_b)` and `classify_deterministically(a, b)` per [data-model.md](data-model.md) §7 — pure functions, no repository, no I/O. `normalise_host` lowercases, strips userinfo and port reusing the `_host` logic at [admissibility.py:31](../../src/shared/tools/linkresolution/admissibility.py#L31), then strips a leading `www.` and a trailing dot. `same_source` is host equality **or a dot-boundary suffix match in either direction**, never eTLD+1, and **resolves toward same source when uncertain** so an unclear case costs a model call rather than a wrong deterministic label (FR-DL-030, [research.md](research.md) R4). Order matters: the different-sources test comes before the one-cited test, which is why an unparseable URL falls through to the classifier
- [X] T022 In `src/portal/disagreement_labels.py`: implement the two free per-side observations — `NO_NOTES` where `notes` is absent or whitespace, `ACCEPTED_AI_UNCHANGED` where `ai_suggestion_accepted is True` — recorded **even when the label is deterministic or the classifier fails**, because they were never in doubt ([data-model.md](data-model.md) §8). The third, `NOTES_CONTRADICT_ANSWER`, comes from the classifier and is added in Phase 3

### The state projection (no status column)

- [X] T023 In `src/portal/disagreement_labels.py`: implement `DisputeLabelState` and `unit_labelling_state(repo, session_id, portal_id)` per [contracts/labelling-pass.md](contracts/labelling-pass.md) §4, deriving all four states from row presence exactly as [data-model.md](data-model.md) §3 states — `never_labelled` from no pass row, `established` from a label row, `awaiting` and `exhausted` split by `count_attempts < 3`. **One reader for every surface**, on the `unit_reconciliation_state` precedent from spec 012: deriving the four states twice is how a template and a route come to disagree about a unit. `stale` compares the stored `submission_ids` against the unit's current latest submissions (FR-DL-068). **Makes no model call and writes nothing** (FR-DL-045)
- [X] T024 In `src/portal/disagreement_labels.py`: implement `labelling_counts(repo, cycle_id=None)` over T016's aggregate, returning `awaiting`, `exhausted`, `established_deterministic` and `established_by_classifier` (FR-DL-091, FR-DL-092). A rising `awaiting` is what a provider outage looks like from outside; a rising `exhausted` is what it looks like after three attempts each

**Checkpoint**: `pytest tests/unit/test_label_deterministic.py -q` green with no provider configured at all, and the T001 baseline unchanged. Two of the six labels can now be established, and quickstart Scenario 2 passes, before a single line of model code exists.

---

## Phase 3: User Story 1 (P1) — A reviewer sees what kind of disagreement each dispute is

> **Goal**: When a unit's second completion is declared, one pass labels every disagreement that unit contains, and each disputed indicator on the escalations page carries a short badge naming the relation between the two positions.
>
> **Independent test**: Construct a unit with one dispute of each kind, drive both assessors to completion, run the pass against a fake provider, and verify each disputed indicator carries the label matching its constructed kind, that the badge is legible without a key, and that no label asserts which assessor was correct.
>
> **This phase is the MVP** and depends on nothing in Phases 4–8.
>
> **T037 and T038 are one atomic group.** The portal call site alone means a unit assessed entirely through the REST API reaches mutual completion and is never labelled — with every portal test still passing. That is the precise bypass FR-DL-080 forbids, and it is invisible until T073.

### Tests

- [X] T025 [P] [US1] In `tests/unit/test_label_classifier_input.py`: write the failing tests for [quickstart.md](quickstart.md) Scenario 3 using a capturing fake. Assert the rendered payload contains the indicator text, two positions and the interval **and nothing else**; that it contains no `role`, no `assessor_actor_id` and no `ai_suggested_answer`, asserted **against the serialised string, not the object**; that a `Prefill` with a distinctive justification seeded for the same question has that string absent from the payload (FR-DL-037); that `src/portal/label_classifier.py` does not import `Prefill`, asserted by reading the module source; and that swapping which assessor is A and which is B with identical content produces the **same** payload and the same `input_digest` (FR-DL-038)
- [X] T026 [P] [US1] In `tests/unit/test_label_classifier_output.py`: write the failing tests for [quickstart.md](quickstart.md) Scenario 4 — the response schema's enum is exactly the four classifier labels with `different_sources` and `one_found_nothing` absent; a fake returning `"different_sources"` is rejected, stores nothing, and writes one `labelling_attempts` row with `failure="schema_rejected"`; malformed JSON and a missing key are likewise rejected and recorded; and a fake returning `not_enough_notes` stores it as a **substantive label**, never conflated with `awaiting` (FR-DL-034)
- [X] T027 [P] [US1] In `tests/unit/test_labelling_dispatch.py`: write the failing tests for [quickstart.md](quickstart.md) Scenario 1 — submissions alone create no pass; A's completion creates none; B's creates exactly one `labelling_passes` row; recomputing the unit ten times, changing the tolerance, closing a round, signing off and publishing still leave exactly one row (FR-DL-007); a unit with no disagreements produces no pass at all; and **with `ai_runtime` unset there is no pass row and no attempt row**, so the unit is `never_labelled` rather than `exhausted` ([research.md](research.md) R6)

### The classifier

- [X] T028 [US1] In `src/portal/label_classifier.py`: add `LABEL_PROMPT_VERSION = "dl-1"` and the `ClassifierInput`, `PositionView` and `ClassifierResult` dataclasses of [contracts/classifier-contract.md](contracts/classifier-contract.md) §1
- [X] T029 [US1] In `src/portal/label_classifier.py`: build `PositionView` from `HumanAssessorSubmission` and **nothing else** — `answer`, `evidence_url`, `notes`, and `ai_suggestion_accepted`. `ai_suggested_answer` is on the same row and is not read; `Prefill` is not queried and not imported. Order the two positions by `(evidence_url or "", notes or "")` ascending, so **role never participates** and the model cannot learn from position which assessor it is reading; the caller keeps `order[i] -> role` to map the response back ([contracts/classifier-contract.md](contracts/classifier-contract.md) §2, [research.md](research.md) R7). Notes are sent **verbatim** — no redaction or truncation, the position recorded in A9 and stated rather than mitigated
- [X] T030 [US1] In `src/portal/label_classifier.py`: implement the SHA-256 `input_digest` over canonical JSON with sorted keys and no whitespace, **including `prompt_version`**, so a changed instruction produces a different digest for identical submissions ([contracts/classifier-contract.md](contracts/classifier-contract.md) §3). This is the artefact FR-DL-056 rests on
- [X] T031 [US1] In `src/portal/label_classifier.py`: write the system instruction as one versioned module constant with the four contractual properties of [contracts/classifier-contract.md](contracts/classifier-contract.md) §5 — it never asks which answer is correct; it defines the three substantive labels by decision procedure in the order the pre-pass leaves them (was one side prevented from reaching the source; did both reach it and describe different content; did both describe the same content and judge it differently); it makes `not_enough_notes` the **required** answer under uncertainty rather than a fallback; and it never refers to Assessor A or B, to roles, or to an AI suggestion's content. Add a comment stating that changing any word of it requires incrementing `LABEL_PROMPT_VERSION`, because the version is what the audit record names
- [X] T032 [US1] In `src/portal/label_classifier.py`: implement `async def classify(provider, settings, payload)` calling `provider.generate` with the response schema of [contracts/classifier-contract.md](contracts/classifier-contract.md) §4 and `temperature=0.0`. The schema's enum omits the two deterministic labels entirely, so FR-DL-033 is enforced by constrained decoding rather than by an instruction the model may ignore. **Re-validate on parse anyway** — a label outside `CLASSIFIER_LABELS`, a missing key or unparseable JSON raises. `classify` has no persistence and no retry loop; it raises and the caller records one attempt row

### The pass

- [X] T033 [US1] In `src/portal/disagreement_labels.py`: implement `dispatch_labelling_pass(...)` with the six preconditions of [contracts/labelling-pass.md](contracts/labelling-pass.md) §1 **in order**, the first failure returning `None` and writing nothing: the enabled flag; `provider_available`; both roles having an `AssessorCompletion`; `_compare` returning non-`None`; a non-empty disputed set; and the insert succeeding. **Precondition 6 is an insert attempt, not a lookup** — `sqlite3.IntegrityError` is caught and returns `None`, which is the once-guard working, not an error. `_compare` is called **read-only**: no `DiscrepancyCase`, no queue item, no round. The disputed set is copied into `data.disputed_question_ids` and everything downstream reads that copy, so a later joint answer cannot change what the pass was supposed to cover (FR-DL-042)
- [X] T034 [US1] In `src/portal/disagreement_labels.py`: implement `async def run_labelling_pass(database_path, settings, runtime, pass_id)` per [contracts/labelling-pass.md](contracts/labelling-pass.md) §2. It **opens its own SQLite connection** — the request's connection is closed by the time this runs — on the precedent at [live_prefill.py:25](../../src/portal/live_prefill.py#L25) ([research.md](research.md) R3). Per dispute: load both latest submissions, compute the free observations, try the pre-pass, write a deterministic label and continue if one fires, otherwise check the attempt cap, call the classifier, and write either a label row or one attempt row. **Idempotent and resumable**: any dispute that already has a label row or three attempt rows is skipped, which is what makes a second run over the same pass safe and is exactly what T056's drain does
- [X] T035 [US1] In `src/portal/disagreement_labels.py`: catch every exception **per dispute** inside the runner, so one failed dispute never stops the pass, and record `NOTES_CONTRADICT_ANSWER` from the classifier response against the correct side by mapping position index back through the caller's `order[i] -> role` map (FR-DL-062)
- [X] T036 [US1] In `src/portal/disagreement_labels.py`: record cost after each classifier call via `CostLedger.record(stage="disagreement_labelling", model_identity=..., input_units=..., output_units=..., cost=estimate_cost(...), agent_index=None)` ([cost_ledger.py:36](../../src/core/telemetry/cost_ledger.py#L36)). `agent_index` is `None` because this is not an assessor agent, and conflating it with one would corrupt the per-agent comparison the ledger exists for. **Deterministic labels record nothing** — they cost nothing (FR-DL-090, [research.md](research.md) R9)

### Dispatch call sites — T037 and T038 are one atomic group

- [X] T037 [US1] In `src/portal/assessor.py::complete_unit` ([assessor.py:309](../../src/portal/assessor.py#L309)): add `request: Request` and `background: BackgroundTasks` parameters and, immediately after the existing `recompute_portal_discrepancy` call at [assessor.py:357](../../src/portal/assessor.py#L357), call `dispatch_labelling_pass(..., dispatched_by="portal", provider_available=getattr(request.app.state, "ai_runtime", None) is not None)`. When a pass is created, schedule `background.add_task(run_labelling_pass, database_path, settings, runtime, pass_id)` — **with the database path and the runtime, never with the request's repository**. Wrap the whole block so a raised exception is caught and logged: the completion is already recorded and the redirect is unchanged (FR-DL-043, FR-DL-044). **Must land in the same change as T038**
- [X] T038 [US1] In `src/api/routers/completions.py::declare_completion` ([completions.py:42](../../src/api/routers/completions.py#L42)): add the identical two parameters and the identical dispatch call immediately after [completions.py:116](../../src/api/routers/completions.py#L116), differing **only** in `dispatched_by="api"`. Without it a unit assessed entirely through the REST API is never labelled and every portal test still passes — the bypass FR-DL-080 forbids. **Must land in the same change as T037**

### The badge

- [X] T039 [US1] In `src/portal/admin.py::escalations_page` ([admin.py:1015](../../src/portal/admin.py#L1015)): call `unit_labelling_state` for each escalated unit and pass the projection to the template. **This is a GET handler**: it must call the projection and never `dispatch_labelling_pass`, never `run_labelling_pass`, and never the classifier (FR-DL-045)
- [X] T040 [US1] In `src/portal/templates/admin_escalations.html`: render the badge for each disputed indicator as **the plain-English phrase and nothing else** — no colour ranking implying severity, no ordering implying priority, no wording suggesting an action (FR-DL-063). Show per-side observations **in the column already holding that assessor's answer and evidence, never in the pair-level row** (FR-DL-062)
- [X] T041 [P] [US1] In `tests/unit/test_label_surfaces.py`: assert the escalations page renders a badge for each disputed indicator with per-side observations against the correct side, and that loading the page 50 times creates no rows and makes no model calls, driven by `NoCallProvider` (FR-DL-045)

**Checkpoint**: `pytest tests/unit/test_labelling_dispatch.py tests/unit/test_label_classifier_input.py tests/unit/test_label_classifier_output.py tests/unit/test_label_surfaces.py -q` green, and the T001 baseline still green. A Senior Reviewer opening the escalations page now reads the composition of a unit's disagreement instead of eleven pairs of free text.

---

## Phase 4: User Story 2 (P1) — Labelling cannot change any assessment outcome

> **Goal**: The platform run twice over identical submissions, once with labelling available and once with it entirely unavailable, produces identical rates, flags, disputed sets, rounds, escalations and published answers.
>
> **Independent test**: Drive a full set of units to publication with the provider disabled, record every discrepancy outcome, repeat with it enabled, and diff. Any difference outside the labels themselves is a failure.
>
> **Deliberately thin on implementation.** US2's property is created by *where* Phase 3's code was placed, not by code written here. This phase proves it and adds only what cannot be proved without it.

- [X] T042 [P] [US2] In `tests/unit/test_disagreement_labels_isolation.py`: implement [quickstart.md](quickstart.md) Scenario 0. Assess one unit twice — once with labelling enabled and a working fake provider, once with `AIQ_DISAGREEMENT_LABELLING_ENABLED=false` — and assert identical `discrepancy_cases`, `escalation_queue_items`, `reconciliation_rounds` and published answers. **Compare the serialised rows, not summaries**; a summary hides exactly the field a regression would move
- [X] T043 [US2] In `tests/unit/test_disagreement_labels_isolation.py`: assert a unit whose every dispute is `exhausted` opens the same automatic round, over the same disputed set, as one whose every dispute is labelled (FR-DL-047), and that `publication_readiness` output is **byte-identical** between the two (FR-DL-066). This is the negative contract the whole Constitution gate rests on, and it is an assertion rather than an absence of references
- [X] T044 [US2] In `src/portal/assessor.py` and `src/api/routers/completions.py`: verify by test that a provider raising inside dispatch, and a provider raising inside the background runner, both leave the completion recorded and the response unchanged, and that **no error surfaces to an assessor** (FR-DL-043, FR-DL-044). Assert on the response status and body, not on a log line
- [X] T045 [US2] In `src/portal/templates/admin_escalations.html`: render the four states of [contracts/surfaces-and-measures.md](contracts/surfaces-and-measures.md) §2 as **four visibly distinct strings** — the badge, "Labelling not yet complete", "Labelling was attempted and could not be completed", and "Not labelled". `awaiting` and `exhausted` must not collapse into one string: a temporary state read as permanent is the misreading FR-DL-058 exists to prevent. Same file as T040, so not parallel with it
- [X] T046 [P] [US2] In `tests/unit/test_label_surfaces.py`: render `assessor_reconcile.html` and `assessor_unit.html` for a unit with established labels and assert **no badge string and no observation string appears in either** (FR-DL-065), and that no rendered surface contains a word asserting which assessor was right — assert against a forbidden-string list ("correct", "wrong", "should have") in label-adjacent markup (SC-003, FR-DL-063)
- [X] T047 [US2] Verify the two files above are absent from the diff: `git diff --name-only -- src/portal/templates/assessor_reconcile.html src/portal/templates/assessor_unit.html src/portal/discrepancy.py src/portal/reconciliation.py src/api/finalize.py src/core/llm_factory.py` returns **nothing**. Blindness and engine isolation are properties of the diff here, which is a stronger statement than any test makes

**Checkpoint**: `pytest tests/unit/test_disagreement_labels_isolation.py -q` green, T047 returns empty, and the T001 baseline unchanged. The feature is now safe to put in front of a live governance process.

---

## Phase 5: User Story 3 (P1) — Every label can be accounted for afterwards

> **Goal**: Asked why a dispute carries a label, an Administrator can show which model produced it, under which prompt version, from exactly which content, and when — and can demonstrate it has not silently changed.
>
> **Independent test**: Run the pass, record each label's provenance, then recompute repeatedly, amend a submission and open a round, verifying after each that no further classification is produced and every recorded label is unchanged.
>
> **The retry cap lives here, not in US1.** FR-DL-052 and FR-DL-057 to FR-DL-059 are one argument: a rule against re-establishing a label would also forbid any retry, and the three-attempt cap is what resolves it. Split across phases, the tree would carry half of a rule.

- [X] T048 [P] [US3] In `tests/unit/test_label_provenance.py`: implement [quickstart.md](quickstart.md) Scenario 6 — every label carries `established_by`, `input_digest`, `stated_reason` and `created_at`, and classifier labels additionally carry `model_identity` and `prompt_version`; a deterministic label is identifiable as such and **names no model** (FR-DL-051); and changing `LABEL_PROMPT_VERSION` changes the digest for identical submissions
- [X] T049 [P] [US3] In `tests/unit/test_label_provenance.py`: assert SC-004 by counting calls on the fake — the total model calls for a unit never exceed its dispute count across viewing, recomputation, amendment, reconciliation, sign-off and publication. Then assert the append-only property two ways: `grep` the module for `UPDATE disagreement_labels` / `DELETE FROM disagreement_labels` and find nothing, and assert row counts on all three tables **never decrease** across a full lifecycle (FR-DL-054)
- [X] T050 [P] [US3] In `tests/unit/test_label_retry_exhaustion.py`: implement [quickstart.md](quickstart.md) Scenario 5 — a provider that always raises produces **one attempt row per run**, so three runs give three rows, no label, and state `exhausted`; a fourth run makes no model call and writes no fourth row; `awaiting` and `exhausted` render as distinct strings; a provider failing twice then succeeding produces two attempt rows and one label; and **amending a submission does not bring an exhausted dispute back into scope** (FR-DL-059) — the deliberate divergence from the pre-clarification design
- [X] T051 [US3] In `src/portal/disagreement_labels.py`: enforce **one attempt per dispute per run**. A failure writes a single attempt row and moves on rather than retrying in a tight loop — the provider has already exhausted its own 30/60/90s and 2/5/10s backoffs before raising ([research.md](research.md) R8), so an immediate retry fails identically and burns the cap. The remaining attempts are consumed by later runs. Add a comment saying so, because "retry twice" reads like a loop and is not one
- [X] T052 [US3] In `src/portal/disagreement_labels.py`: confirm by test that a `schema_rejected` response **counts as an attempt**. The spec's edge case says so explicitly, and it is what prevents a model stuck in a bad output mode from looping against the cap
- [X] T053 [US3] In `src/portal/admin.py` and `src/portal/templates/admin_escalations.html`: make provenance reachable from every badge — model identity or "established without a model", prompt version, input digest, and time (FR-DL-050). Render it on demand rather than inline, so the badge stays a phrase
- [X] T054 [US3] In `src/portal/templates/admin_escalations.html`: where `DisputeLabelState.stale` is true, accompany the badge with "submission has changed since labelling" (FR-DL-068). **The label is still shown** — it is history, honestly dated, and hiding it would lose the record the digest attests to. Same file as T053, so the two sequence
- [X] T055 [P] [US3] In `tests/unit/test_label_surfaces.py`: assert a unit with a submission amended after labelling renders the badge **plus** the changed-since notice, and that no new label row appeared (FR-DL-053, FR-DL-068)
- [X] T056 [US3] In `src/cli.py`: add a `label` click group and a `drain` command — `aiq label drain [--cycle CYCLE_ID] [--limit N]` — on the shape of the `telemetry` group at [cli.py:547](../../src/cli.py#L547). It completes outstanding disputes of passes that **already exist** and **never creates a pass row**, so a unit never dispatched stays `never_labelled`, which is what the spec's "enabled part-way through a cycle" edge case requires. Report `labelling_counts` before and after. Exit non-zero only on a configuration error, never on labelling failures, which are data
- [X] T057 [US3] In `tests/unit/test_label_retry_exhaustion.py`: assert `aiq label drain` completes a pass dispatched while the provider was down **without creating a pass row** — the distinction between finishing an existing pass and dispatching a new one is what reconciles FR-DL-007 with a transient outage ([research.md](research.md) R6), and it is load-bearing rather than pedantic

**Checkpoint**: `pytest tests/unit/test_label_provenance.py tests/unit/test_label_retry_exhaustion.py -q` green. Every label in the system is now traceable to its inputs and its producer, and a provider outage is recoverable without violating the once-only rule.

---

## Phase 6: User Story 4 (P2) — Access disputes are separated from portal disputes

> **Goal**: A unit whose disputes are mostly access failures is distinguishable at a glance from one at the same rate whose disputes are interpretive.
>
> **Independent test**: Construct one unit whose disputes are entirely access failures and one entirely interpretive, at the same rate, and verify the two are distinguishable **without opening individual indicators**.

- [X] T058 [P] [US4] In `tests/unit/test_label_surfaces.py`: construct two units with identical disagreement rates, one all `ONE_BLOCKED` and one all `DIFFERENT_JUDGEMENT`, and assert they are distinguishable from the project detail page alone (SC-005)
- [X] T059 [US4] In `src/portal/disagreement_labels.py`: add `unit_label_composition(repo, session_id, portal_id)` returning the per-label counts for a unit over `unit_labelling_state`, so a reviewer sees the composition without opening each indicator (FR-DL-061). A pure read; it reuses the projection rather than re-deriving state
- [X] T060 [US4] In `src/portal/admin.py::admin_project_detail` ([admin.py:355](../../src/portal/admin.py#L355)): pass the composition to the template for each unit. **A GET handler** — projection only, no dispatch and no model call (FR-DL-045)
- [X] T061 [US4] In `src/portal/templates/admin_project_detail.html`: render the per-unit label composition **beside the existing discrepancy badge**, not in place of it. The rate is the governance figure and stays primary; the composition is description ([contracts/surfaces-and-measures.md](contracts/surfaces-and-measures.md) §1)
- [X] T062 [US4] In `src/portal/templates/admin_project_detail.html`: confirm the composition carries no ordering or colouring that implies an access dispute counts for less. FR-DL-047 keeps every dispute in the round regardless of label, and a surface that implies otherwise contradicts the code beneath it (D8, the clarify answer on routing)

---

## Phase 7: User Story 5 (P2) — Recurring interpretive splits identify ambiguous indicators

> **Goal**: A questionnaire owner sees which indicators repeatedly produced opposite answers from assessors looking at the same evidence, ranked, with the number of units behind each figure visible.
>
> **Independent test**: Label disputes across units in which one indicator is deliberately ambiguous, then verify it ranks highest and that different-source and access disputes do not contribute.
>
> This is the durable output of the whole feature, and the last thing buildable, because it needs labels across many units before it means anything.

- [X] T063 [P] [US5] In `tests/unit/test_indicator_ambiguity.py`: implement [quickstart.md](quickstart.md) Scenario 8 — an indicator disputed in eight units with six `DIFFERENT_JUDGEMENT` ranks above one disputed in eight with six `ONE_BLOCKED`; `DIFFERENT_CONTENT` does **not** count toward the measure, the split that keeps portal volatility out of it (FR-DL-071); `units_measured` and `labelled_share` are present on every row including when only part of the cycle is labelled; and `indicator_ambiguity(cycle_id=X)` and `indicator_ambiguity()` return the per-project and cross-project views **from the same code path** (FR-DL-075)
- [X] T064 [US5] In `src/portal/disagreement_labels.py`: implement `IndicatorAmbiguity` and `indicator_ambiguity(repo, cycle_id=None)` per [contracts/surfaces-and-measures.md](contracts/surfaces-and-measures.md) §3 over T016's aggregate. Key by `indicator_id` where present and `question_id` otherwise ([research.md](research.md) R11). **Only `DIFFERENT_JUDGEMENT` counts** — access failures, different sources and unlabelled disputes must not inflate it, or the measure stops meaning "this question is ambiguous" and starts meaning "this question caused trouble"
- [X] T065 [US5] In `src/portal/disagreement_labels.py`: return `units_measured`, `units_total` and `labelled_share` on every row (FR-DL-072, FR-DL-073). A ranking computed over a third of a cycle is legitimate and must **look like** what it is
- [X] T066 [US5] In `src/portal/admin.py`: add `GET /admin/projects/{cycle_id}/ambiguity` calling `indicator_ambiguity(cycle_id=cycle_id)` — the Senior Reviewer's per-project view, a sibling of the escalations route at [admin.py:1015](../../src/portal/admin.py#L1015). **Note the corrected path**: `/admin/questionnaires/{set_id}` is the indicator set, keyed by set id, not the cycle
- [X] T067 [US5] In `src/portal/admin.py`: add `GET /admin/indicators/ambiguity` calling `indicator_ambiguity()` unfiltered — the Administrator's cross-project view, the one that identifies an indicator as ambiguous in general rather than contested in one country. **That is the whole of the scope distinction and it is presentational**: nothing prevents a request to the unfiltered route, as the spec's Known Limitations records and Out of Scope confirms. Add a comment saying so rather than implying an enforcement that does not exist (FR-DL-067)
- [X] T068 [US5] In `src/portal/templates/admin_indicator_ambiguity.html`: render the ranked table with `units_measured` and `labelled_share` **beside each figure, never behind a tooltip** (FR-DL-072, FR-DL-073). One template serves both routes; the only difference is the title and whether a cycle is named

---

## Phase 8: User Story 6 (P3) — Thin evidence is measured rather than guessed at

> **Goal**: The proportion of disputes whose written material was too thin to characterise is reported, so a future decision to make notes mandatory rests on the observed rate rather than an expectation of it.
>
> **Independent test**: Submit disputes with empty and with minimal notes and verify they are labelled insufficient rather than assigned a substantive label, and that the proportion is reportable.

- [X] T069 [P] [US6] In `tests/unit/test_indicator_ambiguity.py`: assert the `NOT_ENOUGH_NOTES` proportion is reportable for a cycle (FR-DL-074, SC-007), and that a dispute where neither assessor wrote notes and both cited the same portal carries that label rather than a substantive one
- [X] T070 [US6] In `src/portal/disagreement_labels.py`: add the insufficient-notes proportion to `indicator_ambiguity`'s cycle-level return, computed over the cycle's labelled disputes
- [X] T071 [US6] In `src/portal/templates/admin_indicator_ambiguity.html`: present the proportion as a **headline figure rather than a footnote** — this is the number that decides whether notes should become mandatory ([contracts/surfaces-and-measures.md](contracts/surfaces-and-measures.md) §3). Same file as T068, so the two sequence

---

## Phase 9: Polish and cross-cutting concerns

- [X] T072 [P] In `src/api/schemas.py`: add the three response models for [contracts/surfaces-and-measures.md](contracts/surfaces-and-measures.md) §4. The labels model carries `question_id`, `state`, `label`, `badge`, `observations`, `stale` and `provenance` — and **no field capable of holding an assessor's answer or notes**. Verify by reading the model's fields, not by intending not to populate one
- [X] T073 In `src/api/routers/labels.py`: implement `GET /cycles/{cycle_id}/units/{portal_id}/labels`, `GET /cycles/{cycle_id}/indicator-ambiguity` and `GET /labelling/counts` under the existing router-level `X-API-Key` dependency, all three as **pure reads over the projection** (FR-DL-081). **None may create a record or invoke a model** — the mistake `compute_portal_discrepancy` exists to prevent, repeated here for the same reason (FR-DL-045)
- [X] T074 In `src/api/app.py`: register the new router alongside the fifteen existing `include_router` calls at [app.py:42](../../src/api/app.py#L42)
- [X] T075 [P] In `tests/unit/test_label_api_parity.py`: implement [quickstart.md](quickstart.md) Scenario 9 — drive one unit to completion **entirely through the REST API** and another through the portal, and assert identical pass and label rows differing only in `dispatched_by` (FR-DL-080). This is the only test that catches a missing T038, and every portal test passes without it
- [X] T076 [P] In `tests/unit/test_label_api_parity.py`: assert `cost_ledger_entries` gains rows with `stage="disagreement_labelling"` and `agent_index IS NULL`, distinguishable from prefill rows **by stage alone** (FR-DL-090); that deterministic labels add no ledger rows (SC-009); and that `labelling_counts` reports a rising `awaiting` under a down provider and a rising `exhausted` after three runs (FR-DL-092)
- [X] T077 [P] In `src/portal/seed.py`: seed one unit per labelling state — `never_labelled`, `awaiting`, `established` (with at least one deterministic and one classifier label), and `exhausted` — plus one access-dominated and one interpretation-dominated unit at the same rate for T058's fixture shape. Nothing else in the tree constructs them
- [ ] T078 Run the full suite from the repo root: `pytest -q`. Compare against T001's baseline — the count rises by the new tests and nothing previously green has gone red
- [ ] T079 Re-run T002's isolation check and T047's diff check as the final word: `git diff --stat -- src/portal/discrepancy.py` empty, and none of the six protected files in `git diff --name-only`. If either has moved, the Constitution gate that rests on it has failed regardless of what the tests say
- [ ] T080 Walk [quickstart.md](quickstart.md) Scenarios 0–9 in order against a fresh database via `aiq serve` and the seeded demo data, confirming each expectation by hand as well as by test
- [ ] T081 **Optional, costs money.** Run [quickstart.md](quickstart.md) Scenario 10: `aiq label drain --cycle <cycle_id> --limit 5` against the live provider, then **read the five `stated_reason` values against the notes**. This is the only check that tells you whether the instruction distinguishes **Saw different things** from **Judged differently** in practice — the hardest call the classifier makes, and the one the ambiguity measure depends on. Run it before trusting any ambiguity ranking: a measure built on a classifier that cannot draw its central distinction is worse than no measure
- [ ] T082 Run `graphify update .` from the repo root to refresh `graphify-out/graph.json`, which is stale as of this feature's planning — it still indexes the deleted `specs/001`–`specs/014` trees ([plan.md](plan.md) Notes)
- [ ] T083 Re-read [plan.md](plan.md)'s Constitution Check table against the implemented code and confirm all nine gates still hold — in particular that `label_classifier.py` still does not import `Prefill`, that no GET handler in `src/portal/admin.py` or `src/api/routers/labels.py` dispatches or classifies, that the three tables have no mutator in `src/shared/persistence/repositories.py`, and that `publication_readiness` still contains no reference to labelling

---

## Dependencies

```
Phase 1 (Setup, scaffolds, the isolation guard)
   │   T002 is a standing invariant, re-checked at T079
   ▼
Phase 2 (Foundational: enums, tables, repos, settings, pre-pass, projection)
   │   blocks every story phase
   │   Scenario 2 already passes here, with no model code in existence
   ▼
Phase 3 (US1 — classifier, dispatch, runner, the badge)   ◀── MVP
   │        T037+T038 atomic
   ▼
Phase 4 (US2 — isolation proved)          ◀── minimum safe release is 3 + 4
   │
   ▼
Phase 5 (US3 — provenance, retry cap, exhaustion, drain)
   │
   ├──▶ Phase 6 (US4 — per-unit composition)
   │
   └──▶ Phase 7 (US5 — the ambiguity measure)
             │
             ▼
        Phase 8 (US6 — insufficient-notes proportion)
             │
             ▼
        Phase 9 (Polish)
```

**Story-level dependencies:**

| Story | Depends on | Why |
|---|---|---|
| US1 | Phase 2 | the tables, the pre-pass, the projection |
| US2 | US1 | there must be labelling before its absence of effect can be proved |
| US3 | US1 | provenance is a property of records US1 creates |
| US4 | US1 only | composition is an aggregate over the projection; independent of US3 |
| US5 | US1 only | the measure reads label rows; independent of US3 and US4 |
| US6 | US5 | the proportion is reported on US5's routes |

**Cross-story note**: Phases 6 and 7 depend only on Phase 3 and are fully independent of each other and of Phase 5. They are placed after Phase 5 only to keep the three P1 stories ahead of the two P2 ones. A team of two can run Phase 5 and Phase 7 concurrently as soon as Phase 3 lands.

---

## Parallel Execution Examples

**Phase 1** — after T001 and T002, six tasks are independent:

```
T003 (src/portal/disagreement_labels.py)      ┐
T004 (src/portal/label_classifier.py)         │
T005 (src/api/routers/labels.py)              ├── all different files
T006 (admin_indicator_ambiguity.html)         │
T007 (ten test scaffolds)                     │
T008 (tests/unit/conftest.py)                 ┘
```

**Phase 2** — T018/T019 (settings and validation) run alongside everything else. T009/T010 both edit `entities.py` and sequence; T013–T016 all edit `repositories.py` and sequence; T021–T024 all edit `disagreement_labels.py` and sequence. T011 and T020 are test files and parallel with all of it.

**Phase 3** — T025, T026 and T027 are three different test files and fully parallel. T028–T032 all edit `label_classifier.py` and sequence; T033–T036 all edit `disagreement_labels.py` and sequence, but the two modules can be built concurrently by two people. **T037 and T038 are one atomic group and cannot be split.** T041 is parallel with T039/T040.

**Phase 4** — T042 and T046 are the same test file as each other's neighbours but cover disjoint scenarios; only T042 and T046 carry `[P]` and they touch different modules' fixtures. T045 edits `admin_escalations.html`, which T040 also touched, so it is not parallel with any Phase 3 template task still in flight.

**Phase 5** — T048, T049, T050 and T055 are test tasks across two files and largely parallel; T053 and T054 both edit `admin_escalations.html` and sequence. T056 (`cli.py`) is parallel with all of them.

**Phase 7** — T063 (test) is parallel with T064/T065 (`disagreement_labels.py`, sequencing with each other) and with T068 (template). T066 and T067 both edit `admin.py` and sequence.

**Phase 9** — T072, T075, T076 and T077 are four different files and fully parallel. T073 depends on T072, and T074 on T073. T078–T083 are sequential verification steps.

---

## Independent Test Criteria

| Story | Independently testable by |
|---|---|
| US1 | one unit with one dispute of each kind, both completions declared, and a fake provider — **no measure, no API, no provenance surface required** |
| US2 | the same unit assessed twice, once with the provider disabled, and a serialised-row diff — **no labels need be readable for this to pass** |
| US3 | one labelled unit, then recompute, amend, reconcile, sign off and publish, counting model calls on the fake |
| US4 | two hand-constructed units at the same rate, one all-access and one all-interpretive — **from the project detail page alone** |
| US5 | labels seeded directly across units for one deliberately ambiguous indicator — **no pass need ever run** |
| US6 | disputes with empty and minimal notes, and the cycle-level proportion |

---

## Format Validation

All 83 tasks follow `- [ ] Tnnn [P?] [USn?] description with file path`. Story labels appear on Phase 3–8 tasks only; the eight Setup, sixteen Foundational and twelve Polish tasks carry none. No task marked `[P]` shares a file with another `[P]` task in the same phase.
