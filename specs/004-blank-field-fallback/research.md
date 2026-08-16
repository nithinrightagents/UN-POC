# Phase 0 Research: Prefilled Questionnaire Blank-Field Fallback

**Feature Directory**: `specs/004-blank-field-fallback`
**Spec**: [spec.md](./spec.md)

No `NEEDS CLARIFICATION` markers remain in the spec — `/speckit-clarify` (2026-08-16) resolved the three user-facing ambiguities. This document instead resolves the *implementation* unknowns that only became visible once the existing pipeline and review-surface code were read: how the current system already behaves at each of the six blocking conditions, and where it falls short of FR-BF-001 through FR-BF-015.

## Grounding: what the pipeline already does

Read directly from `src/orchestration/scheduler.py`, `src/shared/state/unit_state.py`, `src/review/query.py`, `src/review/unlock.py`, `src/export/writer.py`, and `src/export/invariants.py`:

- Every blocking condition already goes through one function, `escalate(reason: EscalationReason, context: dict, to_state: UnitState = ESCALATED)`, which stores `escalation_reason` **and** the full `context` dict (resolution history, attempt counts, detected language, etc.) directly onto the unit's persisted `data` blob — for *both* terminal blocked states, `ESCALATED` and `UNASSESSABLE` (the `NO_USABLE_URL` case passes `to_state=UNASSESSABLE` but still runs through the same `escalate()` call). **The raw material for every Reason Tag and every piece of Attempt History already exists in the database today.** This feature is a presentation-and-consistency feature, not a new-capture feature.
- `review/query.py::build_question_review` only treats `unit_state == "escalated"` as blocked — `UNASSESSABLE` units are invisible as blocked in the review view (they'd show `delivered_answer=None` with `escalated=False` and no reason). Same bug, same root cause, in `review/unlock.py::portal_review_status`, which only appends to `escalated_question_ids` for `ESCALATED`, not `UNASSESSABLE`.
- `review/web/templates/question.html` renders the raw `escalation_reason` enum value verbatim (`Escalated: unresolved_disagreement`) — not a human-readable tag — and renders `Proposed answer: {{ view.delivered_answer }}`, which prints the literal string `None` for a blank field today.
- `export/invariants.py::VALID_EXCLUSION_REASONS` is missing `language_not_supported` even though `EscalationReason.LANGUAGE_NOT_SUPPORTED` is a real, reachable value (`scheduler.py` escalates with it directly from the per-unit language check). A cycle export containing one such unit would raise `ExportInvariantError` today — a latent bug this feature's exhaustiveness requirement (FR-BF-006) surfaces and fixes as a byproduct.
- There is currently **no path** by which a human answer for a blocked unit ever reaches the export as delivered: `review/actions.py` records a new `AssessorDecision`, but nothing reads that decision back into `unit.state`, and `export/writer.py` includes a record only when `unit.get("state") == UnitState.DELIVERED.value`. FR-BF-013/FR-BF-014/SC-005 require this to work; closing it is this feature's one genuine new-behavior requirement (see R3).
- A second, adjacent bug compounds the above: `export/writer.py` looks up the human decision via `hasattr(repo, "get_assessor_decision")` — a method name that does not exist on `Repository` (the real method, already used correctly by `review/query.py`, is `latest_assessor_decision`). The `hasattr` guard is therefore always `False`, so **no export today ever reflects a human edit or override, for any unit, blocked or normally delivered** — every record silently reports `provenance: "system_proposed"`. R3's fix touches this exact line for blocked units; correcting the method name at the same time (rather than leaving it broken for the `DELIVERED` path only) is in scope as the minimal consistent fix.

## R1: Reason Tag as a pure lookup table, not generated text

**Decision**: One new pure module, `shared/state/reason_tags.py`, holding a `dict[EscalationReason, str]` of canonical templates (Python `str.format`-style placeholders) plus a single `reason_tag(escalation_reason: str, context: dict) -> str` function that looks up the template and fills placeholders from the unit's already-stored context dict.

**Rationale**: `/speckit-clarify` fixed this as a spec-level decision (FR-BF-006: "one fixed, canonical template per blocking condition... deterministic and testable by exact match"). A lookup table is the direct implementation of that decision — it makes "does every condition have a tag" a static, exhaustively-testable property (iterate `EscalationReason`, assert every member has a table entry) rather than a runtime behavior that has to be sampled.

**Alternatives considered**:
- *Compose the string inline at each call site* (in `query.py`, in `export/writer.py`, in the escalate() closure) — rejected: three call sites would drift, and FR-BF-006's "same condition always produces the same wording" guarantee would depend on remembering to keep them in sync.
- *LLM-composed text* — explicitly rejected by the clarify session.

## R2: "Blocked" is a state-set membership check, not a string comparison to `"escalated"`

**Decision**: Everywhere the code currently asks "is this unit escalated?" by comparing to the literal string `"escalated"`, it instead asks "is this unit in a blocked terminal state?" — membership in `{UnitState.ESCALATED, UnitState.UNASSESSABLE}` (the two non-`DELIVERED` members of the existing `TERMINAL_UNIT_STATES` set already defined in `shared/state/entities.py`). Since `escalate()` already writes `escalation_reason` for both states, the presence of that field is a reliable secondary check.

**Rationale**: This is the direct fix for the `UNASSESSABLE`-is-invisible bug found in `query.py` and `unlock.py` above, and it is exactly what FR-BF-001 ("every question–portal unit that reaches a blocking or escalation terminal outcome... including... no usable URL resolved") requires. No new state or flag is introduced — `UNASSESSABLE` was already terminal and already carried a reason; it was just being read incorrectly.

**Alternatives considered**: Adding a new boolean `is_blocked` field to the unit's stored data at write time — rejected as redundant: `state` already carries this information; duplicating it invites the two to disagree.

## R3: A blocked unit's human-supplied answer reaches export without touching the unit state machine

**Decision**: `unit_state.py`'s transition table is **not** modified. `ESCALATED` and `UNASSESSABLE` remain terminal with zero outgoing transitions, exactly as `assert_exhaustive_terminal_coverage` (SC-009, spec 001) requires. Instead, "is this question's answer delivered" is redefined, at the two read sites that need it (`export/writer.py`, and `review/query.py`'s `delivered_answer` computation), as: **`unit.state == DELIVERED`, OR (`unit.state` is blocked AND a `AssessorDecision` exists for this question–portal–session)**. The existing `AssessorDecision` record (actor, timestamp, delivered answer) is the human-attribution mechanism FR-BF-013 requires, reused unchanged.

**Rationale**: The unit state machine's "exactly three terminal states, zero outgoing edges" property is a tested, load-bearing invariant from spec 001 (SC-009), independent of this feature. Mutating it to add a fourth exit (e.g. `ESCALATED → DELIVERED`) would touch the single most safety-critical module in the codebase for a feature that does not need to change the pipeline's own account of *why* it stopped — it only needs review and export to also recognize *that a human later supplied an answer anyway*. Keeping the unit's own state as the immutable record of "the pipeline blocked here for reason X" while deriving "but it does have a delivered answer now" from the presence of a decision record preserves both audit trails (FR-061, unaffected) and this feature's SC-005.

**Alternatives considered**:
- *Add a fourth terminal state* (e.g. `RESOLVED_BY_REVIEWER`) — rejected: multiplies the terminal-state count past the value `assert_exhaustive_terminal_coverage` and several existing tests hard-code as exactly three; broad blast radius for no behavioral gain over the read-time check.
- *Mutate `ESCALATED`/`UNASSESSABLE` units' `state` to `DELIVERED` on human decision* — rejected: would erase the recorded blocking reason from the unit's `state` field (though `escalation_reason` would remain in `data`), and would require exempting this one case from `unit_state.transition()`'s validation, defeating the point of having a single validated transition function.

## R4: No new persistence — Attempt History and Evidence are read from records that already exist

**Decision**: The review surface's presentation of Attempt History (FR-BF-009) and Evidence (FR-BF-008) is built entirely from existing repository reads, widened where the current query is too narrow:
- `repo.get_unit(...)`'s stored `data` blob already carries `resolution_history`, and (depending on which reason fired) `reported_languages`/`supported_languages`, `validated_run_count`/`total_run_count`, or the auth-boundary note — read directly, no new table.
- `repo.list_agent_runs(session_id, question_id, portal_id)` is called **without** the `round_number` filter `build_question_review` currently applies, so every round's positions are available for a disagreement block (today's code only fetches the *latest* adjudicated round).
- `repo.list_adjudication_results(...)` (already called) supplies the per-round `points_of_disagreement`/flag reasoning via `_describe_disagreement`'s recorded output on each `AdjudicationResult`.
- `ValidationResult.verification_attempts` (already persisted) supplies the reachability/verification attempt count for an `UNVERIFIABLE_TARGET` or `UNREACHABLE_PORTAL` block.

**Rationale**: Every one of these fields is already a persisted, append-only record per spec 001's audit-trail requirements (FR-059–FR-063); this feature's job is to read more of what's already there, not to capture anything new. This keeps the diff small and avoids any schema/migration risk.

**Alternatives considered**: A denormalized "blocked unit summary" table populated at escalation time — rejected: would duplicate data already in `units.data` and `agent_runs`/`adjudication_results`, with the usual dual-write consistency risk, for a read pattern (one question's history, viewed occasionally by a reviewer) that has no performance pressure behind it.

## R5: The Reason Tag table also closes the `language_not_supported` export-invariant gap

**Decision**: `export/invariants.py::VALID_EXCLUSION_REASONS` is derived from (or asserted equal to, via a test) the same `EscalationReason` enumeration `reason_tags.py` is keyed on, rather than being a separately hand-maintained `frozenset`. This adds the missing `"language_not_supported"` entry as a direct consequence of the exhaustiveness this feature already requires (FR-BF-001, FR-BF-006), rather than as an unrelated bug-fix commit.

**Rationale**: The gap is real and reachable today (`scheduler.py` can escalate with `LANGUAGE_NOT_SUPPORTED`, and export would then raise `ExportInvariantError` on that cycle) but is squarely inside this feature's own "every recognized blocking condition" requirement — fixing it separately would leave two hand-maintained lists of the same six-or-so reason codes to keep in sync.

**Alternatives considered**: Leave `VALID_EXCLUSION_REASONS` as its own list and add the missing entry by hand — rejected: reintroduces exactly the drift risk R1 already avoided for the tag templates.

## R6: Review-surface presentation changes stay inside the existing rendering modules

**Decision**: `review/web/templates/question.html` and `review/web/templates/questions.html` are modified in place (canonical tag instead of raw enum value; blank/em-dash instead of the literal `None`; the Approve action hidden when there is no system-proposed answer, since FR-BF-002 forbids ever submitting a null/forced answer and the existing `/approve` endpoint would otherwise happily deliver `None`). A new small renderer, `review/web/detail.py::render_attempt_history_html` (alongside the existing `render_agent_detail_html` in the same file), presents the Attempt History from R4. `review/web/evidence.py`'s existing "evidence missing" branch already covers FR-BF-010 (explicit "no evidence" state) and needs no change.

**Rationale**: Matches this codebase's established module boundaries — `detail.py` already owns "per-agent breakdown behind a `<details>` disclosure," which is exactly the shape Attempt History needs. No new top-level module, consistent with how spec 003's plan kept its diff inside existing files.

**Alternatives considered**: A new `review/web/blank_field.py` module — rejected: the two things it would contain (a reason-tag lookup and an attempt-history renderer) already have natural, smaller homes (`shared/state/reason_tags.py` and `review/web/detail.py` respectively); a new module would just be an empty wrapper.

## R7: Reviewer action available on a blocked question is Edit only, not Approve

**Decision**: When a question's unit is blocked (no system-proposed answer exists), the review screen shows only the **Edit** action (labeled to make clear the reviewer is supplying the first answer, not editing one) and, optionally, the existing Reject & Override form for cases where a reviewer wants to record why they're overriding what little partial signal exists. The **Approve** button — which today POSTs `view.system_proposed_answer` verbatim — is not rendered for a blocked question, since there is nothing to approve and doing so would submit `None` as the delivered answer, directly violating FR-BF-002.

**Rationale**: Reuses the existing `AssessorAction.EDIT` / `actions.edit()` path unchanged (system_proposed_answer=`None`, edited_answer=the reviewer's answer) rather than inventing a fourth action type; the resulting `AssessorDecision.provenance` is `human_edited`, which is already a valid, already-exported provenance value.

**Alternatives considered**: A new `AssessorAction.SUPPLY` variant for "there was nothing to approve or edit, this is a first answer" — rejected: `entities.py::AssessorAction` and `export/writer.py`'s provenance mapping are shared, tested surface from spec 001; `human_edited` already communicates "not the system's own answer" accurately enough that a fourth variant would add a distinction without a difference for any consumer identified in either spec.
