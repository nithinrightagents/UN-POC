# Specification Quality Checklist: Disagreement Labelling for Human Assessor Discrepancies

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-07
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

## Notes

- **All three clarifications resolved 2026-09-07**, each to the conservative option. The feature owner chose, in every case, the answer that keeps the label advisory and leaves the existing process untouched:
  1. Labels never divert a dispute away from the automatic reconciliation round — added FR-DL-047, and Out of Scope now excludes label-based diversion explicitly.
  2. Labels are not shown to assessors on any surface — added FR-DL-065, tightened A7.
  3. Notes stay optional and the resulting cost is measured — added FR-DL-074, rewrote the first Known Limitation to record this as an accepted risk with an observable metric rather than an open question.

- **The resolutions are mutually reinforcing.** Taken together they mean this feature adds no assessor-facing surface, no new process path, and no new mandatory input — its entire footprint is a set of read-only annotations on reviewer and administrator surfaces, plus one aggregate measure. That makes SC-002 (identical outcomes with labelling unavailable) straightforward to satisfy and to test, and it means the feature can be withdrawn without unwinding anything.

- **On "no implementation details"**: the Dependencies section names existing modules by path, following the convention established by the preceding specs in this repository. Functional Requirements, Success Criteria and Key Entities are free of implementation detail. This is a deliberate house-style exception, not a leak.

- **On measurability**: several success criteria (SC-001, SC-003, SC-005) are stated as verifiable capabilities rather than numeric thresholds, because the feature's outcome is what a reviewer can determine at a glance rather than a throughput or latency figure. Each is testable by observation against a constructed unit. SC-002, SC-004 and SC-009 are binary and admit no partial pass.

- **Clarify session, 2026-09-07 — five questions asked and integrated, all 16 items still passing.** The two structural answers were the last two:

  4. **Senior Reviewer and Administrator are distinct actors, scoped differently.** A Senior Reviewer is appointed to one project and signs it off; an Administrator sees every project. This produced FR-DL-066 (sign-off cannot depend on labelling state), FR-DL-067 (scope of each view) and FR-DL-075 (the ambiguity measure is per-project for one and cross-project for the other). A Known Limitation records that FR-DL-067 is presentational, since the platform models only the two assessor roles, and Out of Scope now excludes introducing authorisation — so the requirement cannot be misread as a mandate to build a permission model.
  5. **Labelling is one pass per project-unit, run once when that unit's submissions are complete.** This was answered by the feature owner replacing the question's premise rather than choosing among its options, and it simplified the spec materially. An event-driven design needed re-labelling machinery — fresh labels on amendment, re-eligibility after exhausted attempts, supersession, staleness arbitration. A single pass at a fixed point removes all of it: FR-DL-006/007/008 state the trigger, FR-DL-052/053/054/059 became prohibitions instead of procedures, and SC-004 now asserts a hard bound — a unit's model usage never exceeds its one pass, whatever happens to it afterwards.

- **The five answers converge on the same posture.** Advisory only, invisible to assessors, no mandatory input, no influence on sign-off, and a fixed one-pass cost per unit. The feature's entire footprint is a set of read-only annotations on two reviewer-side surfaces plus two aggregate measures, which is what makes SC-002 (identical outcomes with labelling unavailable) straightforward to satisfy, and what would make the feature withdrawable without unwinding anything.

- **One position is stated rather than mitigated**: assessor notes reach the external model provider verbatim (A9, Known Limitations). FR-DL-039 closes the set of content that may be sent, so the surface cannot widen without a change to this spec. This is recorded for OICT review rather than solved, on the grounds that the platform already sends portal content, questionnaire text and prefill research to the same provider through the same entry point.

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`.
