# After Phase 4: User Story 2 (Evidence policy matches how government actually works)

Recorded on 2026-08-21 after completing Phase 4 tasks T029–T037.

## Key Changes Implemented in Phase 4 (US2)

1. **T029–T030**: `evidence_permitted` in `src/shared/tools/linkresolution/locus.py` updated so `national_portal_only` is a *preference*, not a strict lock. Portal and subdomains pass first; any recognized national government domain of the same country passes as well. Removed `portal_exhausted` parameter.
2. **T031**: Removed `link_escalated_off_portal` sticky flag and its read in `src/orchestration/scheduler.py`, and dropped `escalated_off_portal` from `ChainResolutionResult` in `src/shared/tools/linkresolution/chain.py`.
3. **T032**: Maintained portal-first search ordering in `src/orchestration/scheduler.py` via `restrict_to_portal = is_first_attempt` so failing to find content on the portal escalates on the first retry rather than after 3. Verified in `tests/unit/test_locus_preference.py`.
4. **T033–T034**: Added level-of-government rubric rule in `render_rubric_section` in `src/shared/prompts/profiles.py` instructing the model to judge level of government against the service rather than mechanical domain checks. Verified with `tests/unit/test_jurisdiction_prompt.py`.
5. **T035–T036**: Deleted `src/shared/tools/linkresolution/jurisdiction.py` (150 lines of rigid state-abbreviation regex) and `tests/unit/test_jurisdiction.py`. Updated `tests/unit/test_locus_escalation.py`.

## Verification Status
- Full pytest suite: 317 passed (0 failed).
- All Phase 4 tests passing cleanly.
