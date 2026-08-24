# Specification Quality Checklist: Automated Dynamic Discrepancy Detection and Reconciliation

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-24
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

**Status: PASSING — ready for `/speckit-plan`.**

## Validation Notes

**Iteration 1 (2026-08-24)** — one item failing: three open `[NEEDS CLARIFICATION]` markers covering threshold configuration scope, publication behaviour on persistent discrepancy, and joint-answer authorship. Each was retained rather than defaulted because it changed the shape of the work rather than a detail within it.

**Iteration 2 (2026-08-24)** — all items passing. The three questions were answered and written back into the Clarifications section; the spec was revised accordingly.

- **Threshold → per project, administrator-editable.** The process-wide value becomes the default a project inherits. Added FR-DR-060 through FR-DR-066 (per-project storage, inherited 5% default, in-portal editing with no restart, tolerance recorded per comparison, range validation, 0% honoured, change attribution) and User Story 7.

- **Persistent discrepancy → a Senior Reviewer decision, not an automatic outcome.** The answer given was neither of the two options offered: rather than hard-blocking or merely highlighting, the reviewer sees the unresolved discrepancy and chooses to send it back manually or to publish. This was a material correction and reshaped the feature's spine:
  - D3 was rewritten so the cap of one bounds *automatic* send-backs only, leaving the reviewer's authority uncapped.
  - A new **User Story 4** (P1) carries the reviewer's decision, including the case where they take no action — the unit must neither publish nor re-open by itself (FR-DR-038).
  - Added FR-DR-039 and FR-DR-055 through FR-DR-057 for the two dispositions, the attributed manual return with a stated reason, and the recorded decision to publish over a contested indicator.
  - Assumption A5 was added to state that publishing unresolved uses the *existing* precedence rule and marks the indicator contested — this feature makes that rule visible and attributable rather than introducing a new tie-break.

- **Joint answers → either assessor commits, binding both.** Added D5, revised FR-DR-020/022/024 and added FR-DR-026 so round completion does not require both assessors to act. Assumption A4 was revised to match, and an edge case was added for the peer who opens the workspace to find everything already settled.

- **Content quality — passing.** File paths appear only in the Dependencies section, where they record what already exists as grounding for scope. Requirements and success criteria name no technology and are stated as user- and process-level outcomes.

- **Scope boundedness — passing, and deliberately narrowed against the original request.** The "What already exists" subsection separates six already-working capabilities from six genuinely missing ones. The originating request listed the post-submission recomputation and the admin read-only computation as missing; both are already wired and running, on the portal path, the programmatic path, and the seed script. Scope was corrected rather than restating the request. Conversely the request under-described two things now in scope: the reviewer's send-back-or-publish decision, and the fact that the existing badge is two-state with a hard-coded "≤5%" label that will misreport any changed tolerance.

- **Testability — passing.** Every functional requirement is an observable MUST with at least one acceptance scenario or edge case exercising it. The badge, round-cap, blindness, and reviewer-decision requirements each carry a negative case as well as a positive one, including the do-nothing case in User Story 4 scenario 4.

## Notes

- One point is deliberately left open for `/speckit-plan` rather than the spec: FR-DR-057 requires the answer published for a still-contested indicator to follow "a stated rule". Assumption A5 fixes that to the existing precedence behaviour, which today falls back to Assessor A's answer as a best-effort placeholder. Whether that fallback remains acceptable once it is surfaced and attributed is a design question for planning, not a specification gap.
