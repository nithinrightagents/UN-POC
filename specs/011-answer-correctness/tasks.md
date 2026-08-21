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

## Phase 5: Post-Gate Exploration & Refinements
- [x] T018 Test and note single-agent vs multi-agent configuration
- [x] T019 Audit `EGL-321` validator reasoning and record note in fixture
- [x] T020 Audit `SP-166b` domain reference and record note / alternative
