# Technical Research: Removal of AI Prefill and AI Capabilities from Portal

**Feature Directory**: `specs/013-remove-portal-ai`  
**Date**: 2026-08-26  
**Status**: Complete

---

## Research Topics & Decisions

### R1. Scope of Code Removal & Architectural Boundaries

- **Problem**: The codebase contains AI-related logic across multiple layers (portal templates, portal route handlers, background worker `live_prefill.py`, REST API routes, core agent models). We needed to determine exactly where to draw the boundary of removal.
- **Decision**: **Portal-focused removal (Clarification Q1, Option A)**.
  - Remove all AI prefill UI components from portal templates (`assessor_unit.html`, `admin_project_detail.html`).
  - Remove the portal-side AI execution endpoint (`POST /admin/projects/{cycle_id}/units/{portal_id}/assess`).
  - Delete `src/portal/live_prefill.py`.
  - Decouple `src/api/runner.py` from `portal.live_prefill`.
  - Remove prefill query logic (`latest_prefill`) and prefill dictionary assembly from `src/portal/assessor.py`.
  - Remove AI suggestion acceptance tracking from portal assessor submissions.
  - Leave core agent packages in `src/agents/` and `src/orchestration/` intact for standalone headless/benchmarking scripts.
- **Rationale**: Fulfills the user's primary goal to remove AI capabilities from the portal, eliminating UI clutter, confirmation bias, and unauthenticated server load while avoiding destabilizing decoupled offline benchmark CLI tools.
- **Alternatives Considered**:
  - *Complete codebase AI purge*: Would break existing offline evaluation harnesses and require rewriting benchmark/diagnostic test suites.
  - *UI-only hiding*: Leaves dead routes and background workers reachable, risking accidental execution.

---

### R2. Database Schema Clean-up & Migration Strategy

- **Problem**: The SQLite database contains `prefills` and `prefill_candidates` tables, and `human_submissions` contains `ai_suggested_answer` and `ai_suggestion_accepted` columns.
- **Decision**: **Schema clean-up migration (Clarification Q2, Option B)**.
  - Update `src/shared/persistence/schema.py` so new database initializations do not create `prefills` or `prefill_candidates` tables.
  - Drop or omit `ai_suggested_answer` and `ai_suggestion_accepted` from `human_submissions` table schema.
  - Provide a schema migration / cleanup function `migrate_remove_prefill_schema(conn)` executed during `init_db` to safely drop obsolete tables and columns on existing SQLite files.
  - Update `HumanAssessorSubmission` dataclass in `src/shared/state/entities.py` and repository methods in `src/shared/persistence/repositories.py`.
- **Rationale**: Keeps the schema clean and eliminates dead data models, queries, and unused telemetry fields.
- **Alternatives Considered**:
  - *Non-destructive retention (leaving unused tables in schema)*: Retains dead SQL code and confuses maintainers about whether prefills are active.

---

### R3. Assessor Questionnaire UX & Layout Clean-up

- **Problem**: In `src/portal/templates/assessor_unit.html`, each indicator row had an elaborate AI suggestion container with confidence bars, justification quotes, resolver explanations, "Use AI Suggestion" buttons, and fallback alert boxes ("No suggestion produced by AI prefill", "No automated pre-fill available...").
- **Decision**: Remove all AI boxes and fallback alert banners completely.
  - Render a clean, distraction-free indicator card containing:
    1. Indicator header with title, code, and module/question class badge.
    2. Scoring criteria: "What is required", "Why it matters", and "Scoring Guidance (Criteria for Yes / No)".
    3. Previous submission summary box (if the active assessor already submitted this indicator previously).
    4. Clean submission form: Yes/No radio group, Evidence URL input (validated URL), Notes textarea, and Submit button.
- **Rationale**: Assessors can focus purely on evaluating official target websites against objective UN scoring rubrics without AI suggestion bias or distracting warning banners.
- **Alternatives Considered**:
  - *Displaying a generic "Manual Evaluation Mode" notice on each question*: Adds visual noise to all 204 indicators with zero informational value.

---

### R4. Admin Project Detail Page Layout Refactoring

- **Problem**: `src/portal/templates/admin_project_detail.html` had a 3-column status grid (`grid-3`) on each unit card: `[AI Assessment Run]`, `[Assessor Declarations]`, and `[Assessor A/B Discrepancy]`, plus an actions toolbar with "Trigger AI Assessment".
- **Decision**: **Clean 2-Column Grid (Clarification Q3, Option A)**.
  - Refactor the status grid into a 2-column grid (`grid-2`):
    - **Card 1: Assessor Declarations**: Role A completion state & indicator counts, Role B completion state & indicator counts.
    - **Card 2: Assessor A/B Discrepancy**: Live colored tolerance badge, threshold in force, and persistent discrepancy detail if applicable.
  - Remove "Trigger AI Assessment" form button from the actions toolbar.
  - Clean up `_build_unit_rows` in `src/portal/admin.py` to eliminate `job_status` AI execution calls and `prefill_summary` calculations.
- **Rationale**: Provides administrators with immediate, unambiguous visibility into human assessment progress and human consensus without AI run overhead.
- **Alternatives Considered**:
  - *Empty/disabled AI card*: Clutters the UI and implies broken functionality.

---

### R5. MSQ Upload Handling

- **Problem**: `upload_msq_pdf` in `src/portal/admin.py` parsed uploaded MSQ PDFs and ran `match_msq_links(text, questions)` to insert candidates into `prefill_candidates` table for the AI prefill pipeline.
- **Decision**: Simplify `upload_msq_pdf` to ingest and store the MSQ text and document in `msq_documents` repository for human assessor reference, while removing automated heuristic prefill candidate generation.
- **Rationale**: Preserves the value of uploaded MSQ documents as official country submission reference files without coupling them to obsolete prefill candidate tables.

---

### R6. Preservation of Human Discrepancy & Reconciliation Workspace

- **Problem**: Spec 012 introduced automated dynamic discrepancy detection between Assessor A and Assessor B, the Reconciliation Workspace (`assessor_reconcile.html`), and Senior Reviewer arbitration. We must verify that removing AI prefill does not break any part of Spec 012.
- **Decision**: Complete verification of `portal/discrepancy.py`, `portal/reconciliation.py`, and `portal/tolerance.py`.
  - Discrepancy comparison strictly measures `sub_a.answer` vs `sub_b.answer` and joint answers from `latest_joint_answer`.
  - Reconciliation Workspace displays human assessor A's notes vs human assessor B's notes.
  - None of Spec 012 depends on `Prefill` or AI runners.
- **Conclusion**: Human discrepancy detection and reconciliation remain 100% operational and intact.
