# Implementation Plan: Prefilled Questionnaire Blank-Field Fallback

**Feature Directory**: `specs/004-blank-field-fallback`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-16
**Status**: Phase 1 complete — design artifacts generated
**Branch**: `main` (see Notes)

## Summary

Every blocking condition the pipeline already recognizes — a login wall, an unreachable portal, unverifiable evidence, no usable URL, an unsupported/declined language, or unresolved assessor disagreement — already routes a question–portal unit to one of two terminal blocked states (`ESCALATED`, `UNASSESSABLE`) and already persists the full context of why (`escalate()` in `orchestration/scheduler.py` stores `escalation_reason` plus a rich context dict on every blocked unit, for both states). This feature does not add new detection or new capture. It closes three real gaps between what the pipeline already records and what the reviewer and the export currently show:

1. **`UNASSESSABLE` is invisible as blocked** in both the review view (`review/query.py`) and the portal-unlock status (`review/unlock.py`) — only `ESCALATED` is checked today, so a no-usable-URL question silently shows no answer and no reason.
2. **The reason shown is a raw enum string**, not a human-readable tag (`Escalated: unresolved_disagreement`), and a blank field's proposed answer renders as the literal text `None`.
3. **A reviewer's answer to a blocked question never reaches the export** — nothing today reads the recorded `AssessorDecision` back into the unit's delivered status, and (a related, adjacent bug) the export's existing lookup for *any* human decision is dead code (`hasattr(repo, "get_assessor_decision")`, a method that doesn't exist).

The design threads all three fixes through **existing, already-durable data** — no new persisted entity, no schema migration, and (deliberately) no change to the unit state machine's transition table, which spec 001's `assert_exhaustive_terminal_coverage` test guards as exactly three terminal states with zero outgoing edges. Closing gap 3 is done by widening the *read-time* definition of "delivered" (state == `DELIVERED`, or blocked-with-a-recorded-decision) rather than by adding a fourth exit from a terminal state.

**Primary technical challenge**: this is a determinism problem, not a capability problem. `/speckit-clarify` fixed the reason tag as one canonical template per condition, exhaustive over `EscalationReason` — so the actual engineering work is: (a) one small, statically-testable lookup table; (b) two narrow "escalated" → "blocked" widenings in existing read paths; (c) one read-time inclusion-rule change in the exporter that must not disturb any of its seven existing invariants (E1–E7) or its `provenance` semantics.

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / runtime** | Python 3.11+, unchanged | existing `pyproject.toml` |
| **New module** | `shared/state/reason_tags.py` — pure function, no I/O | [research.md](./research.md) R1; [contracts/reason-tags.md](./contracts/reason-tags.md) |
| **Modified modules** | `review/query.py`, `review/unlock.py`, `review/web/templates/question.html`, `review/web/templates/questions.html`, `review/web/detail.py`, `export/writer.py`, `export/invariants.py` | [research.md](./research.md) R2, R5, R6, R7; [data-model.md](./data-model.md) |
| **Unchanged (deliberately)** | `shared/state/unit_state.py`, `shared/state/entities.py`, `shared/persistence/schema.py`, `review/escalations.py`, `review/web/app.py` route structure | [research.md](./research.md) R3 |
| **New configuration** | None — the reason-tag templates are code, not tunables (spec's own Assumptions: this feature doesn't touch retry/attempt limits) | spec.md Assumptions |
| **Persistence** | None new — every field is already on `units.data`, `AssessorAgentRun`, `AdjudicationResult`, `ValidationResult`, `EvidenceArtifact` | [research.md](./research.md) R4 |
| **Review surface** | Existing FastAPI + Jinja2 server-rendered app, WCAG 2.1 AA pattern reused (`<details>/<summary>`) | [contracts/review-surface-delta.md](./contracts/review-surface-delta.md) |
| **Export format** | Existing NDJSON + exclusion-report JSON, additive field only (`reason_tag`) | [contracts/export-schema-delta.md](./contracts/export-schema-delta.md) |
| **Testing** | `pytest`; new `tests/unit/test_reason_tags.py` and `tests/unit/test_blank_field_fallback.py`; extends `tests/unit/test_phase9_export.py` | [quickstart.md](./quickstart.md) |
| **Target scale** | No change — same unit count, same call frequency; this is a read/presentation-path feature | n/a |

**No unresolved NEEDS CLARIFICATION.** The `/speckit-clarify` session (2026-08-16) resolved the three spec-level ambiguities (fixed-template wording, export gains the tag additively, no dedicated filter/sort UI). This plan's Phase 0 research resolved the remaining *implementation* unknowns — see [research.md](./research.md) R1–R7, all decided with no open items carried forward.

### Where this fits relative to spec 001 and spec 003

- **Spec 001** (`FR-043`, `FR-043a`–`FR-043c`, `FR-101`–`FR-106`) already establishes the per-portal review-unlock mechanism and the export's delivered/excluded split this feature extends. Nothing in spec 001's own requirements is contradicted — `FR-043b` ("escalated questions appear... marked as such") is what this feature actually *finishes* implementing correctly (it was previously true for `ESCALATED` only, not `UNASSESSABLE`).
- **Spec 003** is unrelated in surface (language *detection*, not language-block *presentation*) but its `LanguageDecision.resolution_manner` field (`"explicit"` vs `"window_expired"`) is exactly what this feature's `LANGUAGE_DECLINED` reason-tag sub-case reads (research R1, data-model.md's template table) — reused unchanged, no new field.

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md` (same as spec 001's and spec 003's plans). As those plans established, the design is gated against the spec's own non-negotiables and this codebase's own tested invariants in its absence.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **No silent resolution** (spec 001 FR-007/FR-033/FR-082/FR-109, restated here as FR-BF-002) | A blocked unit never gets a forced/guessed answer | The Approve action is not rendered when there is no system-proposed answer (research R7); the only way a blocked question gets an answer is a reviewer explicitly supplying one, recorded as a new `AssessorDecision` | PASS |
| **Exactly three terminal states, zero outgoing edges** (spec 001 SC-009) | `unit_state.py`'s transition table is a tested invariant this feature must not weaken | Not modified at all (research R3); "delivered" for export/review purposes is a read-time derived predicate, never a stored state mutation | PASS |
| **Auditability** (spec 001 FR-059–FR-062) | Every delivered answer must be reconstructable from append-only records | The blocked-unit answer path reuses `AssessorDecision` (already append-only, already actor+timestamp attributed) unchanged; no new mutable record introduced | PASS |
| **Reason-tag determinism** (this feature's own FR-BF-006) | Same condition → same wording, always | `reason_tag()` is a pure function over a static table; exhaustiveness and determinism are directly unit-testable (quickstart Scenario 3) | PASS |
| **Configuration externalized** (spec 001 FR-072–FR-075, precedent) | No literal operational constant hidden in code where it should be tunable | N/A here by design — the spec's own Assumptions section places reason-tag wording and coverage outside "operational parameters," since it is presentation text keyed to a fixed, already-configured enumeration, not a threshold or limit | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

This feature's diff touches no new top-level module and adds exactly one new file plus two new test files.

```
src/
├── shared/
│   └── state/
│       └── reason_tags.py          # NEW — ReasonTag, reason_tag() (contracts/reason-tags.md)
│                                    #   pure, no I/O; keyed on EscalationReason
│
├── review/
│   ├── query.py                    # MODIFIED — blocked-detection widened to ESCALATED|UNASSESSABLE (R2);
│   │                                #   + reason_tag, attempt_history fields; agent_positions spans all
│   │                                #   rounds when blocked (data-model.md)
│   ├── unlock.py                   # MODIFIED — escalated_question_ids covers UNASSESSABLE too (R2)
│   └── web/
│       ├── detail.py                # MODIFIED — + render_attempt_history_html() alongside existing
│       │                             #   render_agent_detail_html()
│       └── templates/
│           ├── question.html        # MODIFIED — reason_tag text, blank (not "None") answer display,
│           │                         #   Approve hidden when no system-proposed answer (R7)
│           └── questions.html       # MODIFIED — blocked badge covers UNASSESSABLE too
│
└── export/
    ├── writer.py                    # MODIFIED — + reason_tag in exclusion items; delivered-record
    │                                 #   eligibility gains blocked-with-decision path; fixes the dead
    │                                 #   hasattr(repo, "get_assessor_decision") lookup (R3)
    └── invariants.py                # MODIFIED — VALID_EXCLUSION_REASONS gains "language_not_supported",
                                      #   asserted equal to {r.value for r in EscalationReason} (R5)

tests/
└── unit/
    ├── test_reason_tags.py          # NEW — exhaustiveness + determinism over EscalationReason
    ├── test_blank_field_fallback.py # NEW — review-view coverage, attempt history, unlock badges
    └── test_phase9_export.py        # MODIFIED — + blocked-unit delivery, + language_not_supported export
```

**What is explicitly NOT touched, and why that boundary matters:**

- `shared/state/unit_state.py` — the transition table and `assert_exhaustive_terminal_coverage`. This is the single highest-blast-radius file in the codebase for this feature to have touched, and it does not need to (research R3).
- `shared/state/entities.py` — no new enum member, no new dataclass field. `EscalationReason` already has every value this feature names.
- `orchestration/scheduler.py` and the three retry loops (`orchestration/routers/retry_loops.py`) — this feature does not change *when* or *how many times* the pipeline retries before declaring a unit blocked (spec's own Out of Scope); it only changes what happens to the record afterward.
- `review/escalations.py` — the coordinator-facing escalation-queue disposition flow (FR-049) is a separate, already-working mechanism. This feature's resolution path is the per-question review screen's Edit action, not the queue.
- `review/web/app.py`'s route structure — same endpoints (`/approve`, `/edit`, `/reject`), conditionally rendered rather than restructured; no new route.

## Phase 0 — Research

Complete. See [research.md](./research.md). Seven decisions recorded, each with rationale and alternatives considered:

| # | Decision |
|---|---|
| R1 | Reason Tag as a pure lookup table (`shared/state/reason_tags.py`), not generated text |
| R2 | "Blocked" is state-set membership (`ESCALATED` ∪ `UNASSESSABLE`), not a string comparison to `"escalated"` |
| R3 | A blocked unit's human-supplied answer reaches export via a read-time eligibility rule, without touching the unit state machine |
| R4 | No new persistence — Attempt History and Evidence are read from records that already exist, widened where the current query is too narrow |
| R5 | The Reason Tag table also closes the `language_not_supported` export-invariant gap |
| R6 | Review-surface presentation changes stay inside existing rendering modules (`detail.py`, the two templates) |
| R7 | Reviewer action on a blocked question is Edit only — Approve is not rendered, since there is nothing to approve |

## Phase 1 — Design & Contracts

Complete.

- **[data-model.md](./data-model.md)** — no new persisted entities; the new `ReasonTag` value type and its template table, the modified `QuestionReviewView`/`AttemptHistoryView`/`PortalReviewStatus` shapes, and the modified export inclusion rule, each with its validation rule.
- **[contracts/](./contracts/)**
  - [reason-tags.md](./contracts/reason-tags.md) — the `reason_tag()` function contract: inputs, determinism and exhaustiveness guarantees, the language-decision sub-case.
  - [export-schema-delta.md](./contracts/export-schema-delta.md) — the additive `reason_tag` exclusion-report field, the `VALID_EXCLUSION_REASONS` fix, and the second delivered-record eligibility path — stated as a delta against spec 001's `export-schema.md`.
  - [review-surface-delta.md](./contracts/review-surface-delta.md) — the `build_question_review()`/`portal_review_status()` behavior changes and the template/action changes — stated as a delta against spec 001's FR-043 family.
- **[quickstart.md](./quickstart.md)** — seven runnable validation scenarios (one seed-data extension + six test/manual scenarios), mapped to the spec's three user stories plus the two adjacent bugs this feature closes.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **The dead `hasattr(repo, "get_assessor_decision")` fix changes existing export output for already-`DELIVERED` units**, not just blocked ones | Any cycle previously exported with human edits/overrides silently reported `provenance: "system_proposed"`; fixing the method name means those same units will now correctly show `human_edited`/`human_overridden` on re-export. This is a *correctness fix*, but it changes output for data outside this feature's own scope. | Called out explicitly in [data-model.md](./data-model.md) and [research.md](./research.md) R3 as an adjacent, necessarily-bundled fix rather than a silent side effect; `tasks.md` should sequence it as its own reviewable unit within this feature so it isn't buried inside the blocked-unit change. No prior export output is mutated retroactively — only future exports are affected. |
| **Widening `agent_positions` to every round for a blocked unit** could be a larger payload on the review screen for a unit with many adjudication retries | Slower page render / more scrolling for a heavily-retried disagreement case (adjudication retry limit defaults to 2 per spec 001, so bounded in practice) | Presented behind the existing `<details>/<summary>` disclosure pattern (research R6), collapsed by default — same accessibility-friendly pattern already used for per-agent breakdown, so the cost is paid only when a reviewer opens it |
| **Reason-tag wording is a fixed template, decided now, but not yet reviewed by actual Assessors** | If the eight-or-so canonical sentences read poorly to a real reviewer, changing wording later is cheap (research R1: derived on read, never persisted) but the *English UX judgment* itself carries some risk of needing a follow-up copy pass | Explicitly scoped in [contracts/reason-tags.md](./contracts/reason-tags.md) as not-yet-final copy — "minor copy wording may be refined during implementation" — while the shape (canonical, deterministic, exhaustive) is fixed by `/speckit-clarify` and not at risk |
| **`review/query.py` and `review/unlock.py` have no dedicated existing test coverage today** | Both files being modified are currently untested (`tests/` has no `test_query.py` or `test_unlock.py`), so regressions in the *unmodified* parts of their behavior wouldn't be caught by a pre-existing safety net | `tests/unit/test_blank_field_fallback.py` is scoped to cover both files' full current behavior (not just the new blocked-unit paths) as part of this feature, closing the gap rather than adding untested code to untested code |

## Notes

- **Branch**: work continues on `main`, matching spec 001's and spec 003's plans — no `before_plan` git hook is configured (`.specify/extensions.yml` does not exist).
- **Graphify skipped.** Installed (`graphify`, via `anaconda3`) but not run: this feature's affected surface — one new file, six modified files, all identified by direct code reading during Phase 0 — is small enough that a repo-wide structural map would not have surfaced anything the targeted reads didn't, matching spec 003's plan precedent for the same call.
- **No setup script found** (`.specify/scripts/` does not exist in this repo), so this plan was produced by reading `FEATURE_SPEC` and the source tree directly rather than via the scripted `check_prerequisites.py` path the command template assumes.

## Post-Design Constitution Re-check

Re-evaluated after data-model.md and contracts/ were written. All five gates from the initial Constitution Check still PASS; one is worth calling out as verified rather than merely assumed:

- **Exactly three terminal states, zero outgoing edges** was checked against the actual `_ALLOWED` transition table in `shared/state/unit_state.py`, not assumed from the spec's description — confirmed `ESCALATED` and `UNASSESSABLE` both map to `set()` (no outgoing transitions) today, and no edit anywhere in this plan's Project Structure touches that file. The design's read-time eligibility rule (R3) was chosen specifically because it requires zero changes here, not adapted to avoid a constraint discovered later.

One design consequence worth recording: **R3 and R5 interact through `export/writer.py`.** Both land in the same function (`export_cycle_answers`), in the same loop over `(portal, question)` pairs — R3 adds a second branch to *when* a record is delivered, R5 fixes what `VALID_EXCLUSION_REASONS` accepts for records that remain excluded. Because both changes are additive to existing branches (an extra `or` condition; an extra frozenset member) rather than restructuring the loop, they can be implemented and tested independently in `tasks.md` without one blocking the other — but both should land before `tests/unit/test_phase9_export.py` is extended, since a test asserting Scenario 4 (blocked-unit delivery) against a fixture that also contains a `LANGUAGE_NOT_SUPPORTED` unit would otherwise fail on the unrelated Scenario 5 gap.
