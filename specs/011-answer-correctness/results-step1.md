# 011 Step 1 Results: Candidate Precedence & Adjudication

**Date:** 2026-08-21  
**Benchmark Set:** `bm-reference-links-us` (25 US indicators)  
**Configuration:**
- `AIQ_VALIDATION_QUALITY_THRESHOLD=0.60`
- `AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD=60`
- `AIQ_MIN_VALIDATED_POSITIONS=1`
- `AIQ_ASSESSOR_AGENT_COUNT=1`

---

## 1. Headline Results & Comparison

| Metric | Baseline (010) | Step 1 (011) | Delta |
|---|---|---|---|
| **Delivered and Correct (Prefill)** | **12 of 25 (48.0%)** | **14 of 25 (56.0%)** | **+2 (+8.0%)** |
| **Total Delivered Prefills** | 20 of 25 (80.0%) | 22 of 25 (88.0%) | +2 |
| **Withheld (`insufficient_positions`)** | 5 of 25 (20.0%) | 3 of 25 (12.0%) | -2 |
| **False Positives** | **0** | **0** | 0 (Preserved) |

---

## 2. Per-Source Performance Breakdown

Candidate adjudication with `choose_best()` and sitemap tie-break increased accuracy across both sources:

| Supplying Source | Total Units | Delivered Prefills | Correct Answers | Accuracy Rate | vs Baseline |
|---|---|---|---|---|---|
| **sitemap** | 7 | 7 | 5 | **71.4%** | +8.4% (was 63%) |
| **search** | 16 | 13 | 7 | **43.8%** | +2.8% (was 41%) |
| **portal_default** | 2 | 2 | 2 | **100.0%** | (was 0%) |
| **prior_survey_kb / msq** | 0 | 0 | 0 | — | — |

---

## 3. Full 25-Question Results Table

| Question | Indicator | Evidence Locus | Supplying Source | Landed URL | Delivered Answer | Expected | Verdict |
|---|---|---|---|---|---|---|---|
| **CP-015** | #015 | `national_portal_only` | `portal_default` | `https://www.usa.gov` | True | True | ✓ MATCH |
| **CP-030** | #030 | `any_government_domain` | `search` | `https://sam.gov/fpds` | False | True | ✗ MISS |
| **EGL-003** | #003 | `national_portal_only` | `search` | `https://www.usa.gov/` | True | True | ✓ MATCH |
| **EGL-036b** | #036b | `national_portal_only` | `search` | `https://www.usa.gov/libraries` | False | True | ✗ MISS |
| **EGL-321** | #321 | `any_government_domain` | `search` | `https://www.epa.gov/citizen-science` | WITHHELD | True | ✗ WITHHELD |
| **EP-141** | #141 | `national_portal_only` | `search` | `https://catalog.data.gov/` | False | True | ✗ MISS |
| **EP-170** | #170 | `national_portal_only` | `search` | `https://catalog.data.gov/` | True | True | ✓ MATCH |
| **EP-304** | #304 | `national_portal_only` | `search` | `https://fiscaldata.treasury.gov/americas-finance-guide/federal-spending/` | False | True | ✗ MISS |
| **IF-011** | #011 | `national_portal_only` | `search` | `https://www.whitehouse.gov/administration/cabinet/` | WITHHELD | True | ✗ WITHHELD |
| **IF-173** | #173 | `any_government_domain` | `search` | `https://www.justice.gov/` | True | True | ✓ MATCH |
| **IF-336** | #336 | `national_portal_only` | `sitemap` | `https://www.usa.gov/laws-and-legal-issues` | False | False | ✓ MATCH |
| **IF-337** | #337 | `national_portal_only` | `search` | `https://www.councils.gov/cioc/` | True | True | ✓ MATCH |
| **IF-338** | #338 | `national_portal_only` | `sitemap` | `https://www.usa.gov/privacy` | False | True | ✗ MISS |
| **IF-340** | #340 | `national_portal_only` | `search` | `https://www.gsa.gov/technology/government-it-initiatives/cybersecurity/cybersecurity-programs-and-policy` | WITHHELD | True | ✗ WITHHELD |
| **SP-043** | #043 | `any_government_domain` | `sitemap` | `https://www.usa.gov/file-taxes` | True | True | ✓ MATCH |
| **SP-048** | #048 | `any_government_domain` | `sitemap` | `https://www.usa.gov/change-address` | True | True | ✓ MATCH |
| **SP-062** | #062 | `any_government_domain` | `portal_default` | `https://www.usa.gov` | False | False | ✓ MATCH |
| **SP-095** | #095 | `national_portal_only` | `sitemap` | `https://www.usa.gov/health` | True | True | ✓ MATCH |
| **SP-108** | #108 | `national_portal_only` | `sitemap` | `https://www.usa.gov/education` | True | True | ✓ MATCH |
| **SP-108a** | #108a | `national_portal_only` | `search` | `https://www.ed.gov/` | False | False | ✓ MATCH |
| **SP-124** | #124 | `national_portal_only` | `search` | `https://www.usajobs.gov/` | True | True | ✓ MATCH |
| **SP-137b** | #137b | `national_portal_only` | `search` | `https://www.ssa.gov/agency/updates/` | True | True | ✓ MATCH |
| **SP-166** | #166 | `national_portal_only` | `search` | `https://www.epa.gov/home` | False | True | ✗ MISS |
| **SP-166b** | #166b | `national_portal_only` | `search` | `https://www.ready.gov/alerts` | False | True | ✗ MISS |
| **TECH-022** | #022 | `national_portal_only` | `sitemap` | `https://www.usa.gov/social-security-report-a-death` | False | True | ✗ MISS |

---

## 4. Key Findings & Observations

1. **Candidate Adjudication Succeeded (T005–T007):**
   - The pipeline now finds agency portals when necessary (`CIO Council` at `councils.gov`, `DOJ` at `justice.gov`, `USAJobs` at `usajobs.gov`, `SSA Updates` at `ssa.gov`) while keeping genuine portal links via sitemap (`/file-taxes`, `/change-address`, `/health`, `/education`).
   - Sitemap accuracy rose to **71.4%** (5/7) and search accuracy rose to **43.8%** (7/16).
2. **True Negatives Remained 100% Intact (T017):**
   - `SP-108a` (retired mobile app): expected NO, delivered NO.
   - `IF-336` (no federal misinformation statute): expected NO, delivered NO.
   - `SP-062` (no national utility payment portal): expected NO, delivered NO.
   - Zero hallucinations or false positives were introduced by the wider search candidate pool.
3. **Threshold Calibration Unblocked Prefills (T013):**
   - Delivered count increased from 20 to 22.
   - Withheld units reduced from 5 to 3 (`EGL-321`, `IF-011`, `IF-340`).
