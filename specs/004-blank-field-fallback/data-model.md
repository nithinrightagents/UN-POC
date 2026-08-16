# Phase 1 Data Model: Prefilled Questionnaire Blank-Field Fallback

**Feature Directory**: `specs/004-blank-field-fallback`
**Spec**: [spec.md](./spec.md) · **Research**: [research.md](./research.md)

## No new persisted entities, no schema migration

Every field this feature needs is already captured by spec 001's entities (`shared/state/entities.py`) and already durable (research.md R4). This feature adds one new pure value type and modifies how three existing read paths interpret existing data. Nothing in `shared/persistence/schema.py` changes.

## New: `ReasonTag` (value type, not a stored entity)

Produced on read by `shared/state/reason_tags.py`; never persisted — it is always re-derived from the unit's stored `escalation_reason` and context, so a future wording change applies retroactively to every past unit without a data migration.

| Field | Type | Notes |
|---|---|---|
| `text` | `str` | Always begins `"Left blank: "` (FR-BF-005). One of exactly `len(EscalationReason)` possible template outputs, per condition, per FR-BF-006. |
| `condition` | `EscalationReason` | The blocking condition the tag names. Carried alongside the rendered text so callers (e.g. the export exclusion report) can still access the raw machine code (FR-BF-015) without re-parsing the sentence. |

**Template table** (the canonical mapping FR-BF-006 requires; final wording is an implementation/tasks-phase detail, this fixes the *shape*):

| `EscalationReason` | Template | Placeholders filled from |
|---|---|---|
| `REQUIRES_AUTHENTICATED_ACCESS` | `Left blank: Login authentication barrier observed` | — |
| `UNRESOLVED_DISAGREEMENT` | `Left blank: Unresolved AI disagreement after retry limit` | — |
| `LANGUAGE_NOT_SUPPORTED` | `Left blank: Unsupported language '{language}' detected` | `context["detected_language"]` |
| `LANGUAGE_DECLINED` | `Left blank: Reviewer declined to proceed in unsupported language '{language}'` | `LanguageDecision.detected_language` (explicit decline) |
| *(language decision window expiry)* | `Left blank: Language decision window expired without a response` | — (`LanguageDecision.resolution_manner == "window_expired"`, FR-BF-006 edge case) |
| `UNREACHABLE_PORTAL` | `Left blank: Portal unreachable after {attempts} attempts` | attempt count recorded at the FR-071 bounded-attempt point |
| `UNVERIFIABLE_TARGET` | `Left blank: Evidence could not be independently verified` | — |
| `NO_USABLE_URL` | `Left blank: No usable URL could be resolved for this question` | — |

**Validation rule**: `reason_tag()` MUST have exactly one template per `EscalationReason` member (tested by iterating the enum — see quickstart.md Scenario 3) plus the one sub-case for language-decision expiry vs. explicit decline, which share `LANGUAGE_DECLINED` but read `resolution_manner` to pick wording (FR-BF-006's edge case: "the wording distinguishes an explicit decline from an expired response window").

## Modified: `QuestionReviewView` (`review/query.py`)

| Field | Change | Reason |
|---|---|---|
| `escalated: bool` | Renamed in meaning (not necessarily in name) to cover both `ESCALATED` and `UNASSESSABLE` — i.e. "blocked", not "escalated specifically" | R2 |
| `escalation_reason: str \| None` | Unchanged (raw code, kept for FR-BF-015's "existing code stays") | — |
| *(new)* `reason_tag: ReasonTag \| None` | Populated whenever `escalated`/blocked is true | FR-BF-005, FR-BF-006 |
| `delivered_answer: object` | Unchanged shape; for a blocked unit with no `AssessorDecision` yet, remains `None` — the template layer is what turns that into a blank field rather than the literal word "None" (R6) | FR-BF-004 |
| `agent_positions: list[AgentPositionView]` | Widened to include every round, not just the round the latest adjudication used, when the unit is blocked | R4, FR-BF-009 |
| *(new)* `attempt_history: AttemptHistoryView` | See below | FR-BF-008, FR-BF-009 |

### New: `AttemptHistoryView` (`review/query.py`, alongside `AgentPositionView`)

| Field | Type | Source |
|---|---|---|
| `resolution_attempts` | `list[dict]` (source, order, returned URL, usable, rejection_reason) | `unit["resolution_history"]` (already stored by `escalate()`) |
| `reachability_attempts` | `int \| None` | recorded at the FR-071 bounded-attempt point for `UNREACHABLE_PORTAL` |
| `verification_attempts` | `int \| None` | `ValidationResult.verification_attempts` |
| `retry_counts` | `dict` (`confidence_retry_count`, `validation_retry_count`, `adjudication_retry_count`) per agent | `AssessorAgentRun` fields already on each run |
| `points_of_disagreement` | `list[str]` | `AdjudicationResult.flag_reason` / the addenda recorded across retry rounds |
| `has_any_evidence` | `bool` | drives FR-BF-010's explicit "no evidence" state — `False` exactly when no `EvidenceArtifact` was ever captured for this unit |

**Validation rule**: `attempt_history.has_any_evidence == False` MUST always render the explicit "no evidence exists" message (FR-BF-010) rather than an empty evidence section — this is the one behavior in `review/web/evidence.py` that must not silently degrade to "nothing shown."

## Modified: `PortalReviewStatus` (`review/unlock.py`)

| Field | Change | Reason |
|---|---|---|
| `escalated_question_ids` | Now populated for both `ESCALATED` and `UNASSESSABLE` units (R2) | FR-BF-003, so `questions.html`'s badge covers every blocked question, not just `ESCALATED` ones |
| `unlocked` / `terminal_count` | Unchanged — `UNASSESSABLE` was already counted as terminal; only the *labeling* was incomplete | — |

## Modified: export exclusion-report item (`export/writer.py`)

| Field | Change | Reason |
|---|---|---|
| `reason` | Unchanged — existing machine-readable code, kept verbatim | FR-BF-015 ("without changing or removing the existing code") |
| *(new)* `reason_tag` | The same `ReasonTag.text` a reviewer would see, added alongside `reason` | FR-BF-015 |

## Modified: export inclusion rule (`export/writer.py`)

A question–portal unit is now eligible for the delivered-answer NDJSON (not the exclusion report) when **either**:

1. `unit.state == DELIVERED` (unchanged, existing behavior), **or**
2. `unit.state` is blocked (`ESCALATED` or `UNASSESSABLE`) **and** `repo.latest_assessor_decision(session, question_id, portal_id)` returns a record (R3).

**Adjacent existing-code note**: `export/writer.py` today gates this same lookup behind `hasattr(repo, "get_assessor_decision")` — a method that does not exist on `Repository` (the real method is `latest_assessor_decision`, already used correctly by `review/query.py`). That `hasattr` guard is always `False`, so today's export *never* picks up a human decision for any unit, blocked or delivered — every exported record silently reports `provenance: "system_proposed"` regardless of what a reviewer actually did. Implementing case 2 above means touching this exact line; the dead `hasattr` check is corrected to call `latest_assessor_decision` directly as part of the same edit, since leaving it broken for `DELIVERED` units while fixing it only for blocked ones would be inconsistent within one function.

In case 2, `provenance` is `human_edited` or `human_overridden` per the existing mapping in `review/actions.py` — never `system_proposed`, since a blocked unit has no system-proposed answer by construction (FR-BF-002).

**Validation rule** (extends export invariant E1): a delivered record produced via case 2 MUST still satisfy every existing per-record invariant (E1–E3) unchanged; the only new source of a `delivered_answer: true` record is an additional *condition* for eligibility, not a new record shape.

## Modified: `export/invariants.py::VALID_EXCLUSION_REASONS`

Extended to include `"language_not_supported"` (R5), and — to prevent the two lists drifting again — asserted in a test to equal `{r.value for r in EscalationReason}` (the same enumeration `reason_tags.py` is keyed on) rather than remaining a hand-maintained literal set.

## Explicitly unchanged

- `shared/state/entities.py` — no field added, no enum member added. `EscalationReason` already has every value this feature needs.
- `shared/state/unit_state.py` — the transition table and `assert_exhaustive_terminal_coverage` are untouched (R3). Still exactly three terminal states, zero outgoing edges from any of them.
- `shared/persistence/schema.py` — no new table, no new column. The `units.data` JSON blob already carries everything `reason_tag()` and `AttemptHistoryView` need.
- `review/escalations.py` (the escalation-queue disposition flow, FR-049) — a separate, already-working mechanism for *coordinator-level* case disposition. This feature's blank-field resolution path is the per-question review screen (`review/web/app.py`'s `/edit` endpoint), not the escalation queue; the two remain independent, matching the spec's Assumptions section (portal-level/queue-level cases are out of scope here).
