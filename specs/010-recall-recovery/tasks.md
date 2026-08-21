# Tasks: Recall Recovery & Resolver Simplification

**Feature Directory**: `specs/010-recall-recovery`
**Created**: 2026-08-21
**Source**: `USA_25Q_GAP_ANALYSIS.md` + full pipeline trace performed 2026-08-21

**No `spec.md` or `plan.md` exists** — `/speckit-specify` and `/speckit-plan` were skipped
deliberately. The problem statement is `USA_25Q_GAP_ANALYSIS.md` and the design is the
gate-by-gate trace recorded below. Every file path and line number here was read before
being written down; where a new file is named, its directory exists. Run `/speckit-specify`
first if you want a reviewable spec to precede this.

## The problem in one sentence

A question must survive **13 independent AND-ed gates** to produce an answer. Each gate was
added to fix one real defect from a previous run and each is individually defensible; stacked,
they reject 72% of questions. 7 of 25 delivered a positive answer in the last run.

## Codebase facts these tasks depend on

Established by inspection. Each removes work someone would otherwise plan for.

1. **`validation_quality_threshold = 0.70` is a latent bug, not a tuning value.**
   `src/shared/config/settings.py:48` sets 0.70; `src/agents/validator/agent.py:172-181`
   computes `quality_score` over exactly **three** booleans. 2/3 = 0.667 < 0.70, so "70%"
   silently means **100% — all three checks must pass**. This is the single largest source of
   `no_suggestion` and it is a one-line fix.
2. **The assessor prompt and the validator prompt contradict each other.**
   `src/shared/prompts/profiles.py:56-64` instructs the assessor to keep `evidence_quote`
   "under ~15 words" from "a SINGLE contiguous run of text"; the validator then judges
   `confidence_proportionate` (`src/agents/validator/agent.py:39-68`) and rejects thin quotes.
   Indicator #124 was lost exactly this way: three correct runs, all discarded.
3. **Screenshots are already dead but still cost.** `src/shared/tools/capture.py:14`
   is a stub returning `None`. `capture_ref` is still threaded through **24 source files**,
   the validator still gates on it (`src/agents/validator/agent.py:90`), and
   `src/orchestration/routers/retry_loops.py:180` papers over the stub with
   `pending.capture_ref or ""` so the gate never fires. Pure dead weight.
4. **The measurement harness already exists.** Feature 009 shipped `diagnose run` /
   `diagnose compare` (`src/cli.py:644-712`), `src/benchmark/diagnostics.py`,
   `attribution.py`, `report.py`, `trace.py`, `urlmatch.py`. **No new harness is needed** —
   only reference entries for the 25-question sample. This is the largest saving here.
5. **`data/benchmark/reference_links_us.json` holds 13 entries** under a top-level `entries`
   key, ids prefixed by module (`CP-030`, `SP-043`, `IF-337`). Only about 7 overlap the
   25-question sample, so the scoreboard needs new entries, not a new format.
6. **Adding reference entries needs no migration** — `benchmark_repo` persists
   `GroundTruthAnswer` as a JSON blob (established by feature 009, fact 2).
7. **`is_national_domain` (`src/shared/tools/linkresolution/jurisdiction.py:146`) blocks the
   only correct answer for state-run services.** Its own docstring concedes the limit:
   `_US_LOCAL_HOSTS` is "the honest admission that hostname shape has a limit."
8. **`exclude_urls` excludes URLs, never hosts** (`src/orchestration/scheduler.py:617-620`).
   A 403 host burns all 3 link retries one URL at a time — how #166 was lost.
9. **403 is already detected correctly** at `src/shared/tools/browser.py:192`
   (`reason = f"http_{status}"`), but the reason survives only inside a justification
   **string** (`src/agents/assessor/agent.py:170`), so no caller can branch on it.
10. **`ranking.py` is 417 lines and 13 hand-tuned constants** doing lexically what one cheap
    model call does semantically. `scripts/run_usa_sample.py` already drives the 25-question
    sample end to end against `data/usa_sample.db`, cycle `usa-sample-2026`.

## Scope note

This trades precision for recall, deliberately. More YES answers will be produced and some
will be wrong. That is the correct direction right now: a pipeline that answers "No" to
everything yields no signal to tune against. Phase 2 exists so the trade is *measured* rather
than *felt*, and it blocks every other phase for that reason.

---

## Phase 1: Setup

- [x] T001 Run the 25-question sample unchanged via `scripts/run_usa_sample.py` and write the per-question outcome table to `specs/010-recall-recovery/baseline-before.md` — delivered/no-suggestion counts, resolved URL, and terminal `prefill_reason` per question. This is the "7 of 25" figure every later phase is measured against; without it no task in this feature can be shown to have worked.
- [x] T002 [P] Record the current test-suite state by running `pytest -q` and appending the pass/fail counts to `specs/010-recall-recovery/baseline-before.md`, so a failure introduced in Phase 3+ is distinguishable from one that was already there.
- [x] T003 [P] Point `.specify/feature.json` at `specs/010-recall-recovery` so subsequent speckit commands operate on this feature rather than 009.

---

## Phase 2: Foundational (blocking prerequisites)

**These block every user story. Nothing in Phase 3+ may start until Phase 2 completes** — each
story's independent test is a number produced by this scoreboard, and a story shipped without
it is a change whose effect nobody can see.

- [x] T004 Compute the set difference between the 25 question ids in the sample cycle `usa-sample-2026` (read them from `data/usa_sample.db`, do not hardcode from the gap analysis) and the 13 ids already in `data/benchmark/reference_links_us.json`; write the missing ids to `specs/010-recall-recovery/missing-references.md` as the work list for T005.
- [x] T005 Add one entry per missing id to `data/benchmark/reference_links_us.json`, following the existing schema exactly (`question_id`, `indicator_id`, `country_id`, `expected_answer`, `reference_url`, `no_valid_link`, `accepted_alternatives`, `confidence`, `verified_on`, `origin`, `note`). Take `reference_url` and `expected_answer` from the "Antigravity Real-World Finding" column of `USA_25Q_GAP_ANALYSIS.md`, and set `origin` to `"USA 25Q gap analysis 2026-08-21"`.
- [x] T006 [P] Mark the three verified true negatives in `data/benchmark/reference_links_us.json` with `expected_answer: false` — #336 (no US misinformation statute, First Amendment), #108a (federal education app retired 2022), #062/#063 (utility billing is municipal/private) — each with a `note` recording the reason, so a correct "No" scores as a pass instead of a miss.
- [x] T007 [P] Set `no_valid_link: true` on the #062/#063 utility entries in `data/benchmark/reference_links_us.json`, since no national utility payment portal exists and every national candidate is therefore wrong (the D4 case feature 009 already supports).
- [x] T008 Extend `tests/unit/test_reference_fixture.py` to assert the fixture now covers every id in the 25-question sample, so a future sample change that outruns the reference set fails loudly instead of silently scoring a subset.
- [x] T009 Create `scripts/score_25q.py` that runs the sample via the existing `run_usa_sample` entry point and then `run_diagnostic` from `src/benchmark/diagnostics.py` against `data/benchmark/reference_links_us.json`, printing exactly one headline line (`"N of 25 correct (was M)"`) plus the per-stage attribution breakdown `src/benchmark/report.py` already renders.
- [x] T010 Run `scripts/score_25q.py` against the untouched pipeline and record its output in `specs/010-recall-recovery/baseline-before.md` as the scoreboard's own baseline — this must reproduce T001's count, and a disagreement between them means the scoreboard is wrong, not the pipeline.
- [x] T011 Confirm reference isolation by running `python -m src.cli verify benchmark-isolation` against the T010 session, checking that no newly added reference URL leaked into any prompt or unit row via `verify_benchmark_isolation` in `src/benchmark/verify.py`.

**Checkpoint**: every subsequent phase can now be answered with a number instead of an opinion.

---

## Phase 3: User Story 1 — Valid answers stop being discarded (P1)

**Goal**: Stop rejecting work the pipeline already did correctly. No structural change; only
gates that are provably mis-set or self-contradictory.

**Independent test**: Run `scripts/score_25q.py`. The count must rise, and the three
`no_suggestion` questions (#124, #166, #166b) must reach a terminal answer of any value.

- [x] T012 [P] [US1] Write a failing unit test in `tests/unit/test_validation_threshold.py` asserting that a validator judgment with two of three booleans true returns `passed=True`, pinning fact 1 so the 0.70/three-check arithmetic can never silently regress.
- [x] T013 [US1] Change `validation_quality_threshold` from `0.70` to `0.60` in `src/shared/config/settings.py:48` and add a comment stating that the score is computed over exactly three booleans, so 0.70 meant 3-of-3 and 0.60 means 2-of-3.
- [x] T014 [US1] Add a comment at `src/agents/validator/agent.py:181` recording the same arithmetic next to the comparison, since that is where a future reader will be standing when the number confuses them.
- [x] T015 [P] [US1] Write a failing unit test in `tests/unit/test_single_position_delivery.py` asserting a unit with one `VALIDATED_PASS` run and one failed run reaches `UnitState.DELIVERED` rather than `no_suggestion(INSUFFICIENT_POSITIONS)`.
- [x] T016 [US1] Add `min_validated_positions: int = 1` to `Settings` in `src/shared/config/settings.py` and register `AIQ_MIN_VALIDATED_POSITIONS` in `_ENV_MAP`, so the all-of-N requirement becomes a tunable rather than an assumption baked into the agent count.
- [x] T017 [US1] Change `src/orchestration/scheduler.py:583` from `len(validated_runs) < settings.assessor_agent_count` to `len(validated_runs) < settings.min_validated_positions`. Both agents still run and disagreement still routes to the resolver — this changes only how many must survive validation.
- [x] T018 [US1] Delete the final validation gate at `src/orchestration/scheduler.py:779-812`, including the `validator_node` call, the `final_validation_passed` flag, and the `FAILED_FINAL_VALIDATION` branch. It re-runs a check that already passed minutes earlier on the same evidence and can therefore only ever remove an answer, never add one.
- [x] T019 [US1] Update `tests/unit/test_final_validation_gate.py` and `tests/unit/test_final_validation.py` to match T018 — the per-agent validation loop in `src/orchestration/routers/retry_loops.py` is retained and still needs its coverage; only the duplicate delivery-time gate is gone.
- [x] T020 [US1] Delete the hard negative-confidence cap at `src/agents/assessor/agent.py:500-502` (`if not raw_answer and raw_conf > 60`). It manufactures the exact "confidence not proportionate" gap the validator then fails the run on, and the prompt at `src/shared/prompts/profiles.py` already instructs the model to calibrate honestly.
- [x] T021 [US1] Change `confidence_acceptance_threshold` from `75` to `60` in `src/shared/config/settings.py:52`, so a well-evidenced answer the model honestly scores in the 60s proceeds instead of burning a confidence retry.
- [x] T022 [US1] Rewrite the `evidence_quote` instructions in `src/shared/prompts/profiles.py:56-64`: raise the length budget from "~15 words" to roughly 40, and permit a heading plus its immediately following sentence as one span. Keep the verbatim-copy requirement — `search_by_text` still has to relocate it on the live page — and keep the volatile-number guidance unchanged.
- [x] T023 [US1] Add an explicit rule to `_JUDGMENT_PROMPT` in `src/agents/validator/agent.py:39-68` stating that a section heading, navigation label, or link text naming the feature **is** sufficient evidence that the feature exists, and must not be failed for brevity. This is the other half of T022; shipping either alone leaves the contradiction in place.
- [x] T024 [P] [US1] Add `unreachable_reason: str | None` to `AssessorAgentRun` in `src/shared/state/entities.py` (near `portal_unreachable` at `:287`) and populate it from `page_result.reason` at `src/agents/assessor/agent.py:166-174`, so callers can branch on `http_403` instead of parsing it out of a justification string.
- [x] T025 [US1] Implement host-level exclusion in `src/orchestration/scheduler.py`: when every run reports `portal_unreachable` with an `unreachable_reason` of `http_4xx` or `interstitial`, add the failed URL's host to a `blocked_domains` list on `unit_data` alongside the existing `tried_urls` write at `:617-620`.
- [x] T026 [US1] Thread `blocked_domains` from `src/orchestration/scheduler.py:401` through `resolve_link` in `src/shared/tools/linkresolution/chain.py` to `search_for_link`, and reject any candidate on a blocked host inside `_acceptable` in `src/shared/tools/linkresolution/sources/search.py`, so one anti-bot host costs one retry instead of three.
- [x] T027 [P] [US1] Add a unit test in `tests/unit/test_blocked_domains.py` asserting that a candidate on a host previously recorded as 403 is rejected by `_acceptable` while the same path on an unblocked host is accepted.
- [x] T028 [US1] Run `scripts/score_25q.py` and record the result in `specs/010-recall-recovery/after-phase3.md` against the T010 baseline.

**Checkpoint**: US1 is independently shippable and is the recommended MVP. It changes no
policy and no architecture — it stops discarding answers the pipeline already produced.

---

## Phase 4: User Story 2 — Evidence policy matches how government actually works (P1)

**Goal**: Two rules in the codebase are not conservative, they are wrong. Fix the rules rather
than tuning around them.

**Independent test**: The six federated-architecture questions (#338, #337, #170, #141, #304,
#011) resolve off `usa.gov` to the correct national agency domain, and #054-class state-run
services stop being scored as national absences.

- [x] T029 [P] [US2] Write failing unit tests in `tests/unit/test_locus_preference.py` asserting that a `national_portal_only` question whose portal lacks the content accepts evidence on another national government domain **without** requiring the `portal_exhausted` flag, while portal evidence still wins when it exists.
- [x] T030 [US2] Change `evidence_permitted` in `src/shared/tools/linkresolution/locus.py:37-72` so `national_portal_only` is a *preference*, not a lock: portal and subdomains pass first as today, and any national government domain of the same country passes as well. Delete the `portal_exhausted` parameter and its callers' plumbing — the question is about the country, and the portal is only where we look first.
- [x] T031 [US2] Remove the `link_escalated_off_portal` sticky flag and its read at `src/orchestration/scheduler.py:749-772`, now that T030 makes it meaningless, and drop `escalated_off_portal` from `ChainResolutionResult` in `src/shared/tools/linkresolution/chain.py:36-44`.
- [x] T032 [US2] Keep the portal-first *search* ordering intact at `src/orchestration/scheduler.py:332-338` — `restrict_domain` on the first attempt is what makes the portal preferred — but confirm by test in `tests/unit/test_locus_preference.py` that failing to find it there now escalates on the first retry rather than after three.
- [x] T033 [P] [US2] Write a failing unit test in `tests/unit/test_jurisdiction_prompt.py` asserting the rendered assessor prompt contains the level-of-government rule, replacing `tests/unit/test_jurisdiction.py` which tests the hostname regex being deleted.
- [x] T034 [US2] Add a level-of-government rule to the rubric section built by `render_rubric_section` in `src/shared/prompts/profiles.py:236-274`, in these terms: judge the level of government against the *service*, not the domain; a nationally-delivered service should be evidenced on a national government site; a service constitutionally delivered by states or municipalities (driving licences, vehicle registration, water and electricity billing, local property records) is correctly evidenced by a state or municipal portal, or by the national portal's page directing citizens to it; never answer No merely because the service is not run federally.
- [x] T035 [US2] Delete `src/shared/tools/linkresolution/jurisdiction.py` (150 lines of state-abbreviation and agency-acronym regex) and its import and call sites in `src/shared/tools/linkresolution/locus.py:29` and `src/shared/tools/linkresolution/sources/search.py`. T034 now carries this judgment in language the model can apply to services the regex could never enumerate.
- [x] T036 [US2] Delete `tests/unit/test_jurisdiction.py` and check `tests/unit/test_locus_escalation.py` for assertions that depended on the strict lock, updating rather than deleting any that still describe wanted behaviour.
- [x] T037 [US2] Run `scripts/score_25q.py` and record the result in `specs/010-recall-recovery/after-phase4.md`, specifically confirming the six federated-architecture questions now resolve off-portal.

**Checkpoint**: the two policy defects behind 8 of the 18 failures are gone, and about 150
lines with them.

---

## Phase 5: User Story 3 — Relevance judged by meaning, not arithmetic (P2)

**Goal**: Replace 417 lines of hand-tuned lexical scoring (`ranking.py`) with a single model call
evaluating candidate meaning against the question, and drop the mechanical heuristics that
tried to compensate for lexical ranking's blind spots.

**Independent test**: #022 (personal data access) resolves to `login.gov` rather than
`usa.gov/accessibility`, and #092 (government expenditure) resolves to `usaspending.gov` rather
than `usa.gov/tribes`.

- [x] T038 [P] [US3] Write a failing unit test in `tests/unit/test_relevance_judge.py` with a stubbed provider, asserting the judge returns the index of the semantically correct candidate for a #022-shaped case (an "accessibility" page and a "your online account" page offered against a personal-data-access question) and returns `None` when no candidate fits.
- [x] T039 [US3] Create `src/shared/tools/linkresolution/relevance.py` with `async def choose_best(provider, model, question, candidates) -> int | None`, sending the question title, its `what` text, and the numbered candidate list (url, title, snippet) and requiring a JSON `{"index": n}` or `{"index": null}` reply. Follow the existing provider-call and JSON-extraction shape in `_resolve_via_llm` at `src/shared/tools/linkresolution/sources/search.py:229-266`.
- [x] T040 [US3] Wire `choose_best` into `_best` in `src/shared/tools/linkresolution/sources/search.py`, replacing the `rank_candidates` + `meets_relevance_floor` pair. Keep the `_acceptable` domain/admissibility filter ahead of it — the judge picks among *permitted* candidates, it does not decide permission — and keep the existing `rejections` recording so the diagnostic report still names why a candidate lost.
- [x] T041 [US3] Add a deterministic fallback in `src/shared/tools/linkresolution/sources/search.py`: when no provider is configured or the judge call raises, fall back to first-acceptable-by-engine-order rather than failing resolution. A search stage that cannot rank must still return something for the assessor to read.
- [x] T042 [US3] Delete `src/shared/tools/linkresolution/ranking.py` and its imports in `src/shared/tools/linkresolution/sources/search.py:45-50` and `src/shared/tools/linkresolution/sources/sitemap.py`. Sitemap ranking has no snippets to judge and thousands of URLs to choose from, so give it a minimal local slug-overlap sort inside `sitemap.py` rather than reviving the deleted module.
- [x] T043 [US3] Reduce `src/shared/tools/linkresolution/admissibility.py` to the mechanical checks only — dead shorteners, non-content subdomains, and the `check_usable` extension test. Delete `_EDITORIAL_SEGMENTS` and `_DATED_PATH`: whether a blog post answers an indicator is a relevance judgment, and T039 now makes it with the page's actual title and snippet in hand.
- [x] T044 [US3] Fix every import orphaned by Phase 5 — `path_depth` and `is_site_root` consumers, plus any `ranking` import remaining in `src/benchmark/diagnostics.py` and under `src/shared/tools/linkresolution/` — by running `python -c "import src.cli"` and resolving what it raises.
- [x] T045 [US3] Delete `tests/unit/test_ranking.py` and `tests/unit/test_relevance_floor.py`, and prune the assertions in `tests/unit/test_admissibility.py` that covered the editorial and dated-path rules removed by T043.
- [x] T046 [US3] Record the per-question model-call cost delta in `specs/010-recall-recovery/after-phase5.md` using the existing `CostLedger`, since T039 adds one call per resolution attempt and the trade must be visible.
- [x] T047 [US3] Run `scripts/score_25q.py` and record the result in `specs/010-recall-recovery/after-phase5.md`.

**Checkpoint**: roughly 550 lines deleted, replaced by about 80.

---

## Phase 6: User Story 4 — Dead screenshot plumbing removed (P3)

**Goal**: Delete a feature that was switched off but never taken out. No behaviour change is
intended; this is why it is last.

**Independent test**: `scripts/score_25q.py` returns the identical count to Phase 5, and no
reference to `capture_ref` remains outside the database file.

- [x] T048 [US4] Delete the capture gate at `src/agents/validator/agent.py:90` — the `output.evidence.capture_ref is None` clause only — keeping the `evidence is None` and `element_reference is None` checks, which are real.
- [x] T049 [US4] Delete `src/shared/tools/capture.py` and its import and call at `src/agents/assessor/agent.py:40,487`, constructing `EvidenceOutput` without a `capture_ref`.
- [x] T050 [US4] Remove `capture_ref` from `EvidenceArtifact` (`src/shared/state/entities.py:260`), `PrefillRecord` (`:518`), and `EvidenceOutput` (`src/shared/state/schemas.py:88`), then from the persistence round-trip at `src/shared/persistence/repositories.py:904,1015` and the `or ""` workaround at `src/orchestration/routers/retry_loops.py:180`.
- [x] T051 [US4] Remove the `capture_dir` parameter from the call chain: `src/orchestration/scheduler.py`, `src/orchestration/routers/retry_loops.py`, `src/agents/assessor/agent.py:131,194,218,421,579,593`, `src/benchmark/runner.py`, and `src/cli.py`.
- [x] T052 [US4] Remove `capture_ref` from the API and export surfaces: `src/api/schemas.py:336`, `src/api/routers/prefills.py:121`, `src/export/writer.py:134`, and `src/orchestration/prefill_writer.py:34,68`. Treat the export change as a contract change and note it in the completion report.
- [x] T053 [US4] Delete the screenshot rendering from the review and portal surfaces: `capture_url` in `src/portal/common.py:17-23`, its use at `src/portal/assessor.py:113`, the image block in `src/review/web/evidence.py:64-67`, the capture template block in `src/portal/templates/assessor_unit.html`, and the static capture mount comment at `src/portal/webapp.py:74`.
- [x] T054 [US4] Remove `capture_ref` seeds from `src/portal/seed.py:80` and `src/review/seed_demo.py:109`, and update `tests/unit/test_prefill_pipeline.py`, `tests/unit/test_final_validation.py`, `tests/unit/test_prefill_reasons.py`, `tests/unit/test_resolver.py`, `tests/unit/test_resolve_only.py`, `tests/unit/test_prefill_budget.py`, `tests/unit/test_language_support_check.py` and `tests/independence/test_agent_isolation.py` accordingly.
- [x] T055 [US4] Confirm the removal is total by running `grep -rn "capture_ref\|capture_dir\|capture_region\|capture_url" src/ tests/ --include="*.py" --include="*.html"` and expecting no matches. Leave the existing `capture_ref` column in `data/aiq.db` alone — historical rows are not worth a migration.

---

## Phase 7: Polish & Cross-Cutting

- [x] T056 Run the full suite (`pytest`) and reconcile every failure against the T002 baseline, so a pre-existing failure is never mistaken for one this feature introduced.
- [x] T057 [P] Verify coverage still meets the project's 80% floor via `pytest --cov=src --cov-report=term-missing`, paying attention to `src/shared/tools/linkresolution/` where the most code was deleted.
- [x] T058 [P] Update the module docstrings in `src/shared/tools/linkresolution/chain.py`, `locus.py` and `admissibility.py`, which currently narrate defect histories for code this feature deletes — a docstring describing a removed heuristic is worse than none.
- [x] T059 [P] Add a short note under `docs/` recording the precision/recall trade this feature made and the date, so the next person to see a wrong YES understands it was chosen rather than overlooked.
- [x] T060 Run `graphify update .` to refresh the knowledge graph after roughly 700 lines were removed.
- [x] T061 Run `scripts/score_25q.py` one final time and write `specs/010-recall-recovery/results.md` comparing every phase against the T010 baseline, with the per-stage attribution breakdown for whatever still fails.
- [x] T062 Run `python -m src.cli diagnose compare <baseline-session> <final-session>` and confirm no indicator that passed at baseline regressed — a net gain hiding an individual regression is the failure mode `compare` exists to catch.

---

## Dependencies

```
Phase 1 (Setup: T001-T003)
    └─> Phase 2 (Scoreboard: T004-T011)   [BLOCKS EVERYTHING]
            ├─> Phase 3 (US1: T012-T028)   P1  — MVP
            │       └─> Phase 4 (US2: T029-T037)   P1
            │               └─> Phase 5 (US3: T038-T047)   P2
            └─> Phase 6 (US4: T048-T055)   P3  (independent of US1-US3)
                    └─> Phase 7 (Polish: T056-T062)
```

**Cross-story couplings, stated explicitly because these are the ones that bite:**

- **T022 and T023 must ship together.** T022 alone lets the assessor write longer quotes that
  the validator still fails; T023 alone tells the validator to accept headings the assessor is
  still instructed not to write. The contradiction is only resolved by both.
- **Phase 4 must follow Phase 3, not run beside it.** Both change how many questions reach
  delivery. Interleaved, the scoreboard cannot attribute the movement to either.
- **T042 (delete `ranking.py`) breaks `sitemap.py`,** which ranks thousands of URLs with no
  snippets and cannot use the model judge. T042 carries its own replacement; do not split it.
- **Phase 6 is deliberately last and deliberately independent.** It is the only phase expected
  to move the score by zero, which is also its acceptance criterion — running it earlier would
  put a wide, behaviour-neutral diff in the middle of the phases whose whole purpose is to
  move the number.
- **T030 deletes the `portal_exhausted` parameter** that `tests/unit/test_locus_escalation.py`
  exercises. Read that test before deleting, not after.

## Parallel opportunities

- **Phase 1**: T002 and T003 run together after T001.
- **Phase 2**: T006 and T007 run together once T005 lands the entries; T008 is independent of
  both. T009-T011 are strictly sequential.
- **Phase 3**: the two failing-test tasks T012 and T015 run together and alongside T024. The
  prompt pair T022/T023 is independent of the settings changes T013/T016/T021 and can be done
  by a second person. T027 runs alongside T025-T026.
- **Phase 4**: T029 and T033 (both tests) run together, before their implementations.
- **Phase 5**: T038 runs alongside T039. T043-T045 are independent files once T042 lands.
- **Phase 6**: T048-T053 all touch different files and parallelise widely, but T054 must
  follow all of them.
- **Across stories**: Phase 6 is independent of Phases 3-5 and can proceed concurrently by a
  second person from the moment Phase 2 completes.

## Implementation strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1).** This is the recommendation. It changes no policy
and no architecture — it only stops discarding answers the pipeline already produced correctly
— and it should recover the three `no_suggestion` questions plus most of the four rows the gap
analysis labels "Pipeline Bug". Ship it, read the number, then decide.

**Recommended first release = MVP + Phase 4 (US2).** Both stories are P1. Phase 3 alone raises
the count without touching the largest single cause of failure, which is the six questions lost
to a domain lock that mis-models how the US federal government publishes anything.

**Phase 5 is the deletion that matters most for maintenance** and the least for the immediate
number. Do it once Phases 3-4 have confirmed the scoreboard moves, so the LLM judge is measured
against a pipeline that is otherwise working rather than one that is failing for other reasons.

**Phase 6 is pure debt paydown.** Run it whenever a second person is free.
