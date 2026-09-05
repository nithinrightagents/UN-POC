# Tasks: Unit-Level Assessor Assignment

**Feature**: `014-unit-assessor-auto-assignment`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [plan.md](plan.md) | [research.md](research.md) | [data-model.md](data-model.md) | [contracts/assessor-source-and-ingestion.md](contracts/assessor-source-and-ingestion.md) | [contracts/unit-assignment-and-override.md](contracts/unit-assignment-and-override.md) | [contracts/assignment-gated-access.md](contracts/assignment-gated-access.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-09-05

## Conventions

- `[P]` = parallelizable (different file, no dependency on an incomplete task in this list). Two tasks editing the same file are never both marked `[P]`.
- `[USn]` = belongs to User Story n's phase (spec.md priorities: US1–US3 = P1, US4 = P2). Setup, Foundational, and Polish tasks carry no story label.
- **No new dependency.** FastAPI, Jinja2, and SQLite are already declared; nothing below adds a package ([plan.md](plan.md) Technical Context).
- **No model call anywhere in this feature.** The human A/B path has no AI in it, so every test task below runs offline and free.
- **`src/agents/**`, `src/orchestration/**`, `src/export/**`, `src/benchmark/**`, `src/review/**`, and `src/shared/state/unit_state.py` are never edited by any task below.** Spec 013 removed AI from the portal and this feature adds none back, assignment recommendation included ([spec.md](spec.md) Out of Scope). A task that needs to touch one of those files has gone wrong.
- **`src/portal/discrepancy.py`, `src/portal/reconciliation.py`, and `src/portal/tolerance.py` are never edited by any task below.** Reconciliation compares the A-role and B-role answers of record regardless of who submitted them (A6). If a task appears to need a change there, the blind-read boundary has been crossed and the design is wrong, not the file.
- **`tests/independence/` is never edited by any task below.** It is the regression signal for FR-AC-004; a task that needs to change it has widened the blind-read boundary.
- **The platform selects nobody.** No task below may introduce matching, ranking, capacity, or load-balancing. FR-IN-004 and SC-004 assert that nothing chooses; the roster's `languages`/`organisation`/`notes` exist solely for FR-MO-003's override display, and T042 tests that assignment cannot read them.

---

## Implementation Strategy

Seven increments.

1. **Increment 1** (Phase 1, Setup): Baseline run, the two seed data files, and empty scaffolds. No behaviour change.
2. **Increment 2** (Phase 2, Foundational): Four tables, the entities, the repository methods, the source loader and ingestion, the legacy migration, and the **retirement of the project-level pair**. Largest phase by some distance, because this feature's machinery is shared rather than per-story. **Nothing in Phases 3–6 can start until it lands.** T024–T028 are one atomic group — see the note there.
3. **Increment 3** (Phase 3, **US1** — P1, the MVP): `create_units`, verbatim application, the four refusals, staffing counts, and the per-unit display. This is the feature's headline: a project's units arrive already staffed with nobody entering anything.
4. **Increment 4** (Phase 4, **US2** — P1): Access derived from the assignment. **The widest change in the feature** — seven portal routes, two API routers, two templates, both seed scripts. It lands as one change rather than route-by-route because a half-migrated codebase leaves the old `role`-from-request path alive for whatever forgets to call the resolver.
5. **Increment 5** (Phase 5, **US3** — P1): Per-unit override, the change log, and the preservation guarantees. Assignment arriving from an external database is only acceptable because it is correctable.
6. **Increment 6** (Phase 6, **US4** — P2): The gaps made visible. Deliberately thin, and honestly so: the four refusals themselves are built in Phase 3, because US1 is *wrong* without them — a defect entry must not staff a unit. This phase adds the reason surfacing and the assertions that prove nothing is silently half-staffed.
7. **Polish** (Phase 7): The read-only roster page, the demo seed rewrite, a blindness sweep, and full regression.

**MVP**: Phase 3 (US1) is a coherent, shippable increment on its own — units arrive staffed from the source database and the project reports its staffing. The minimum *useful* release is Phases 3 + 4 together, because per-unit pairs without assignment-gated access are decorative: an assessor can still open any unit in any role by editing the URL, exactly as today.

---

## Phase 1: Setup and baseline

> Goal: A green baseline, the seed source data, and empty scaffolds. No behaviour change.

- [X] T001 Run `pytest -q` from the repo root over `tests/` and record the passing count, plus the names of the four tests in `tests/unit/test_assessor_assignment.py`; this is the baseline every later phase is compared against, and those four are the only tests **expected** to go red in Phase 2 ([quickstart.md](quickstart.md) Prerequisites)
- [X] T002 [P] Create `data/reference/assessors.json` with 24 demonstration assessor records in the shape of [data-model.md](data-model.md) §10 — `assessor_id`, `display_name`, `email`, `organisation`, `languages`, `notes`. Fabricated personnel only, with `@ekap-demo.org` addresses; no real names and no real contact details, because `data/` is served statically at `/data` ([webapp.py:77](../../src/portal/webapp.py#L77))
- [X] T003 [P] Create `data/reference/unit_assessor_mapping.json` with 80 valid entries — 40 `unit_type: "country"` and 40 `unit_type: "city"`, `unit_code` drawn from `un_member_states.json` — plus the **four deliberate defect entries** of [data-model.md](data-model.md) §10: one naming the same assessor twice, one naming only `assessor_a_id`, one referencing an `assessor_id` absent from T002, and one for a `unit_code` no project can contain. Each defect entry carries a comment-free but obvious code (`IS`, `MT`, `LU`, `ZZ`) so a test can name it. Coverage of 40 per classification comfortably exceeds SC-001's twelve
- [X] T004 [P] Create `src/shared/reference/assessors.py` as a scaffold mirroring [`countries.py`](../../src/shared/reference/countries.py) — module-level `_REPO_ROOT`, two `_PATH` constants, frozen dataclasses, `@lru_cache(maxsize=1)`. Its docstring must state that these two functions are **the entire replacement seam** for the programme's real assessor database (FR-DB-005, SC-013), and that nothing else in the tree may open either JSON file
- [X] T005 [P] Create `src/portal/assignment.py` as a scaffold whose docstring states: this module is the single home for ingestion, verbatim application, validation, override, and role resolution; the portal **selects nobody** (FR-IN-004); and `unit_assessor_assignments` is a **lifecycle** table on the `reconciliation_rounds` precedent while `assignment_changes` is append-only ([research.md](research.md) R2)
- [X] T006 [P] Create four test modules as scaffolds with a `@pytest.mark.unit` module marker: `tests/unit/test_assessor_source.py`, `tests/unit/test_unit_assignment.py`, `tests/unit/test_assessor_access.py`, and `tests/integration/test_assignment_migration.py` (the last with `@pytest.mark.integration`)
- [X] T007 [P] In `tests/unit/conftest.py`: add the fixtures this feature's tests share, extending the existing file without replacing any spec 007/008/012 fixture — an `ingested` fixture calling `ingest_assessor_source(Repository(conn))` (needed because `conn`/`db_path` tests run `init_db` only, while `client` tests get ingestion free through the lifespan at [conftest.py:69-72](../../tests/unit/conftest.py#L69)), a `staffed_unit` factory returning a portal with a known pair assigned, and a `legacy_cycle` factory writing a `survey_cycles` row whose raw `data` JSON carries `assessor_a_email`/`assessor_b_email`

---

## Phase 2: Foundational — tables, ingestion, migration, and the retirement

> Goal: Everything every story phase depends on. **Must complete before Phase 3.**
>
> **T024–T028 are one atomic group.** Retiring the project-level pair, deleting its two routes, re-homing the freeze, migrating existing projects, and rewriting the tests that assert the old behaviour all land together. Split them and the intermediate state is worse than either end: delete `assign_assessors` without re-homing the guard and `status` never becomes `"locked"` again, so all fifteen guarded routes silently become editable mid-assessment — the exact skew the guard exists to prevent.

### Schema and entities

- [X] T008 In `src/shared/persistence/schema.py`: add the `assessors`, `unit_assessor_mapping`, `unit_assessor_assignments`, and `assignment_changes` tables with their four indexes exactly as given in [data-model.md](data-model.md) §1–4. Each DDL block carries a comment stating its classification — `unit_assessor_assignments` is **lifecycle** (mutable, `reconciliation_rounds` precedent), `assignment_changes` is **append-only** (`tolerance_changes` precedent), and the two ingested tables are **source replicas** that survive project deletion. `idx_unit_assignment_one_per_unit` is a correctness guarantee, not an optimisation; say so, so it is not later "tidied" into a plain index
- [X] T009 In `src/shared/state/entities.py`: add `Assessor`, `UnitAssessorMappingEntry`, `RoleAssignment`, `UnitAssessorAssignment`, and `AssignmentChange` dataclasses plus the `AssignmentSource` and `UnstaffedReason` enums, per [data-model.md](data-model.md) §1–4. `UnitAssessorMappingEntry.assessor_a_id`/`_b_id` are **deliberately nullable** — a source database naming only one role is a case the platform must detect and report (FR-IN-007), not one it may reject at load; document that on the fields
- [X] T010 In `src/shared/state/entities.py`: give `UnitAssessorAssignment` an `is_staffed` property returning `role_a is not None and role_b is not None` (FR-UA-005), and a `role_for(assessor_id)` helper returning `AssessorRole | None`. Same file as T009, so not parallel with it

### Persistence

- [X] T011 [P] In `src/shared/persistence/repositories.py`: add `upsert_assessor` (`ON CONFLICT(assessor_id) DO UPDATE`, so re-ingestion refreshes and never duplicates — FR-DB-004), `get_assessor`, `list_assessors`, `load_assessor_index`, `upsert_mapping_entry` (`ON CONFLICT(unit_type, unit_code) DO UPDATE`), and `load_mapping_index` returning `dict[tuple[str, str], UnitAssessorMappingEntry]`
- [X] T012 In `src/shared/persistence/repositories.py`: add `get_unit_assignment(cycle_id, portal_id)`, `list_unit_assignments(cycle_id)` returning a `dict` keyed by `portal_id`, and `upsert_unit_assignment(assignment)`. `upsert_unit_assignment` is the **only** mutator on the table and must be callable inside [`begin_immediate()`](../../src/shared/persistence/repositories.py#L978) so a read-modify-write of the pair serialises ([data-model.md](data-model.md) §3 Concurrency). Same file as T011
- [X] T013 In `src/shared/persistence/repositories.py`: add `insert_assignment_change(change)` and `list_assignment_changes(cycle_id, portal_id)` ordered by `changed_at`. **No update and no delete method** — the append-only property is enforced by the absence of a mutator, as spec 012 did for `tolerance_changes`
- [X] T014 In `src/shared/persistence/repositories.py`: add `has_any_human_activity(session_id) -> bool`, one `SELECT 1 ... LIMIT 1` against each of `human_assessor_submissions` and `assessor_completions`, both already indexed on `session_id` ([schema.py:306, 309](../../src/shared/persistence/schema.py#L306)). This is the new trigger for the freeze in T026
- [X] T015 In `src/shared/persistence/repositories.py`: extend `delete_cycle` ([repositories.py:84](../../src/shared/persistence/repositories.py#L84)) to delete `unit_assessor_assignments` and `assignment_changes` rows for the cycle. **`assessors` and `unit_assessor_mapping` must not be touched** — they are the ingested source, not project data, and surviving project deletion is what makes them so ([data-model.md](data-model.md) §9)

### Source loading and ingestion

- [X] T016 [P] Write `tests/unit/test_assessor_source.py` per [quickstart.md](quickstart.md) Scenario 0: a fresh database ingests 24 assessors and 84 mapping entries; a second ingestion leaves both counts unchanged (FR-DB-004); a mapping file with a duplicate `(unit_type, unit_code)` raises at load rather than silently keeping one; a missing required key or an unknown `unit_type` raises. Written before T017 and T018
- [X] T017 Implement `list_source_assessors()` and `list_source_mapping()` in `src/shared/reference/assessors.py`, reading T002 and T003. A malformed source file **must raise at load**, not yield an empty list — an empty roster that ingests cleanly leaves every unit unstaffed with `no_mapping_entry`, indistinguishable from a source database that genuinely covers nothing ([contracts/assessor-source-and-ingestion.md](contracts/assessor-source-and-ingestion.md) §1)
- [X] T018 Implement `ingest_assessor_source(r) -> IngestSummary` in `src/portal/assignment.py`: roster written **before** mapping, so the `unknown_assessor` check in T035 reads a complete roster. Idempotent by T011's upserts. It writes to `assessors` and `unit_assessor_mapping` only — **never** an assignment row (FR-IN-003 puts application at unit creation)
- [X] T019 Implement `validate_pair(assessor_a_id, assessor_b_id, roster) -> UnstaffedReason | None` in `src/portal/assignment.py` — the **single** validator, returning `INCOMPLETE_MAPPING_ENTRY`, `DUPLICATE_ASSESSOR`, `UNKNOWN_ASSESSOR`, or `None`. Both the ingestion path (T035) and the override path (T052) call it, and that shared call is what makes FR-UA-002's "whether ingested or manual" true by construction rather than by two checks that can drift

### The retirement — atomic group

- [X] T020 [P] Write the migration tests in `tests/integration/test_assignment_migration.py` per [quickstart.md](quickstart.md) Scenario 7, using T007's `legacy_cycle` fixture. **The tests must start from a stored legacy `data` blob, never from a constructed `SurveyCycle`** — a migration that reads through `get_cycle()` finds `None` for both emails once T024 lands and silently migrates nothing, and a test built the obvious way passes against that broken version ([data-model.md](data-model.md) §8). Assert: every unit gets both roles with `source = migration`; `human_assessor_submissions` is row-for-row identical before and after (SC-011); an unmatched email creates a roster record rather than leaving the unit unstaffed; a second startup migrates nothing further
- [X] T021 Implement `migrate_project_level_assignments(conn)` in `src/portal/assignment.py` per [data-model.md](data-model.md) §8. Reads `assessor_a_email`/`assessor_b_email` **from the raw `survey_cycles.data` JSON**, resolves each against the roster by email or creates a record, then writes one assignment per portal plus two `assignment_changes` rows. Idempotent by skipping any cycle that already has assignment rows. **Reads and writes no submission or completion row** — role attribution already lives on `HumanAssessorSubmission.role` and never leaves it (FR-UA-008, [data-model.md](data-model.md) §7)
- [X] T022 In `src/portal/webapp.py`: call `ingest_assessor_source` then `migrate_project_level_assignments` inside the existing lifespan, after `init_db` and beside `sweep_interrupted_jobs` ([webapp.py:50](../../src/portal/webapp.py#L50)), logging counts in the same style. **Ordering is load-bearing**: ingestion must precede migration, because migration resolves legacy emails against the roster
- [X] T023 [P] Rewrite `tests/unit/test_assessor_assignment.py`. All four of its current tests assert the retired project-level model (assign → `status == "locked"` → mutations blocked → unassign reopens). Replace them with the freeze tests of [quickstart.md](quickstart.md) Scenario 8: a fully staffed project with no submissions is still editable; after the first human submission every guarded route redirects with `?lock_error=1`; overriding an assessor still works after work has started; no `SurveyCycle` ever reaches `status == "locked"`. Written before T024–T026
- [X] T024 In `src/shared/state/entities.py`: remove `assessor_a_email` and `assessor_b_email` from `SurveyCycle`, and change the `status` comment to record that `"locked"` is retired. **No data rewrite is needed** — `_coerce` assigns only keys present in the type hints ([serialization.py:47-49](../../src/shared/persistence/serialization.py#L47)), so existing stored blobs deserialise cleanly and drop the two keys. Same file as T009/T010
- [X] T025 In `src/portal/admin.py`: delete the `assign_assessors` ([admin.py:692](../../src/portal/admin.py#L692)) and `unassign_assessors` ([admin.py:709](../../src/portal/admin.py#L709)) routes and the now-unused `assign_error` query parameter on `project_detail` ([admin.py:284](../../src/portal/admin.py#L284)) — it is reintroduced with new values in T051
- [X] T026 In `src/portal/admin.py`: rename `_blocked_if_locked` ([admin.py:56](../../src/portal/admin.py#L56)) to `_blocked_if_work_started` and change its condition from `cycle.status == "locked"` to `r.has_any_human_activity(session_id_for_cycle(cycle_id))` (T014). Keep the docstring's explanation of *why* units and questions freeze — it is the reason the guard survives at all ([research.md](research.md) R4) — and add that the trigger is now assessment having begun, not assessors having been named. Import `session_id_for_cycle` from `portal.common` alongside the existing `ensure_session` — it is a pure helper ([common.py:17](../../src/portal/common.py#L17)), so the guard creates no session as a side effect. Update all fifteen call sites (L337, 391, 417, 483, 520, 530, 540, 550, 558, 569, 591, 624, 641, 649, 663): the **first argument changes too**, from a `SurveyCycle | None` to the `Repository`, and the eleven sites currently passing `r.get_cycle(cycle_id)` (L337, 483, 520, 530, 540, 550, 558, 569, 591, 641, 649) drop that now-redundant fetch. Return type, redirect target, and `?lock_error=1` are unchanged. Same file as T025
- [X] T027 In `src/portal/templates/admin_project_detail.html`: delete the "Assign Assessors / Assessors Assigned" card at [:130-176](../../src/portal/templates/admin_project_detail.html#L130) in full — both branches, both email inputs, the Assign & Lock button, the Unassign & Reopen button, and the two `cycle.assessor_a_email`/`_b_email` references. The staffing card that replaces it is T038; deleting first keeps this phase's diff free of half-built UI
- [X] T028 Run `pytest -q` and `ruff check src tests`. Green here means the retirement is complete and self-consistent: nothing references the two removed fields, the two removed routes, or the old guard name. Compare against T001's baseline — the only difference should be the four rewritten tests in `test_assessor_assignment.py`line — the only difference should be the four rewritten tests in `test_assessor_assignment.py`

---

## Phase 3: US1 — A project's units arrive already staffed (Priority: P1) 🎯 MVP

> **Goal**: An administrator creates a project, adds units, names nobody — and every unit the source database covers arrives with its own Assessor A and Assessor B.
>
> **Independent test**: With the mapping pre-ingested, create a project with twelve mapped units and verify each holds its own distinct pair with no administrator input, and that the project reports its staffed/unstaffed counts.

### Tests

- [X] T029 [P] [US1] In `tests/unit/test_unit_assignment.py`: the staffing tests of [quickstart.md](quickstart.md) Scenario 1 — twelve mapped country units all staffed with zero assessor input (SC-001); **at least two distinct A-role assessors across the twelve**, because a single pair repeated everywhere would pass a naive assertion while reproducing exactly the behaviour this feature replaces; a thirteenth unit added afterwards staffed on creation, not on next page load (FR-IN-003); a LOSI project's city units staffed identically from `unit_type: "city"` entries (FR-UA-010); two projects containing the same country both starting from the same mapped pair (US1 §5)
- [X] T030 [P] [US1] In `tests/unit/test_unit_assignment.py`: the verbatim tests of [quickstart.md](quickstart.md) Scenario 2 — every assigned `assessor_id` equals what the mapping names, asserted **on the ids**, not on "some assessor was assigned" (SC-004); and re-ingesting a roster whose `languages`/`organisation`/`notes` have been rewritten to nonsense produces **identical** assignments (FR-DB-006). Different test functions from T029 but the same file, so not parallel with it — merge into one task if that ordering is inconvenient
- [X] T031 [P] [US1] In `tests/unit/test_unit_assignment.py`: the four refusal tests — for each of the T003 defect entries, assert the unit is **wholly** unstaffed with the right `ingest_defect`, and specifically that **neither** role is filled. The natural bug is to assign A and then fail on B; D8 forbids half-assignment, so "none, not one" is the assertion that matters
- [X] T032 [P] [US1] In `tests/unit/test_unit_assignment.py`: a unit the mapping does not cover produces **no assignment row at all** ([research.md](research.md) R9), and a mapping entry whose `(unit_type, unit_code)` matches no unit anywhere produces no error, no row, and no log line (FR-IN-009)
- [X] T033 [P] [US1] In `tests/unit/test_unit_assignment.py`: a national project's added unit takes `unit_type = "country"` and a LOSI project's takes `"city"`, **and posting a contradicting `unit_type` in the form has no effect** — the enforcement test for FR-UA-009 (T037)

### Implementation

- [X] T034 [US1] Implement `create_units(r, cycle_id, portals)` in `src/portal/assignment.py`: insert the portals, load the mapping index and roster index **once** per call, then apply per unit. Two index reads per call regardless of unit count — `create_project` tags 193 units in one go ([admin.py:236](../../src/portal/admin.py#L236)) and must not issue 386 lookups ([contracts/assessor-source-and-ingestion.md](contracts/assessor-source-and-ingestion.md) §3)
- [X] T035 [US1] Implement `apply_mapping_entry(r, cycle_id, portal, entry, roster)` in `src/portal/assignment.py`: call T019's `validate_pair`; on a reason, write a row carrying `ingest_defect` and **no role**; otherwise assign both roles with `source = MAPPING`, `set_by_actor_id = None`, and write two `assignment_changes` rows. Iteration is over **units**, never over entries, which is what makes FR-IN-009 free. This function reads exactly `entry.assessor_a_id` and `entry.assessor_b_id` — no other field of the entry or of any `Assessor` is in scope. Same file as T034
- [X] T036 [US1] Implement `staffing_summary(r, cycle_id) -> StaffingSummary` in `src/portal/assignment.py` — derived, never stored: one read of the project's assignment rows joined in memory against its portals, returning `total_units`, `staffed_units`, and `unstaffed` keyed by `portal_id`. A unit with no row reports `no_mapping_entry`. Same file as T035
- [X] T037 [US1] In `src/portal/admin.py`: route `create_project` ([admin.py:262](../../src/portal/admin.py#L262)), `add_units` ([admin.py:617](../../src/portal/admin.py#L617)), and `bulk_add_units` ([admin.py:656](../../src/portal/admin.py#L656)) through `create_units`, and **derive `unit_type` from `cycle.project_type`** in all three, dropping the `unit_type` form read at [admin.py:661](../../src/portal/admin.py#L661) — `"country"` for `NATIONAL_OSI`, `"city"` for `LOSI_CITY`, exactly as [cycles.py:127-132](../../src/api/routers/cycles.py#L127) already does. This is what enforces FR-UA-009: deriving makes a mixed project unrepresentable rather than merely rejected. Existing tests that post `unit_type` keep passing, because FastAPI ignores unexpected form fields
- [X] T038 [US1] In `src/portal/admin.py`: in `project_detail`, load the project's assignments and the roster **once** before `_build_unit_rows` and pass both in; inside the loop ([admin.py:81](../../src/portal/admin.py#L81)) add `"assignment"` and `"staffing"` keys from dict lookups only. That loop already walks submissions, comparison, discrepancy, reconciliation state, and readiness per unit — **no task may add a query to it**. Pass `staffing_summary(r, cycle_id)` to the template. Same file as T037
- [X] T039 [P] [US1] In `src/api/routers/cycles.py`: route unit creation at [cycles.py:127](../../src/api/routers/cycles.py#L127) through `create_units`, so the REST surface staffs units identically (FR-IN-003, parity gate)
- [X] T040 [P] [US1] In `src/portal/seed.py`: create portals through `create_units` rather than `insert_portals`, so a seeded demo project is staffed from the mapping like any other
- [X] T041 [US1] In `src/portal/templates/admin_project_detail.html`: add the staffing summary card in place of the one T027 deleted — *"N of M units staffed"* (FR-SV-002) — and two unit-table columns showing each role's assigned display name and email, or an unstaffed marker. Reason wording is T057's; this task shows *whether*, not *why*
- [X] T042 [US1] Run the Phase 3 tests plus `pytest -q`. **Checkpoint**: US1 is independently verifiable here — create a twelve-unit project, enter nothing, see twelve staffed units and an accurate count

---

## Phase 4: US2 — Different units are worked by different assessors (Priority: P1)

> **Goal**: An assessor reaches only the units they are assigned to, in the role the assignment gives them, with blindness intact.
>
> **Independent test**: Staff two units with disjoint pairs; verify each assessor reaches only their own unit, in the correct role, and that neither can read the other role's submissions.
>
> **This is the widest change in the feature.** It is also a precondition, not a refinement: today [`assessor_picker.html`](../../src/portal/templates/assessor_picker.html) links to `?role=A` and `?role=B` with **no `actor_id`**, so both roles fall through to the `"assessor-1"` default at [assessor.py:60](../../src/portal/assessor.py#L60) and every portal-navigated submission is attributed to the same actor. There is no identity for an assignment check to be about until that is fixed.

### Tests

- [X] T043 [P] [US2] In `tests/unit/test_assessor_access.py`: the assigned-access tests of [quickstart.md](quickstart.md) Scenario 6 — the A-role assignee opens the unit and is placed in role A **without supplying a role**; the B-role assignee passing `role=A` is still placed in B (FR-AC-002); the same person, A on one unit and B on another, opens each in the right role (FR-UA-004, US2 §4)
- [X] T044 [P] [US2] In `tests/unit/test_assessor_access.py`: the refusal tests — an unassigned person gets `403` **and the response body contains no question text, no submission, and no evidence URL** (assert on the body, not just the status — FR-AC-003, SC-007); Kenya's A-role assessor is refused on Brazil in the same project (US2 §2); a half-staffed unit refuses everyone including the holder of its one filled role (FR-UA-005, US2 §5); an unstaffed unit refuses everyone **including an assessor assigned to a different unit of the same project**, proving no project-wide fallback survives (FR-UA-007, SC-012); completion declaration is refused to anyone but the assigned holder of the declared role (FR-AC-005)
- [X] T045 [P] [US2] In `tests/contract/test_assessor_input.py` or a sibling module: the API parity tests — a body `role` contradicting the assignment returns `409` naming the assigned role; an unassigned `actor_id` returns `403`; the stored role on a submission and a completion is always the resolved one, never the requested one ([contracts/assignment-gated-access.md](contracts/assignment-gated-access.md) §5)

### Implementation

- [X] T046 [US2] Implement `resolve_actor_role(r, cycle_id, portal_id, actor_id) -> AssessorRole | None` in `src/portal/assignment.py`, returning the role the actor holds per the current assignment, or `None`. A unit with only one role filled returns `None` for everyone, including that role's holder (FR-UA-005). There is **no** project-wide fallback branch (FR-UA-007) — its absence is the requirement
- [X] T047 [US2] In `src/portal/assessor.py`: remove `role` from `unit_form` ([assessor.py:54-61](../../src/portal/assessor.py#L54)), `submit` ([:120-127](../../src/portal/assessor.py#L120)), `complete` ([:202-207](../../src/portal/assessor.py#L202)), `reconcile` ([:260-266](../../src/portal/assessor.py#L260)), and the joint-answer route ([:341](../../src/portal/assessor.py#L341)); make `actor_id` required with no default; resolve the role through T046 and return `403` with a plain sentence on `None`. Drop `role=` from the reconciliation redirect's query string at [:78-82](../../src/portal/assessor.py#L78). **Do not touch any `latest_human_submission(..., role=...)` call** — blindness is a query shape and this feature changes who holds a role, never what a role can see (FR-AC-004)
- [X] T048 [US2] In `src/portal/templates/assessor_picker.html`: replace the per-unit "Open as A" / "Open as B" buttons with an identity selection followed by a list of only the units that identity is assigned to, each labelled with the role held there. Add a visible note that selecting an identity is **not** authentication (A3) — the page must not imply a login it does not have
- [X] T049 [P] [US2] In `src/portal/templates/assessor_unit.html`: remove `role` from every form and hidden input; the role is displayed as resolved context, not submitted as a value
- [X] T050 [P] [US2] In `src/api/routers/human.py` and `src/api/routers/completions.py`: derive the role through T046 for the submission POST ([human.py:60-84](../../src/api/routers/human.py#L60)), the answers GET ([human.py:118-179](../../src/api/routers/human.py#L118)), and the completion POST ([completions.py:61-103](../../src/api/routers/completions.py#L61)). `role` **stays in the request schema** and is validated: a contradiction returns `409` naming the assigned role, an unassigned actor returns `403`. Validate rather than drop, so an existing client's wrong assumption surfaces as an error instead of being silently corrected, and no wire shape breaks
- [X] T051 [US2] Run the Phase 4 tests, then `pytest tests/independence -q`. **`tests/independence/` must pass unedited** — it is the regression signal for FR-AC-004. If a test there needs changing, stop: the blind-read boundary moved and it should not have. **Checkpoint**: US2 is independently verifiable here

---

## Phase 5: US3 — An administrator changes an assigned assessor (Priority: P1)

> **Goal**: Either role on any unit can be reassigned from the portal, affecting only that unit, with submitted work preserved and every change recorded.
>
> **Independent test**: Change one unit's assessor and verify only that unit changed. Then submit answers, reassign that role, and verify the answers survive and the incoming assessor sees them.

### Tests

- [X] T052 [P] [US3] In `tests/unit/test_assessor_assignment.py`: the override tests of [quickstart.md](quickstart.md) Scenario 4 — overriding one unit leaves siblings unchanged (SC-005); two projects both containing the same country, overriding one leaves the other untouched (FR-UA-011, US3 §2); an override naming the unit's other assessor is refused with `assign_error=duplicate` and the row is unchanged (FR-MO-004); an unknown `assessor_id` is refused with `assign_error=unknown`; clearing returns the unit to unstaffed with `cleared_by_administrator` (FR-MO-005); **re-running mapping application after an override leaves the override in place** (FR-IN-010, SC-006)
- [X] T053 [P] [US3] In `tests/unit/test_assessor_assignment.py`: the preservation tests of [quickstart.md](quickstart.md) Scenario 5 — submit as the A-role assessor, reassign role A, then assert every submission is still retrievable, unaltered, and still attributed to whoever made it (FR-MO-006); the incoming assessor sees them as the role's prior work (FR-MO-007, SC-008); completion status and discrepancy state are byte-identical before and after (FR-MO-009, US3 §8); the outgoing assessor now gets `403` (US3 §7); `assignment_changes` holds one row per role write with outgoing id, incoming id, actor, and time (FR-MO-008, SC-009). Same file as T052, so not parallel with it if both are worked at once

### Implementation

- [X] T054 [US3] Implement `set_role_assignment(r, cycle_id, portal_id, role, assessor_id, actor_id)` and `clear_role_assignment(...)` in `src/portal/assignment.py`: read-modify-write of the single assignment row inside `begin_immediate()` ([data-model.md](data-model.md) §3 Concurrency), calling T019's `validate_pair` — the **same** validator the ingestion path uses — and writing one `assignment_changes` row with `source = ADMINISTRATOR`. Clearing sets the role to `None` and `ingest_defect = CLEARED_BY_ADMINISTRATOR`
- [X] T055 [US3] In `src/portal/admin.py`: add `POST /admin/projects/{cycle_id}/units/{portal_id}/assessors` taking `role`, `assessor_id` (empty clears), and `actor_id`; `303` to the project on success, `303` with `assign_error=duplicate` or `assign_error=unknown` on refusal, `404` on an unknown project or unit. **This route is deliberately not behind `_blocked_if_work_started`** — mid-cycle replacement is US3's explicit motivation, and reassignment writes no submission so it cannot skew the indicator set the freeze protects (FR-MO-009). Reinstate the `assign_error` query parameter on `project_detail` with the new values
- [X] T056 [US3] In `src/portal/templates/admin_project_detail.html`: add the per-role override control to each unit row — a `<select>` of roster assessors showing **name, email, and organisation** (FR-MO-003), with an empty option to clear, posting to T055. Same file as T041
- [X] T057 [US3] Run the Phase 5 tests plus `pytest -q`. **Checkpoint**: US3 is independently verifiable here — override a unit in under thirty seconds entirely within the portal, and confirm only that unit moved (SC-005)

---

## Phase 6: US4 — Gaps in the source data are visible, not silent (Priority: P2)

> **Goal**: A unit the source database cannot staff says so, with a reason, rather than looking ready with nobody responsible.
>
> **Independent test**: Ingest a mapping with deliberate gaps and conflicts, add the units, and verify partial staffing with per-unit reasons and no half-assigned or duplicated pairing.
>
> **Deliberately thin, and honestly so.** The four refusals themselves are built in Phase 3 (T031, T035), because US1 is *wrong* without them — a defect entry must not staff a unit. What is left here is the surfacing and the assertions that nothing is silently half-staffed.

### Tests

- [X] T058 [P] [US4] In `tests/unit/test_unit_assignment.py`: the reporting tests of [quickstart.md](quickstart.md) Scenario 3 — one assertion per `UnstaffedReason` that the project view names the reason in plain words (FR-SV-001); `staffing_summary`'s counts match the rendered rows (FR-SV-002); zero units are unstaffed without a recorded reason (SC-003)
- [X] T059 [P] [US4] In `tests/unit/test_unit_assignment.py`: assign the unstaffed units by hand and confirm the units already staffed are byte-identical afterwards (US4 §5); and that a change is visible on the redirect that immediately follows it (FR-SV-003)

### Implementation

- [X] T060 [US4] In `src/portal/templates/admin_project_detail.html`: render each unstaffed unit's reason as a sentence, never an enum value — *"No entry in the assessor database for this unit."* / *"The assessor database names the same person for both roles."* / *"The assessor database names an assessor who is not on record."* / *"Only one role is named in the assessor database."* / *"Cleared by an administrator."* ([contracts/unit-assignment-and-override.md](contracts/unit-assignment-and-override.md) §4). Same file as T041 and T056
- [X] T061 [US4] Run the Phase 6 tests plus `pytest -q`. **Checkpoint**: US4 is independently verifiable here — a project whose mapping has gaps shows exactly which units are unstaffed and why

---

## Phase 7: Polish and cross-cutting concerns

- [X] T062 [P] Create `src/portal/templates/admin_assessors.html` and add `GET /admin/assessors` to `src/portal/admin.py`: a **read-only** list of every ingested assessor with display name, email, organisation, languages, and notes (FR-DB-007). **No create, edit, deactivate, or delete control** — assessor lifecycle management is out of scope by the spec's own Out of Scope section and belongs with the real assessor database. A future task that adds an edit button here is a scope violation, not an improvement
- [X] T063 [P] In `src/portal/seed_lifecycle_demo.py`: staff its units from the seeded mapping through `create_units`, then submit as the **assigned assessors' real ids** rather than the free-form `"demo-assessor-a"` / `"demo-assessor-b"` strings at [:124](../../src/portal/seed_lifecycle_demo.py#L124), [:137](../../src/portal/seed_lifecycle_demo.py#L137), and [:150](../../src/portal/seed_lifecycle_demo.py#L150), which are unrelated to the emails at [:62-63](../../src/portal/seed_lifecycle_demo.py#L62). Assessor identity on a submission is the stable identifier on the ingested record (A1)
- [X] T064 [P] Write the source-swap test of [quickstart.md](quickstart.md) Scenario 2: point the loader at a different `assessors.json` and mapping with the same unit coverage, and assert **the same units are staffed and the same units unstaffed for the same reasons — only the people differ** (SC-013). This is the test that proves the replacement seam is real rather than asserted
- [X] T065 Sweep every route that renders or returns unit content and confirm none discloses a peer role's submission to an actor who does not hold that role — the portal's five assessor routes, the two API human routes, and the admin unit rows. Blindness is unchanged by design (FR-AC-004); this is a confirmation pass, not a change, and any edit it prompts belongs in a bug fix, not here
- [X] T066 Grep the tree for `assessor_a_email`, `assessor_b_email`, `_blocked_if_locked`, `assign-assessors`, `"locked"`, and `actor_id: str = "assessor-1"`. Every hit outside `specs/` must be gone. Confirm `data/reference/assessors.json` and `unit_assessor_mapping.json` are opened by nothing except `src/shared/reference/assessors.py` — the replacement seam is only a seam if it is the sole reader
- [X] T067 Run the full gate: `pytest -q`, `ruff check src tests`, then `graphify update .` to keep `graphify-out/` current per `CLAUDE.md`. Compare the passing count against T001's baseline and account for every difference
- [X] T068 Walk [quickstart.md](quickstart.md)'s six manual steps against a running server, confirming in particular that no "Assign Assessors" card or "Assign & Lock" button remains anywhere in the admin surface, and that the assessor picker states plainly that identity selection is not authentication

---

## Dependencies

```
Phase 1 (Setup, T001–T007)
    ↓
Phase 2 (Foundational, T008–T028)  ── BLOCKING: nothing below starts until T028 is green
    ↓
Phase 3 (US1, T029–T042)  🎯 MVP
    ↓
    ├── Phase 4 (US2, T043–T051) ──┐
    │                               ├── Phase 6 (US4, T058–T061)
    └── Phase 5 (US3, T052–T057) ──┘
                                    ↓
                            Phase 7 (Polish, T062–T068)
```

**Story-level dependencies**

| Story | Depends on | Why |
|---|---|---|
| US1 | Phase 2 | Needs the tables, the roster, the mapping, and the validator |
| US2 | Phase 2, **US1** | `resolve_actor_role` has nothing to resolve until units carry assignments |
| US3 | Phase 2, **US1** | Override edits an assignment that US1 creates |
| US4 | Phase 2, **US1** | The refusals are built in US1; this story surfaces them |

US2 and US3 are independent of each other and can run in parallel once US1 lands. US4 depends on both only for its integration assertions; its reason rendering (T060) needs US1 alone.

**Within-phase ordering that is not negotiable**

- T017 → T018 → T019 (loader before ingest before validator's roster lookups)
- T023 before T024–T027 (tests written against the intended behaviour first)
- T024–T028 as one atomic group (see the Phase 2 note)
- T034 → T035 → T036 (all in `assignment.py`; not parallel)
- T046 before T047, T049, T050 (every caller needs the resolver)
- T019 before T035 and T054 (one validator, two callers)

---

## Parallel execution examples

**Phase 1** — T002 through T007 are six different files and run together:

```
T002 data/reference/assessors.json
T003 data/reference/unit_assessor_mapping.json
T004 src/shared/reference/assessors.py
T005 src/portal/assignment.py
T006 four test scaffolds
T007 tests/unit/conftest.py
```

**Phase 2** — T011 and T016 are parallel (repository vs. test module); T012–T015 all edit `repositories.py` and are strictly sequential. T020 and T023 are parallel with each other and with the T011–T015 chain.

**Phase 3** — T029 through T033 are all in `tests/unit/test_unit_assignment.py` and are marked `[P]` only in the sense that they are independent *test functions*; if one person writes them, treat them as one task. T039 and T040 are genuinely parallel with each other and with T037–T038 (different files).

**Phase 4** — T043, T044, T045 are parallel (three test modules). T049 and T050 are parallel with each other; both wait on T046.

**Phase 7** — T062, T063, T064 are parallel. T065 through T068 are sequential verification.

---

## Independent test criteria

| Story | Priority | Independently verifiable when |
|---|---|---|
| **US1** | P1 | A twelve-unit project created with zero assessor input comes back fully staffed, with at least two distinct A-role assessors across it, and an accurate staffed/unstaffed count |
| **US2** | P1 | Two units with disjoint pairs: each assessor reaches only their own, in the assignment's role regardless of what the request says, and `tests/independence/` still passes unedited |
| **US3** | P1 | One unit's assessor changed from the portal, only that unit moved, prior submissions intact and visible to the incoming assessor, and the change on the record |
| **US4** | P2 | A mapping with four deliberate defects yields four unstaffed units, each naming its reason, and none half-assigned |

---

## Format validation

All 68 tasks carry a checkbox, a sequential ID, a file path, `[P]` only where the file is not shared with another incomplete task, and a `[USn]` label on every task in Phases 3–6 and on no task in Phases 1, 2, or 7.

| Phase | Tasks | Count |
|---|---|---|
| 1 — Setup | T001–T007 | 7 |
| 2 — Foundational | T008–T028 | 21 |
| 3 — US1 (MVP) | T029–T042 | 14 |
| 4 — US2 | T043–T051 | 9 |
| 5 — US3 | T052–T057 | 6 |
| 6 — US4 | T058–T061 | 4 |
| 7 — Polish | T062–T068 | 7 |
| **Total** | | **68** |
