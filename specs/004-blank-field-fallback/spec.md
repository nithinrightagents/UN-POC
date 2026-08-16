# Feature Specification: Prefilled Questionnaire Blank-Field Fallback

**Feature Directory**: `specs/004-blank-field-fallback`
**Created**: 2026-08-16
**Status**: Draft
**Input**: Implement prefilled questionnaire blank-field fallback for escalated and unverified questions. When an assessment unit hits any escalation or blocking condition (such as an authentication/login wall, unreachable portal, unsupported language, or unresolved agent disagreement), the system must leave the answer field blank (null) in the prefilled questionnaire rather than forcing an answer or blocking the review. Each blank question must include an explicit human-readable reason tag (e.g., "Left blank: Login authentication barrier observed", "Left blank: Unresolved AI disagreement after retry limit", "Left blank: Unsupported language 'fr' detected") along with all captured evidence, URLs, and attempt history so the human reviewer can see why it was left blank and easily provide the final answer during manual review.

## Overview

A question–portal unit can hit a condition the automated pipeline cannot answer through on its own: the portal sits behind a login wall, the portal never responds, its content is in a language outside the supported set, or the independent AI assessors never converge on an answer even after retries. Today these units reach a terminal blocked state, but that state is not uniformly and legibly surfaced to the human reviewer at the point where they review a portal's questions — one blocked question risks either forcing a low-confidence guess into the field or leaving the reviewer unable to tell why a question has no answer.

This feature makes the blocked outcome a first-class, visible result: the answer field is left blank rather than guessed, the blank carries an explicit, plain-language reason describing exactly which condition caused it, and everything the pipeline already gathered before it got blocked — URLs visited, evidence captured, prior AI positions, and the record of what was attempted — travels with that blank field so the reviewer can supply the final answer without leaving the review screen or reconstructing the history themselves. Review of the rest of the portal's questions is never held up by one blocked question.

## Clarifications

### Session 2026-08-16

- Q: Should each blank-field Reason Tag be a fixed, canonical template per blocking condition, or freely composed text per instance? → A: Fixed, canonical template per blocking condition, with only the identifying detail (language code, attempt count, etc.) substituted in — deterministic and testable by exact match, not freely composed.
- Q: The answer export already reports a machine-readable exclusion code (e.g. `requires_authenticated_access`) for every non-delivered question — should this feature change that export? → A: Add the human-readable Reason Tag as an additional field alongside the existing raw exclusion code; the existing code is left unchanged so current export consumers are unaffected.
- Q: Does this feature need a dedicated filter/group-by-reason control in the reviewer UI, or is distinguishable wording enough on its own? → A: Distinguishable wording alone is sufficient; no dedicated filter/grouping control is required by this feature.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reviewer sees a blank field instead of a forced guess or a blocked screen (Priority: P1)

A reviewer opens a portal's pre-filled questionnaire. One of its questions hit a login wall and another never converged after the disagreement retry limit. Both appear in the set with their answer field empty and a short, specific reason instead of either a shaky forced answer or a missing/greyed-out row that stops the reviewer from proceeding.

**Why this priority**: This is the core behavior change. Without it, a blocked question either corrupts the delivered data with an unfounded answer or stalls the reviewer's ability to close out the rest of the portal — both outcomes this feature exists to remove.

**Independent Test**: Can be fully tested by seeding units in each blocking condition, opening the portal's review set, and confirming every blocked question shows a null answer and a reason string, while every other question on the same portal is reviewable normally.

**Acceptance Scenarios**:

1. **Given** a question–portal unit that reached a login-wall block, **When** the reviewer opens that portal's pre-filled set, **Then** the question is present with its answer field blank and a reason tag beginning "Left blank:" describing the login barrier.
2. **Given** a question–portal unit where the independent assessors never converged after the configured retry limit, **When** the reviewer opens the set, **Then** the question is present with its answer field blank and a reason tag describing the unresolved disagreement.
3. **Given** a portal with nine answerable questions and one blocked question, **When** the reviewer opens the portal's review set, **Then** all ten questions are visible and the nine answerable ones can be approved, edited, or overridden without the blocked one preventing it.
4. **Given** a question–portal unit for which no usable URL could ever be resolved, **When** the reviewer opens the set, **Then** the question still appears (rather than being silently dropped) with a blank answer and a reason describing that no URL was found.

---

### User Story 2 - Reviewer resolves a blank field using only what's on screen (Priority: P2)

Having seen why a question was left blank, the reviewer needs enough context to supply the real answer without opening another tool or log. The blank field is accompanied by every URL the pipeline visited for that question, any evidence already captured before the block occurred, the AI assessors' positions if any assessment ran, and a record of what was attempted and how many times.

**Why this priority**: A visible reason without the supporting detail still forces the reviewer to go hunting through logs or ask an engineer, which defeats the purpose of surfacing the block at all. This is what makes the blank field actionable rather than just informative.

**Independent Test**: Seed a blocked unit with partial pipeline activity (e.g., one AI assessor ran before the second assessor's disagreement escalated it, or three unreachable attempts were made before giving up), open its review screen, and confirm the URLs, evidence, positions, and attempt counts are all present without navigating away.

**Acceptance Scenarios**:

1. **Given** a unit escalated after unresolved disagreement, **When** the reviewer views the blank question, **Then** every AI assessor's answer, confidence, and justification from every round is shown, along with the specific points of disagreement.
2. **Given** a unit blocked after repeated unreachable-portal attempts, **When** the reviewer views the blank question, **Then** the number of attempts made and the resolved URL that was targeted are shown.
3. **Given** a unit blocked before any evidence could be captured (e.g., no usable URL was ever found), **When** the reviewer views the blank question, **Then** the screen explicitly states that no evidence exists rather than showing an empty or broken evidence section.
4. **Given** a unit blocked partway through, where one AI assessor produced a partial answer and evidence before the block occurred, **When** the reviewer views the blank question, **Then** that partial answer and evidence are shown as context, clearly marked as not the delivered answer.

---

### User Story 3 - Reviewer tells blocking conditions apart from the reason text alone (Priority: P3)

Reasons are specific to what happened, not a single generic "escalated" label: a login wall, an unreachable portal, an unsupported language (naming the language), and an unresolved disagreement each read differently. A reviewer scanning a portal's questions, or a coordinator scanning many portals, can tell which situation they're dealing with from the tag text alone.

**Why this priority**: Distinguishing the condition matters for triage (a batch of unsupported-language blanks calls for a translator; a batch of login-wall blanks calls for credentialed access) but the feature still delivers its core value (User Story 1) with a single generic reason. This refines that value rather than being required for it.

**Independent Test**: Seed one blocked unit for each distinct blocking condition the system already recognizes, and confirm each produces reason text that names its specific condition (and, where applicable, the specific detail such as the language code or attempt count) rather than a shared generic label.

**Acceptance Scenarios**:

1. **Given** two blocked units, one from a login wall and one from an unresolved disagreement, **When** their reason tags are compared, **Then** the wording clearly identifies which condition caused each one.
2. **Given** a unit blocked because the portal's detected language fell outside the supported set, **When** the reason tag is shown, **Then** it names the specific language detected.
3. **Given** a unit blocked because a human explicitly declined to proceed in an unsupported language versus one blocked because that decision window expired without a response, **When** the reason tags are compared, **Then** the wording distinguishes an explicit decline from an expired response window.

### Edge Cases

- A unit passes through more than one blocking condition before reaching its final terminal state (e.g., a transient unreachable attempt during URL resolution, later followed by unresolved disagreement during assessment): the reason tag reflects the condition that actually produced the terminal block, not an earlier condition that was subsequently worked around.
- A question is blocked on every portal it applies to versus blocked on only one portal in a cycle: each portal's review set shows its own independent reason; a widespread pattern is a triage observation for the reviewer/coordinator, not a different system behavior.
- The reviewer supplies a final answer for a blank field: it is captured through the same attribution mechanism (who, when) as any other reviewer decision, and the question is no longer presented as blank once answered.
- A portal's questions are entirely blocked units (e.g., the portal never resolves to any URL at all): the portal still becomes available for review once every question on it has reached a terminal state, exactly as a portal with a mix of answered and blocked questions would.

## Functional Requirements *(mandatory)*

#### Coverage

- **FR-BF-001**: The blank-field fallback MUST apply to every question–portal unit that reaches a blocking or escalation terminal outcome, including at minimum: an authentication/login barrier encountered, a portal that stays unreachable after the configured attempts, evidence that cannot be independently verified, no usable URL resolved for the question, a detected language outside the supported set (whether declined by a human or left undecided until the decision window expires), and assessor disagreement unresolved after the retry limit.
- **FR-BF-002**: The system MUST NOT substitute a forced, guessed, or default answer for a unit that hits any condition covered by FR-BF-001, regardless of how much partial evidence or how many partial AI positions exist for it.
- **FR-BF-003**: A blocked question MUST NOT prevent any other question on the same portal from becoming available for review once that other question independently reaches its own terminal state, and MUST NOT prevent the portal itself from becoming available for review once every one of its questions — blocked or answered — has reached a terminal state.

#### Blank value and reason tag

- **FR-BF-004**: A blocked question MUST appear in the portal's pre-filled review set with its answer field set to null/blank rather than omitted from the set.
- **FR-BF-005**: Every blank answer field MUST carry exactly one explicit, human-readable reason describing the condition that caused it, presented as a short tag beginning "Left blank:".
- **FR-BF-006**: The reason tag's wording MUST come from one fixed, canonical template per blocking condition (not freely composed per instance, and not a single shared generic label covering every condition), with only the identifying detail substituted in when the condition has one — for example, the detected language code for an unsupported-language block, or the number of attempts made for an unreachable-portal block. The same blocking condition MUST always produce the same reason tag wording, so tags are deterministic and comparable across questions and portals.
- **FR-BF-007**: When a unit is affected by more than one blocking condition over the course of its processing, the reason tag MUST describe the condition that produced the unit's final terminal state, not a condition that occurred earlier and was subsequently resolved without blocking the unit.

#### Evidence and attempt history

- **FR-BF-008**: A blank question's presentation MUST include every URL the pipeline visited or considered for that unit (including candidates that were rejected), and any evidence already captured before the block occurred.
- **FR-BF-009**: A blank question's presentation MUST include the full record of what was attempted before the block: link-resolution attempts and their outcomes, reachability/verification attempt counts, retry counts, and — for a disagreement block — every AI assessor's answer, confidence, and justification from every round together with the specific points of disagreement.
- **FR-BF-010**: When a blank question has no captured evidence at all (for example, because no usable URL was ever found), the presentation MUST state that explicitly rather than showing an empty or broken evidence section.
- **FR-BF-011**: Any partial AI-assessor answer that exists for a blocked unit MUST be shown to the reviewer as context and MUST be clearly distinguished from a delivered answer.

#### Reviewer resolution

- **FR-BF-012**: The reviewer MUST be able to supply the final answer for a blank question from the same screen that presents its reason, evidence, and attempt history, without navigating to a separate tool.
- **FR-BF-013**: A final answer the reviewer supplies for a previously blank question MUST be attributed to the acting person and timestamped, on the same terms as any other reviewer decision on a question.
- **FR-BF-014**: A question left blank and not yet answered by a reviewer MUST remain distinguishable, wherever delivered answers are reported or extracted downstream, from a question whose answer has been delivered.
- **FR-BF-015**: Wherever a blocked question's existing machine-readable exclusion code is already reported downstream (for example, in the answer export's exclusion report), that record MUST also carry the same human-readable Reason Tag as an additional field, without changing or removing the existing code.

### Key Entities

- **Blocking Condition**: The specific circumstance — login barrier, unreachable portal, unverifiable evidence, no usable URL, unsupported/declined/undecided language, or unresolved assessor disagreement — that caused a question–portal unit to reach a terminal blocked outcome rather than a delivered answer.
- **Reason Tag**: The explicit, human-readable statement of why an answer field was left blank, always naming the specific Blocking Condition and its identifying detail when one exists.
- **Attempt History**: The record, already gathered by the pipeline for a blocked unit, of what was tried before the block: URLs considered and their resolution outcome, reachability/verification attempts, retry counts, and — where assessment occurred — every AI assessor's position across every round.

## Success Criteria *(mandatory)*

- **SC-001**: 100% of question–portal units that reach a blocking or escalation terminal outcome appear in their portal's review set with a blank answer field and a reason tag — none are silently dropped from the set and none carry a forced or guessed answer.
- **SC-002**: A reviewer can identify why any given question was left blank, and what was already attempted, entirely from that question's own review screen, without consulting any other tool, log, or person.
- **SC-003**: Across a review set containing every recognized blocking condition, each condition's reason tag is distinguishable from every other condition's by its wording alone — a reviewer can tell which condition they're looking at just by reading the tag, with no separate filter, grouping control, or additional context needed.
- **SC-004**: A portal containing a mix of answered and blocked questions becomes reviewable, and its answered questions remain fully actionable (approve/edit/override), regardless of how many of its other questions are blocked.
- **SC-005**: Once a reviewer supplies a final answer for a previously blank question, it is no longer presented as blank and is reported downstream as a delivered answer with the reviewer's attribution.

## Assumptions

- "Prefilled questionnaire" refers to the per-portal review set an Assessor sees once every question on that portal has reached a terminal state (delivered or blocked) — the existing point at which a portal becomes available for human review. It is distinct from the downstream machine-readable export, which already excludes non-delivered answers and reports them with a machine-readable reason code through its own mechanism; this feature only extends that export's exclusion record with the same human-readable Reason Tag (FR-BF-015), it does not restructure it.
- The set of blocking conditions in FR-BF-001 is the complete set the system currently distinguishes. If a new kind of blocking condition is introduced by future work, giving it its own reason tag is part of that future change, not an open obligation of this feature.
- This feature does not change when or how many times the pipeline retries a unit before declaring it blocked — it changes what the reviewer sees once that terminal outcome is reached. Retry and attempt limits remain governed by existing configuration.
- A portal-level discrepancy flag (raised when two assessors' answers diverge broadly across a portal) is a distinct review case that does not leave any individual question's answer blank, since the individual questions involved already have delivered consensus answers; it is out of scope for this feature.

## Dependencies

- The existing terminal-state handling that already determines when a question–portal unit is blocked (login barrier, unreachable portal, unverifiable evidence, no usable URL, unsupported language, unresolved disagreement) and records the specific condition that caused it.
- The existing per-portal review surface that already withholds a portal from review until every one of its questions reaches a terminal state, and already presents evidence, URLs, and AI-assessor positions for answerable questions.
- The existing capture of URLs, evidence, and attempt/retry counts during assessment, which this feature surfaces for blocked units rather than newly collecting.
- The existing reviewer-decision and attribution mechanism, reused for the answer a reviewer supplies to a previously blank question.

## Out of Scope

- Automatically resolving, re-attempting, or answering a blocked unit beyond the pipeline's existing configured attempt and retry limits.
- Changing how many retries or attempts a unit gets before it is declared blocked.
- Changing the downstream export's existing machine-readable exclusion codes or its structure, beyond adding the human-readable Reason Tag alongside each existing code (FR-BF-015).
- Portal-level discrepancy case handling, which is a separate review mechanism that does not blank any individual question.
- Introducing new kinds of blocking conditions beyond the ones the system already recognizes.
- A dedicated filter, sort, or group-by-reason control in the reviewer UI; distinguishable tag wording alone satisfies the requirement to tell blocking conditions apart.
