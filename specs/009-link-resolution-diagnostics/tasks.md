# Tasks: Link Resolution Diagnostics

**Feature Directory**: `specs/009-link-resolution-diagnostics`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-21

**No `plan.md` exists** — `/speckit-plan` was skipped. These tasks were derived from `spec.md`
plus direct inspection of the codebase, so the file paths below are real and current rather
than proposed. Where an existing file is named, it was read; where a new file is named, its
directory exists. Run `/speckit-plan` first if you want a design document to precede this.

## Codebase facts these tasks depend on

Established by inspection before writing this list. Each one removes work someone would
otherwise plan for:

1. **Per-question resolution evidence is already persisted.** `src/orchestration/scheduler.py:418`
   writes the full `ResolutionAttempt` history into the unit row; `:437` records
   `link_escalated_off_portal`; `:750` records `evidence_locus_violation`. All of it is
   readable through `repo.list_units(session_id)`. **Stage attribution needs no new
   instrumentation** — only a reader and a classifier. This is the single largest saving in
   the feature.
2. **`ground_truth_answers` stores a JSON `data` blob**, not typed columns
   (`src/shared/persistence/benchmark_repo.py:40-62`). Adding reference-link fields to
   `GroundTruthAnswer` therefore needs **no database migration**.
3. **`src/benchmark/` already contains** `store.py`, `runner.py`, `measures.py`, `compare.py`,
   `verify.py`. Per D2 this feature extends that package; it does not create a sibling.
4. **`run_benchmark_session`** (`src/benchmark/runner.py:37`) already drives the real
   `run_batch` under `SessionMode.BENCHMARK` with `cycle_id=None`, so FR-LD-009 and FR-LD-013
   are largely satisfied by reusing it.
5. **The truncation behind FR-LD-027 is `src/shared/prompts/profiles.py:275`** —
   `page_text[:15000]`, which discards silently. Reporting truncation requires making it
   record that it happened.
6. **The link-retry gate is `src/orchestration/scheduler.py:584`**, requiring `all(...)` agents
   to report `portal_unreachable` or `link_likely_wrong`.

---

## Phase 1: Setup

- [X] T001 Create the reference fixture `data/benchmark/reference_links_us.json` with a documented schema — per entry: `question_id`, `country_id`, `expected_answer`, `reference_url`, `no_valid_link`, `accepted_alternatives`, `confidence` (`authoritative` | `provisional`), `verified_on`, `origin`, `note`. Seed all thirteen indicators from FR-LD-006 (#030, #043, #045, #054, #055, #092, #095, #108, #336, #337, #339, #340, #341) with the links established during live validation.
- [X] T002 [P] Mark #054 and #339 `provisional` in `data/benchmark/reference_links_us.json` per FR-LD-007, with #054 additionally carrying `no_valid_link: true` and the stated reason that US driver's licences are issued subnationally, and #339's note recording that its known target is a thin generic page rather than the right-to-information page the indicator asks for.
- [X] T003 [P] Create `tests/fixtures/reference/minimal.json` — three entries covering an authoritative reference, a provisional one, and a `no_valid_link` one — so unit tests never read the real seeded fixture.

---

## Phase 2: Foundational (blocking prerequisites)

**These block every user story. Nothing in Phase 3+ can start until Phase 2 completes.**

- [X] T004 Extend `GroundTruthAnswer` in `src/shared/state/entities.py` with `reference_url: str | None`, `no_valid_link: bool`, `accepted_alternatives: list[str]`, `confidence: str`, `verified_on: str | None`, `origin: str | None`, and `note: str | None`, all defaulted so existing rows and callers keep working (FR-LD-002, FR-LD-003, FR-LD-004, FR-LD-005, FR-LD-034). No schema migration — `benchmark_repo` persists this dataclass as a JSON blob.
- [X] T005 Extend `BenchmarkStore.load_from_json` in `src/benchmark/store.py` to read the new fields from each fixture entry and to accept a top-level `entries` key alongside the existing `pairs` key, so the reference fixture and the legacy `data/benchmark/module_2_1.json` both load (FR-LD-001, FR-LD-035).
- [X] T006 [P] Create `src/benchmark/urlmatch.py` with `urls_equivalent(a, b) -> bool`, normalising scheme, `www` prefix, trailing slash, default ports, fragment, and tracking parameters (`utm_*`, `gclid`, `fbclid`) — the FR-LD-016 equivalence rule, as one pure function every comparison uses.
- [X] T007 [P] Create `src/benchmark/trace.py` with a frozen `UnitResolutionTrace` dataclass and `read_unit_traces(repo, session_id) -> dict[tuple[str, str], UnitResolutionTrace]`, reading `repo.list_units(session_id)` and lifting `resolution_history`, `resolved_url`, `supplying_source`, `link_escalated_off_portal`, `evidence_locus_violation`, `prefill_reason`, and the terminal state out of each unit's data blob. This is the raw material for all stage attribution, and it adds no instrumentation because the scheduler already writes every one of these fields.
- [X] T008 [P] Add unit tests in `tests/unit/test_urlmatch.py` covering the FR-LD-016 equivalence pairs and, as negative cases, two URLs differing in path or host that must NOT be equivalent.
- [X] T009 [P] Add unit tests in `tests/unit/test_reference_fixture.py` asserting `data/benchmark/reference_links_us.json` parses, contains exactly the thirteen FR-LD-006 indicators, and marks #054 and #339 provisional per FR-LD-007.
- [X] T010 Backfill indicators #108 and #092 into the `usa-test-2026` cycle in `data/aiq.db`, since the cycle currently holds 11 of the 13 seeded indicators and the full set cannot otherwise be measured (spec Dependencies).
- [X] T011 Extend `verify_benchmark_isolation` in `src/benchmark/verify.py` to assert that no reference URL from the loaded set appears in any prompt, agent input, or unit row of the session under test, enforcing FR-LD-008 for links as it already does for answers.

---

## Phase 3: User Story 1 — An engineer learns which stage lost a link (P1)

**Goal**: For every divergence, name one responsible stage and quote that stage's own recorded reason.

**Independent test**: Take an indicator whose reference link is known and whose pipeline result is known to be wrong; run the diagnostic and confirm the report names one stage and quotes its recorded reason, rather than reporting only that the answer was wrong.

- [X] T012 [P] [US1] Write failing unit tests in `tests/unit/test_stage_attribution.py` for each US1 acceptance scenario, building `UnitResolutionTrace` values by hand: an exact match names the supplying source; every source exhausted lists each with its reason; a locus refusal names the gate and the refused URL; never-widened is distinguished from widened-and-found-nothing; a correct link with a negative answer attributes to assessment.
- [X] T013 [US1] Create `src/benchmark/attribution.py` with a `PipelineStage` string enum forming the closed set FR-LD-022 requires: one member per `LinkSource` (`prior_survey_kb`, `msq`, `sitemap`, `search`, `portal_default`), plus `locus_gate`, `off_portal_escalation`, `page_retrieval`, `assessment`, and `environment`.
- [X] T014 [US1] Implement `attribute(trace, reference) -> StageAttribution` in `src/benchmark/attribution.py`, walking the ordered `resolution_history` to find the first source that should have produced the reference and did not, then falling through to the locus gate, escalation, retrieval, and assessment in that order (FR-LD-022, FR-LD-023, FR-LD-025, FR-LD-026).
- [X] T015 [US1] Implement the escalation distinction in `src/benchmark/attribution.py`: report `never_widened` when `link_escalated_off_portal` is false and a portal candidate was accepted, versus `widened_and_failed` when it is true and resolution still failed (FR-LD-024).
- [X] T016 [US1] Make truncation observable — change `src/shared/prompts/profiles.py:275` to record that `page_text` exceeded 15000 characters and by how much, and carry that flag onto the agent run so `attribution.py` can report it (FR-LD-027). Without this the flag cannot be reported at all; every other attribution input already exists.
- [X] T017 [US1] Implement environmental-failure classification in `src/benchmark/attribution.py`, mapping unreachable hosts, timeouts, and exhausted API quota to `PipelineStage.ENVIRONMENT` and excluding them from resolution-failure totals (FR-LD-028).
- [X] T018 [US1] Create `src/benchmark/diagnostics.py` with `run_diagnostic(...)`, which calls the existing `run_benchmark_session` from `src/benchmark/runner.py`, then joins `read_unit_traces` output against the loaded reference set to produce one `IndicatorVerdict` per indicator (FR-LD-009, FR-LD-013 — both inherited from benchmark mode's `cycle_id=None` session).
- [X] T019 [US1] Implement the three-way link verdict in `src/benchmark/diagnostics.py`: `match` via `urls_equivalent` against the reference or any accepted alternative, `miss` otherwise, with the `divergent_plausible` branch stubbed to `miss` until T031 (FR-LD-036).
- [X] T020 [US1] Create `src/benchmark/report.py` rendering the per-indicator report — reference, resolved link, verdict, attributed stage, stage reason (FR-LD-029) — plus totals separating resolution failures from assessment failures (FR-LD-030).
- [X] T021 [US1] Add a `diagnose` click group with a `run` command to `src/cli.py`, following the existing `verify` group at `src/cli.py:165`, taking `--cycle`, `--questions`, and `--reference-set`, and writing the report to stdout.
- [X] T022 [US1] Record the configuration each diagnostic run used in `src/benchmark/diagnostics.py` by reusing the `ConfigurationSnapshot` that `run_benchmark_session` already writes, and surface its id in the report header (FR-LD-014).
- [X] T023 [US1] Mark an interrupted run incomplete in `src/benchmark/diagnostics.py`, reusing `SessionStatus.INTERRUPTED`, and have `report.py` refuse to present its totals as though they covered the full set (FR-LD-015).
- [X] T024 [US1] Add an integration test in `tests/integration/test_diagnostics.py` driving `run_diagnostic` against a stubbed provider and an `httpx.MockTransport` client over three indicators — one clean match, one lost in search, one resolved-but-answered-No — asserting each is attributed to a different stage.

**Checkpoint**: US1 is independently shippable. It answers the question the feature exists for.

---

## Phase 4: User Story 2 — References are curated, reviewable, and honest about their limits (P1)

**Goal**: The measuring instrument is trustworthy, and says so when it is not.

**Independent test**: Add a reference for an indicator with no valid national link and one marked provisional; confirm both round-trip through a run and are reported distinctly from an ordinary confident reference.

- [X] T025 [P] [US2] Write failing unit tests in `tests/unit/test_reference_verdicts.py` for the US2 acceptance scenarios: a `no_valid_link` reference scores the portal's own page as a pass; a provisional reference is reported separately; a stale reference is charged to the reference, not the pipeline.
- [X] T026 [US2] Implement the `no_valid_link` verdict path in `src/benchmark/diagnostics.py`, scoring the pipeline's documented correct behaviour for that case as a pass (FR-LD-019). The spec deliberately does not name that behaviour — read it from the pipeline spec rather than inventing it.
- [X] T027 [US2] Implement reference staleness checking in `src/benchmark/diagnostics.py`: issue a HEAD request (falling back to GET) against each reference URL before comparing, and mark a reference whose URL no longer serves a page as `stale`, excluding it from pipeline-failure totals (FR-LD-020, SC-008).
- [X] T028 [US2] Implement loud failure on a missing indicator in `src/benchmark/diagnostics.py` — when the requested set names an indicator absent from either the cycle or the reference set, raise naming each missing id rather than proceeding over a smaller set (FR-LD-011, D3, SC-006). This is the defect that hid #108 and #092.
- [X] T029 [US2] Separate provisional from authoritative totals in `src/benchmark/report.py`, so the headline figure is never inflated by references not yet trusted (FR-LD-031).
- [X] T030 [US2] Report reference provenance in `src/benchmark/report.py` — verification date and origin per indicator (FR-LD-002) — so a reviewer can judge a reference without opening the fixture.
- [X] T031 [US2] Implement the `divergent_plausible` branch in `src/benchmark/diagnostics.py`, replacing the T019 stub: a resolved URL that is not the reference but passes admissibility and jurisdiction checks for the indicator's `evidence_locus` is classified `divergent_plausible`, excluded from the headline pass rate, and listed individually for review (FR-LD-036, FR-LD-037).
- [X] T032 [US2] Add an integration test in `tests/integration/test_diagnostics.py` asserting that a run naming an indicator absent from the cycle fails and names it, and that a run over a `no_valid_link` indicator passes when the pipeline returns the portal page.

**Checkpoint**: verdicts can now be trusted and audited. US1 + US2 is the recommended first release.

---

## Phase 5: User Story 3 — Resolution measured without paying for assessment (P2)

**Goal**: A fast, free loop for iterating on ranking and admissibility.

**Independent test**: Run the same question set resolution-only and end to end; confirm the link verdicts agree and that the resolution-only run performed no assessment.

- [X] T033 [P] [US3] Write a failing unit test in `tests/unit/test_resolve_only.py` asserting that a resolution-only batch dispatches no assessor agent and that every unit reaches `UnitState.RESOLVED`.
- [X] T034 [US3] Add a `resolve_only: bool = False` parameter to `run_batch` in `src/orchestration/scheduler.py` which returns each unit at `UnitState.RESOLVED` immediately after the resolution block at `:437`, before any agent is dispatched.
- [X] T035 [US3] Thread `resolve_only` through `run_benchmark_session` in `src/benchmark/runner.py`, skipping the `compute_benchmark_measures` call — which reads adjudication results that will not exist — when it is set.
- [X] T036 [US3] Mark answer-level comparisons `not_evaluated` rather than failed in `src/benchmark/diagnostics.py` and `src/benchmark/report.py` when the run was resolution-only (FR-LD-021, US3 scenario 2).
- [X] T037 [US3] Add a `--resolve-only` flag to the `diagnose run` command in `src/cli.py`.
- [X] T038 [US3] Add an integration test in `tests/integration/test_diagnostics.py` running the same three indicators both ways and asserting the link verdicts are identical and that the resolution-only run created no `AssessorAgentRun` rows.
- [X] T039 [US3] Record and report elapsed wall-clock time for a resolution-only run in `src/benchmark/report.py`, so SC-004's five-minute bound over the seeded thirteen is observed rather than assumed.

**Checkpoint**: the edit-measure-edit loop that this feature is meant to put in place of ad-hoc scripts now exists.

---

## Phase 6: User Story 4 — A regression is caught before it ships (P3)

**Goal**: Two runs can be compared by indicator, not by total.

**Independent test**: Record a run, degrade a resolution input so a known-good indicator fails, run again, and confirm the comparison names that indicator as newly regressed rather than merely reporting a lower total.

- [X] T040 [P] [US4] Write a failing unit test in `tests/unit/test_diagnostic_comparison.py` for the case the spec calls out specifically: two runs with identical totals but different indicators failing must still surface the change.
- [X] T041 [US4] Persist per-indicator diagnostic verdicts in `src/benchmark/diagnostics.py` via `BenchmarkRepository`, keyed by session id, so a later run can be compared against an earlier one (FR-LD-032).
- [X] T042 [US4] Implement `compare_diagnostic_runs(...)` in `src/benchmark/compare.py`, alongside the existing `compare_benchmark_runs`, listing indicators whose verdict changed in both directions with their before and after stage attribution (FR-LD-033).
- [X] T043 [US4] Add a `diagnose compare` command to `src/cli.py` taking two session ids.
- [X] T044 [US4] Add a `--fail-on-regression` flag to `diagnose compare` in `src/cli.py` exiting non-zero when any indicator regressed. The default remains exit zero regardless of results, because a run depends on live government sites and a paid search API, and a third-party outage must not be indistinguishable from a code defect (FR-LD-038).

---

## Phase 7: Polish & Cross-Cutting

- [X] T045 [P] Add a section to the project README or a note under `docs/` describing how to add a reference link and what `authoritative` versus `provisional` commits the author to, since the fixture is the measuring instrument and its quality is a human process rather than a code path.
- [X] T046 [P] Verify test coverage over the new modules meets the project's 80% floor via `pytest --cov=src/benchmark --cov-report=term-missing`.
- [X] T047 Run the full suite (`pytest`) and confirm no regression against the 305 tests currently passing.
- [X] T048 Run `graphify update .` to refresh the knowledge graph after the new modules land.
- [X] T049 Execute the seeded thirteen end to end and record the resulting stage-attribution breakdown in `specs/009-link-resolution-diagnostics/` as the baseline for future comparison — the first real answer to whether the production pipeline now produces the correct links.


---

## Dependencies

```
Phase 1 (Setup: T001-T003)
    └─> Phase 2 (Foundational: T004-T011)   [BLOCKS EVERYTHING]
            ├─> Phase 3 (US1: T012-T024)     P1  — MVP
            │       └─> Phase 4 (US2: T025-T032)  P1  (T031 replaces the T019 stub)
            ├─> Phase 5 (US3: T033-T039)     P2  (independent of US2)
            └─> Phase 6 (US4: T040-T044)     P3  (needs US1 verdicts to persist)
                    └─> Phase 7 (Polish: T045-T049)
```

**Cross-story couplings, stated explicitly because these are the ones that bite:**

- T031 (US2) replaces the stub left by T019 (US1). US1 ships with `divergent_plausible`
  collapsed into `miss`, which understates the pass rate — acceptable for a first cut, and the
  honest direction to err in, but it must not be published as a final figure.
- T041 (US4) depends on T019's verdict shape being stable. Do not start Phase 6 before Phase 4
  settles the third verdict, or the persisted history will need rewriting.
- T016 (US1) touches `src/shared/prompts/profiles.py`, which is production prompt code rather
  than diagnostics. It is the only task here that changes what the assessor sees, and it
  changes only the *recording* of truncation, not the truncation itself. Removing the
  truncation is out of scope.

## Parallel opportunities

- **Phase 1**: T002 and T003 run together once T001 fixes the schema.
- **Phase 2**: T006, T007, T008, T009 are four independent files — the widest parallel window in
  the feature. T004 must land before T005; T010 and T011 are independent of both.
- **Phase 3**: T012 (tests) runs alongside T013. After T014, the report (T020) and CLI (T021)
  proceed in parallel with T016's prompt change.
- **Phase 4**: T025 runs alongside T026-T028. T029 and T030 both edit `report.py`, so they are
  not parallel with each other.
- **Across stories**: once Phase 2 lands, US3 (Phase 5) is independent of US2 and can run
  concurrently with Phase 4 by a second person.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** That delivers the point of the feature: a wrong
answer names the stage that caused it. It reports a pessimistic pass rate until T031, and its
reference set is not yet audited, but it replaces a day of manual bisection immediately.

**Recommended first release = MVP + Phase 4 (US2).** Both stories are P1, and shipping US1
alone means publishing verdicts from an instrument whose own accuracy is unmeasured — the
failure mode US2 exists to prevent.

Phases 5 and 6 improve the loop rather than the answer, and can follow at whatever pace the
iteration actually demands.
