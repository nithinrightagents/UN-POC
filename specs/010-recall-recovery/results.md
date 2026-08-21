# Final Results: 010-Recall-Recovery & Resolver Simplification

**Date**: 2026-08-21  
**Specification**: [`specs/010-recall-recovery`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/specs/010-recall-recovery)  
**Status**: All 8 Phases Complete (T001–T062)

---

## Executive Summary

The `010-recall-recovery` initiative addressed a critical defect in the EKAP e-government prefill pipeline: **valid government services were routinely dropped or marked unassessable due to excessive defensive heuristics**.

Across Phases 1 through 7:
- Over **750 lines** of dead, brittle, and hand-tuned heuristic code were deleted (`jurisdiction.py`, `ranking.py`, `capture.py`, editorial regexes).
- Hand-tuned lexical token counting was replaced with a semantic relevance LLM judge (`choose_best`) running on lightweight flash models (< $0.0001 per query).
- Mechanical locus locking was relaxed to **locus preference** (portal first, escalating to national government domains on retry), delegating jurisdiction fitness to the assessor prompt rubric.
- Confidence and validation thresholds were realistically calibrated (`0.60`–`0.70`), and redundant delivery-time final validation gates were eliminated.
- Dead screenshot plumbing (`capture_ref`, `capture_dir`, `capture_url`) was excised completely across all backend, pipeline, API, export, and web surfaces.

---

## Phase-by-Phase Progression

| Phase | Focus Area | Code Change | Test Suite Result |
|---|---|---|---|
| **Phase 1: Setup & Configuration** | Feature flags & baseline capture | Added configurable recall toggles in `settings.py` | 341 passed |
| **Phase 2: Reference Fixtures & Scoreboard** | Diagnostic attribution & ground truth fixtures | Added `tests/fixtures/reference_verdicts_us_25q.json` & scoreboard diagnostic engine | 341 passed |
| **Phase 3: Valid Answers Retained (US1)** | Threshold calibration, confidence gates, single validated position delivery | Removed duplicate delivery-time gate; calibrated validation & confidence thresholds; added `blocked_domains` transport filtering | 348 passed |
| **Phase 4: Government Evidence Policy (US2)** | Locus preference & rubric prompt | Deleted `jurisdiction.py` (150 lines regex); implemented locus preference over lock; added level-of-government rubric prompt | 317 passed (pruned deleted regex tests) |
| **Phase 5: Semantic Relevance (US3)** | LLM semantic judge & local sitemap slug overlap | Deleted `ranking.py` (418 lines); implemented `choose_best` semantic judge; stripped non-mechanical heuristics from `admissibility.py` | 281 passed (pruned ranking tests) |
| **Phase 6: Dead Screenshot Removal (US4)** | Clean removal of capture plumbing | Deleted `src/shared/tools/capture.py`; removed `capture_ref`, `capture_dir`, and `capture_url` from entities, schemas, API, export, and UI templates | 281 passed |
| **Phase 7: Polish & Documentation** | Verification, knowledge graph, docs | Documented precision/recall trade-off; refreshed graphify graph; full suite verification | 281 passed |

---

## System Architecture Summary

```
                +------------------------------------------------+
                |           Link Resolution Chain                |
                |  (Prior Survey KB -> MSQ -> Sitemap -> Search) |
                +------------------------------------------------+
                                       |
                +------------------------------------------------+
                |    Semantic Relevance Judge (choose_best)      |
                |    Mechanical Admissibility (Dead Shorteners/  |
                |    Non-Content Subdomains)                     |
                +------------------------------------------------+
                                       |
                +------------------------------------------------+
                |     Assessor Agents (N >= 2 Independent)       |
                |  - Level-of-Government Prompt Rubric           |
                |  - 40-word quote budget + heading sufficiency  |
                +------------------------------------------------+
                                       |
                +------------------------------------------------+
                |   Per-Agent Validation & Adjudication Loop     |
                |  - min_validated_positions = 1 delivery        |
                |  - Direct Delivery on Consensus (No 2nd Gate)  |
                +------------------------------------------------+
```

---

## Test Suite Verification

- **Total Tests Passing**: 281 passed in 23.25s.
- **Pre-existing Failures**: 0.
- **Regressions**: 0.
- **Orphaned Capture References**: 0 (`src/` and `tests/` confirmed clean).
