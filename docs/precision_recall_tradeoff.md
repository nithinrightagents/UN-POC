# Precision vs. Recall Calibration Note (2026-08-21)

## Overview
On 2026-08-21, the system underwent a major recall recovery overhaul (`specs/010-recall-recovery`) following gap analysis against the 25-question benchmark sample (`USA_25Q_GAP_ANALYSIS.md`).

Historically, the pipeline had accumulated defensive heuristics designed to minimize false positives:
- Rigid 85% validation threshold and 90% confidence gates.
- Strict locus locks discarding off-portal national government evidence.
- 150 lines of state/agency regex (`jurisdiction.py`) blocking valid federal services.
- Over 400 lines of lexical token count arithmetic (`ranking.py`) and aggressive editorial path filtering.
- Redundant delivery-time validation gates rejecting valid consensus answers.
- Dead screenshot capture plumbing.

These defensive mechanisms created a severe recall defect where **valid government services were discarded or marked unassessable**.

## Architectural Shifts & Intentional Trade-offs

1. **Threshold & Confidence Calibration**:
   - Validation threshold aligned to `0.70` (matching human assessment rubric guidelines).
   - Confidence calibrated to standard `0.70` baseline for binary answers.
   - Host-level domain blocking moved to network transport layer (`blocked_domains`).
   - Redundant delivery-time gate removed in favor of independent assessor verification.

2. **Locus Preference vs. Lock**:
   - `national_portal_only` is treated as a search preference (portal first) rather than an exclusionary lock.
   - Any valid government domain of the surveyed nation is admissible on retry.
   - Level-of-government evaluation is delegated to the LLM assessor prompt rubric rather than mechanical regexes.

3. **Semantic Relevance vs. Arithmetic Lexical Scoring**:
   - Replaced hand-tuned lexical scoring weights with an LLM semantic judge (`choose_best`) running on low-cost models (< $0.0001 per resolution).
   - Sitemap uses lightweight slug-overlap matching.
   - Mechanical admissibility is restricted to dead shorteners and non-content asset/data subdomains.

4. **Screenshot Capture Removal**:
   - Removed obsolete headless capture plumbing (`capture_ref`, `capture_dir`, `capture_url`) across all agent, orchestration, and review surfaces.

## Key Operating Principle
The EKAP assessment platform is designed as an **AI Prefill assistant** for blind human assessor pairs (A/B), not an autonomous final judge. A suggestable candidate with verified textual evidence empowers the human reviewer to verify or override, whereas a false negative / unassessable result forces human assessors to reconstruct searches from scratch.
