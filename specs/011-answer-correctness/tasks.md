# Tasks — 011: Get to a Meaningful Answer, Simply

## Phase 1: Setup & Groundwork
- [x] T001 Reconcile `scripts/score_25q.py` to evaluate delivered prefills (credit answer matches only when prefill was actually delivered/suggested, matching human reviewer delivery) in `scripts/score_25q.py`
- [x] T002 Add architectural comment block atop `src/orchestration/scheduler.py` naming the live path and documenting dormant 2-agent components
- [x] T003 Wrote `scripts/reset_runs.py` to clean run rows while preserving seed data
- [x] T004 Backed up baseline DB and purged run rows

## Phase 2: Link Resolution Precedence & Judgment (TDD)
- [x] T009 [P] Write unit tests in `tests/unit/test_chain_adjudication.py` verifying sitemap vs search adjudication with `choose_best()` and sitemap tie-break
- [x] T010 [P] Write unit test in `tests/unit/test_chain_adjudication.py` for single usable candidate short-circuit (no judge call needed when only one usable)
- [x] T011 [P] Write regression test in `tests/unit/test_chain_adjudication.py` asserting `search_for_link` is called with `restrict_domain=None` on attempt #1 while sitemap receives `portal_url`
- [x] T005 Update `src/shared/tools/linkresolution/chain.py` to evaluate both sitemap and search attempts without prematurely short-circuiting on sitemap hit
- [x] T006 Implement chain-level adjudication with `choose_best()`, portal tie-break on None/tie, and record winning source in `history`
- [x] T007 Split `restrict_domain` so sitemap receives portal scope while search runs unrestricted (`restrict_domain=None`)
- [x] T008 Perform cost check and verification of candidate adjudication
- [x] T021 Fix recursive link-retry call in `src/orchestration/scheduler.py` to forward `resolve_only=resolve_only`
- [x] T012 Run full test suite (`pytest -q`) and ensure all 281+ tests pass

## Phase 3: Validation Threshold & Logging Alignment
- [x] T013 Update `.env` to set `AIQ_VALIDATION_QUALITY_THRESHOLD=0.60` and `AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD=60`
- [x] T014 Log effective configuration values at run start (`validation_quality_threshold`, `confidence_acceptance_threshold`, `min_validated_positions`, `assessor_agent_count`)

## Phase 4: Gate Measurement & Attribution
- [x] T015 Run `python scripts/score_25q.py` on clean DB and document output in `specs/011-answer-correctness/results-step1.md`
- [x] T016 Include per-source correctness breakdown (sitemap vs search vs portal_default) in `results-step1.md`
- [x] T017 Validate that true negatives (`SP-108a`, `IF-336`, `SP-062`) did not flip to false positives

## Phase 5: Step 4 — Link Delivery & Validation Recovery
- [x] T022 Fix config invariant: `AIQ_BEST_EFFORT_CONFIDENCE_CEILING=55` in `.env` and `settings.py` (below threshold 60)
- [x] T023 Deliver resolved link + confident answer on validation gap as best-effort flagged (`PrefillReason.NEEDS_HUMAN_REVIEW`) in `scheduler.py`
- [x] T024 Handle DOM truncation in validator via `VerificationOutcome.TRUNCATED_UNVERIFIABLE` and propagate flags
- [x] T025 Prevent retry loop answer flips by providing targeted re-cite addendum for mechanical validation failures
- [x] T026 Add regression test coverage in `test_best_effort_delivery.py`, `test_truncated_validation.py`, `test_retry_addendum_wording.py`
- [x] T027 Add `validated_negative_confidence_floor = 55` for validated negatives
- [x] T028 Fallback in `review/query.py` (`build_question_review`) to `repo.latest_prefill(...)` when no adjudication records exist

## Phase 6: Step 5 — Asymmetric Evidence & False Negative Elimination
- [x] T040 Allow one-hop navigation in `src/agents/assessor/agent.py` to cross to same-country government domains passing admissibility and rank same-domain first
- [x] T041 Implement negative recheck in `src/orchestration/scheduler.py`: unanimous `No` must survive second look before delivery
- [x] T042 Formulate negative recheck query in `scheduler.py` from `question.what` rather than `question.title` to break keyword traps
- [x] T043 Reject frozen archive snapshots (`*snapshot*`, `*archive*`) in `src/shared/tools/linkresolution/admissibility.py`
- [x] T044 Add guard benchmark checks for true negative retention and false negative recovery in `test_negative_recheck_and_gate.py`
- [x] T046 Implement negative delivery gate in `scheduler.py`: require >= 2 distinct pages & >= 2 queries for clean floored negative; otherwise deliver flagged `NEEDS_HUMAN_REVIEW`
- [x] T047 Attach negative provenance (`pages_examined`, `queries_used`, `blocked_domains`) to prefill `unit_context` in `scheduler.py`
- [x] T048 Verify test suite (307 passing tests) across all components

## Phase 7: Post-Gate Exploration & Refinements
- [x] T018 Test and note single-agent vs multi-agent configuration
- [x] T019 Audit `EGL-321` validator reasoning and record note in fixture
- [x] T020 Audit `SP-166b` domain reference and record note / alternative
