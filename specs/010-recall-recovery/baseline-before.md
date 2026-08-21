# Baseline Before: Recall Recovery & Resolver Simplification

**Captured**: 2026-08-21
**Session**: usa-sample-2026-workflow-session
**DB**: data/usa_sample.db

---

## T001: 25-Question Sample Outcome (Baseline)

Run via `python scripts/run_usa_sample.py` against session `usa-sample-2026-workflow-session`.

| Metric | Count |
|--------|-------|
| delivered | 22 |
| no_suggestion | 3 |
| unassessable | 0 |
| escalated | 0 |
| in_progress | 0 |
| **Total** | **25** |

### Per-Question Detail

| Question ID | Indicator | State | Resolved URL | prefill_reason |
|-------------|-----------|-------|--------------|----------------|
| usa-sample-2026:CP-015 | #015 | delivered | https://www.usa.gov/official-language-of-us | |
| usa-sample-2026:CP-030 | #030 | delivered | https://sam.gov/fpds | |
| usa-sample-2026:EGL-003 | #003 | delivered | https://www.usa.gov/search-gov | |
| usa-sample-2026:EGL-036b | #036b | delivered | https://www.usa.gov/libraries | |
| usa-sample-2026:EGL-321 | #321 | delivered | https://19january2021snapshot.epa.gov/e-enterprise/about-e-enterprise-environment_.html | |
| usa-sample-2026:EP-141 | #141 | delivered | https://data.gov/open-gov/ | |
| usa-sample-2026:EP-170 | #170 | delivered | https://open.gsa.gov/data/ | |
| usa-sample-2026:EP-304 | #304 | delivered | https://www.usa.gov/education | |
| usa-sample-2026:IF-011 | #011 | delivered | https://www.usa.gov/agency-index | |
| usa-sample-2026:IF-173 | #173 | delivered | https://www.usa.gov/historical-documents | |
| usa-sample-2026:IF-336 | #336 | delivered | https://www.usa.gov | |
| usa-sample-2026:IF-337 | #337 | delivered | https://www.usa.gov/agencies/chief-information-officers-council | |
| usa-sample-2026:IF-338 | #338 | delivered | https://www.usa.gov/privacy | |
| usa-sample-2026:IF-340 | #340 | delivered | https://www.nist.gov/mep/cybersecurity-resources-manufacturers/compliance-cybersecurity-and-privacy-laws-and-regulations | |
| usa-sample-2026:SP-043 | #043 | delivered | https://www.usa.gov/file-taxes | |
| usa-sample-2026:SP-048 | #048 | delivered | https://www.usa.gov/change-address | |
| usa-sample-2026:SP-062 | #062,#063 | delivered | https://www.usa.gov/help-with-utility-bills | |
| usa-sample-2026:SP-095 | #095 | delivered | https://www.usa.gov/health | |
| usa-sample-2026:SP-108 | #108 | delivered | https://www.usa.gov/education | |
| usa-sample-2026:SP-108a | #108a | delivered | https://www.usa.gov/education | |
| usa-sample-2026:SP-124 | #124 | **no_suggestion** | https://www.usa.gov/jobs | insufficient_positions |
| usa-sample-2026:SP-137b | #137b | delivered | https://www.ready.gov/alerts | |
| usa-sample-2026:SP-166 | #166 | **no_suggestion** | https://www.state.gov/environment/ | insufficient_positions |
| usa-sample-2026:SP-166b | #166b | **no_suggestion** | https://www.ready.gov/alerts | insufficient_positions |
| usa-sample-2026:TECH-022 | #022,#024 | delivered | https://www.usa.gov/accessibility | |

**Note**: All 3 `no_suggestion` cases (#124, #166, #166b) share `insufficient_positions` as the terminal reason — confirming fact 1 from the codebase analysis.

---

## T002: Test Suite Baseline

Run via `pytest -q`:

```
341 passed in 16.96s
```

**0 pre-existing failures.**

---

## T010: Scoreboard Baseline (scripts/score_25q.py)

*(Populated by T010 in Phase 2)*
