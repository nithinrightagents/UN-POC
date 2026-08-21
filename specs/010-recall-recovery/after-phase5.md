# After Phase 5: User Story 3 (Relevance judged by meaning, not arithmetic)

Recorded on 2026-08-21 after completing Phase 5 tasks T038–T047.

## Key Changes Implemented in Phase 5 (US3)

1. **T038–T039**: Created semantic relevance judge `choose_best(provider, model, question, candidates)` in [`src/shared/tools/linkresolution/relevance.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/shared/tools/linkresolution/relevance.py). It evaluates candidate links against indicator title and what-text via targeted model prompting, returning the index or `null`. Verified in `tests/unit/test_relevance_judge.py`.
2. **T040–T041**: Wired `choose_best` into `search_for_link` in [`src/shared/tools/linkresolution/sources/search.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/shared/tools/linkresolution/sources/search.py). Maintained pre-filter mechanical checks with deterministic fallback to engine order when no provider is configured or upon failure.
3. **T042**: Deleted `src/shared/tools/linkresolution/ranking.py` (418 lines of hand-tuned regex weights and term tiers). Implemented clean, self-contained slug-overlap matching in [`src/shared/tools/linkresolution/sources/sitemap.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/shared/tools/linkresolution/sources/sitemap.py).
4. **T043**: Reduced [`src/shared/tools/linkresolution/admissibility.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/shared/tools/linkresolution/admissibility.py) strictly to mechanical checks (dead shorteners, non-content subdomains like analytics/cdn, and `check_usable` extensions). Deleted rigid `_EDITORIAL_SEGMENTS` and `_DATED_PATH` regex.
5. **T044–T045**: Verified CLI import clean with `python -c "import src.cli"`. Deleted `tests/unit/test_ranking.py` and `tests/unit/test_relevance_floor.py`. Pruned editorial/dated-path assertions in `tests/unit/test_admissibility.py`.

## Cost & Token Accounting (T046)
- The semantic relevance judge adds 1 lightweight model call (`temperature=0.0`) per candidate resolution set when internet search is invoked.
- Typical payload: ~300 prompt tokens (question title, description, up to 10 candidate titles/snippets) + ~15 completion tokens (`{"index": 0}`).
- At standard flash tier pricing, this represents < $0.0001 per resolved search attempt.

## Test Verification
- All 281 unit, contract, and integration tests passed cleanly (`pytest`).
