# Interface Contracts & Surface Specification: Portal Clean-up

**Feature Directory**: `specs/013-remove-portal-ai`  
**Date**: 2026-08-26  
**Status**: Complete

---

## 1. Portal Route Inventory & Endpoint Deltas

### Retired / Removed Endpoints

| Method | Path | Prior Purpose | Action |
|---|---|---|---|
| `POST` | `/admin/projects/{cycle_id}/units/{portal_id}/assess` | Dispatched automated multi-agent Vertex AI assessment job | **REMOVED** from `src/portal/admin.py` |

---

### Preserved & Cleaned Endpoints

| Method | Path | Role / Actor | Changes |
|---|---|---|---|
| `GET` | `/admin` | Admin | Preserved. Lists all projects/cycles. |
| `POST` | `/admin/projects` | Admin | Preserved. Creates project and target units. |
| `GET` | `/admin/projects/{cycle_id}` | Admin / Senior Reviewer | **Cleaned**: Unit rows render a 2-column grid (`Assessor Declarations` and `Assessor A/B Discrepancy`), removing AI Assessment Run card and Trigger AI Assessment button. |
| `POST` | `/admin/projects/{cycle_id}/units` | Admin | Preserved. Adds new country/city portal unit. |
| `POST` | `/admin/projects/{cycle_id}/questions` | Admin | Preserved. Adds custom indicator to questionnaire. |
| `POST` | `/admin/projects/{cycle_id}/units/{portal_id}/msq` | Admin | **Cleaned**: Ingests MSQ PDF for human reference, omitting heuristic AI candidate extraction. |
| `POST` | `/admin/projects/{cycle_id}/units/{portal_id}/publish` | Senior Reviewer | Preserved. Evaluates human readiness, joint answers, and publishes final score. |
| `POST` | `/admin/projects/{cycle_id}/tolerance` | Senior Reviewer | Preserved (Spec 012). Sets custom per-project discrepancy tolerance. |
| `GET` | `/assessor/{cycle_id}/{portal_id}` | Assessor (A or B) | **Cleaned**: Template context contains no `row.ai` dicts; renders clean scoring rubric and submission form. |
| `POST` | `/assessor/{cycle_id}/{portal_id}/question/{question_id}/submit` | Assessor (A or B) | **Cleaned**: Saves human Yes/No answer, evidence URL, notes; does not compute AI match telemetry. |
| `POST` | `/assessor/{cycle_id}/{portal_id}/complete` | Assessor (A or B) | Preserved. Validates all questions answered and records completion declaration. |
| `GET` | `/assessor/{cycle_id}/{portal_id}/reconcile` | Assessor (A or B) | Preserved (Spec 012). Reconciliation Workspace for disputed indicators. |
| `POST` | `/assessor/{cycle_id}/{portal_id}/reconcile/{question_id}/joint` | Assessor (A or B) | Preserved (Spec 012). Commits joint consensus answer with justification. |
| `GET` | `/public/{cycle_id}/{portal_id}` | Public | Preserved. Renders published unit scorecard. |

---

## 2. Template Surface Contracts

### `src/portal/templates/assessor_unit.html`

- **Removed Markup**:
  - All `<div class="ai-suggestion-box">`, `<button class="btn-ai-fill">`, and `#icon-sparkles` / `#icon-bot` elements.
  - Resolver characterization blocks and alternative position displays.
  - Alert boxes stating "No suggestion produced by AI prefill" or "No automated pre-fill available".
  - JavaScript event listener `document.querySelectorAll('.btn-ai-fill')`.
- **Rendered Question Structure**:
  1. Question Title, Number, and Module Badge (`question.question_class`).
  2. Indicator Description ("What is required", "Why it matters").
  3. Scoring Rubric ("Criteria for Yes", "Criteria for No").
  4. Previous Submission Box (`row.mine`): Shows active assessor's recorded answer, evidence link, and notes if present.
  5. Submission Form:
     - Radio group: `Yes` (`answer=true`) / `No` (`answer=false`).
     - Text input: `evidence_url` (placeholder: official portal URL or clean URL input).
     - Textarea: `notes` (findings, observations).
     - Submit button: `Save Finding`.

---

### `src/portal/templates/admin_project_detail.html`

- **Removed Markup**:
  - `<!-- AI Pre-fill Status -->` column in the status grid.
  - `<form .../units/{portal_id}/assess>` trigger button in the actions toolbar.
- **Refactored Unit Status Grid**:
  ```html
  <div class="grid-2" style="margin-bottom: 1.25rem;">
      <!-- Assessor A/B Completion Status -->
      <div class="status-card">
          <div class="status-title">Assessor Declarations</div>
          <div class="status-body">
              <div>Role A: {{ row.readiness.roles.A badge }}</div>
              <div>Role B: {{ row.readiness.roles.B badge }}</div>
          </div>
      </div>

      <!-- Discrepancy Status -->
      <div class="status-card">
          <div class="status-title">Assessor A/B Discrepancy</div>
          <div class="status-body">
              {{ row.badge_html | safe }}
          </div>
      </div>
  </div>
  ```
- **Refactored Actions Toolbar**:
  - MSQ Upload Form.
  - Role A / Role B questionnaire navigation buttons.
  - Senior Reviewer Publish button.
