# Feature Specification: Automated Dynamic Discrepancy Detection and Reconciliation

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Created**: 2026-08-24
**Status**: Draft
**Input**: When both Assessor A and Assessor B have submitted answers for a unit, the system must automatically compute the discrepancy rate in real time and surface it dynamically in the portal — no manual eyeballing. Above the threshold it must open a Reconciliation Workspace showing only the conflicting indicators side by side, take a single unified joint answer with a justification, mark the escalation resolved, and route to Senior Reviewer sign-off. The Admin Project Detail view must show a live coloured discrepancy badge per unit. The threshold defaults to 5% but must be changeable. An assessment may be sent back to the assessors for reconciliation **at most once** — if a discrepancy persists after both assessors resubmit, it must be highlighted rather than sent back again.

## Overview

Two blind human assessors answer the same questionnaire for the same unit. Where they disagree beyond a tolerated rate, the UN process requires the disagreement to be worked out rather than silently averaged or arbitrarily resolved in one assessor's favour. Today the platform can *detect* that condition but it cannot *act* on it: the disagreement rate is computed and recorded, and it is shown as a number on an administrative screen, but no assessor is ever taken to a screen where the disagreement can actually be settled. The loop terminates in a queue entry that only a Senior Reviewer can discharge, which pushes every disagreement — including the trivially reconcilable ones — onto the single most expensive reviewer in the process.

This feature closes that loop. It adds the missing human-facing half of the discrepancy machinery: a **Reconciliation Workspace** where the two assessors, and only for the indicators they actually disagreed on, see their own answer beside their peer's and agree a single joint answer with a written justification. Everything they already agreed on stays settled and locked — reconciliation is never an invitation to re-open the whole questionnaire.

It also puts a hard bound on the loop. The platform sends an assessment back to the assessors **automatically at most once**. If the two of them still disagree beyond the threshold after that round, the platform stops sending it back on its own and instead marks the unit as a **persistent discrepancy** — visually distinct from a first-round flag — so a Senior Reviewer can see immediately that assessor-level reconciliation has been tried and has failed. From there the decision is a person's, not the system's: the Senior Reviewer looks at what was attempted and either **sends it back for another round deliberately** or **proceeds to publish** with the disagreement on the record. What is bounded is the machine's willingness to loop, not the reviewer's authority.

Finally it makes the tolerated rate a real setting rather than a constant. The 5% figure is the UN default, not a law of the process, and each project must be able to run to its own tolerance, changeable by the person who owns the project without a redeploy.

### What already exists, and what this feature actually adds

A significant part of the described behaviour is already built and running. Naming it precisely keeps this feature's scope honest and prevents rebuilding working machinery.

**Already in place (no work required):**

- The comparison engine itself — both the write path that records an audit case and queues an escalation, and the read-only path safe to call from display routes.
- Recomputation after every assessor submission, on both the portal submission path and the programmatic submission path, and in the seed script.
- The read-only computation being called on the Admin Project Detail page load, per unit, and passed to the template.
- An idempotency guard that prevents a resubmission leaving the same disagreement set from queuing a duplicate escalation.
- Arbitrated per-indicator answers being read back at publication time, so an arbitrated answer beats a raw Assessor-A-wins default.
- A configurable tolerance value with an environment-variable override, defaulting to 5%.

**Genuinely missing (this feature's scope):**

- **The Reconciliation Workspace** — no screen, no route, no template. This is the substance of the feature.
- **Joint answer submission by assessors** — today only a Senior Reviewer can record settled answers, through the escalation disposition screen. Assessors have no way to converge.
- **The one-round automatic cap and the persistent-discrepancy state** — no notion of reconciliation rounds exists at all, so nothing bounds the loop and nothing distinguishes "disagreed once" from "disagreed even after reconciliation".
- **The Senior Reviewer's send-back-or-publish decision** — a reviewer can dispose of an escalation today, but there is no way to hand a unit back to the assessors for another attempt, and no record of having chosen to publish over an unresolved disagreement.
- **A truthful, multi-state discrepancy badge** — the existing badge is two-state (flagged / not flagged), does not distinguish full consensus from a tolerated non-zero rate, and its label hard-codes "≤5%" so it will state the wrong tolerance the moment the threshold is changed.
- **Per-project threshold configurability** — the value is settable only as a process-wide environment variable, so it cannot differ between projects and cannot be changed by the person who owns the project.

## Decisions Taken

- **D1 — Reconciliation deliberately breaks blindness, and only after both assessors have committed.** Blindness between Assessor A and Assessor B is a core property of the assessment phase and is enforced by never reading the peer's answers while rendering a role's screen. The Reconciliation Workspace intentionally suspends that property, because a disagreement cannot be discussed without both positions being visible. It is therefore reachable only for a unit with an open reconciliation round, and only for the indicators in that round's disputed set. It never exposes the peer's answer for an indicator the two already agree on, and it is never reachable during the ordinary assessment phase. Because identity is not authenticated, this is enforced by limiting what the routes can return rather than by checking who is asking — see Known Limitations.
- **D2 — Consensual indicators are locked during reconciliation.** Only the disputed indicators are editable in the workspace. This is what makes reconciliation bounded and auditable: the joint answer set is exactly the disagreement set, so the record shows precisely what was contested and precisely what was agreed. Allowing free re-editing would make the disagreement set meaningless and could introduce *new* disagreements during a round intended to remove them.
- **D3 — Automatic send-back is capped at one; the Senior Reviewer's judgement is not capped.** The platform returns a unit to its assessors on its own exactly once. A unit still above threshold after that round enters a persistent-discrepancy state, distinct from a first-round flag on every surface that shows discrepancy. The system then takes no further action of its own: it neither loops nor silently accepts. The Senior Reviewer decides, and has two explicit choices — send it back for another reconciliation round, or publish with the unresolved disagreement recorded. Every manual send-back is a deliberate, attributed act, which is what distinguishes it from the automatic ping-pong the cap exists to prevent.
- **D4 — Reconciliation does not replace Senior Reviewer sign-off; it feeds it.** A successful joint reconciliation resolves the escalation and records the agreed answers as the settled answers for those indicators. The unit still proceeds to Senior Reviewer sign-off before publication, exactly as it does today. Reconciliation removes disagreement; it does not confer publication authority on assessors.
- **D5 — A joint answer is committed by whichever assessor submits it first, and it binds the pair.** The workspace takes one answer per disputed indicator, not one per assessor. The first submission settles that indicator and locks it; the peer sees it as agreed rather than being asked again. This matches "a single unified joint answer" and keeps the round completable when one assessor is slower than the other. It rests on the two having actually conferred, which the mandatory justification field records; the platform does not attempt to verify that a conversation happened.
- **D6 — Detection runs continuously, but reconciliation opens only at mutual completion.** The two are deliberately decoupled. The rate is recomputed on every submission and shown throughout, because a Senior Reviewer watching a project wants to see divergence forming. Opening a round is a different act: it takes both assessors off the questionnaire, and it spends the unit's single automatic attempt. Doing that on a partial comparison would be wrong twice over — the disputed set would be provisional, and a unit could burn its one round while an assessor still had most of the questionnaire in front of them. So the round waits for both completion declarations, which is the same signal publication readiness already depends on.

## Clarifications

### Session 2026-08-24

- Q: Who changes the discrepancy threshold, and at what scope? → A: **Per project, editable by a Senior Reviewer in the portal.** Each project stores its own tolerance and a Senior Reviewer can change it while the project is running. The existing process-wide value becomes the default a project inherits when it has not set one of its own, so two projects may legitimately run to different tolerances. See FR-DR-060–FR-DR-066.
- Q: When the one reconciliation round is exhausted and the discrepancy persists, may the unit still be published, or is publication hard-blocked? → A: **Neither — it becomes the Senior Reviewer's explicit decision.** The Senior Reviewer sees that the discrepancy was not resolved and chooses between sending the unit back to the assessors manually for another round, or publishing it with the unresolved disagreement on the record. Publication is therefore not blocked, but it is also never automatic: the persistent state must be actively dispositioned rather than passed over. See FR-DR-033–FR-DR-039 and FR-DR-055–FR-DR-057.
- Q: Does a joint answer require both assessors to act, or may either assessor commit it on behalf of the pair? → A: **Either assessor commits it, and it binds both.** The first joint answer submitted for a disputed indicator settles it and locks it; the peer sees it as agreed rather than being prompted again. The round completes once every disputed indicator carries a joint answer, regardless of which assessor supplied each one. See D5, FR-DR-020 and FR-DR-024.
- Q: When does a reconciliation round actually open for a flagged unit? → A: **Only once both assessors have declared their assessment complete.** One automatic round opens at that point and both assessors attempt it. If the discrepancy is resolved, it is resolved. If it is not, the Senior Reviewer decides whether to send another round. Recomputation and the badge continue to run on every submission throughout, so an above-tolerance rate is visible before completion — it simply opens nothing. See D6 and FR-DR-004, FR-DR-008, FR-DR-009.
- Q: What happens to the two assessor completion declarations when a reconciliation round opens? → A: **They stand untouched.** Reconciliation is a bounded amendment to an assessment that is already complete, not a reopening of it, so no assessor re-declares and publication readiness stays satisfied throughout. What gates sign-off during reconciliation is the round's own state, not the declarations. See FR-DR-058 and FR-DR-059.
- Q: Are "administrator" and "Senior Reviewer" one actor or two? → A: **One actor, called Senior Reviewer throughout.** The separate "administrator" term is dropped, and setting a project's tolerance becomes a Senior Reviewer capability alongside dispositioning a persistent discrepancy. There is no role model to enforce a split, and naming two actors would imply a separation of duties the platform does not provide. See A7 and Known Limitations.
- Q: Should the admin badge computation carry a performance requirement? → A: **No — deliberately deferred.** The feature sets no latency or scale target. The known cost is recorded as a limitation rather than a requirement: the badge is recomputed per unit on every page load and each computation walks every indicator, so cost grows with units × indicators. At current POC scale this is acceptable, and it will be revisited if it becomes slow rather than designed around now. See Known Limitations.
- Q: How is the blindness boundary enforced, given the portal has no authentication and role arrives as a request parameter? → A: **Structurally, and the gap is recorded rather than papered over.** Blindness becomes a property of what the routes can return — no route reads across roles outside an open round's disputed set — rather than a check on who is asking. The absence of identity verification is stated as a known limitation and deferred to a future authentication feature, so the spec does not promise enforcement the platform cannot deliver. See FR-DR-014, FR-DR-015, FR-DR-017, FR-DR-018 and Known Limitations.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A disagreement is detected and acted on without anyone looking for it (Priority: P1)

Assessor B saves the last of their answers for a unit. Assessor A finished earlier. Without anyone requesting a comparison, the platform compares every indicator both of them have answered, finds that they differ on more than the tolerated share, records the disagreement, and places the unit in the reconciliation queue. Both assessors, on their next visit to that unit, are taken to the Reconciliation Workspace rather than back to the ordinary questionnaire.

**Why this priority**: Automatic detection is the premise of the whole feature. Without it every other story requires someone to notice a number on an admin screen, which is exactly the manual eyeballing this feature removes.

**Independent Test**: Have two assessors answer the same unit with a controlled number of differing answers, one set below the tolerance and one above. Verify that the below-tolerance case produces no reconciliation and no queue entry, and the above-tolerance case produces both, with no user action other than the submissions themselves.

**Acceptance Scenarios**:

1. **Given** Assessor A has answered all indicators and Assessor B answers the final one, **When** the submission is saved, **Then** the disagreement rate over the commonly answered indicators is recomputed immediately and reflects that submission.
2. **Given** the recomputed rate exceeds the tolerated rate but at least one assessor has not declared completion, **When** recomputation completes, **Then** the disagreement is recorded and displayed, but no reconciliation round opens, no work item is queued, and neither assessor is routed away from the questionnaire.
3. **Given** the rate exceeds the tolerated rate, **When** the second assessor declares their assessment complete, **Then** the unit's one automatic reconciliation round opens, its work item is queued once, and both assessors are routed to the workspace.
4. **Given** the recomputed rate is at or below the tolerated rate, **When** the second assessor declares completion, **Then** the disagreement is recorded for audit but no reconciliation is opened and no work item is queued.
5. **Given** only one assessor has answered anything on the unit, **When** they submit, **Then** nothing is compared, nothing is flagged, and the unit reports that it is awaiting the second assessor.
6. **Given** a unit already has an open reconciliation for a given set of disputed indicators, **When** a further submission leaves that same set disputed, **Then** no second work item is created for the same set.

---

### User Story 2 - Two assessors settle their differences in a focused diff view (Priority: P1)

An assessor opens a unit that has been flagged. Instead of the full questionnaire they are shown only the indicators they and their peer answered differently. For each one they see the indicator, their own answer with their evidence and notes, and their peer's answer with theirs, side by side. They agree one answer for each disputed indicator and write why. Everything they already agreed on is shown as settled and cannot be edited.

**Why this priority**: This is the missing capability. Detection without a place to resolve simply moves the work to the Senior Reviewer.

**Independent Test**: Flag a unit with a known disagreement set, open the workspace as each role in turn, and verify the disputed set is exactly what is editable, that each role sees its own answers attributed to itself and its peer's attributed to the peer, and that agreed indicators are present but locked.

**Acceptance Scenarios**:

1. **Given** a flagged unit whose disagreement set is a strict subset of its indicators, **When** an assessor opens the Reconciliation Workspace, **Then** only that subset is presented as requiring a joint answer.
2. **Given** the workspace is open for Assessor A, **When** the disputed indicators are rendered, **Then** A's own answer is labelled as theirs and B's answer is labelled as the peer's, and the same holds with the roles exchanged for Assessor B.
3. **Given** an indicator both assessors answered identically, **When** the workspace is rendered, **Then** that indicator is not editable and is shown as already settled.
4. **Given** a disputed indicator, **When** a joint answer is submitted without a justification, **Then** the submission is rejected with a message naming what is missing, and no joint answer is recorded.
5. **Given** a unit that is not flagged, **When** the Reconciliation Workspace is requested for it, **Then** access is refused and the requester is returned to the ordinary assessment view.
6. **Given** any unit without an open reconciliation round, **When** its workspace is requested by anyone in any role, **Then** the request is refused.
7. **Given** an indicator the two assessors agreed on, **When** the workspace is requested in either role, **Then** no route returns the peer's answer for that indicator.

---

### User Story 3 - The system sends work back once, then stops and hands over (Priority: P1)

Both assessors work through the disputed indicators and submit joint answers, but they cannot agree on several of them and the rate remains above tolerance. The platform does not send the unit back a second time on its own. It marks the unit as a persistent discrepancy — clearly distinguished from a first-round flag everywhere discrepancy is shown — and leaves it for the Senior Reviewer with the record of what was attempted.

**Why this priority**: Without the cap the process can loop indefinitely between two assessors who will not converge, and there is no signal that assessor-level reconciliation has been exhausted.

**Independent Test**: Drive a unit through a full reconciliation round that leaves the rate above tolerance, and verify that no further reconciliation is opened by the system, that the unit's state is distinguishable from a first-round flag, and that the number of rounds consumed and who opened each is visible.

**Acceptance Scenarios**:

1. **Given** a flagged unit in its automatic reconciliation round, **When** joint answers bring the rate to or below tolerance, **Then** the reconciliation is closed as resolved and the unit proceeds toward Senior Reviewer sign-off.
2. **Given** a flagged unit in its automatic round, **When** the round completes with the rate still above tolerance, **Then** the unit enters the persistent-discrepancy state, the system opens no further round, and the assessors are not sent back automatically.
3. **Given** a unit in the persistent-discrepancy state, **When** an assessor opens it, **Then** they are not routed into a reconciliation workspace and are told the disagreement now sits with the Senior Reviewer.
4. **Given** a unit in the persistent-discrepancy state, **When** any surface displaying discrepancy renders it, **Then** it is visually and textually distinct from a unit flagged for the first time.
5. **Given** a unit whose reconciliation resolved successfully, **When** a later submission re-opens a disagreement above tolerance, **Then** the unit enters the persistent-discrepancy state directly, because its automatic round has been consumed.

---

### User Story 4 - The Senior Reviewer decides what happens to an unresolved disagreement (Priority: P1)

A Senior Reviewer opens a unit marked as a persistent discrepancy. They can see that reconciliation was attempted, which indicators are still contested, what each assessor answered, and what if anything the two agreed. They then make a call: send the unit back to the assessors for another round, giving a reason, or publish it with the unresolved disagreement recorded. The platform does neither on its own — it waits for that decision.

**Why this priority**: This is the other half of the cap. Bounding the automatic loop is only safe if a person can still override it, and leaving the unit in limbo would be worse than either outcome.

**Independent Test**: Take a unit into the persistent-discrepancy state, then exercise both branches: a manual send-back, verifying a new round opens and is attributed to the reviewer; and a publish, verifying the unit publishes with the disagreement recorded and nothing silently substituted.

**Acceptance Scenarios**:

1. **Given** a unit in the persistent-discrepancy state, **When** the Senior Reviewer views it, **Then** they see the still-contested indicators, both assessors' answers, any joint answers already agreed, and the fact that the automatic round has been used.
2. **Given** a unit in the persistent-discrepancy state, **When** the Senior Reviewer sends it back for another round, **Then** a new reconciliation round opens, the assessors are routed to the workspace again, and the round is recorded as manually opened by that reviewer with their stated reason.
3. **Given** a unit in the persistent-discrepancy state, **When** the Senior Reviewer chooses to publish, **Then** the unit publishes and the unresolved disagreement is recorded against it rather than being discarded.
4. **Given** a unit in the persistent-discrepancy state on which the Senior Reviewer has taken no action, **When** time passes with no further submissions, **Then** the unit neither publishes nor re-opens by itself, and it continues to appear as outstanding work.
5. **Given** a unit published with an unresolved disagreement, **When** an indicator that was still contested is published, **Then** the answer used is determined by a stated rule and the contested status is recorded, so no assessor's answer is presented as agreed when it was not.
6. **Given** a manually re-opened round, **When** it completes with the rate still above tolerance, **Then** the unit returns to the persistent-discrepancy state and the same decision is offered again, with the round count incremented.

---

### User Story 5 - A Senior Reviewer sees the true discrepancy position of every unit at a glance (Priority: P2)

A Senior Reviewer opens a project and sees, for every unit, the current disagreement rate as a coloured badge: green where the two assessors agree completely, amber where they differ but within tolerance, red where they differ beyond it. Where a unit's reconciliation round has been used up, the badge additionally says so. Nothing about viewing the page changes the data.

**Why this priority**: This is the surface that removes manual eyeballing at the project level, but it reports state rather than creating it, so it follows detection and reconciliation.

**Independent Test**: Construct units at 0%, within tolerance, above tolerance, above tolerance after reconciliation, and awaiting a second assessor, then load the project page and verify each renders its distinct state — and that repeated loads create no new records.

**Acceptance Scenarios**:

1. **Given** a unit where both assessors agree on every commonly answered indicator, **When** the project page renders, **Then** the unit shows a green full-consensus badge with a 0% rate.
2. **Given** a unit whose rate is above zero but within tolerance, **When** the project page renders, **Then** the unit shows an amber badge stating the rate and the tolerance actually in force.
3. **Given** a unit whose rate exceeds tolerance while at least one assessor is still working, **When** the project page renders, **Then** the unit shows a red badge stating the rate and that the assessment is still in progress — not that reconciliation is pending.
4. **Given** a unit whose rate exceeds tolerance and whose reconciliation round is open, **When** the project page renders, **Then** the unit shows a red badge stating the rate and that reconciliation is pending.
5. **Given** a unit in the persistent-discrepancy state, **When** the project page renders, **Then** the badge shows the red rate and additionally indicates that reconciliation has been exhausted.
6. **Given** any unit, **When** the project page is loaded repeatedly, **Then** no discrepancy record and no work item is created by those loads.
7. **Given** a project whose tolerance has been changed from the default, **When** any badge renders, **Then** the tolerance it names is the one in force for that project, never a hard-coded figure.
8. **Given** a unit only one assessor has answered, **When** the project page renders, **Then** the unit reports that it is awaiting the second assessment rather than showing a rate.

---

### User Story 6 - Agreed answers reach the Senior Reviewer as settled answers (Priority: P2)

Once the assessors have agreed a joint answer for every disputed indicator, the reconciliation work item is closed as resolved by joint review, the agreed answers are recorded as the settled answers for those indicators together with the justification and who agreed it, and the unit moves into Senior Reviewer sign-off. At publication the agreed answer is what is used — never one assessor's original answer.

**Why this priority**: Reconciliation is worthless if its output is discarded at publication, but it depends on the workspace existing first.

**Independent Test**: Reconcile a unit whose disputed indicators had A and B differing, then inspect the answer used at sign-off and publication for each of those indicators, verifying it is the jointly agreed value.

**Acceptance Scenarios**:

1. **Given** joint answers have been recorded for every disputed indicator, **When** the round closes, **Then** the reconciliation work item is marked resolved by joint review and is no longer outstanding.
2. **Given** a resolved reconciliation, **When** the unit's final answer for a previously disputed indicator is determined, **Then** the jointly agreed answer is used in preference to either assessor's original.
3. **Given** a resolved reconciliation, **When** the Senior Reviewer reviews the unit, **Then** the justification text and the identity of who agreed each joint answer are available to them.
4. **Given** a reconciliation that has been resolved, **When** it is viewed again, **Then** it cannot be silently re-resolved with different answers by a later action.
5. **Given** a unit both assessors have declared complete, **When** a reconciliation round opens, closes, or is re-opened on it, **Then** both completion declarations stand unchanged and neither assessor is asked to declare completion again.
6. **Given** a unit with an open reconciliation round, **When** sign-off is attempted for it, **Then** it is refused until the round closes as resolved, exhausted, or no longer required.

---

### User Story 7 - A project runs to a tolerance other than 5% (Priority: P2)

A project is set to a tolerance other than the 5% default. Every subsequent comparison, flag decision, badge, and displayed label for that project uses the new figure. Comparisons already recorded keep the tolerance they were judged under, so the audit trail stays truthful.

**Why this priority**: Explicitly required, and cheap once the value is read from a single place, but nothing else depends on it.

**Independent Test**: Change the tolerance, then verify that a rate between the old and new figures flags under one and not the other, and that previously recorded comparisons still report the tolerance they were judged under.

**Acceptance Scenarios**:

1. **Given** no tolerance has been set for a project, **When** any comparison is made, **Then** 5% is used.
2. **Given** the tolerance is changed, **When** a subsequent comparison is made, **Then** the new figure decides whether the unit is flagged.
3. **Given** the tolerance is changed, **When** any surface names the tolerance, **Then** it names the new figure.
4. **Given** a comparison recorded under a previous tolerance, **When** that record is read back, **Then** it still reports the tolerance that was in force when it was made.
5. **Given** an attempt to set a tolerance outside the range 0% to 100%, **When** it is submitted, **Then** it is rejected and the previous value stands.

---

### Edge Cases

- **No overlap yet.** Neither assessor has answered any indicator the other has. Nothing is compared; the unit reports that it is awaiting assessment rather than reporting 0%.
- **Partial overlap.** The two have answered different subsets. The rate is computed over the intersection only, and the badge makes clear the comparison is partial rather than implying a complete assessment.
- **A single indicator in common, and they differ.** The rate is 100% and the unit shows as above tolerance. This is correct but noisy early in an assessment; the display must show how many indicators were actually compared so a 100% over one indicator is not mistaken for a fully assessed catastrophe. No round opens, because neither assessor has declared completion.
- **The rate is above tolerance for most of the assessment, then falls below it by the end.** Nothing opens. The round is decided by the rate at mutual completion, not by the worst rate seen along the way — though the intermediate comparisons remain in the audit record.
- **One assessor declares completion and the other never does.** The rate is computed and displayed but no round ever opens, and the unit cannot reach sign-off. It appears as awaiting the second declaration rather than as a discrepancy problem.
- **An assessor withdraws or amends an answer after declaring completion.** The rate is recomputed. If this pushes a previously-within-tolerance unit above it, the automatic round opens at that point, provided the unit has not already consumed it.
- **An assessor changes an answer during an open reconciliation.** Recomputation reflects it, and the disputed set is recalculated. If this removes a disputed indicator, the joint answer for it is no longer required.
- **A new disagreement appears after a resolved reconciliation.** The automatic round is already spent, so the unit goes directly to persistent discrepancy rather than being sent back by the system.
- **Both assessors open the workspace at once and both submit a joint answer for the same indicator.** Exactly one joint answer stands for that indicator; the second submitter is told the answer was already agreed rather than silently overwriting it.
- **One assessor answers every disputed indicator before the other opens the workspace.** The round completes. The peer, on opening it, finds every indicator settled and nothing to do, which is a valid outcome of either-assessor-commits and must read as agreed rather than as an error.
- **A joint answer is submitted for an indicator not in the disputed set.** It is rejected.
- **A Senior Reviewer sends a unit back repeatedly.** Each return is a deliberate attributed act with a stated reason and increments the round count. Nothing caps it, because nothing automatic is happening, but the accumulating record makes a pattern of returns visible.
- **A Senior Reviewer sends a unit back after the assessors have already agreed everything.** There is no disputed set left to open a round over; the return is refused with that reason rather than opening an empty workspace.
- **A unit is published over an unresolved disagreement, and later someone asks what was published.** The contested indicators, the rule that chose the published answer, and the reviewer who decided are all on the record.
- **The tolerance is raised while a unit sits flagged.** On the next recomputation the unit may fall within tolerance; it is then no longer flagged, and its open reconciliation is closed as no longer required rather than left dangling.
- **The tolerance is lowered while units sit within tolerance.** Units that were previously fine may flag on their next recomputation. This is correct, but it must not retroactively rewrite comparisons already recorded under the old tolerance.
- **The tolerance is set to 0%.** Any disagreement at all flags the unit, and the amber band is empty. This is legitimate and must not be treated as unset.
- **An assessor never declares completion.** Discrepancy is still computed over what has been answered, but the unit cannot reach sign-off, exactly as today.

## Functional Requirements *(mandatory)*

#### Automatic detection

- **FR-DR-001**: Every assessor answer submission MUST trigger an immediate recomputation of the disagreement rate for that unit, with no user action required to request it.
- **FR-DR-002**: The disagreement rate MUST be computed over exactly the indicators both assessors have answered, and MUST report how many indicators that was.
- **FR-DR-003**: Where neither assessor has an answer for any indicator the other has answered, the system MUST report the unit as not yet comparable, and MUST NOT report a rate of 0%.
- **FR-DR-004**: A recomputation whose rate exceeds the tolerance in force MUST record the disagreement, the disputed indicator set, the rate, and the tolerance applied.
- **FR-DR-005**: A recomputation whose rate is at or below the tolerance MUST record the comparison for audit but MUST NOT open a reconciliation.
- **FR-DR-006**: A recomputation that leaves an already-open reconciliation's disputed set unchanged MUST NOT create a second work item for it.
- **FR-DR-007**: Displaying discrepancy MUST NOT create records of any kind; only a submission or an explicit administrative action may do so.
- **FR-DR-008**: While either assessor has not yet declared their assessment complete, an above-tolerance rate MUST NOT open a reconciliation round, MUST NOT queue a work item, and MUST NOT route any assessor away from the questionnaire. It MUST still be recorded and displayed.
- **FR-DR-009**: When the second assessor declares their assessment complete and the rate then exceeds the tolerance in force, the system MUST open the unit's one automatic reconciliation round, queuing its work item exactly once and routing both assessors to the workspace.

#### The Reconciliation Workspace

- **FR-DR-010**: A unit with an open reconciliation round MUST route both assessors to the Reconciliation Workspace instead of the ordinary questionnaire. A unit that is above tolerance but has no open round MUST NOT.
- **FR-DR-011**: The workspace MUST present only the disputed indicators as requiring a joint answer.
- **FR-DR-012**: Indicators on which the assessors already agree MUST be shown as settled and MUST NOT be editable within the workspace.
- **FR-DR-013**: For each disputed indicator the workspace MUST show, side by side, the viewing assessor's own answer and their peer's answer, each with its supporting evidence and notes, each attributed to its author.
- **FR-DR-014**: The workspace MUST be reachable only for a unit with an open reconciliation round. A request for any other unit MUST be refused, regardless of who makes it.
- **FR-DR-015**: Outside an open reconciliation round, no route MUST expose one assessor's answers to a request made in the other's role. Blindness is a property of what the routes are capable of returning, not of who is asking: no surface outside the workspace reads across roles at all.
- **FR-DR-016**: The workspace MUST state the tolerance in force, the current rate, how many indicators were compared, and that this is the unit's only reconciliation round.
- **FR-DR-017**: Within the workspace, the only peer answers exposed MUST be those for indicators in the disputed set that opened the round. No route MUST return the peer's answer for an agreed indicator, at any time.
- **FR-DR-018**: Identity and role arrive as request parameters and are not authenticated. The platform therefore MUST NOT claim to verify that a requester is the assessor they name, and requirements FR-DR-014, FR-DR-015 and FR-DR-017 MUST hold structurally — by limiting what any route can return — rather than by trusting a claimed identity. See Known Limitations.

#### Joint answers

- **FR-DR-020**: Each disputed indicator MUST accept exactly one joint answer for the pair, submitted by either assessor, and that answer MUST bind both.
- **FR-DR-021**: A joint answer MUST carry a written justification, and MUST be rejected if the justification is absent or empty.
- **FR-DR-022**: A joint answer MUST record which assessor submitted it and when.
- **FR-DR-023**: A joint answer for an indicator outside the disputed set MUST be rejected.
- **FR-DR-024**: Once a joint answer exists for an indicator, that indicator MUST be shown to the peer as agreed rather than presented for answering again, and a second submission for it MUST NOT silently overwrite the first. Where two submissions race, exactly one MUST stand and the other MUST be told the answer was already agreed.
- **FR-DR-025**: Joint answers MUST NOT overwrite either assessor's original submissions; the originals MUST remain readable for audit.
- **FR-DR-026**: A reconciliation round MUST be treated as complete once every indicator in the disputed set that opened it carries a joint answer, irrespective of which assessor supplied each one.

#### Round cap and persistence

- **FR-DR-030**: The system MUST return a unit to its assessors for reconciliation automatically at most once. The default and initial automatic cap is one round.
- **FR-DR-031**: The number of reconciliation rounds a unit has consumed, and whether each was opened automatically or by a Senior Reviewer, MUST be recorded and MUST be visible on the surfaces that report discrepancy.
- **FR-DR-032**: Where the rate is at or below tolerance at the end of a reconciliation round, the reconciliation MUST be closed as resolved.
- **FR-DR-033**: Where the rate still exceeds tolerance at the end of a round, the unit MUST enter the persistent-discrepancy state, and the system MUST NOT open a further round on its own.
- **FR-DR-034**: The persistent-discrepancy state MUST be distinguishable — visually and in text — from a first-time flag on every surface that reports discrepancy.
- **FR-DR-035**: A unit in the persistent-discrepancy state MUST NOT route assessors into a workspace of its own accord, and MUST tell them the disagreement now sits with the Senior Reviewer.
- **FR-DR-036**: A disagreement arising after a unit's automatic round has been consumed MUST place the unit directly into the persistent-discrepancy state.
- **FR-DR-037**: Where a tolerance change causes a flagged unit to fall within tolerance, its open reconciliation MUST be closed as no longer required rather than left open.
- **FR-DR-038**: A unit in the persistent-discrepancy state MUST remain in it, appearing as outstanding work, until a Senior Reviewer acts on it. It MUST NOT publish itself, re-open itself, or lapse.
- **FR-DR-039**: A manually re-opened round that again ends above tolerance MUST return the unit to the persistent-discrepancy state and offer the same decision again, with the round count incremented.

#### The discrepancy badge

- **FR-DR-040**: Every unit on the project detail view MUST display its current disagreement rate, computed at page load without writing anything.
- **FR-DR-041**: The badge MUST distinguish five states: full consensus at exactly 0%; within tolerance above 0%; above tolerance with the assessment still in progress; above tolerance with reconciliation open; and above tolerance with reconciliation exhausted.
- **FR-DR-042**: The badge MUST use green for full consensus, amber for within tolerance, and red for above tolerance, and MUST NOT rely on colour alone to convey the state.
- **FR-DR-043**: The badge MUST name the tolerance actually in force and MUST NOT display a hard-coded figure.
- **FR-DR-044**: A unit not yet comparable MUST show that it is awaiting the second assessment rather than a rate.
- **FR-DR-045**: The badge MUST show how many indicators were compared, so a high rate over a small overlap is not mistaken for a high rate over a full assessment.

#### Routing to Senior Reviewer sign-off

- **FR-DR-050**: A resolved reconciliation MUST close its work item as resolved by joint assessor review.
- **FR-DR-051**: Jointly agreed answers MUST be recorded as the settled answers for their indicators and MUST take precedence over either assessor's original answer wherever a single answer for the unit is determined.
- **FR-DR-052**: The Senior Reviewer MUST be able to see, for each previously disputed indicator, both original answers, the agreed answer where one exists, the justification, and who agreed it.
- **FR-DR-053**: Reconciliation MUST NOT grant assessors publication authority; a reconciled unit MUST still pass Senior Reviewer sign-off before publication.
- **FR-DR-054**: A work item already resolved MUST NOT be silently re-resolved with different answers by a later action.
- **FR-DR-055**: For a unit in the persistent-discrepancy state the Senior Reviewer MUST be offered exactly two dispositions: return it to the assessors for a further reconciliation round, or proceed to publish it with the disagreement unresolved.
- **FR-DR-056**: A Senior Reviewer's return MUST require a stated reason, MUST open a new reconciliation round attributed to that reviewer, and MUST route the assessors back into the workspace for the indicators still in dispute.
- **FR-DR-057**: A Senior Reviewer's decision to publish over an unresolved disagreement MUST record who decided, when, and which indicators were still contested; and for each such indicator the answer published MUST be determined by a stated rule and MUST be marked as contested rather than presented as agreed.
- **FR-DR-058**: Opening, closing, or re-opening a reconciliation round MUST NOT invalidate, clear, or require re-issuing either assessor's completion declaration. Assessors MUST NOT be asked to re-declare completion because a round occurred.
- **FR-DR-059**: While a reconciliation round is open, the unit MUST NOT pass Senior Reviewer sign-off. The round must close — as resolved, exhausted, or no longer required — before sign-off can proceed.

#### Tolerance configuration

- **FR-DR-060**: The tolerated disagreement rate MUST be held per project, so two projects may run to different tolerances at the same time.
- **FR-DR-061**: A project that has not set its own tolerance MUST use 5%.
- **FR-DR-062**: A Senior Reviewer MUST be able to change a project's tolerance from within the portal while the project is running, without a redeploy or restart, and the new value MUST apply to the next comparison.
- **FR-DR-063**: Every comparison MUST record the tolerance under which it was judged, and reading that record back MUST report that tolerance rather than the project's current one.
- **FR-DR-064**: A tolerance outside 0% to 100% inclusive MUST be rejected, leaving the previous value in force.
- **FR-DR-065**: A tolerance of 0% MUST be honoured as meaning "any disagreement flags", and MUST NOT be treated as unset.
- **FR-DR-066**: A change to a project's tolerance MUST record who changed it, when, and the previous value.

#### Programmatic parity

- **FR-DR-070**: The programmatic submission path MUST trigger the same recomputation, flagging, round-cap, and persistence behaviour as the portal path, so a unit assessed programmatically cannot bypass reconciliation.
- **FR-DR-071**: A unit's current discrepancy state — rate, indicators compared, tolerance in force, rounds consumed, and whether it is persistent — MUST be retrievable programmatically.

### Key Entities

- **Discrepancy comparison**: One recorded comparison of the two assessors' answers for a unit at a point in time. Carries the disputed indicator set, the rate, the number of indicators compared, the tolerance in force at the time, and the outcome.
- **Reconciliation round**: One bounded opportunity for the two assessors to settle a flagged unit. Carries which unit, which disputed set it opened over, whether it was opened automatically or by a named Senior Reviewer and with what reason, when it opened, when it closed, and how it closed — resolved, exhausted, or no longer required.
- **Joint answer**: The single agreed answer for one previously disputed indicator, carrying the agreed value, the written justification, which assessor submitted it, and when. Additive; it never overwrites the originals, and it binds both assessors.
- **Reconciliation work item**: The queue entry that makes a flagged unit visible as outstanding work and that is closed when reconciliation resolves or the Senior Reviewer dispositions it.
- **Senior Reviewer disposition of a persistent discrepancy**: The record of the reviewer's choice — return for another round, or publish unresolved — carrying who decided, when, the reason given, and which indicators were still contested at the time.
- **Project tolerance**: The tolerated disagreement rate held per project, defaulting to 5% where a project has not set its own, with a record of who last changed it and from what.

## Success Criteria *(mandatory)*

- **SC-001**: When the second assessor saves their final answer, the unit's disagreement position is current and visible without anyone requesting a recomputation, on that assessor's next view of the unit.
- **SC-002**: 100% of units whose disagreement rate exceeds the tolerance at mutual completion are opened for reconciliation exactly once, and no unit is ever opened automatically before both assessors have declared completion, however divergent their partial answers are.
- **SC-003**: An assessor entering reconciliation is presented only with indicators actually in dispute — never the full questionnaire — so the work is proportional to the disagreement rather than to the questionnaire's length.
- **SC-004**: A Senior Reviewer can determine the discrepancy position of every unit in a project from a single screen, without opening any unit, and can tell full consensus, tolerated disagreement, flagged disagreement, and exhausted reconciliation apart at a glance.
- **SC-005**: 100% of jointly agreed answers are the values used at publication for their indicators; no originally differing answer is published for an indicator that was reconciled.
- **SC-006**: No sequence of assessor submissions, however long, causes the system to return a unit to its assessors more than once. Every subsequent return is traceable to a named Senior Reviewer.
- **SC-007**: Every unit that remains in disagreement after reconciliation is explicitly marked as such and waits for a Senior Reviewer decision; none is silently published, silently dropped, or left to lapse.
- **SC-008**: A Senior Reviewer facing a persistent discrepancy can both send it back and publish it, and whichever they choose is attributable to them afterwards, with the contested indicators recorded.
- **SC-009**: A Senior Reviewer can change a project's tolerance and see it take effect on the next comparison with no restart, without affecting any other project, and every surface naming the tolerance names the new figure.
- **SC-010**: Loading any display of discrepancy any number of times produces no new records.
- **SC-011**: No portal route returns one assessor's answers to a request made in the other's role, except for the disputed set of an open reconciliation round. This holds however the request is made, including requests that name a role directly rather than arriving through the portal's own navigation.

## Assumptions

- **A1**: "Discrepancy rate" means the proportion of commonly answered indicators on which the two assessors' answers differ, consistent with the existing engine. Indicators only one assessor has answered are excluded rather than counted as disagreements.
- **A2**: "Exceeds the threshold" is strictly greater than, so a rate exactly equal to the tolerance is within tolerance. This matches the existing engine and makes the amber band inclusive of its upper bound.
- **A3**: The cap of one applies only to rounds the system opens by itself. A Senior Reviewer's returns are not counted against it and are not themselves capped, because each is a deliberate attributed act rather than an automatic loop; the accumulating round record is what makes repeated returns visible.
- **A4**: A reconciliation round is complete when a joint answer exists for every indicator in the disputed set that opened it, at which point the rate is recomputed and the round closes as resolved or exhausted. Because either assessor may commit a joint answer, a round can complete without both assessors having acted.
- **A5**: Where a unit is published over an unresolved disagreement, the answer published for a still-contested indicator follows the existing precedence rule already applied at publication, and is marked as contested. This feature does not introduce a new tie-break rule; it makes the existing one visible and attributable rather than silent.
- **A6**: Senior Reviewer sign-off, publication readiness, and the existing escalation disposition mechanism keep their current behaviour; this feature adds paths into them, not replacements for them. Publication readiness gains one condition — no open reconciliation round — but its existing both-roles-declared requirement is untouched, and reconciliation never clears a declaration.
- **A7**: Assessor identity is carried on submissions as it is today; no new authentication or role model is introduced. This spec names exactly three actors: **Assessor A**, **Assessor B**, and the **Senior Reviewer**. The Senior Reviewer is the existing reviewer who already dispositions escalations, and is also the actor who sets a project's tolerance — there is no separate administrator, because there is no permission model that could distinguish one.
- **A8**: The reconciliation workspace is a portal screen consistent with the existing assessor surfaces in layout, accessibility, and behaviour, and is not a separate application.

## Dependencies

- The existing discrepancy comparison engine (`src/portal/discrepancy.py`), which already provides both a writing recomputation and a read-only computation, the idempotency guard on queue entries, and the settled-answer lookup used at publication.
- The existing recomputation call sites, which already fire on every portal submission (`src/portal/assessor.py`), every programmatic submission (`src/api/routers/human.py`), and in the seed script (`src/portal/seed.py`).
- The existing read-only call on the project detail route (`src/portal/admin.py`) and the partial badge already rendered by `src/portal/templates/admin_project_detail.html`, which this feature extends and corrects to name the tolerance in force.
- The existing escalation queue, its disposition mechanism with its concurrency guarantee, and the settled-answer precedence applied at publication (`src/review/escalations.py`, `src/api/finalize.py`).
- The existing tolerance setting and its environment override (`src/shared/config/settings.py`), which the chosen configuration scope will build on.
- The assessor completion declaration and publication readiness gate, unchanged.

## Known Limitations

- **Identity is claimed, not verified.** The portal has no authentication; an assessor's role and identity arrive as request parameters. Anyone able to reach the portal can therefore present themselves as either assessor by changing a URL. This predates the feature and is not introduced by it, but it bounds what the blindness requirements can promise: FR-DR-014, FR-DR-015 and FR-DR-017 are enforced structurally, by limiting what any route is capable of returning, and deliberately make no claim about verifying who is asking. Genuine enforcement requires an authentication and assessor-assignment model, which is a separate feature.
- **Badge computation cost grows with units × indicators, and is not bounded by any requirement.** The project detail view recomputes discrepancy per unit on each page load, and each computation walks every indicator on the unit. No latency or scale target is set for this feature — a deliberate deferral, recorded so it is not mistaken for an oversight. At POC scale it is acceptable; a full national questionnaire across many units will make the page noticeably slower, and the remedy (a stored per-unit summary refreshed on submission, or a batched read) is a later optimisation rather than a change to any behaviour specified here.
- **Attribution is therefore as trustworthy as the environment.** A joint answer records the actor who submitted it (FR-DR-022) and a Senior Reviewer decision records who decided (FR-DR-057), but neither is cryptographically or session-bound. The audit trail is reliable for reconstructing what happened, not for proving who did it against a determined insider.

## Out of Scope

- Any change to how the two AI assessor agents disagree or how the resolver agent settles them. That path is separate by design and must not be wired to this one.
- Automatic resolution of a human disagreement by the AI. Reconciliation is between the two people.
- Free-text discussion, threaded comments, or messaging between assessors beyond the joint answer's justification field.
- Changing the blindness model during the ordinary assessment phase.
- Changing the scoring, ranking, or publication formulas.
- Reconciliation across units or across projects; reconciliation is per unit.
- Notifying assessors outside the portal that a unit needs reconciliation.
