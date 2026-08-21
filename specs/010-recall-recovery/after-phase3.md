# After Phase 3: User Story 1 (Valid answers stop being discarded)

Recorded on 2026-08-21 after completing Phase 3 tasks T012–T028.

## Scoreboard Comparison

| Metric | Phase 2 Baseline (T010) | Phase 3 (US1) (T028) | Delta |
|---|---|---|---|
| Total Indicators Evaluated | 25 | 25 | 0 |
| Authoritative Matches | 8 | 7 | -1 |
| Authoritative Divergent Plausible | 13 | 14 | +1 |
| Authoritative Misses / Divergences | 2 | 2 | 0 |
| Provisional Matches | 0 | 0 | 0 |
| Provisional Misses | 2 | 2 | 0 |
| Resolution Failures (Link) | 2 | 2 | 0 |
| Environmental Failures | 0 | 0 | 0 |
| Test Suite Passing | 341 | 348 | +7 |

## Key Changes Implemented in Phase 3 (US1)

1. **T012–T014**: Lowered `validation_quality_threshold` from `0.70` to `0.60` in `settings.py` so that 2 out of 3 validator judgment booleans (66.7%) pass validation rather than requiring 100% perfection. Added clarifying comments and unit tests.
2. **T015–T017**: Added `min_validated_positions = 1` setting and updated `scheduler.py` so a single validated pass can proceed to prefill delivery rather than requiring all `assessor_agent_count` agents to survive validation.
3. **T018–T019**: Removed the duplicate delivery-time final validation gate (`FR-PF-030`) at scheduler line ~779-812 which re-validated positions that already passed the per-agent validation loop. Updated test fixtures.
4. **T020–T021**: Deleted the artificial negative-confidence hard cap (`raw_conf = 60`) from `assessor/agent.py` and lowered `confidence_acceptance_threshold` from `75` to `60` in `settings.py`.
5. **T022–T023**: Expanded the assessor `evidence_quote` length budget from ~15 words to ~40 words in `profiles.py` (allowing heading + following sentence), and added the heading-sufficiency rule to `_JUDGMENT_PROMPT` in `validator/agent.py`.
6. **T024–T027**: Added `unreachable_reason` tracking to `AssessorAgentOutput` / `AssessorAgentRun` and host-level exclusion (`blocked_domains`) in `scheduler.py`, `chain.py`, and `search.py`, with unit test in `test_blocked_domains.py`.

## Verification Status
- Full pytest suite: 348 passed (0 failed).
- Benchmark isolation: 0 leaks verified.
