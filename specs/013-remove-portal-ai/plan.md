# Implementation Plan: Removal of AI Prefill and AI Capabilities from Portal

**Feature Directory**: `specs/013-remove-portal-ai`  
**Spec**: [spec.md](./spec.md)  
**Created**: 2026-08-26  
**Status**: Phase 1 complete — design artifacts generated  
**Branch**: `main`

---

## Summary

The UN-POC portal was originally built to include automated AI prefill capabilities alongside human evaluations. In practice, automated LLM prefill generation adds unneeded UI complexity, introduces confirmation bias for human evaluators, creates unauthenticated backend trigger risks, and clutters administrative views.

This implementation plan defines the complete file-by-file removal of AI prefill UI components, portal routes, background runners, and AI submission telemetry from the portal application. The portal becomes a 100% human-verified evaluation system, while preserving the underlying domain models, double-blind assessor workflows, dynamic discrepancy detection and Reconciliation Workspace (Spec 012), and Senior Reviewer publication pipelines.

---

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / Runtime** | Python 3.11+, FastAPI, Jinja2, SQLite | `pyproject.toml` |
| **New Dependencies** | **None.** | [research.md](./research.md) |
| **Deleted Modules** | `src/portal/live_prefill.py` | [research.md](./research.md) R1 |
| **Modified — Templates** | `src/portal/templates/assessor_unit.html`, `src/portal/templates/admin_project_detail.html` | [contracts/portal-surface.md](./contracts/portal-surface.md) |
| **Modified — Portal Routes** | `src/portal/admin.py` (remove `/assess` route & AI summary), `src/portal/assessor.py` (remove `row.ai` & submission AI telemetry), `src/portal/seed.py` | [contracts/portal-surface.md](./contracts/portal-surface.md) |
| **Modified — Persistence & Data** | `src/shared/persistence/schema.py` (drop `prefills`/`prefill_candidates`), `src/shared/persistence/repositories.py`, `src/shared/state/entities.py` | [data-model.md](./data-model.md) |
| **Modified — Decoupling** | `src/api/runner.py` (remove import of `portal.live_prefill`) | [research.md](./research.md) R1 |
| **Testing** | `pytest tests/unit` — zero model calls, fast offline execution | [quickstart.md](./quickstart.md) |

---

## Constitution Check

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **100% Human Assessment Integrity** | Portal must not present automated AI suggestions to assessors | All AI prefill cards, bot alert boxes, and "Use AI Suggestion" buttons are completely removed from `assessor_unit.html`. | **PASS** |
| **Blind A/B Integrity** | Assessors evaluate independently and blindness is preserved | Assessor A and Assessor B workflows remain fully separated and blind until mutual completion triggers Spec 012 reconciliation. | **PASS** |
| **Human Discrepancy & Reconciliation** | Discrepancy detection (Spec 012) must remain functional | Dynamic discrepancy recomputation and the Reconciliation Workspace compare human Assessor A vs Assessor B and are 100% intact. | **PASS** |
| **Schema Hygiene** | Schema reflects active data structures without dead tables | Prefill tables and unused AI telemetry columns in `human_submissions` are dropped via clean migration. | **PASS** |
| **Zero Emoji Rule** | Portal templates adhere to anti-slop zero-emoji design | Refactored templates use clean SVG icons (`#icon-users`, `#icon-check`, etc.) and zero emojis. | **PASS** |

---

## Proposed Changes by Component

### 1. Portal User Interface (`src/portal/templates/`)

#### [MODIFY] [`assessor_unit.html`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/portal/templates/assessor_unit.html)
- Remove AI suggestion container (lines 280-315).
- Remove fallback alert boxes ("No suggestion produced by AI prefill", "No automated pre-fill available...").
- Remove "Use AI Suggestion" button (`.btn-ai-fill`) and client-side JavaScript handler.
- Retain clean scoring criteria (What, Why, Criteria for Yes/No), previous human submission summary box, and submission form.

#### [MODIFY] [`admin_project_detail.html`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/portal/templates/admin_project_detail.html)
- Refactor 3-column status grid (`grid-3`) into a clean 2-column status grid (`grid-2`):
  - Column 1: `Assessor Declarations` (Role A / Role B completion status).
  - Column 2: `Assessor A/B Discrepancy` (Status badge, persistent discrepancy table).
- Remove "AI Assessment Run" status card.
- Remove "Trigger AI Assessment" form and button from the actions toolbar.

---

### 2. Portal Backend Routes (`src/portal/`)

#### [DELETE] [`src/portal/live_prefill.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/portal/live_prefill.py)
- Remove file completely.

#### [MODIFY] [`admin.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/portal/admin.py)
- Remove `POST /admin/projects/{cycle_id}/units/{portal_id}/assess` endpoint.
- In `_build_unit_rows`, remove `st = job_status(...)`, `row["run_in_progress"]`, and `row["prefill_summary"]`.
- In `upload_msq_pdf`, remove `match_msq_links` and `insert_prefill_candidate` loops (save MSQ document only).

#### [MODIFY] [`assessor.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/portal/assessor.py)
- In `assessor_unit`, remove `r.latest_prefill` query and `prefill_dict` (`row.ai`) construction.
- In `submit_answer`, remove `ai_suggested_answer` and `ai_suggestion_accepted` from `HumanAssessorSubmission` instantiation and `insert_human_submission`.

#### [MODIFY] [`seed.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/portal/seed.py)
- Remove calls to `latest_prefill`.
- Instantiate `HumanAssessorSubmission` directly with `answer`, `evidence_url`, and `notes` without AI flags.

---

### 3. Shared Persistence & Domain Entities (`src/shared/`)

#### [MODIFY] [`schema.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/shared/persistence/schema.py)
- Remove `prefills` and `prefill_candidates` from active `CREATE TABLE` DDL.
- Remove `ai_suggested_answer` and `ai_suggestion_accepted` columns from `CREATE TABLE human_submissions`.
- In `init_db()`, execute `DROP TABLE IF EXISTS prefill_candidates` and `DROP TABLE IF EXISTS prefills`.

#### [MODIFY] [`entities.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/shared/state/entities.py)
- In `HumanAssessorSubmission`, remove `ai_suggested_answer` and `ai_suggestion_accepted` fields.

#### [MODIFY] [`repositories.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/shared/persistence/repositories.py)
- Update `insert_human_submission`, `latest_human_submission`, and `list_human_submissions` SQL queries to align with the updated `human_submissions` table schema.

---

### 4. API Runner Decoupling (`src/api/`)

#### [MODIFY] [`runner.py`](file:///c:/Users/Nithin/Desktop/RightAgents/UN-POC/src/api/runner.py)
- Decouple from `portal.live_prefill` (or remove obsolete background runner reference).

---

## Verification Plan

### Automated Tests
```bash
# Run UI quality tests (Zero Emoji, Contrast, Jinja2 rendering)
pytest tests/unit/test_ui_quality_checks.py -v

# Run human assessor completion, discrepancy, and joint answer tests
pytest tests/unit/test_assessor_completion.py tests/unit/test_portal_discrepancy.py tests/unit/test_joint_answers.py -v

# Run full unit suite
pytest tests/unit -v
```

### Manual Verification
1. Run `python src/portal/seed.py` and start server with `python src/cli.py serve`.
2. Inspect Assessor view (`/assessor/2026-test/portal_dk?role=A`) to ensure clean questionnaire rendering without AI elements.
3. Submit answers as Assessor A and B, complete assessments, and verify discrepancy detection & Reconciliation Workspace work seamlessly.
4. Inspect Admin view (`/admin/projects/2026-test`) to ensure clean 2-column status layout.
