# Feature Specification: Removal of AI Prefill and AI Capabilities from Portal

**Feature Directory**: `specs/013-remove-portal-ai`  
**Created**: 2026-08-26  
**Status**: Draft  
**Input**: "I want to remove the ai prefill or any ai capability from the portal and code remove whats necessary"

---

## Overview

The UN-POC assessment portal initially incorporated automated AI prefill generation—running automated web scrapers and multi-agent LLM pipelines to propose answers, confidence metrics, and justifications to human assessors. While intended as a time-saver, in practice AI suggestions introduced confirmation bias, cluttered the human evaluation workspace, required separate background job management on the admin dashboard, and added operational complexity to what is fundamentally an authoritative human audit process.

This feature removes all AI prefill suggestions, AI execution triggers, and AI background processing components from the portal user interface and its supporting portal backend routes. The portal transitions into a streamlined, 100% human-verified assessment platform:

1. **Human-Centric Assessor Workspace**: Assessors evaluate assigned indicators directly and independently through primary research and official portal examination. The assessor view presents only the indicator specification, scoring guidance, previous human submissions, and the clean input form (Yes/No, Evidence URL, Assessor Notes). All AI suggestion banners, AI confidence badges, AI resolver characterizations, and 1-click "Use AI Suggestion" buttons are eliminated.
2. **Streamlined Admin Project Management**: Administrators register projects, configure indicators, assign country/city portal URLs, upload Member State Questionnaire (MSQ) reference documents, track human assessor completion progress, and review discrepancy rates without AI execution triggers, AI run status cards, or prefill statistics.
3. **Portal Code Clean-up & Route Decoupling**: The portal backend code is cleaned up to remove portal-level AI job dispatch routes (`/admin/.../assess`), the portal background runner (`live_prefill.py`), and AI prefill query logic on assessor page loads. Human assessor submission handlers stop recording AI-matching telemetry.
4. **Preservation of Core Human Evaluation & Discrepancy Reconciliation**: Removing AI capabilities from the portal strictly preserves all human assessment workflows: independent blind assessment by Assessor A and Assessor B, completeness enforcement (mandatory Yes/No on every indicator), dynamic human-to-human discrepancy detection & Reconciliation Workspace (Spec 012), Senior Reviewer arbitration, and one-click scorecard publication.

---

## Decisions Taken

- **D1 — Complete visual and functional removal of AI from the portal.** No AI suggestions, AI confidence badges, AI rationales, or AI trigger buttons will be presented to human assessors or administrators anywhere in the portal UI.
- **D2 — Removal of portal-side AI execution endpoints.** The admin portal route for triggering AI assessment jobs (`POST /admin/projects/{cycle_id}/units/{portal_id}/assess`) and the portal-specific background runner (`src/portal/live_prefill.py`) are retired and removed from the portal surface.
- **D3 — MSQ upload preserved as reference documentation only.** Uploading MSQ PDF submissions remains supported in the portal for administrative record-keeping and assessor reference, but automated heuristic prefill candidate generation from MSQ text is removed from the portal upload handler.
- **D4 — Portal submission telemetry decoupled from AI.** When human assessors submit answers in the portal, `ai_suggested_answer` and `ai_suggestion_accepted` are no longer calculated or stored on new portal submissions.
- **D5 — Discrepancy reconciliation remains 100% human-driven.** Dynamic discrepancy calculation and the Reconciliation Workspace (Spec 012) compare **Assessor A vs Assessor B** (human-to-human divergence). This functionality contains no AI dependency and remains fully operational.
- **D6 — Schema clean-up migration.** Obsolete prefill database tables (`prefills`, `prefill_candidates`) and AI-related telemetry columns (`ai_suggested_answer`, `ai_suggestion_accepted`) in human submission records are dropped/cleaned up to maintain schema hygiene and prevent dead data accumulation.

---

## Clarifications

### Session 2026-08-26

- Q: What is the scope of code removal across portal vs headless API vs core agent packages? → A: Portal-focused removal. Remove all AI prefill UI components, portal-side AI routes (`/assess`), the portal worker (`live_prefill.py`), and submission AI telemetry from the portal layer, while leaving core agent packages and headless API endpoints intact for decoupled CLI or testing tools.
- Q: How should database schema and prefill tables be handled? → A: Schema clean-up migration. Apply a database migration to drop obsolete prefill tables (`prefills`, `prefill_candidates`) and remove AI tracking columns (`ai_suggested_answer`, `ai_suggestion_accepted`) from `human_submissions`.
- Q: How should the Admin Unit Status grid be structured once AI Assessment Run is removed? → A: Clean 2-column grid (`grid-2`). Refactor the 3-column status layout into a clean 2-column grid displaying **Assessor A/B Declarations** and **Assessor A/B Discrepancy**.
- Q: Does removing AI from the portal affect the headless REST API or standalone benchmarking tools? → A: This feature focuses on removing AI capabilities and prefill artifacts from the **portal** (UI, portal routes, portal templates, and portal submission handlers) and removing dead portal-specific AI execution code. Core headless agent libraries in `src/agents/` and CLI tools can remain decoupled or cleaned up as portal dependencies are severed.
- Q: How does an assessor verify indicators without AI prefill? → A: Assessors follow the standard UN evaluation protocol: examining the official target portal URL provided, consulting the uploaded MSQ document if available, and recording their own verified evidence URL and notes.
- Q: Will the "Use AI Suggestion" button or sparkles icon remain in any form? → A: No. All AI prefill action buttons, sparkle icons, bot icons, and associated client-side auto-fill JavaScript are completely removed from portal templates.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Human Assessor conducts assessment in a clean, unbiased interface (Priority: P1)

A human assessor opens a unit's questionnaire. Each indicator clearly displays the indicator title, question requirements, scoring guidance, and their own current submission (if previously saved). No AI suggestions, AI confidence meters, AI justifications, or AI auto-fill buttons appear. The assessor enters their finding (Yes or No), provides the verified official evidence URL, enters explanatory notes, and submits their assessment.

**Why this priority**: This is the primary user interaction of the portal. Removing AI bias and clutter ensures assessors evaluate portals objectively and efficiently.

**Independent Test**: Load the assessor questionnaire for an assigned unit. Verify that no indicator displays AI suggestion containers, confidence scores, bot icons, or auto-fill buttons. Submit answers and verify they are recorded accurately under the assessor's role without AI telemetry.

**Acceptance Scenarios**:

1. **Given** an assigned unit and cycle, **When** an assessor opens `/assessor/{cycle_id}/{portal_id}?role=A`, **Then** the page renders without any AI suggestion cards, AI confidence badges, or "No AI prefill available" alert banners.
2. **Given** an indicator row, **When** the assessor views the question details, **Then** they see the question title, what/why/how criteria, their own saved submission (if any), and the submission form.
3. **Given** an assessor filling in an answer, **When** they choose Yes or No and provide evidence and notes, **Then** their submission is recorded purely as human work without evaluating whether it matched any AI suggestion.
4. **Given** an indicator with previous submissions, **When** the assessor reviews the page, **Then** only their own previous submission summary is displayed in the summary box.

---

### User Story 2 - Administrator manages survey units without AI execution triggers or statuses (Priority: P1)

An administrator views the Project Detail page for a survey cycle. For each assigned country or city portal, the administrator sees the official portal link, assessor completion status (Role A and Role B), and live human discrepancy rates. There are no "Trigger AI Assessment" buttons, no "AI Assessment Run" cards, and no prefill breakdown badges.

**Why this priority**: Removes administrative cognitive load and accidental triggers of resource-intensive background AI pipelines from the portal management UI.

**Independent Test**: Load `/admin/projects/{cycle_id}` as an administrator. Verify that each unit card displays only official portal info, Assessor A/B declarations, discrepancy status, MSQ upload, and Senior Reviewer publication controls.

**Acceptance Scenarios**:

1. **Given** a survey cycle with registered units, **When** an administrator loads the project detail page, **Then** each unit card displays status for Assessor Declarations and Assessor A/B Discrepancy without an "AI Assessment Run" status box.
2. **Given** a unit card on the project detail page, **When** reviewing the actions toolbar, **Then** only MSQ PDF upload, Assessor A/B links, and Senior Reviewer Publish buttons are present (no "Trigger AI Assessment" button).
3. **Given** an administrator uploading an MSQ document, **When** the PDF is uploaded, **Then** the document is saved and recorded for the unit without attempting automated AI candidate link extraction.
4. **Given** any administrative action, **When** viewing the overall dashboard, **Then** no background AI runs are initiated or monitored.

---

### User Story 3 - Assessor completion and Senior Reviewer publication remain fully functional (Priority: P1)

Assessors A and B complete their evaluations across all indicators and submit their declarations of completion. If discrepancy exceeds tolerance, they settle differences in the Reconciliation Workspace. The Senior Reviewer inspects the verified human submissions and publishes the unit scorecard.

**Why this priority**: Ensures the core business value of the platform—authoritative, double-blind evaluation and verified publication—operates flawlessly without AI prefill dependencies.

**Independent Test**: Have Assessor A and Assessor B submit all indicators on a unit, declare completion, resolve any discrepancies, and verify that the Senior Reviewer can publish the final scorecard with accurate scoring.

**Acceptance Scenarios**:

1. **Given** an assessor who has answered all indicators, **When** they declare completion, **Then** their completion declaration is recorded and publication readiness updates accordingly.
2. **Given** a unit where Assessor A and Assessor B differ beyond tolerance, **When** both complete the questionnaire, **Then** the dynamic Reconciliation Workspace opens normally for human-to-human dispute settlement.
3. **Given** a unit meeting all human publication readiness criteria, **When** the Senior Reviewer clicks Publish, **Then** the scorecard is calculated and published successfully.

---

### User Story 4 - Codebase clean-up and retirement of obsolete portal AI modules (Priority: P2)

Developers and maintainers navigate a clean codebase where portal routers and templates have no dangling references to AI prefill runners, dead endpoints, or unused AI utility functions.

**Why this priority**: Eliminates dead code, reduces maintenance overhead, and ensures the portal architecture matches its stated human-verified purpose.

**Independent Test**: Inspect portal route definitions and templates. Verify that `live_prefill.py` is removed, the `/assess` portal route is removed, and all references to AI prefill in portal handlers are cleaned up.

**Acceptance Scenarios**:

1. **Given** the portal router package (`src/portal/`), **When** analyzing routes, **Then** no `/assess` route exists in `admin.py`.
2. **Given** the portal template package (`src/portal/templates/`), **When** inspecting `assessor_unit.html` and `admin_project_detail.html`, **Then** no AI prefill markup, styles, or scripts remain.
3. **Given** the portal codebase, **When** running portal test suites, **Then** all portal tests pass with 100% human-driven assertions.

---

## Edge Cases

- **Existing database with prefill rows**: When the portal connects to an existing database containing legacy `prefills` table records, the portal UI simply ignores them and renders clean human-only forms.
- **Unit with no submissions**: Renders a clean blank input form with indicator scoring guidance and no error or warning about missing AI prefills.
- **Rapid submission of indicators**: Assessors submit consecutive indicators via AJAX or standard form POST; responses return fast without performing AI prefill comparison overhead.
- **MSQ upload with corrupt PDF**: Handled gracefully with standard upload validation without triggering background link-matching exceptions.

---

## Functional Requirements *(mandatory)*

### Assessor Interface & Workflow

- **FR-RPAI-001**: The assessor unit view (`/assessor/{cycle_id}/{portal_id}`) MUST NOT render any AI suggested answer, AI confidence score, AI justification text, or AI resolver characterization.
- **FR-RPAI-002**: The assessor unit view MUST NOT render any 1-click "Use AI Suggestion" button or AI-related trigger element.
- **FR-RPAI-003**: The assessor unit view MUST NOT render any "No suggestion produced by AI prefill" or "No automated pre-fill available" alert banners.
- **FR-RPAI-004**: For each indicator, the assessor view MUST display only the indicator title, description/what/why, scoring guidance (criteria for Yes/No), previous human submission summary (if present for that assessor), and the human submission form.
- **FR-RPAI-005**: When an assessor submits an answer for an indicator, the portal submission handler MUST record the answer without computing or storing `ai_suggested_answer` or `ai_suggestion_accepted`.
- **FR-RPAI-006**: The assessor completion declaration flow MUST operate based solely on the count of human-answered indicators against the total question count.

### Admin Interface & Workflow

- **FR-RPAI-007**: The Admin Project Detail view (`/admin/projects/{cycle_id}`) MUST NOT display an "AI Assessment Run" status card, AI progress meter, or prefill summary badges (Suggested / No Suggestion / Reason breakdown).
- **FR-RPAI-008**: The Admin Project Detail view MUST NOT render a "Trigger AI Assessment" button or any form submitting to an AI assessment endpoint.
- **FR-RPAI-009**: The Admin Project Detail view unit status section MUST cleanly present **Assessor A/B Declarations** and **Assessor A/B Discrepancy** status.
- **FR-RPAI-010**: The Admin MSQ upload feature MUST store the uploaded MSQ document for reference without attempting automated AI candidate link extraction or candidate insertion.

### Portal Backend & Routes

- **FR-RPAI-011**: The portal admin router MUST NOT expose the `POST /admin/projects/{cycle_id}/units/{portal_id}/assess` endpoint.
- **FR-RPAI-012**: The portal assessor router (`src/portal/assessor.py`) MUST NOT query prefill tables or construct `row.ai` dictionaries when preparing template context for assessor views.
- **FR-RPAI-013**: The portal module `src/portal/live_prefill.py` MUST be removed from the portal package.
- **FR-RPAI-014**: The portal seed script (`src/portal/seed.py`) MUST seed human assessor evaluations directly without depending on prefill generation or storing AI acceptance flags.
- **FR-RPAI-015**: The database schema and entities MUST be migrated to remove `prefills` and `prefill_candidates` tables and remove `ai_suggested_answer` and `ai_suggestion_accepted` from `human_submissions`.

### Human Discrepancy & Publication Preservation

- **FR-RPAI-016**: Dynamic discrepancy rate calculation between Assessor A and Assessor B MUST remain fully functional and independent of any AI data.
- **FR-RPAI-017**: The Reconciliation Workspace (`/assessor/{cycle_id}/{portal_id}/reconcile`) and joint answer submission mechanism MUST remain fully functional.
- **FR-RPAI-018**: Publication readiness checks and Senior Reviewer publication actions MUST evaluate only human assessor completion, discrepancy tolerance, and joint arbitration records.
- **FR-RPAI-019**: Public scorecards and rankings views MUST render accurate scores computed from verified human submissions and settled joint answers.

---

## Success Criteria *(measurable, technology-agnostic)*

- **SC-001**: 100% of portal pages (Admin, Assessor, Reconciliation, Public) render without any AI suggestion widgets, AI badges, AI trigger buttons, or AI alert banners.
- **SC-002**: An assessor can navigate, evaluate, and submit all questions on a unit questionnaire with zero network calls or queries to AI prefill services.
- **SC-003**: Administrator project management screens load cleanly with 0 references to AI assessment runs or prefill counts.
- **SC-004**: Double-blind human assessment, completion declaration, human discrepancy detection, reconciliation workspace, and publication workflows achieve 100% test pass rate without AI dependencies.
- **SC-005**: Portal response time on assessor and project detail pages improves or remains instantaneous due to eliminating prefill lookup and formatting overhead.

---

## Key Entities

- **SurveyCycle**: Project/cycle definition containing questionnaire indicators, target units, and discrepancy tolerance threshold.
- **TargetPortal**: Country or municipal unit under evaluation with its official portal URL.
- **HumanAssessorSubmission**: Evaluation record containing the human assessor's answer (Yes/No), evidence URL, notes, timestamp, role (A or B), and actor ID.
- **AssessorCompletion**: Formal declaration submitted by an assessor indicating that all indicators for a unit have been reviewed and answered.
- **DiscrepancyCase & JointAnswer**: Record of human-to-human divergence between Assessor A and Assessor B, and any settled consensus answers agreed in the Reconciliation Workspace.
- **PublicationRecord**: Final published scorecard signed off by the Senior Reviewer.
