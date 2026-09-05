# Specification Quality Checklist: Unit-Level Assessor Assignment

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-05
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

## Validation Notes

### Iteration 1 (2026-09-05) — initial draft

Restated "dummy DB" in business terms as seeded demonstration data; ordered the selection constraints so conflicts were testable; added migration of existing project-level assignments, which had been left unaddressed.

### Iteration 2 (2026-09-05) — over-broad, corrected in iteration 3

Wrongly permitted projects holding a mixture of country and city units, reasoning from what the code allows (`unit_type` is an independent per-unit form field in the portal admin path) rather than from the survey model. Corrected by the user: **a project is national or city, never both.** The same iteration added a staffing dashboard, roster CRUD, and an approval gate that had not been asked for.

### Iteration 3 (2026-09-05) — rescoped

Cut from 388 lines / 57 FRs to 290 / 46: mixed-type projects forbidden, approval gate removed, roster lifecycle management removed, staffing dashboard removed. Reductions recorded in Out of Scope so they read as decisions rather than omissions.

### Iteration 4 (2026-09-05) — `/speckit-clarify`, model corrected

Clarification established that **the assessor database already records which assessors cover which units, and the portal only ingests that mapping.** The portal makes no selection at all. This invalidated a substantial part of iteration 3, which had specified a selection algorithm the feature does not need.

Removed as moot:

- The entire selection rule set — language matching, regional matching, capacity limits, workload balancing, determinism of selection (the former D5 and FR-AA-005 through FR-AA-011).
- Success criteria measuring load spread and capacity adherence.
- Assumptions defining language fit, region derivation, and load counting. Responsibility for pairing suitability now sits with the source database (A7).
- The `Assessor` entity's capacity and availability fields, which existed only to drive selection. Descriptive details remain, explicitly barred from influencing assignment (FR-DB-006).

Added in their place:

- Ingestion semantics: setup-time pre-ingestion rather than a running sync (D5, FR-IN-001), applied when a unit comes into existence (FR-IN-003), never overwriting an administrator's assignment (FR-IN-010, SC-006).
- Source-data validation: same person in both roles, unknown assessor reference, single-role entry, and uncovered unit each leave the unit visibly unstaffed with a reason (FR-IN-005 through FR-IN-009), covered by User Story 4.
- Mapping keyed by unit identity rather than by project (D4, FR-DB-002), with assignments on one project's unit independent of another project's unit of the same identity (FR-UA-011).
- SC-004 and SC-013, asserting that the platform substitutes nobody and that swapping demonstration data for real data changes only *who* is assigned.

**Two gaps found during this pass are now moot and need no further action**: the country reference data has no region field (`un_member_states.json` carries only `code`, `name`, `most_populous_city`), and assessor identity was split between project-level emails and unrelated submission `actor_id` strings. The first disappeared with region-based selection; the second is settled by A1 — identity is the stable identifier on the ingested record.

**Still live for planning, not a spec defect**: `_blocked_if_locked` guards 16 admin routes off the project-level lock that D11 retires. What guards project edits afterwards is an implementation decision, deliberately left to `/speckit-plan`.

**Result**: 16/16 items passing, unchanged from iteration 3 — no checkbox changed state. 10 clarification points recorded in the spec's Clarifications section, 0 [NEEDS CLARIFICATION] markers. The Validation Notes above were rewritten (rather than left untouched) because iteration 3's notes described a selection model the spec no longer contains.

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`
