# Feature Specification: Disagreement Labelling for Human Assessor Discrepancies

**Feature Directory**: `specs/017-disagreement-labelling`
**Created**: 2026-09-07
**Status**: Draft
**Input**: The discrepancy between two assessors is currently only a number — the proportion of indicators they answered differently. That number says how often they disagreed but nothing about how they disagreed, so every dispute reaches a reviewer looking identical. This feature adds a short, self-explanatory label to each disagreement, describing the relation between the two positions — never a verdict on which one is correct. The boolean comparison and its tolerance gate are unchanged and remain the only trigger for arbitration. A model assigns the label; it never influences whether a unit is flagged.

## Overview

Two blind assessors answer the same questionnaire for the same unit. Where the proportion of differing answers exceeds the project's tolerance, the platform opens a reconciliation round and, failing that, escalates to a Senior Reviewer. That machinery works and is not changed here.

What it cannot do is distinguish *kinds* of disagreement. A dispute where one assessor found a portal page the other never located, a dispute where both looked at the same page and read it differently, and a dispute where one hit a login wall are three unrelated problems with three unrelated remedies — and today they are indistinguishable, appearing as three identical entries in a disputed-indicator list. The reviewer reconstructs the difference by reading both assessors' notes, one indicator at a time, for every unit.

This feature attaches a label to each disagreement that names the relation between the two positions: **Used different sources**, **One found nothing**, **One couldn't access**, **Saw different things**, **Judged differently**, or **Not enough notes**. The labels are descriptive and symmetric. None of them says an assessor was wrong, because determining who is right is the reviewer's job and this feature deliberately does not encroach on it.

Labelling runs once per project-unit, as a single pass at the point that unit's assessment submissions are complete — after the numeric comparison has already decided the unit's fate, and before sign-off and publication, which follow. It cannot move a rate, flag a unit that was within tolerance, or clear one that was above it. That separation is the feature's central constraint: a project's tolerance is a governance parameter a Senior Reviewer sets and the audit record must reproduce, so nothing non-deterministic may participate in the decision it drives.

A large part of the value is an aggregate the labels make possible for the first time. When two trained assessors examine the same evidence and reach opposite conclusions on the same indicator across many units, the indicator's wording — not the assessors — is the likely problem. Counting **Judged differently** per indicator across a cycle turns disagreement, which today is only noise, into an evidence-based measure of which questions are ambiguous.

### What already exists, and what this feature actually adds

**Already in place (no work required):**

- The boolean comparison engine, its differing-answer rate, and the strictly-greater-than tolerance test.
- Recomputation on every assessor submission and completion declaration, on both the portal and programmatic paths.
- A read-only computation path safe to call from display routes, which creates no records.
- Per-project tolerance with a process-wide default and an environment override.
- The one-automatic-round cap, the reconciliation workspace, the escalation queue, and Senior Reviewer disposition.
- The evidence URL and free-text notes fields on every assessor submission, and the record of whether the assessor accepted the AI suggestion.
- A model provider through which all model invocation passes, and a background job mechanism.

**Genuinely missing (this feature's scope):**

- **Any characterisation of a disagreement beyond "these two answers differ".** No label, no taxonomy, no stored classification.
- **A deterministic comparison of the two cited evidence sources.** The engine compares booleans only; the two `evidence_url` values are stored and displayed but never compared, so even the cases that need no model at all are not distinguished.
- **Per-side observations about submission quality** — that an assessor's notes contradict their own answer, that they accepted the AI suggestion unchanged, or that they wrote nothing.
- **An indicator-level ambiguity measure.** Disagreement is only ever aggregated per unit; it is never aggregated per question across units, so a systematically ambiguous indicator is invisible.
- **Any record of how a characterisation was produced** — which model, which prompt, over which inputs — which is the precondition for trusting it in an audit.

## Decisions Taken

- **D1 — The numeric gate is untouched and remains the sole trigger for arbitration.** The differing-answer rate, the tolerance comparison, the round-opening conditions and the escalation are computed exactly as they are today, from booleans alone. Labelling runs afterwards, over disputes the comparison has already identified. This is not merely an ordering convenience: the tolerance is a parameter a Senior Reviewer sets and every recorded comparison stamps the tolerance it was judged under, so the decision it drives must be reproducible from the submissions alone. A model in that path would make the same inputs yield different outcomes on replay.
- **D2 — A label describes a relation between two positions, never a verdict on either.** Every label in the set can be stated without asserting which assessor is correct, and the set contains no label that could be read as one. "Used different sources" states a fact about the pair; "one assessor used the wrong source" would be arbitration. This constraint governs the wording of the labels themselves, not only their definitions, because a label shown as a badge is read without its definition.
- **D3 — The classifier never sees the AI's own answer.** The prefill's suggested answer and its justification are withheld from the classifier. Supplying them would give the model a position of its own to measure the assessors against, which is the arbitration role this feature exists to avoid. The one prefill-derived input retained is *whether* an assessor accepted the suggestion — a fact about that assessor's process, carrying no information about what was suggested.
- **D4 — The classifier does not know which position is Assessor A's.** The two positions are presented without role identity. Because every label is symmetric, role is not needed to assign one, and withholding it removes any possibility of a label correlating with a role.
- **D5 — Evidence comparison is deterministic first, and a model is consulted only for what determinism cannot settle.** Comparing the two cited sources by normalised host resolves the cases where the assessors cited different portals, or where only one cited anything at all, without a model call. Only disputes over the same source reach the classifier, which then chooses among three possibilities rather than six. This is both cheaper and materially more reliable: a three-way choice with an explicit decision procedure is a different reliability class from a six-way one.
- **D6 — Labelling is one pass per project-unit, run once.** When a unit's assessment submissions are complete, a single pass labels every disagreement that unit contains, and that pass is not repeated. Sign-off and publication come afterwards, so in the ordinary course the labels are already in place when the Senior Reviewer looks at the unit. Each classification stores the model identity, the prompt version, and a digest of the exact inputs it was produced from, and is the audit record of what was said about the assessors' original positions. A later amendment does not produce a new label — the record describes the disagreement as it stood when the two assessors independently submitted, which is the disagreement worth understanding.
- **D7 — Labelling is a background activity and degrades to nothing.** It never runs on a display path, never delays an assessor's submission, and when the model is unavailable the dispute simply carries no label. Everything else — rate, flag, round, escalation, publication — proceeds identically, which is what makes the whole feature safe to add to a working process.
- **D8 — Labels inform people; they do not act.** A label changes what a reviewer is shown and what order work is presented in. It never resolves a dispute, never selects an answer, and never substitutes for the reconciliation round or the Senior Reviewer's decision.

## Clarifications

### Session 2026-09-07

- Q: Does a label ever change which disputes consume the unit's one automatic reconciliation round? → A: **No. Labels are advisory everywhere, and this case is not an exception.** The automatic round opens under exactly the conditions it opens under today, over exactly the disputes the boolean comparison identified. A dispute labelled **One couldn't access** consumes the round like any other; the label is surfaced so the access problem is visible and can be pursued separately, but it diverts nothing and excuses nothing. Diverting on a label would let a model output decide the process path a unit takes, which is the outcome D1 exists to prevent, and it would do so on the one label that can never be established deterministically. See D1, FR-DL-042, FR-DL-046 and FR-DL-047.
- Q: Are labels visible to the two assessors inside the reconciliation workspace, or only to the Senior Reviewer and Administrator? → A: **Senior Reviewer and Administrator surfaces only.** The reconciliation round exists to make two people re-examine a disagreement and converge on the evidence. Telling them in advance that the platform has characterised their disagreement — as judged differently, say — invites both to accept that framing rather than look again, which would substitute the label for the re-examination. The label describes the round's input; it is not an input to the round. See A7, FR-DL-060 and FR-DL-065.
- Q: What happens when an attempt to establish a label fails? → A: **Retry twice, then stop.** Three attempts in total, counted above the model provider's own transient-failure handling rather than as part of it. Without this, FR-DL-052's rule against re-establishing a label over unchanged inputs — written to prevent paying twice for the same work — would also have prevented any retry, since a failure leaves the inputs unchanged, so one dropped connection would have blanked a disagreement permanently. After the third attempt the dispute settles as attempted-and-unlabelled, which is a distinct and visible state from awaiting labelling. See FR-DL-052, FR-DL-057, FR-DL-058, FR-DL-059 and FR-DL-064.
- Q: Are disagreements labelled on every unit, or only on units whose rate exceeded the tolerance? → A: **Every unit, flagged or not.** A unit within tolerance still contains real disagreements — three differing answers out of a hundred is 3%, triggers nothing, and is still three disagreements. Labelling only flagged units would compute the indicator ambiguity measure over a sample consisting solely of units that already disagreed heavily, and would entirely miss the most diagnostic pattern available: an indicator that produces exactly one disagreement in almost every country. See FR-DL-001, FR-DL-070 and A8.
- Q: Should notes become mandatory when an assessor's answer diverges from the AI suggestion? → A: **Notes stay optional, and the resulting cost is measured rather than assumed.** The submission form is unchanged. Where assessors write nothing, disputes over a shared source are labelled **Not enough notes**, and the proportion of disputes ending there is reported, so a future decision to require notes rests on the observed rate rather than on an expectation of it. See A4, FR-DL-074, SC-007 and Known Limitations.
- Q: When does labelling run, and does it continue after a project is signed off? → A: **Once per project-unit, when that unit's assessment submissions are complete — before sign-off, and never again.** Labelling is a single pass at a fixed point in the pipeline rather than a process that reacts to later events. This removes the question of post-sign-off labelling entirely, and with it the re-labelling machinery an event-driven design needed: no fresh label on amendment, no re-eligibility after exhausted attempts, no superseded labels to arbitrate between. What a label describes is fixed and easy to state — the two assessors' original independent positions — which is also the right basis for the ambiguity measure, since it counts questions that made two trained people differ before they conferred. See D6, FR-DL-006, FR-DL-007, FR-DL-008, FR-DL-052, FR-DL-053, FR-DL-059 and FR-DL-068.
- Q: Are the Senior Reviewer and the Administrator the same reviewer-side actor, or genuinely distinct? → A: **Distinct, and scoped differently.** A Senior Reviewer is appointed to one project and signs off that project's questionnaire; their view of labels is confined to it. An Administrator sees every project. This matters here for two reasons: the aggregate measures are only meaningful across cycles, which makes the cross-cycle view an Administrator view; and sign-off is the one remaining place a label could quietly acquire authority, so FR-DL-066 states that it cannot — an unlabelled or attempted-and-unlabelled dispute never stands in the way of a sign-off. See A7, FR-DL-060, FR-DL-066, FR-DL-067, FR-DL-075 and Known Limitations.
- **Amendment, 2026-09-07 (planning)**: A3, D5 and FR-DL-030 previously specified comparison by *registrable domain*. Planning research found this wrong for government hosts in one direction — `dvla.gov.uk` and `hmrc.gov.uk` share the registrable domain `gov.uk`, so two assessors citing entirely different agency portals would have been recorded as having used the same source, and a **Used different sources** label would have been asserted deterministically with no model reviewing it. The comparison is now by normalised host, with a subdomain treated as the same source as its parent, and uncertainty resolving toward *same source* so that an unclear case reaches the classifier instead. See [research.md](./research.md) R4.
- Q: Do assessors' notes leave the platform to reach the model provider, or should they be redacted or withheld first? → A: **Sent as they were written, with the position stated rather than mitigated.** The platform already sends materially more to the same provider through the same single entry point: full portal page content, questionnaire document text, and the prefill research. Notes are professional commentary about public government websites, written by assessors who know their work is reviewed. Redacting this one path while the others send everything would present a more careful privacy posture than the platform actually has, and would degrade the labels — the distinction between describing different content and judging it differently lives in exactly the descriptive detail a redactor would strip. The value is in stating the position plainly so it can be reviewed, not in changing it. See A9, FR-DL-036, FR-DL-039 and Known Limitations.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A reviewer sees what kind of disagreement each dispute is (Priority: P1)

A Senior Reviewer opens a flagged unit and, for each disputed indicator, sees a short label stating how the two positions relate — that they cited different portals, that only one found anything, that they described the same page differently, or that they described the same thing and called it differently. The reviewer forms an accurate picture of the unit without reading every pair of notes.

**Why this priority**: This is the feature. Everything else either supports it or is derived from it.

**Independent Test**: Construct a unit with one dispute of each kind, drive it through detection, and verify each disputed indicator carries the label matching its constructed kind, that the label is legible without reference to a key, and that no label asserts which assessor is correct.

**Acceptance Scenarios**:

1. **Given** a dispute where the two assessors cited pages on different portals, **When** the reviewer views the unit, **Then** the dispute is labelled as using different sources.
2. **Given** a dispute where one assessor cited a page and the other recorded finding nothing, **When** the reviewer views the unit, **Then** the dispute is labelled as one having found nothing.
3. **Given** a dispute where both cited the same portal and their notes describe different page content, **When** the reviewer views the unit, **Then** the dispute is labelled as having seen different things.
4. **Given** a dispute where both cited the same portal and their notes describe the same content but they answered oppositely, **When** the reviewer views the unit, **Then** the dispute is labelled as judged differently.
5. **Given** a dispute where neither assessor wrote notes and both cited the same portal, **When** the reviewer views the unit, **Then** the dispute is labelled as not having enough notes, and no other label is guessed.

### User Story 2 - Labelling cannot change any assessment outcome (Priority: P1)

The platform is run twice over identical submissions, once with labelling available and once with it entirely unavailable. Every rate, flag, round, escalation and published answer is identical. The only difference is the presence of labels.

**Why this priority**: This is the constraint that makes the feature safe to add to a live governance process. If it does not hold, nothing else about the feature matters.

**Independent Test**: Run a full set of units to publication with the model provider disabled, record every discrepancy outcome, then repeat with it enabled and diff the outcomes. Any difference outside the labels themselves is a failure.

**Acceptance Scenarios**:

1. **Given** the model provider is unavailable, **When** assessors submit answers that exceed the tolerance, **Then** the unit is flagged, a round opens and an escalation is queued exactly as it would with the provider available.
2. **Given** the model provider is unavailable, **When** a reviewer views a flagged unit, **Then** the disputed indicators are listed with their labels shown as pending, and the unit's rate, tolerance and state are shown normally.
3. **Given** a dispute has been labelled, **When** the discrepancy is recomputed, **Then** the rate and the flag decision are computed from booleans alone and are identical to what they would be if no label existed.
4. **Given** the model returns a malformed or unrecognised response, **When** labelling completes, **Then** the dispute carries no label and no error surfaces to the assessors.

### User Story 3 - Every label can be accounted for afterwards (Priority: P1)

Asked why a dispute carries a particular label, an Administrator can show which model produced it, under which prompt version, from exactly which submission content, and when — and can demonstrate that the label has not silently changed since.

**Why this priority**: The output of a model is entering a UN audit trail. A label that cannot be accounted for is worse than no label, because it carries apparent authority without traceability.

**Independent Test**: Run the labelling pass over a unit, record each label's provenance, then recompute the unit's discrepancy repeatedly, amend a submission, and open a reconciliation round — verifying after each that no further classification is produced and every recorded label is unchanged.

**Acceptance Scenarios**:

1. **Given** a labelled dispute, **When** its provenance is inspected, **Then** the model identity, prompt version, input digest and time of production are all present.
2. **Given** a unit whose labelling pass has run, **When** discrepancy is recomputed any number of times, **Then** no further classification is produced and no model call is made.
3. **Given** a unit whose labelling pass has run, **When** an assessor amends their answer, evidence or notes, **Then** no new classification is produced, the recorded labels are unchanged, and the surface shows that the submission has changed since labelling.
4. **Given** a label produced by the deterministic comparison rather than by a model, **When** its provenance is inspected, **Then** it is identifiable as such and names no model.

### User Story 4 - Disputes that are not disagreements about the portal are separated out (Priority: P2)

A dispute arising because one assessor met a login wall, a dead link or a language barrier is distinguishable at a glance from a dispute about what the portal actually offers, so an Administrator can pursue the access problem separately — while the dispute itself continues through reconciliation like any other.

**Why this priority**: It is the clearest case of the rate alone being uninformative. An access failure and an interpretive split are equally one differing answer, and are worked identically today, so the access problem is never seen as a distinct thing to fix. The label makes it visible; it deliberately does not make it count for less.

**Independent Test**: Construct a unit whose disputes are entirely access failures and one whose disputes are entirely interpretive, and verify the two are distinguishable without opening individual indicators.

**Acceptance Scenarios**:

1. **Given** a dispute where one assessor's notes record an access barrier and the other's do not, **When** the dispute is labelled, **Then** it carries the access label.
2. **Given** a unit whose disputes are all access failures, **When** an Administrator reviews it, **Then** the unit is distinguishable from a unit with the same rate whose disputes are interpretive.

### User Story 5 - Recurring interpretive splits identify ambiguous indicators (Priority: P2)

A questionnaire owner reviews a cycle and sees which indicators repeatedly produced opposite answers from assessors who were looking at the same evidence, ranked by how often it happened — the evidence needed to rewrite an ambiguous question before the next edition.

**Why this priority**: It is the aggregate return on the labelling investment and the input to questionnaire improvement, but it depends on labels existing across many units first.

**Independent Test**: Label disputes across a set of units in which one indicator is deliberately ambiguous and others are not, then verify the ambiguous indicator ranks highest on the measure and that disputes arising from different sources or access failures do not contribute to it.

**Acceptance Scenarios**:

1. **Given** a cycle with labelled disputes across many units, **When** the ambiguity measure is produced, **Then** it counts only disputes where both assessors described the same evidence and answered oppositely.
2. **Given** an indicator whose disputes are predominantly different-source disputes, **When** the ambiguity measure is produced, **Then** that indicator is not ranked as ambiguous on the basis of those disputes.
3. **Given** the measure for an indicator, **When** it is inspected, **Then** the number of units contributing to it is stated alongside it, so a high proportion over few units is not read as a strong signal.

### User Story 6 - Thin evidence is measured rather than guessed at (Priority: P3)

Where assessors have written too little for the nature of a dispute to be established, that is stated plainly and counted, rather than being filled with a plausible-looking label.

**Why this priority**: It protects the credibility of every other label, but it reports a limitation rather than creating capability.

**Independent Test**: Submit disputes with empty and with minimal notes, and verify they are labelled as insufficient rather than assigned a substantive label, and that the proportion is reportable.

**Acceptance Scenarios**:

1. **Given** a dispute where neither assessor wrote notes, **When** it is labelled, **Then** it carries the insufficient-notes label.
2. **Given** a dispute where the model cannot confidently choose among the candidate labels, **When** it is labelled, **Then** it carries the insufficient-notes label rather than the model's best guess.
3. **Given** a set of labelled units, **When** an Administrator reviews labelling quality, **Then** the proportion of disputes carrying the insufficient-notes label is reportable.

### Edge Cases

- **A dispute where neither assessor cited any evidence.** Both cited nothing, so the sources cannot differ. The dispute goes to the classifier if either wrote notes, and is labelled insufficient otherwise.
- **A dispute where both cited the same page but one recorded no notes.** The single set of notes may still establish an access barrier; otherwise the dispute is labelled insufficient. A one-sided account never establishes that the two saw different things, because there is nothing to compare it against.
- **Both assessors cite the same portal by different URLs** — a homepage and a subpage of the same domain. This is the same source; it is not a different-source dispute.
- **A country's portal spans several domains.** Two assessors citing genuinely different domains of the same portal estate are recorded as using different sources. The label is accurate as a statement about the pair even where both are legitimate.
- **A URL cannot be parsed.** It is treated as no evidence cited for the purposes of the deterministic comparison, and the dispute is not rejected.
- **The two submissions are weeks apart.** The portal may have changed between them. This makes a same-source content difference more likely and is recorded alongside the label as context; it never by itself determines a label.
- **An assessor amends a submission while the pass is in flight.** The classification is stored against the inputs the classifier actually received, and no second classification follows. A label is never attributed to content it did not see; its input digest records what it did see.
- **A dispute is resolved by a joint answer before the pass runs.** The comparison already excludes indicators carrying a joint answer, so the dispute ceases to exist and no label is produced. A label recorded before the joint answer is retained for the record.
- **A reconciliation round changes both assessors' answers.** No new labels are produced. The recorded labels describe the original independent disagreement, which is the disagreement the ambiguity measure is about — a question that made two trained people differ before they conferred.
- **The tolerance is raised and a unit falls back within tolerance.** Labels already produced are retained; they describe disagreements that genuinely occurred.
- **A unit has a single compared indicator and the assessors differ.** The rate is 100% and the single dispute is labelled normally. The label does not compensate for the small comparison base; the number of indicators compared is what conveys that.
- **The model returns a label outside the defined set.** The response is rejected and the dispute is left unlabelled. An unrecognised label is never stored. The rejected response counts as an unsuccessful attempt.
- **Labelling fails three times for the same dispute.** No further automatic attempts are made, and nothing later brings it back into scope. The dispute is shown as attempted-and-unlabelled rather than as awaiting labelling, and continues through reconciliation, sign-off and publication exactly as it would with a label.
- **The model provider is unavailable for an extended period.** Every unit whose pass runs during it exhausts its attempts and settles unlabelled, and restoring the provider does not bring those units back into scope, because a unit's pass runs once. Those units are permanently unlabelled absent a deliberate re-run.
- **Both assessors accepted the AI suggestion unchanged, yet differ.** Not possible for the same indicator, since the suggestion is one value; if both flags appear on one dispute it indicates a data fault and is recorded as such rather than labelled.
- **Labelling is enabled part-way through a cycle.** Units whose submissions were already complete never had a pass and stay unlabelled; units completed from then on are labelled normally. Aggregate measures state the proportion of disputes they were computed over, so the partial coverage is visible in the figure rather than hidden behind it.

## Functional Requirements *(mandatory)*

#### What is labelled

- **FR-DL-001**: The system MUST assign a label to each indicator the boolean comparison has identified as a disagreement for a unit, on every unit, whether or not that unit's disagreement rate exceeded its tolerance.
- **FR-DL-002**: The system MUST NOT assign a label to an indicator on which the two assessors agree, nor to an indicator only one assessor has answered.
- **FR-DL-003**: Exactly one label from the defined set MUST apply to a dispute at a time.
- **FR-DL-004**: A dispute for which no label has been established MUST be shown as unlabelled, and MUST NOT be shown as any substantive label.
- **FR-DL-005**: An indicator that ceases to be a disagreement MUST retain any label already recorded against it, as a record of a disagreement that occurred.
- **FR-DL-006**: Labelling MUST run as a single pass over one project-unit, dispatched once that unit's assessment submissions are complete, covering every disagreement the boolean comparison identifies for that unit at that moment.
- **FR-DL-007**: The pass MUST NOT be dispatched again for a unit it has already run for. Labelling is not a reaction to later events — not to a recompute, not to an amendment, not to a reconciliation round, and not to sign-off or publication.
- **FR-DL-008**: The pass MUST run before the unit reaches sign-off in the ordinary course, and MUST NOT be a precondition of reaching it.

#### The label set

- **FR-DL-010**: The label set MUST consist of exactly the following six labels, and MUST NOT be extended at runtime.
- **FR-DL-011**: **Used different sources** MUST mean: both positions cite evidence, and the cited evidence is on different portals.
- **FR-DL-012**: **One found nothing** MUST mean: one position cites evidence and the other records having found none.
- **FR-DL-013**: **One couldn't access** MUST mean: the positions cite the same source, and one records being unable to reach or read it — including a login wall, a dead link, and a language barrier.
- **FR-DL-014**: **Saw different things** MUST mean: the positions cite the same source, both reached it, and they describe different content there.
- **FR-DL-015**: **Judged differently** MUST mean: the positions cite the same source, describe the same content, and answer oppositely.
- **FR-DL-016**: **Not enough notes** MUST mean: the written material is insufficient to establish which of the other labels applies.
- **FR-DL-017**: Every label MUST describe the relation between the two positions. No label MUST assert, imply, or rank which position is correct, and this MUST hold for the label as displayed as well as for its definition.
- **FR-DL-018**: A label MUST be intelligible on its own where it is displayed, without the reader consulting a key or definition.

#### Per-side observations

- **FR-DL-020**: The system MUST record, for each side of a dispute independently, whether that assessor's notes contradict their own recorded answer.
- **FR-DL-021**: The system MUST record, for each side independently, whether that assessor accepted the AI suggestion unchanged without writing notes of their own.
- **FR-DL-022**: The system MUST record, for each side independently, whether that assessor wrote no notes.
- **FR-DL-023**: These observations MUST be independent of the label and MUST be capable of accompanying any label.

#### Establishing the label

- **FR-DL-030**: The system MUST compare the two cited evidence sources by normalised host before consulting any model, treating a subdomain as the same source as its parent host and two sibling hosts as different sources. Where the comparison is uncertain it MUST resolve toward *same source*, so that an unclear case reaches the classifier rather than being asserted as a different-sources disagreement without one.
- **FR-DL-031**: Where both positions cite evidence on different portals, the system MUST establish **Used different sources** without consulting a model.
- **FR-DL-032**: Where exactly one position cites evidence, the system MUST establish **One found nothing** without consulting a model.
- **FR-DL-033**: Where the positions cite the same portal, or neither cites evidence, the system MUST consult the classifier, which MUST choose among **One couldn't access**, **Saw different things**, **Judged differently**, and **Not enough notes** only.
- **FR-DL-034**: Where the classifier cannot establish one of those labels with confidence, the result MUST be **Not enough notes**, and MUST NOT be a best guess among the others.
- **FR-DL-035**: A response naming a label outside the set applicable to the case MUST be rejected and MUST NOT be stored.
- **FR-DL-036**: The classifier MUST receive only the indicator's own text, the two positions' answers, cited evidence and notes, and the interval between the two submissions.
- **FR-DL-037**: The classifier MUST NOT receive the AI prefill's suggested answer or its justification.
- **FR-DL-038**: The classifier MUST NOT receive which position belongs to which assessor role.
- **FR-DL-039**: The content listed in FR-DL-036 MUST be the complete set of what reaches the classifier. It MUST NOT be extended without a corresponding change to this specification, so that what leaves the platform for this purpose remains answerable to review.

#### Separation from the numeric outcome

- **FR-DL-040**: The differing-answer rate MUST be computed from the recorded answers alone, exactly as it is today, and MUST NOT be influenced by any label, flag, or classifier output.
- **FR-DL-041**: Whether a unit exceeds its tolerance MUST be determined from that rate alone.
- **FR-DL-042**: No label MUST cause an indicator to be added to, or removed from, the disputed set.
- **FR-DL-043**: Labelling being unavailable, failing, or timing out MUST NOT change any rate, flag, disputed set, round, escalation, or published answer, and MUST NOT surface an error to an assessor.
- **FR-DL-044**: Labelling MUST NOT delay the recording of an assessor's submission or completion declaration.
- **FR-DL-045**: Displaying a label MUST NOT create records of any kind, and MUST NOT invoke a model.
- **FR-DL-046**: Labelling MUST NOT resolve a dispute, select an answer for an indicator, or discharge a work item.
- **FR-DL-047**: No label MUST affect whether a reconciliation round opens, which disputes that round covers, or whether the unit's one automatic round is treated as consumed. Every dispute the comparison identified is carried into the round regardless of the label it bears.

#### Provenance and re-use

- **FR-DL-050**: Every recorded label MUST carry the identity of the model that produced it, the version of the instruction used, a digest of the exact inputs, and the time it was produced.
- **FR-DL-051**: A label established without a model MUST be identifiable as such and MUST name no model.
- **FR-DL-052**: A label that has been successfully established MUST NOT be established again. The only repetition permitted is a further attempt within the same pass where no label was established at all (FR-DL-057).
- **FR-DL-053**: A change to either assessor's answer, cited evidence, or notes after the pass has run MUST NOT produce a new label. The recorded label continues to describe the submissions the classifier actually saw, which is what its stored input digest attests.
- **FR-DL-054**: A recorded label MUST NOT be altered or deleted. The record is append-only.
- **FR-DL-055**: Labels MUST be recorded per indicator per unit, so that a unit's disputes can carry different labels.
- **FR-DL-056**: A label MUST be attributed only to the input content the classifier actually received.
- **FR-DL-057**: Where an attempt to establish a label does not produce one, the system MUST make up to two further attempts — three in total. These attempts MUST be counted only after the model provider's own handling of transient failures has been exhausted, and MUST NOT be conflated with it.
- **FR-DL-058**: After the third unsuccessful attempt the dispute MUST be left unlabelled, and the fact that labelling was attempted and exhausted MUST be recorded, so that a dispute nobody has yet tried to label is distinguishable from one that was tried and could not be.
- **FR-DL-059**: A dispute whose attempts are exhausted MUST remain unlabelled, and MUST NOT be re-attempted automatically by any later event. Recovering it would require a deliberate re-run, which is out of scope here.

#### Surfacing

- **FR-DL-060**: Each disputed indicator MUST show its label wherever that indicator's dispute is presented to a Senior Reviewer or an Administrator.
- **FR-DL-061**: A unit's disputes MUST be summarisable by label, so a reviewer can see the composition of a unit's disagreement without opening each indicator.
- **FR-DL-062**: Per-side observations MUST be shown against the side they describe, never against the pair.
- **FR-DL-063**: A label MUST be presented as a description of the disagreement and MUST NOT be presented as a recommendation, a resolution, or a confidence in either answer.
- **FR-DL-064**: Where a label is not available, the surface MUST say so plainly and MUST show the dispute normally in every other respect. A dispute awaiting labelling and a dispute whose labelling attempts were exhausted MUST be distinguishable, so that a temporary state is not read as a permanent one.
- **FR-DL-065**: Labels and per-side observations MUST NOT be shown to an assessor, and MUST NOT appear on the reconciliation workspace or on any other assessor-facing surface.
- **FR-DL-066**: Sign-off of a project's questionnaire MUST NOT depend in any way on labelling state. A dispute that is awaiting labelling, or whose labelling attempts were exhausted, MUST NOT block, delay or qualify a sign-off, and no label MUST be required to be acknowledged, dismissed or resolved before one. A Senior Reviewer signs off on the answers and the reconciliation, exactly as today; the labels are description they may read on the way.
- **FR-DL-067**: A Senior Reviewer's view of labels, per-side observations and aggregate measures MUST be confined to the project they are appointed to. An Administrator MUST be able to see all of them across every project.
- **FR-DL-068**: A label MUST be presented as describing the two submissions as they stood when the unit was labelled. Where a submission has changed since, that MUST be apparent on the surface, so that a label is not read as describing content it never saw.

#### The indicator ambiguity measure

- **FR-DL-070**: The system MUST report, per indicator across all units in a cycle, how often its disputes were labelled **Judged differently**.
- **FR-DL-071**: The measure MUST exclude every other label, so that access failures, different sources and unlabelled disputes do not contribute to it.
- **FR-DL-072**: The measure MUST state the number of units it was computed over alongside the figure.
- **FR-DL-073**: The measure MUST be reportable for a cycle whose disputes are only partly labelled, stating the proportion labelled.
- **FR-DL-074**: The proportion of a cycle's disputes carrying the **Not enough notes** label MUST be reportable, so the cost of leaving notes optional is observable rather than assumed.
- **FR-DL-075**: The measure MUST be viewable for a single project by that project's Senior Reviewer, and across projects by an Administrator. The cross-project view is the one that identifies an indicator as ambiguous in general rather than contested in one country, and it is therefore the view the questionnaire's wording is revised from.

#### Programmatic parity

- **FR-DL-080**: A submission made programmatically MUST produce the same labelling behaviour as one made through the portal.
- **FR-DL-081**: A dispute's label, per-side observations, and provenance MUST be retrievable programmatically.

#### Operability

- **FR-DL-090**: Model usage arising from labelling MUST be attributable in the platform's existing usage and cost telemetry, and MUST be distinguishable from usage arising from prefill, so the cost of this feature can be known separately from the cost of the research it sits beside.
- **FR-DL-091**: The proportion of a cycle's disputes settled by the deterministic pre-pass, as against those requiring a model call, MUST be reportable, since only the latter incur usage.
- **FR-DL-092**: The number of disputes currently awaiting labelling, and the number settled as attempted-and-unlabelled, MUST be observable, so that a provider outage is visible as a rising count rather than as silently missing labels.

### Key Entities

- **Disagreement label**: The recorded characterisation of one dispute, on one indicator, for one unit. Carries the label, the per-side observations, a short stated reason, whether it was established deterministically or by a model, the model identity and instruction version where applicable, a digest of the inputs it was produced from, and when it was produced. Additive: a new one never erases its predecessor.
- **Evidence source comparison**: The deterministic result of comparing the two cited evidence URLs by normalised portal identity — same portal, different portals, or only one cited — which settles two of the six labels on its own and constrains the classifier's choices for the rest.
- **Indicator ambiguity measure**: The per-indicator count and proportion of disputes labelled **Judged differently** across a cycle, with the number of contributing units and the proportion of that indicator's disputes that carry any label.

## Success Criteria *(mandatory)*

- **SC-001**: A Senior Reviewer can tell what kind of disagreement each disputed indicator represents without reading either assessor's notes.
- **SC-002**: Running an identical set of assessments with labelling entirely unavailable produces identical rates, flags, disputed sets, rounds, escalations and published answers to running it with labelling available.
- **SC-003**: No label, in any surface where it appears, states or implies which assessor was correct.
- **SC-004**: Every label present in the system can be traced to the inputs and the producer it came from, and the total model usage attributable to a unit never exceeds that of its single labelling pass — no amount of viewing, recomputation, amendment, reconciliation, sign-off or publication produces a further label or a further model call.
- **SC-005**: A reviewer can distinguish a unit whose disagreement is predominantly about access from one with the same disagreement rate whose disagreement is predominantly about interpretation, from a single screen.
- **SC-006**: For a cycle's completed assessments, the indicators most often producing opposite answers from assessors examining the same evidence can be ranked, with the number of units behind each figure visible.
- **SC-007**: Disputes whose written material is too thin to characterise are reported as such, and their proportion is measurable rather than concealed by substantive-looking labels.
- **SC-008**: An assessor's experience of submitting an answer and declaring completion is unchanged in behaviour and in responsiveness.
- **SC-009**: The two labels that can be established from cited evidence alone are established without any model usage.

## Assumptions

- **A1**: "Disagreement" continues to mean what the existing engine means by it: the two assessors recorded different answers for an indicator both answered, excluding indicators already carrying a joint answer.
- **A2**: The tolerance comparison remains strictly greater than, and the per-project tolerance with its process-wide default is unchanged.
- **A3**: Two cited URLs represent the same source when their normalised hosts are equal, or when one host is a subdomain of the other. Different paths on one host are the same source; a national portal and a subdomain of it are the same source; two sibling agency hosts are different sources. The registrable domain is deliberately *not* the unit of comparison — two different government agencies routinely share one, and treating them as one source would assert a same-source disagreement where none exists. Where a unit records an official portal URL, it may be used to refine this, but the host comparison is the baseline rule.
- **A4**: Notes are the primary material a label is established from. Where the parties wrote nothing, no substantive label is derivable, and the insufficient-notes label is the correct and expected outcome rather than a failure.
- **A5**: The classifier is a model of modest capability selected for cost, configured per deployment, run with deterministic settings, and reached through the platform's existing model provider. No behaviour specified here depends on which model it is.
- **A6**: The interval between the two submissions is context that makes a same-source content difference more plausible. It is never sufficient on its own to establish a label.
- **A7**: This feature adds no actor and changes no assessor-facing surface. It inherits the two reviewer-side actors the discrepancy process already defines: a **Senior Reviewer**, appointed to a single project and responsible for signing off that project's questionnaire, whose view is confined to that project; and an **Administrator**, who sees every project. Labels are seen by those two and by no one else. The assessors' questionnaire and the reconciliation workspace are untouched by this feature.
- **A8**: The volume of labelling work is bounded by the number of disagreements, not by questionnaire length. Every unit is labelled, but a unit within tolerance produces few disputes by definition and a unit above it produces disputes proportional to its rate, so total volume across a cycle stays a small fraction of answers submitted — reduced further by the disputes the deterministic comparison settles without a model call.
- **A9**: Assessor-written notes reach the external model provider, as free text, exactly as submitted. This is stated rather than mitigated: the platform already sends materially more to the same provider through the same single entry point — full portal page content, questionnaire document text, and the prefill research — and notes are professional commentary about public government websites. Redacting this one path while the others send everything would present a more careful privacy posture than the platform actually has, and would degrade the labels for no real protection. No redaction, filtering, or transformation is applied.
- **A10**: Notes may be written in any language the assessors work in. The classifier is expected to read them as submitted; the labels it returns are drawn from the fixed set regardless of the language of the material, so a label never varies with the language it was derived from.
- **A11**: The stored label is the audit record. Should a later model version disagree with a stored label, the stored label stands as what was said at the time; it is not retrospectively corrected.

## Dependencies

- The existing comparison engine (`src/portal/discrepancy.py`), whose disputed set is this feature's input and whose rate and flag this feature must leave untouched.
- The existing recomputation call sites on the portal submission path (`src/portal/assessor.py`), the programmatic path (`src/api/routers/human.py`), and the seed script (`src/portal/seed.py`).
- The read-only computation used by display routes (`src/portal/admin.py`), which must remain free of model invocation.
- The assessor submission record and its evidence, notes, suggestion-acceptance and timestamp fields (`src/shared/state/entities.py`).
- The reconciliation round machinery, its one-automatic-round cap, and the escalation queue (`src/portal/reconciliation.py`, `src/review/escalations.py`).
- The model provider through which all model invocation passes (`src/core/llm_factory.py`), and its existing model identity and usage reporting.
- The background job mechanism (`src/api/jobs.py`), so labelling runs off the submission path.
- Per-project tolerance and its process-wide default (`src/shared/config/settings.py`), unchanged by this feature but the parameter whose integrity D1 protects.

## Known Limitations

- **The feature's value is bounded by how much assessors write, and notes are deliberately left optional.** Where notes are thin, most disputes over a shared source will be labelled insufficient, and the labels that survive will be the two derivable from cited URLs alone. This is a known and accepted risk taken in preference to imposing a mandatory field before there is evidence it is needed: FR-DL-074 makes the resulting proportion observable, so the decision can be revisited against a real figure. A high insufficient rate is a finding about the feature, not a defect in it.
- **The distinction between describing different content and judging the same content differently is the hardest the classifier makes**, and it is the one the ambiguity measure depends on. It rests entirely on how precisely assessors describe what they saw. Where that distinction cannot be drawn confidently the result is the insufficient label, which protects the measure at the cost of coverage.
- **Portal volatility is inferred, never observed.** No page content is captured at the time of assessment, so a same-source content difference cannot be distinguished from a portal that changed between the two visits other than by the interval between submissions. Capturing evidence at submission time would settle it and is not in scope here.
- **A label is a model's characterisation and carries no warrant beyond its provenance.** It is presented to a reviewer as description, and every process outcome remains determined by the boolean comparison and by people. Nothing in this feature should be read as validating a label's accuracy.
- **A prolonged provider outage permanently blanks the units labelled during it.** Because a unit's pass runs once, restoring the provider does not bring those units back into scope, and no later event will. The affected disputes are visibly marked as attempted-and-unlabelled rather than lost silently, and they are unaffected in every other respect, but they stay unlabelled. An Administrator-triggered re-run over a named set of units would close this gap and is deliberately not specified here; nothing above would have to change to accommodate one.
- **Assessment free text leaves the platform.** Notes written by assessors are sent verbatim to the external model provider, and are subject to that provider's handling and retention terms rather than the platform's. This is the same provider and the same entry point the platform already uses for portal content, questionnaire documents and prefill research, so labelling widens what is already sent rather than opening a new channel — but it does widen it, to include text written by named assessors rather than text retrieved from public sources. It is recorded here so that any data-handling review of the platform sees it stated rather than having to discover it. FR-DL-039 fixes the set of content that may be sent, so the surface cannot grow without a change to this specification.
- **The confinement of a Senior Reviewer's view to their own project is presentational, not enforced.** The platform has no permission model — the only roles it models are the two assessors — so FR-DL-067 constrains what each surface presents, not what a determined request could retrieve. This feature does not introduce authorisation and must not be read as having done so; if one is added later, these requirements state what it would need to enforce.
- **Identity remains claimed rather than verified**, as it is throughout the portal. Per-side observations are attributed to the role that submitted, with the same trust properties as every other attribution in the assessment process.

## Out of Scope

- Any change to the differing-answer rate, the tolerance, the comparison, or the conditions under which a unit is flagged.
- Diverting, excusing, deferring or discounting a dispute on the basis of its label, including sparing a unit's automatic reconciliation round for access-related disputes.
- Any change to assessor-facing surfaces, including showing labels in the reconciliation workspace.
- Introducing authorisation, a permission model, or any enforcement of the Senior Reviewer / Administrator distinction beyond what each surface presents.
- Making notes mandatory, on divergence from the AI suggestion or otherwise.
- Any AI participation in resolving a disagreement, selecting an answer, arbitrating between assessors, or signing off a unit.
- Fetching, scraping or re-verifying portals to determine which assessor is correct.
- Labelling agreements — characterising indicators where the two assessors gave the same answer, including detecting agreement reached by unrelated reasoning.
- Any change to how the AI assessor agents disagree with each other, or how the resolver settles them.
- Rewriting or editing indicators identified as ambiguous. This feature produces the measure; acting on it is questionnaire work.
- Notifying anyone outside the portal that a dispute carries a particular label.
- Retrospective labelling of disputes from previous cycles.
