# Tasks: Prefilled Questionnaire Blank-Field Fallback

**Feature**: `004-blank-field-fallback`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [plan.md](plan.md) | [research.md](research.md) | [data-model.md](data-model.md) | [contracts/reason-tags.md](contracts/reason-tags.md) | [contracts/export-schema-delta.md](contracts/export-schema-delta.md) | [contracts/review-surface-delta.md](contracts/review-surface-delta.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-08-16

## Conventions

- `[P]` = parallelizable (different file, no dependency on an incomplete task in this list).
- `[USn]` = belongs to User Story n's phase (spec.md priorities: US1=P1, US2=P2, US3=P3). Setup, Foundational, and Polish tasks carry no story label.
- Every persisted entity, enum member, and the unit state machine are **unchanged** by this feature (research.md R3; plan.md Constitution Check) — no task below touches `shared/state/unit_state.py`, `shared/state/entities.py`, or `shared/persistence/schema.py`.

---

## Implementation Strategy

MVP-first delivery in three increments, each independently testable per its own quickstart.md scenario(s):

1. **Increment 1** (Phase 1–2): Setup + the two shared building blocks (`reason_tags.py`'s table, the blocked-state helper). Zero visible behavior change yet.
2. **Increment 2** (Phase 3, US1 — P1, the MVP): Every blocked question shows a blank field and a canonical reason instead of a forced/missing answer, on the existing review screen, without holding up the rest of the portal.
3. **Increment 3** (Phase 4, US2 — P2): Evidence and attempt history are bundled on that same screen, and a reviewer's answer to a blocked question actually reaches the export as delivered (closing the two adjacent gaps research.md found: the missing `UNASSESSABLE` export path and the dead `get_assessor_decision` lookup).
4. **Increment 4** (Phase 5, US3 — P3): Reason tags are proven exhaustive and mutually distinguishable, and the one two-way case (language declined vs. window-expired) is wired correctly.
5. **Polish** (Phase 6): Full regression pass, manual quickstart walkthrough, copy review.

---

## Phase 1: Setup

> Goal: Scaffold the two new files. No new dependency — `pyproject.toml` is unchanged.

- [X] T001 Create `src/shared/state/reason_tags.py` with a module docstring referencing [contracts/reason-tags.md](contracts/reason-tags.md) and the necessary imports (`EscalationReason`, `UnitState` from `shared.state.entities`)
- [X] T002 [P] Create `tests/unit/test_reason_tags.py` with a `@pytest.mark.unit` module marker and the import of `shared.state.reason_tags`
- [X] T003 [P] Create `tests/unit/test_blank_field_fallback.py` with a `@pytest.mark.unit` module marker and the imports needed to build a `Repository` against an in-memory/temp SQLite DB (mirror the fixture setup already used in `tests/unit/test_escalation_concurrency.py`)

---

## Phase 2: Foundational — Shared building blocks

> Goal: The reason-tag table and the blocked-state check exist and are independently correct before any story wires them into review or export.
>
> **Must complete before Phase 3.** Every story phase below depends on both.

- [X] T004 In `src/shared/state/reason_tags.py`: define `@dataclass(frozen=True) class ReasonTag` (`text: str`, `condition: EscalationReason`) and the `REASON_TAGS: dict[EscalationReason, str]` template table exactly as specified in [data-model.md](data-model.md)'s template table (all seven `EscalationReason` members — `REQUIRES_AUTHENTICATED_ACCESS`, `UNRESOLVED_DISAGREEMENT`, `LANGUAGE_NOT_SUPPORTED`, `LANGUAGE_DECLINED`, `UNREACHABLE_PORTAL`, `UNVERIFIABLE_TARGET`, `NO_USABLE_URL`; `PORTAL_DISCREPANCY` is intentionally excluded per spec.md Assumptions — it never blanks an individual question)
- [X] T005 In `src/shared/state/reason_tags.py`: implement `def reason_tag(escalation_reason: str, context: dict, resolution_manner: str | None = None) -> ReasonTag` per [contracts/reason-tags.md](contracts/reason-tags.md) — looks up the template, fills `{language}` from `context.get("detected_language")` and `{attempts}` from the unit's stored attempt count, and for `LANGUAGE_DECLINED` selects between the "reviewer declined" wording and the "window expired" wording based on `resolution_manner` (`"explicit"` vs `"window_expired"`); raises `KeyError` (not a silent fallback) if `escalation_reason` doesn't match any `EscalationReason` value, so a future untagged reason fails loudly in tests rather than rendering a generic label live
- [X] T006 [P] In `src/shared/state/reason_tags.py`: define `BLOCKED_UNIT_STATES = frozenset({UnitState.ESCALATED.value, UnitState.UNASSESSABLE.value})` and `def is_blocked(state: str) -> bool` (research R2) — the single shared check `review/query.py`, `review/unlock.py`, and `export/writer.py` all use instead of comparing to the literal string `"escalated"`
- [X] T007 In `tests/unit/test_reason_tags.py`: add `test_every_escalation_reason_has_a_template` — iterate `EscalationReason`, skip `PORTAL_DISCREPANCY`, assert `reason_tag(r.value, {}).text.startswith("Left blank: ")` for every remaining member (fills required placeholders with fixture values where needed, e.g. `{"detected_language": "fr"}` for `LANGUAGE_NOT_SUPPORTED`)

---

## Phase 3: US1 (P1) — Blank field instead of a forced guess or a blocked screen

> Goal: Every blocked question — including the previously-invisible `UNASSESSABLE` ones — appears in its portal's review set with a blank answer and a canonical reason, and never holds up any other question on the same portal.
>
> **Independent test**: seed one unit per blocking condition; open the portal's review set; every blocked question shows a blank answer and a "Left blank: ..." reason; every non-blocked question on the same portal remains independently approvable/editable (spec.md User Story 1, Acceptance Scenarios 1–4).

- [X] T008 [US1] In `src/review/query.py::build_question_review`: replace the `escalated = unit_state == "escalated"` check with `shared.state.reason_tags.is_blocked(unit_state)` (T006); add a `reason_tag: ReasonTag | None` field to `QuestionReviewView`, populated via `shared.state.reason_tags.reason_tag(escalation_reason, unit, ...)` (T005) whenever the unit is blocked, else `None`
- [X] T009 [US1] In `src/review/query.py::build_question_review`: confirm (and add an inline assertion/comment if not already true) that `delivered_answer` and `system_proposed_answer` are never set to a non-`None` placeholder for a blocked unit with no `AssessorDecision` — this is the direct implementation of FR-BF-002, verified by T013 below
- [X] T010 [US1] In `src/review/unlock.py::portal_review_status`: replace `if state == UnitState.ESCALATED.value` with `if shared.state.reason_tags.is_blocked(state)` (T006) when appending to `escalated_question_ids`, so `UNASSESSABLE` units are included; `unlocked`/`terminal_count` logic is unchanged
- [X] T011 [US1] In `src/review/web/templates/question.html`: replace the `{% if view.escalated %}<p ...>Escalated{% if view.escalation_reason %}: {{ view.escalation_reason }}{% endif %}</p>{% endif %}` block with `{% if view.escalated %}<p class="badge badge--fail" role="alert">{{ view.reason_tag.text }}</p>{% endif %}`; change `Proposed answer: <strong>{{ view.delivered_answer }}</strong>` so a `None` value renders as an explicit placeholder (e.g. `<em>Not yet answered</em>`) instead of the literal text `None`
- [X] T012 [US1] In `src/review/web/templates/question.html`: wrap the existing Approve `<form>` in `{% if view.system_proposed_answer is not none %}...{% endif %}` so it is not rendered for a blocked question with nothing to approve (research R7 — prevents the existing `/approve` endpoint from ever being invoked with a `None` answer)
- [X] T013 [P] [US1] In `tests/unit/test_blank_field_fallback.py`: add `test_coverage` — parametrized over the seven blocking conditions from T004 (seed a unit per condition directly via `repo.upsert_unit(..., state, {"escalation_reason": reason.value, ...})`, matching `NO_USABLE_URL` to `UnitState.UNASSESSABLE` and the rest to `UnitState.ESCALATED` per `orchestration/scheduler.py`'s actual `escalate()` calls); assert `build_question_review()` returns `escalated=True`, `delivered_answer is None`, `system_proposed_answer is None`, and a non-empty `reason_tag.text`; assert a sibling `DELIVERED` unit on the same portal is unaffected (`escalated=False`, real `delivered_answer`)
- [X] T014 [US1] In `tests/unit/test_blank_field_fallback.py`: add `test_portal_unlock_includes_unassessable` — a portal whose questions are a mix of `DELIVERED`, `ESCALATED`, and `UNASSESSABLE` units is reported `unlocked=True` by `portal_review_status()` once every question is terminal, and `escalated_question_ids` contains both the `ESCALATED` and the `UNASSESSABLE` question IDs (closes the gap research R2 found)
- [X] T015 [US1] Extend `seed_demo_review()` in `src/review/seed_demo.py` to also seed one unit per blocking condition (quickstart.md Scenario 0), so `aiq seed demo-review` followed by `aiq serve` demonstrates User Story 1 manually with no assessment pipeline running

---

## Phase 4: US2 (P2) — Evidence and attempt history on screen; reviewer's answer reaches export

> Goal: A reviewer can see everything the pipeline gathered before a block — URLs, partial evidence, every round's agent positions, retry/attempt counts — on the same screen as the blank field, and supplying a final answer there makes that question exportable as delivered.
>
> **Independent test**: for a disagreement-blocked unit, every round's agent positions and the points of disagreement are visible on its review screen; for an unreachable-portal unit, the attempt count is visible; posting an `edit` decision for either then produces a delivered NDJSON record with the reviewer's answer (spec.md User Story 2, Acceptance Scenarios 1–4; SC-005).

- [X] T016 [US2] In `src/review/query.py`: add `@dataclass class AttemptHistoryView` (`resolution_attempts: list[dict]`, `reachability_attempts: int | None`, `verification_attempts: int | None`, `retry_counts: list[dict]`, `points_of_disagreement: list[str]`, `has_any_evidence: bool`) per [data-model.md](data-model.md)
- [X] T017 [US2] In `src/review/query.py::build_question_review`: when the unit is blocked, populate `attempt_history` by reading `unit.get("resolution_history", [])`, `unit.get("reason")`/attempt-count fields already stored by `escalate()`'s context, each agent run's `confidence_retry_count`/`validation_retry_count` (via `repo.list_agent_runs(session_id, question_id, portal_id)` called **without** the `round_number` filter so every round is returned — R4), each run's `ValidationResult.verification_attempts` (via `repo.list_validation_results(run.run_id)`), and every `AdjudicationResult.flag_reason` across rounds (via `repo.list_adjudication_results(session_id, question_id, portal_id)`, already called); set `has_any_evidence = evidence is not None`
- [X] T018 [US2] In `src/review/query.py::build_question_review`: when blocked, set `agent_positions` from the full unfiltered `repo.list_agent_runs(...)` result (all rounds) instead of the round-filtered call currently used for the adjudicated-round display, so a disagreement block shows every round's positions (FR-BF-009)
- [X] T019 [US2] Implement `render_attempt_history_html(history: AttemptHistoryView) -> str` in `src/review/web/detail.py`, alongside the existing `render_agent_detail_html`, presenting resolution attempts, reachability/verification counts, retry counts, and points of disagreement behind a `<details>/<summary>` disclosure (research R6, WCAG-AA pattern reused unchanged)
- [X] T020 [US2] In `src/review/web/app.py::question_page`: call `render_attempt_history_html(view.attempt_history)` when `view.escalated` and pass the result to the template as `attempt_history_html`; in `src/review/web/templates/question.html`, render `{{ attempt_history_html | safe }}` inside the existing `{% if view.escalated %}` block
- [X] T021 [P] [US2] In `tests/unit/test_blank_field_fallback.py`: add `test_attempt_history` — for a seeded disagreement-blocked unit with two rounds of agent runs, assert `attempt_history.points_of_disagreement` is non-empty and `agent_positions` covers both rounds; for a seeded unreachable-portal unit, assert `attempt_history.reachability_attempts` matches the seeded count; for a seeded `NO_USABLE_URL`/`UNASSESSABLE` unit with no evidence, assert `attempt_history.has_any_evidence is False`
- [X] T022 [US2] In `src/export/writer.py::export_cycle_answers`: replace `dec = repo.get_assessor_decision(...) if hasattr(repo, "get_assessor_decision") else None` with `dec = repo.latest_assessor_decision(sess_used.session_id, q.question_id, p.portal_id)` (research R3 — fixes the dead lookup for every unit, not only blocked ones)
- [X] T023 [US2] In `src/export/writer.py::export_cycle_answers`: change the exclusion condition from `if not unit or unit.get("state") != UnitState.DELIVERED.value:` to also treat a unit as delivered when `shared.state.reason_tags.is_blocked(unit.get("state"))` **and** T022's `dec` is not `None` — such a unit now builds a normal delivered `record` (reusing the existing `record = {...}` construction below) instead of an `excluded_items` entry, with `provenance` taken from `dec` exactly as the `DELIVERED` path already computes it
- [X] T024 [US2] In `src/export/writer.py::export_cycle_answers`: for units that remain excluded, add `"reason_tag": shared.state.reason_tags.reason_tag(esc_reason, unit).text if unit and unit.get("escalation_reason") else None` to the `excluded_items.append({...})` dict (FR-BF-015)
- [X] T025 [P] [US2] In `src/export/invariants.py`: add the single missing member, `"language_not_supported"`, to `VALID_EXCLUSION_REASONS` (every other `EscalationReason` value, including `"portal_discrepancy"`, is already present); add a test in `tests/unit/test_phase9_export.py` asserting `VALID_EXCLUSION_REASONS == {r.value for r in EscalationReason} | {"awaiting_human_review"}` (research R5 — the pre-existing `"awaiting_human_review"` code covers a question simply not yet reviewed, not a blocking condition, so it stays as the one addition beyond the enum)
- [X] T026 [P] [US2] In `tests/unit/test_phase9_export.py`: add `test_blocked_unit_with_decision_reaches_export` — seed a blocked unit, record an `edit` decision via `review.actions.edit(...)`, run `export_cycle_answers()`, assert the question appears in the NDJSON output with `delivered_answer: true` and `provenance: "human_edited"`, and does **not** appear in the exclusion report (quickstart Scenario 4)
- [X] T027 [P] [US2] In `tests/unit/test_phase9_export.py`: add `test_blocked_unit_without_decision_stays_excluded` — the same seeded unit with no decision recorded appears only in the exclusion report, with both `reason` (unchanged raw code) and the new `reason_tag` populated
- [X] T028 [P] [US2] In `tests/unit/test_phase9_export.py`: add `test_language_not_supported_exports_cleanly` — a cycle containing one unresolved `LANGUAGE_NOT_SUPPORTED`-escalated unit exports without raising `ExportInvariantError` (quickstart Scenario 5, reproduces then closes the T025 gap)

---

## Phase 5: US3 (P3) — Reason tags proven exhaustive and mutually distinguishable

> Goal: Every recognized blocking condition's tag reads differently from every other's, provably rather than by inspection; the one two-way condition (language declined vs. decision-window expiry) renders correctly for each of its two sub-cases.
>
> **Independent test**: one seeded unit per blocking condition, all seven-plus-one reason tags pairwise distinct; a `LANGUAGE_DECLINED` unit whose `LanguageDecision.resolution_manner == "explicit"` reads differently from one whose `resolution_manner == "window_expired"` (spec.md User Story 3, Acceptance Scenarios 1–3).

- [X] T029 [US3] In `src/review/query.py::build_question_review`: for a blocked unit whose `escalation_reason == "language_declined"`, look up the portal's decision via `repo.list_language_decisions(portal_id)` (already exists — no new repository method needed) and pass its `resolution_manner` through to `reason_tag()` (T005)
- [X] T030 [US3] In `src/export/writer.py::export_cycle_answers`: apply the same `resolution_manner` lookup as T029 when building the `reason_tag` for an excluded `language_declined` item, so the export's tag matches what the reviewer saw
- [X] T031 [P] [US3] In `tests/unit/test_reason_tags.py`: add `test_language_declined_sub_cases_differ` — `reason_tag("language_declined", {}, resolution_manner="explicit").text != reason_tag("language_declined", {}, resolution_manner="window_expired").text`, and neither is empty
- [X] T032 [P] [US3] In `tests/unit/test_reason_tags.py`: add `test_determinism` — calling `reason_tag()` twice with identical inputs returns identical `.text` (FR-BF-006)
- [X] T033 [P] [US3] In `tests/unit/test_blank_field_fallback.py`: add `test_tags_mutually_distinguishable` — build a review view for one seeded unit per blocking condition (reusing T013's fixtures) and assert `len({v.reason_tag.text for v in views}) == len(views)` (spec User Story 3, Acceptance Scenario 1)

---

## Phase 6: Polish & Cross-Cutting Concerns

> Goal: Full regression safety, and a manual walkthrough of every quickstart.md scenario against the seeded demo data.

- [X] T034 Run `pytest tests/unit tests/contract tests/integration -q` and confirm every test outside the files this feature added/modified passes unmodified — in particular `tests/unit/domain/test_unit_state.py`'s `assert_exhaustive_terminal_coverage`, which this feature must never cause to fail (plan.md Constitution Check; research R3)
- [X] T035 [P] Review the eight rendered reason-tag strings (T004's table) against spec.md's own three worked examples ("Left blank: Login authentication barrier observed", "Left blank: Unresolved AI disagreement after retry limit", "Left blank: Unsupported language 'fr' detected") and adjust wording only — not shape — if any reads awkwardly (contracts/reason-tags.md notes final copy is not fixed by the contract)
- [X] T036 Manually walk quickstart.md Scenarios 0–6 end-to-end via `aiq seed demo-review` + `aiq serve`: confirm every blocked question shows a blank field, its reason tag, and its attempt history; confirm Approve is absent and Edit successfully delivers an answer that then appears in a subsequent `aiq export` run

---

## Dependency Graph

```
T001 → T002, T003 (independent scaffolds)
T001 → T004 → T005 → T007
T001 → T006
T004, T005, T006 (Foundational) → all of Phase 3, 4, 5

T008, T009 (query.py, sequential — same function) → T013, T014
T010 (unlock.py, independent of T008/T009) → T014
T011, T012 (question.html, sequential — same file) → T015 (manual demo depends on the template rendering correctly)
T006 → T008, T010

T016 → T017 → T018 (query.py additions, sequential — same function/file)
T017, T018 → T019 → T020
T019, T020 → T021
T022 → T023 (writer.py, sequential — same function)
T023 → T024
T025 (invariants.py, independent of T022–T024)
T022, T023, T024 → T026, T027 (parallel)
T024, T025 → T028

T008 (reason_tag wired into query.py) → T029
T024 (reason_tag wired into writer.py) → T030
T005 → T031, T032 (parallel, independent of query.py/writer.py wiring)
T013, T029 → T033

T013, T021, T026, T027, T028, T033 (all story tests complete) → T034 → T035 → T036
```

---

## Parallel Execution Opportunities

| Group | Tasks | Can run in parallel after |
|---|---|---|
| Setup | T002, T003 | T001 |
| Foundational | T006 | T001 (independent of T004/T005's sequential chain) |
| US1 tests | T013 | T008, T009, T010 |
| US2 export tests | T026, T027, T028 | T022, T023, T024, T025 |
| US2 fixture work | T021 | T017, T018, T019, T020 |
| US3 reason-tag tests | T031, T032 | T005 (don't need query.py/writer.py wiring) |
| Polish | T035 | T034 |

Note: `review/query.py` (T008, T009, T016–T018, T029) and `export/writer.py` (T022–T024, T030) are each edited sequentially within their own story phase — genuine cross-task parallelism on those two files is limited. `question.html` (T011, T012, T020) is likewise sequential within itself. The reason-tag table (T004/T005) and the blocked-state helper (T006) are the only Foundational pieces safe to parallelize against each other.

---

## Story → Task Mapping

| Story | Priority | Requirements | Tasks | Independent test criteria |
|---|---|---|---|---|
| US1 | P1 (MVP) | FR-BF-001, FR-BF-002, FR-BF-003, FR-BF-004, FR-BF-005 | T008–T015 | Every blocking condition shows a blank answer + reason on its portal's review screen; no blocked question prevents any other question or the portal itself from becoming reviewable |
| US2 | P2 | FR-BF-008–FR-BF-015 | T016–T028 | Attempt history and evidence (or an explicit "no evidence" state) are visible on the blocked question's own screen; a reviewer-supplied answer reaches the export as delivered; `language_not_supported` no longer breaks export |
| US3 | P3 | FR-BF-006, FR-BF-007 | T029–T033 | Every recognized condition's tag is textually distinct from every other's; the two `language_declined` sub-cases read differently |

---

## MVP Scope

**Minimum viable fix**: T001–T015 (Setup + Foundational + US1). At this point every blocking condition — including the previously-invisible `UNASSESSABLE` one — is visible to a reviewer as a blank field with a specific reason, and no blocked question ever holds up review of the rest of its portal. This alone resolves the spec's headline requirement (no forced answers, no blocked review).

**Full feature**: T001–T036 — adds evidence/attempt-history bundling and the export-reachability fix (US2, the second-largest piece of real behavior change in this feature), tag exhaustiveness/distinguishability proof (US3), and the full regression + manual walkthrough (Polish).

**Recommended sequencing note**: T022 (fixing the dead `hasattr(repo, "get_assessor_decision")` lookup) changes export output for **every** `DELIVERED` unit that has a human decision, not just blocked ones — this is called out as a risk in plan.md and should land as its own reviewable commit within Phase 4, not buried inside T023's blocked-unit eligibility change, even though both are small edits to the same function.

---

## Format Validation

All 36 tasks follow `- [ ] T0NN [P?] [USn?] Description with exact file path(s)`. Setup (T001–T003), Foundational (T004–T007), and Polish (T034–T036) carry no story label. Every US-labeled task (T008–T033) names its story. Every task names at least one concrete file path.
