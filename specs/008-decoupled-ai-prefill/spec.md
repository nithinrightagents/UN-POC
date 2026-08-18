# Feature Specification: Decoupled AI Prefill

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Created**: 2026-08-18
**Status**: Draft
**Input**: The AI will not be in the loop with the human for the questionnaire. It should provide a prefill, and the human decides whether to use it or not. Defining the prefill: the questionnaire is loaded, then we search past questionnaires, then the MSQ, then the internet. Two assessor agents do that in parallel. They are validated, then assessed for discrepancy. Based on the discrepancy, the best combination of both assessors' outputs is validated and then delivered as a prefill.

## Overview

Today the AI and the humans share one loop. The assessment pipeline produces an adjudicated answer that is treated as an outcome in its own right: when the two AI assessors cannot be reconciled the question is parked as a human work item and a person is required to unblock the machine, and when no human ever answers a question the AI's own answer is what gets published. The AI therefore both consumes human attention and, in the gap where humans are silent, decides. Neither is what this platform is supposed to do — the AI's role is to save the two human assessors time, not to take a position that stands on its own.

This feature separates the two loops completely. The AI side runs to completion on its own and its only output is a **prefill**: a per-question suggested answer carrying its evidence, its confidence, and how it was arrived at. The human side reads that prefill as a starting point and decides, per question, to use it, change it, or ignore it entirely. The AI never waits on a human, never creates work for a human, and never supplies an answer that counts as anyone's assessment.

What closes the loop on the human side is that the assessor cannot leave a question blank. Every indicator needs an explicit yes or no from them, and where they cannot verify something the answer is **no**, not a gap. That single rule is what lets the AI be removed from publication outright: because a completed assessment covers the whole questionnaire, there is never a hole for an AI answer to fill, and every published score is computed over the same complete indicator set — so two countries' scores remain comparable in the same ranking table, which they would not be if assessors could stop half way.

Producing that prefill is a fixed sequence. The questionnaire's indicators are loaded for the unit being assessed. For each indicator the evidence to examine is located through an ordered cascade — past questionnaires first, then the government's own MSQ submission, then an internet search — where a later source is consulted only when the earlier ones yield nothing usable. Two assessor agents then work that evidence **in parallel and independently**, each producing its own answer, confidence, and justification, and each passing its own validation before it counts. The two validated positions are then compared. Where they agree, that answer stands. Where they disagree, a **resolver agent** examines what the disagreement actually is, determines which position is correct, and that becomes the answer — the dispute is settled by the AI, not handed to a person. The resulting single position is validated once more, as a position in its own right, and only what survives that second gate is offered as the prefill. Anything that does not survive it is delivered as a prefill with no suggestion and a stated reason, which is a perfectly good outcome — the assessor simply starts that question from scratch, exactly as they would have without any AI at all.

The end of a run is therefore one prefilled questionnaire per unit: every indicator carrying at most one suggested answer, with the evidence behind it and an honest signal of how contested it was.

## Decisions Taken

Three points were underspecified by the original input and are consequential enough to name. D1 and D2 were settled by the requester during specification; D3 follows directly from the input's core statement and is recorded here rather than left implicit.

- **D1 — Confirmed: the assessor cannot leave a question blank, so the gap the AI used to fill no longer exists.** Every indicator requires an explicit yes or no from the assessor; where they cannot verify something, the answer is **no**, not a blank. Because a completed assessment covers the whole questionnaire, the AI prefill is never reached at publication and is removed from the precedence chain outright. This supersedes the final term of `specs/007-headless-rest-api/spec.md` FR-API-032 (**adjudicated AI answer**) and the running system's further fallback to the heuristic pre-fill row. That spec's FR-API-023 is superseded too, in that a question with no suggestion now reports the reason taxonomy of FR-PF-034 rather than spec 004's blank-field reasons. It also preserves score comparability, which a human-only chain would otherwise have broken: the published score's denominator counts only answered questions, so partial coverage would have turned a whole-questionnaire score into a partial-coverage one and made two units with different completion rates incomparable in the same ranking table. Mandatory completion removes that failure mode rather than merely disclosing it. See FR-PF-005 and FR-PF-005a–005e.
- **D2 — Confirmed.** Where the two validated assessors agree on the answer, that answer stands as the prefill. Where they disagree, a **resolver agent** examines what the disagreement actually is, determines which position is correct, and that becomes the answer. Either way the run ends with one prefilled questionnaire — a single suggested answer per indicator, never a pair of competing ones. See FR-PF-024 and FR-PF-026.
- **D3 — AI-side disagreement creates no human work item.** It is recorded as prefill metadata and operator telemetry only. The escalation queue continues to serve human A/B discrepancy, which is untouched. See FR-PF-002.

## Clarifications

### Session 2026-08-18

- Q: The unit lifecycle has exactly three terminal outcomes (delivered, escalated, unassessable) with an exhaustive-coverage guarantee. Since the AI no longer escalates, where does a prefill that produced no suggestion terminate? → A: A distinct no-suggestion terminal outcome of its own. The existing unassessable outcome keeps its narrower meaning (evidence could not be located) so historical records do not silently change meaning, the escalated outcome becomes unreachable from a prefill run, and the specific reason is carried on the prefill rather than encoded in the outcome.
- Q: A unit cannot be published until an assessor's work on it is complete — what makes it complete? → A: An explicit act by the assessor, never inferred from every indicator happening to have an answer. The action is blocked until every indicator is answered, and it records which role, which person, and when. Publication checks for that declaration, not merely for a full set of answers.
- Q: Must the headless programmatic interface (spec 007) keep pace with what this feature adds and changes? → A: Yes, full parity. Prefill retrieval, the completion declaration, and publishing under the revised rules are all reachable programmatically. This is forced rather than optional: publication now requires a completion declaration, so an interface that cannot make one could never publish again.
- Q: Should an unattended prefill run have a spending limit, given nothing currently stops one? → A: Yes. A run halts when its recorded spend passes a configured budget; the indicator in flight finishes, no further indicators are dispatched, and those never reached receive a no-suggestion prefill with a budget-reached reason. Re-running resumes them. An unset budget means no cap, preserving today's behaviour.
- Q: "Discrepancy" already means the two humans disagreed. What should the AI-side equivalent be called? → A: Renamed throughout to the **resolver agent**, with the comparison it acts on called the agreement outcome and its output the resolver decision. "Discrepancy" is reserved for the human A/B path — its threshold, its cases, and its escalation queue — so the two can never be wired together by name. "Adjudicator" was also avoided, being taken by the existing mechanical comparison.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An assessor starts from a prefilled questionnaire and keeps full authority (Priority: P1)

A human assessor opens a unit's questionnaire and finds each indicator already carrying a suggested answer, the evidence URL it came from, a confidence, and a short justification. For each question they either take the suggestion as-is, take it and change something, or disregard it and answer independently. What they cannot do is skip it: every indicator needs an explicit yes or no before their assessment of that unit is complete, and where they cannot verify something the answer is no. Whatever they decide, the answer recorded is theirs.

**Why this priority**: This is the feature's entire purpose — the AI exists to accelerate the human, and an accelerator the human cannot freely override or ignore is not an accelerator. Requiring an answer on every indicator is the other half of the same idea: it is what makes the human, rather than the AI, the source of every published answer. Every other story serves this one.

**Independent Test**: For a unit with prefills present, have an assessor accept some prefills unchanged, modify others, and answer the rest independently, then confirm that the recorded submissions are exactly what the assessor entered, that no untouched question acquired an answer, that the assessor was never blocked from answering any question regardless of what the prefill said, and that attempting to complete the unit with an indicator outstanding is refused and names it.

**Acceptance Scenarios**:

1. **Given** a unit whose prefill run has completed, **When** an assessor opens that unit's questionnaire, **Then** each question shows its prefilled suggestion together with the evidence URL, confidence, and justification behind it.
2. **Given** a prefilled question, **When** the assessor accepts the suggestion without change, **Then** an answer is recorded attributed to that assessor, and the record notes that it matched the prefill.
3. **Given** a prefilled question, **When** the assessor submits an answer that differs from the suggestion, **Then** the assessor's answer is what is recorded, with no warning, confirmation step, or approval required to depart from the prefill.
4. **Given** a prefilled question the assessor has not yet acted on, **When** they attempt to mark the unit complete, **Then** completion is refused and the outstanding indicators are named — the prefill never stands in as their answer, and an explicit yes or no is required for every indicator.
5. **Given** a question the assessor cannot verify from any evidence, **When** they answer it, **Then** they record an explicit **no** rather than leaving it blank, and that no is a real assessment attributed to them.
6. **Given** a unit with no prefill run ever performed, **When** an assessor opens it, **Then** every question is answerable normally with the suggestion area shown as empty, and nothing about the workflow is blocked.
7. **Given** a question whose answer was settled by the resolver agent, **When** the human assessor views it, **Then** they see one suggested answer, together with the position that was not selected and the fact that the question was contested, so they know how much to lean on it before deciding.
8. **Given** an assessor part-way through a unit, **When** they leave and return, **Then** their saved answers are intact and the unit is shown as incomplete with the outstanding indicators identified.
9. **Given** an assessor who has answered every indicator on a unit, **When** they have not yet declared their assessment complete, **Then** the unit is not publishable — a full set of answers alone does not finish it.
10. **Given** an assessor who has answered every indicator, **When** they declare their assessment complete, **Then** the declaration is recorded against their role and person with the time, and the unit becomes eligible for publication once the other required role has done the same.
11. **Given** an assessor who has declared completion, **When** they revise one of their answers, **Then** the answer is updated and the unit remains complete, because every indicator still carries an answer.

---

### User Story 2 - The prefill is produced end to end with no human involvement (Priority: P1)

An operator triggers prefill generation for a unit and it runs to completion on its own — locating evidence, running both assessors, validating each, settling any disagreement between them, and validating the result again — producing a prefill for every indicator in the questionnaire without at any point requiring a person to answer a question, resolve a conflict, or approve a step.

**Why this priority**: "The AI is not in the loop with the human" is only true if the AI side can finish alone. A pipeline that stops and waits for a person on hard questions is exactly the coupling this feature removes, so this is co-equal with User Story 1.

**Independent Test**: Trigger a prefill run for a unit whose indicator set includes questions the AI handles confidently, questions where the two agents disagree, and questions with no usable evidence. Run it with no human interacting at all and confirm it reaches completion, that every indicator ends with a prefill record, and that no human work item was created by the run.

**Acceptance Scenarios**:

1. **Given** a unit and its cycle's loaded questionnaire, **When** prefill generation is triggered, **Then** the run proceeds unattended and terminates on its own, producing one prefill record per indicator in the questionnaire.
2. **Given** an indicator whose two assessor agents reach different answers, **When** the run processes it, **Then** the resolver agent settles it into a single prefilled answer and the run continues, without creating a human task and without leaving the question for a person.
3. **Given** an indicator for which no usable evidence can be located, **When** the run processes it, **Then** it produces a prefill carrying no suggestion together with the reason, and continues to the next indicator.
4. **Given** a completed prefill run, **When** the human work queues are inspected, **Then** the run has added nothing to them.
5. **Given** a prefill run in progress, **When** an assessor opens the same unit, **Then** they can answer questions immediately, seeing prefills for the indicators already completed and empty suggestions for the rest, with neither side waiting on the other.

---

### User Story 3 - Evidence is located through the ordered source cascade (Priority: P2)

For each indicator, the system looks for the evidence to assess in a fixed order — past questionnaires from prior survey cycles, then the government's MSQ submission for that unit, then an internet search — moving to the next source only when the previous one produced nothing usable, and records every source it tried and why each was accepted or rejected.

**Why this priority**: The prefill is only as trustworthy as where its evidence came from, and the cheapest, most authoritative sources must be exhausted before an open web search. It is below the first two stories because the prefill mechanism is what delivers value; the ordering makes that value defensible and auditable.

**Independent Test**: Run prefill generation for indicators contrived so that the first source succeeds, only the second succeeds, only the third succeeds, and none succeed, then confirm the correct source supplied each resolved link, that later sources were not consulted once an earlier one succeeded, and that the full attempt history is recorded in every case.

**Acceptance Scenarios**:

1. **Given** an indicator whose answer is available in a prior cycle's questionnaire data, **When** evidence is located for it, **Then** that source supplies the link and neither the MSQ nor an internet search is consulted.
2. **Given** an indicator with nothing usable in prior questionnaires but present in the unit's MSQ submission, **When** evidence is located, **Then** the MSQ supplies the link and no internet search is performed.
3. **Given** an indicator absent from both prior questionnaires and the MSQ, **When** evidence is located, **Then** an internet search is performed and its result is used if usable.
4. **Given** any indicator, **When** evidence location completes, **Then** every source consulted is recorded with its order, what it returned, whether that was usable, and the reason for any rejection.
5. **Given** an indicator where every source in the cascade fails, **When** evidence location completes, **Then** the indicator proceeds to a no-suggestion prefill naming the exhausted cascade as the reason, without either assessor agent being run for it.
6. **Given** a located evidence link from any source, **When** the assessors run, **Then** each one examines that evidence directly rather than treating the source's own record as the answer.

---

### User Story 4 - Two assessors run in parallel, and a resolver agent settles what they dispute (Priority: P2)

Each indicator is assessed by two agents working at the same time and independently of one another, neither seeing the other's position. Each position must pass validation to count. Where the two validated positions agree, that answer stands. Where they disagree, a resolver agent examines what the disagreement actually is, determines which position is correct, and that becomes the answer. Either way the indicator ends with exactly one suggested answer.

**Why this priority**: Two independent looks, with a dedicated agent to settle what they dispute, are what make a prefill worth showing rather than a single model's guess — and what let the AI finish a contested question by itself instead of handing it to a person. It sits below evidence location because positions built on the wrong evidence are worse than useless however they are settled.

**Independent Test**: For indicators engineered to produce agreement, agreement with divergent confidence, and outright answer disagreement, confirm the two agents ran concurrently and independently, that only validated positions counted, that the resolver agent was invoked on the disagreement and only on the disagreement, and that every indicator ended with exactly one suggested answer.

**Acceptance Scenarios**:

1. **Given** an indicator with usable evidence, **When** it is assessed, **Then** two assessor agents run concurrently, neither is given the other's answer, confidence, or justification, and the elapsed time is materially less than running them one after the other.
2. **Given** both agents have produced positions, **When** the positions are considered, **Then** each is validated independently and a position that fails validation does not count toward the outcome.
3. **Given** two validated positions that both answer yes, **When** the outcome is determined, **Then** the prefill's answer is yes, the resolver agent is not invoked, and the prefill is marked uncontested with a confidence reflecting the strength of the agreement.
4. **Given** two validated positions that agree on the answer but differ sharply in confidence, **When** the outcome is determined, **Then** the agreed answer still stands, the resolver agent is still not invoked, and the confidence gap is recorded and reduces the prefill's confidence.
5. **Given** two validated positions where one answers yes and the other no, **When** the outcome is determined, **Then** the resolver agent examines both positions with their evidence, characterizes the disagreement, determines which is correct, and that determination becomes the prefill's single answer, recorded with its reasoning and at a confidence reflecting that the question was contested.
6. **Given** a disagreement settled by the resolver agent, **When** the assessor views the question, **Then** they see one suggested answer, and the position that was not selected is visible alongside it rather than hidden.
7. **Given** a disagreement the resolver agent cannot settle, **When** the outcome is determined, **Then** the prefill carries no suggestion and the unresolved-disagreement reason, and no human work item is created.
8. **Given** only one position survives validation, **When** the outcome is determined, **Then** no suggestion is produced, the insufficient-positions reason is recorded, and the resolver agent is not invoked to assess the lone position.
9. **Given** a completed run over a full questionnaire, **When** the assessor opens the unit, **Then** every indicator that produced a suggestion shows exactly one suggested answer — one prefilled questionnaire, not a set of choices.

---

### User Story 5 - Only a validated position is offered, and nothing is escalated (Priority: P2)

The single resolved position — however it was arrived at — is validated once more, on its own terms, before it is shown to anyone. What passes becomes the suggestion. What fails is delivered as a prefill with no suggestion and a stated reason — never as a task in someone's queue.

**Why this priority**: The second gate is what stops a merge of two shaky positions from being presented as a confident suggestion, and withholding rather than escalating is the concrete mechanical form of "the AI creates no human work". Both are essential to the feature being honest, but only after there is something to gate.

**Independent Test**: Construct resolved positions that pass and fail the final validation, confirm the passing ones become suggestions and the failing ones become no-suggestion prefills carrying their reason, and confirm across the whole run that no AI-side outcome produced a human queue item.

**Acceptance Scenarios**:

1. **Given** a resolved position, **When** it is validated as a position in its own right, **Then** only a position that passes is offered as a suggestion.
2. **Given** a resolved position that fails the final validation, **When** the prefill is written, **Then** it carries no suggestion and states that the resolved position failed validation, and the assessor sees an empty suggestion for that question.
3. **Given** an indicator that reaches a no-suggestion prefill for any reason — no usable evidence, insufficient validated positions, unresolved disagreement, or failed final validation — **When** the run completes, **Then** the specific reason is recorded and distinguishable from the other reasons.
4. **Given** any AI-side disagreement or failure during the run, **When** the run completes, **Then** no escalation work item and no arbitration task has been created by it.
5. **Given** a completed run over a full questionnaire, **When** its outcomes are summarized, **Then** an operator can see how many indicators produced a suggestion and how many produced each kind of no-suggestion reason.

---

### User Story 6 - Prefill is regenerated freely without disturbing human work (Priority: P3)

An operator re-runs prefill generation for a unit — because evidence changed, an MSQ arrived, or an earlier run was incomplete. The newer prefills replace what the assessors see as suggestions, and nothing an assessor has already submitted is altered.

**Why this priority**: Decoupling is only real if either side can move without permission from the other, and re-running is the common case where the two could collide. It ranks last because a single successful run already delivers the feature's value.

**Independent Test**: Run prefill generation for a unit, have assessors submit answers to some questions, re-run generation, and confirm every prior human submission is unchanged and still attributed to its assessor, while the suggestions shown reflect the newer run.

**Acceptance Scenarios**:

1. **Given** a unit whose assessors have already submitted answers to some questions, **When** prefill generation is re-run, **Then** every existing human submission is unchanged in answer, evidence, notes, and attribution.
2. **Given** a re-run that produces a different suggestion for a question an assessor already answered, **When** that assessor reopens the question, **Then** their own submitted answer is still what stands, with the newer suggestion shown alongside it rather than replacing it.
3. **Given** a re-run of a unit whose previous run was interrupted part-way, **When** it completes, **Then** every indicator has a prefill record, including those the interrupted run never reached.
4. **Given** multiple prefill runs for the same question, **When** the assessor's screen is rendered, **Then** the most recent completed prefill is the one shown.
5. **Given** a re-run in progress, **When** an assessor submits an answer at the same moment, **Then** the submission succeeds and is not lost or rejected because of the run.

### Edge Cases

- The questionnaire loaded for a cycle has no indicators: the prefill run completes immediately having produced nothing, and reports that rather than failing.
- An indicator's evidence is located but the page cannot be reached or read when the assessors try to examine it: the indicator resolves to a no-suggestion prefill naming the unreachable evidence, and the run continues to the remaining indicators.
- Both assessor agents fail outright (provider unavailable, timeout): the indicator resolves to a no-suggestion prefill naming the failure, and the run does not abandon the remaining indicators.
- The two agents agree on the answer but each cites a different evidence URL: the agreed answer stands without invoking the resolver agent, and both URLs are recorded so the assessor can see each place the answer was found.
- The resolver agent selects a position whose evidence then fails the final validation of the resolved position: the indicator resolves to a no-suggestion prefill carrying the failed-validation reason, rather than falling back to the position the resolver agent rejected.
- The evidence page is in a language the platform does not support: the indicator resolves to a no-suggestion prefill naming the language, rather than a suggestion derived from a page the pipeline cannot read reliably.
- An indicator is flagged as requiring authenticated access, or every agent hits a login wall: the indicator resolves to a no-suggestion prefill naming the access boundary, with no attempt to guess an answer.
- An assessor opens a unit while its prefill run is still in flight: completed indicators show suggestions, the rest show empty suggestions, and the assessor is never blocked from answering any of them.
- The budget is reached part-way through a run: the indicator in flight finishes, no further indicators are dispatched, the rest receive budget-reached prefills, and the run reports as completed with that reason counted — not as a failure.
- A prefill run is triggered for a unit that already has one in flight: only one run proceeds, and both triggers report the same run.
- A prefill exists for an indicator that was later removed from the questionnaire: it is not shown to the assessor, and it does not appear in the run summary as an assessable indicator.
- Both human assessors ignore every prefill on a unit: the unit's answers are entirely theirs and the published result reflects only their answers, with the prefills leaving no trace in the score.
- Every question on a unit has a prefill but no human has answered anything: the unit is neither completable nor publishable, and the prefills are never published as though they were assessments.
- An assessor answers most of a unit and stops: their work is saved and resumable, but the unit stays incomplete and unpublishable until every indicator carries an explicit answer from them.
- An assessor genuinely cannot verify an indicator from any evidence: they answer no, which is a real assessment, rather than skipping it — "unverifiable" and "not present" resolve to the same published answer by design.
- An indicator is added to the questionnaire after an assessor completed a unit: the unit reverts to incomplete for that assessor until the new indicator is answered, rather than publishing as though it did not exist.

## Functional Requirements *(mandatory)*

#### Decoupling: the AI produces suggestions, never answers

- **FR-PF-001**: The AI prefill pipeline MUST run to completion without requiring any human input, decision, or approval at any point in its execution.
- **FR-PF-002**: The prefill pipeline MUST NOT create any human work item — no escalation queue entry, arbitration task, or review assignment — as a result of any AI-side disagreement, low confidence, or failure. AI-internal disagreement MUST be recorded as prefill metadata and operator-visible telemetry only.
- **FR-PF-003**: A prefill MUST NOT constitute an answer by, or on behalf of, any assessor. An answer MUST be recorded only when a human submits one.
- **FR-PF-004**: A question for which a prefill exists but no human has submitted an answer MUST be treated as unanswered by every downstream consumer, including scoring, publication, and completeness reporting.
- **FR-PF-005**: The AI prefill MUST be excluded from the publication precedence chain entirely. The final answer for a question MUST be determined from human submissions alone — an arbitration-resolved answer, then agreement between the two assessors, then a single assessor's answer. This supersedes the final term of `specs/007-headless-rest-api/spec.md` FR-API-032 and removes the running system's further fallback to the heuristic pre-fill row.
- **FR-PF-005a**: An assessor MUST give an explicit answer for every indicator on a unit. A blank MUST NOT be a valid terminal state for a question — it MUST represent only work not yet done.
- **FR-PF-005b**: Where an assessor cannot verify an indicator from any evidence, they MUST record an explicit negative answer rather than leaving it blank. That negative MUST be a real assessment attributed to them, indistinguishable in the record from any other negative answer they give.
- **FR-PF-005c**: An assessor MUST be able to save partial work and resume it, and MUST be prevented only from marking their assessment of a unit **complete** while any indicator remains unanswered. A refused completion MUST name the outstanding indicators rather than failing generically.
- **FR-PF-005d**: A unit MUST NOT be publishable until each assessor whose answers the precedence chain requires has explicitly declared their assessment of that unit complete. Every indicator carrying an answer is a precondition of that declaration, never a substitute for it. Because completion is mandatory, no published question MUST ever lack a human answer, and the precedence chain MUST NOT need a fallback for one.
- **FR-PF-005e**: Where an indicator is added to a questionnaire after an assessor has completed a unit, that unit MUST revert to incomplete for that assessor until the new indicator is answered, and MUST NOT remain publishable in the meantime.
- **FR-PF-005f**: Completion MUST be an explicit act performed by the assessor and MUST NOT be inferred from every indicator happening to carry an answer. The act MUST be refused while any indicator is unanswered, and the resulting record MUST carry the assessor role, the acting person, and when they declared it.
- **FR-PF-005g**: An assessor MUST be able to revise an answer after declaring completion, and doing so MUST leave the unit complete, since every indicator still carries an answer. Only an indicator left without an answer — per FR-PF-005e — MUST revert the unit to incomplete.
- **FR-PF-005h**: An assessor MUST be able to see, before declaring completion, how many of the unit's indicators they have answered and which remain outstanding, so completion is never a guess.
- **FR-PF-006**: The prefill pipeline and the human assessment workflow MUST be able to proceed concurrently for the same unit, with neither blocking, delaying, or invalidating the other.
- **FR-PF-007**: The human assessor workflow MUST remain fully usable for a unit that has no prefill at all, with an empty suggestion shown per question and no step of the workflow blocked or altered.

#### Human decision over the prefill

- **FR-PF-008**: For each question, an assessor MUST be shown the prefill's suggested answer together with the evidence URL, confidence, and justification it was derived from.
- **FR-PF-009**: An assessor MUST be able to accept the suggestion unchanged, submit a different answer, or defer the question and return to it later, with no confirmation, justification, or approval required to depart from or ignore the suggestion. Deferral MUST be temporary only — per FR-PF-005a an explicit answer is required before the unit can be completed.
- **FR-PF-009a**: A prefill's suggestion MUST NOT be recorded as an assessor's answer by default, by timeout, or by the assessor completing the unit without acting on that question. Every recorded answer MUST come from a deliberate act by the assessor.
- **FR-PF-010**: A submitted answer MUST be recorded as the assessor's own, attributed to that assessor, regardless of whether it matches the prefill.
- **FR-PF-011**: Each submission MUST record what the prefill suggested at the time and whether the assessor's answer matched it, so the prefill's usefulness can be measured without that record affecting the answer itself.
- **FR-PF-012**: A prefill MUST be shown identically to both assessor roles and MUST NOT expose either role's submissions to the other — the prefill is not a channel through which A and B can observe one another.
- **FR-PF-013**: Where a prefill's answer was settled by the resolver agent, the position that was not selected MUST be visible to the human alongside the single suggestion, together with the fact that the question was contested, so a settled dispute is recognizable as one that occurred.

#### Evidence location cascade

- **FR-PF-014**: For each indicator, evidence MUST be located through an ordered cascade of sources: past questionnaires from prior survey cycles, then the unit's MSQ submission, then an internet search.
- **FR-PF-015**: A later source MUST be consulted only when every earlier enabled source has yielded no usable result.
- **FR-PF-016**: Every source consulted MUST be recorded with its position in the order, what it returned, whether that result was usable, and the reason for rejection where it was not.
- **FR-PF-017**: A located evidence link MUST be examined directly by the assessor agents before any answer is produced from it; a source's own stored record MUST NOT be accepted as the answer without that examination.
- **FR-PF-018**: When every source in the cascade fails to yield usable evidence, the indicator MUST resolve to a prefill with no suggestion, carrying the exhausted-cascade reason, and MUST NOT dispatch either assessor agent.

#### Parallel independent assessment

- **FR-PF-019**: Each indicator with usable evidence MUST be assessed by two assessor agents running concurrently.
- **FR-PF-020**: The two agents MUST be independent: neither MUST be given the other's answer, confidence, justification, or evidence, and neither MUST be able to influence the other's position.
- **FR-PF-021**: Each agent's position MUST be validated independently, and a position that fails validation MUST NOT count toward the outcome.
- **FR-PF-022**: Each position MUST carry its answer, a confidence, a justification, and the evidence it relied on.

#### Agreement assessment and resolution

- **FR-PF-023**: The two validated positions MUST be compared for agreement on the answer, and whether they agree MUST determine how a single position is arrived at.
- **FR-PF-024**: Two validated positions agreeing on the answer MUST yield that answer as the prefill directly, without invoking the resolver agent, carrying a confidence that reflects the strength of the agreement and marked as uncontested.
- **FR-PF-025**: Two validated positions agreeing on the answer but differing in confidence beyond the configured tolerance MUST still yield that agreed answer — a confidence gap MUST NOT change the answer and MUST NOT invoke the resolver agent. The gap MUST be recorded and MUST reduce the prefill's confidence.
- **FR-PF-026**: Two validated positions disagreeing on the answer MUST be resolved by a **resolver agent**, which MUST examine both positions with their evidence and justifications, characterize what the disagreement actually is, determine which position is correct, and produce that as the single answer with its own reasoning. Its determination MUST become the prefill's answer.
- **FR-PF-026a**: The resolver agent MUST be invoked only where the two validated positions disagree on the answer, never as a routine third opinion on questions the assessors already agreed on.
- **FR-PF-026b**: The resolver agent's output MUST record the characterization of the disagreement, which position it selected, and why — so an assessor and an operator can both see how a contested question was settled.
- **FR-PF-026c**: The losing position MUST be retained and MUST be visible to the assessor alongside the suggestion, so a settled disagreement is still recognizable as one that occurred.
- **FR-PF-026d**: Where the resolver agent cannot determine which position is correct, the indicator MUST resolve to a prefill with no suggestion carrying the unresolved-disagreement reason. It MUST NOT create a human work item, and MUST NOT fall back to picking a position arbitrarily.
- **FR-PF-027**: The agreement outcome — uncontested, agreed with a confidence gap, or resolved by the resolver agent — MUST be recorded on the prefill and MUST be distinguishable by any consumer of it. A prefill resolved by the resolver agent MUST carry a confidence reflecting that it was contested.
- **FR-PF-028**: Arriving at a single position MUST require two validated positions. Where fewer survive validation, the indicator MUST resolve to a prefill with no suggestion carrying the insufficient-positions reason, and the resolver agent MUST NOT be invoked to assess a lone position.
- **FR-PF-028a**: Every indicator that produces a suggestion MUST produce exactly one suggested answer. The completed run MUST yield one prefilled questionnaire per unit — never a set of competing answers for the assessor to choose between.
- **FR-PF-029**: The confidence tolerance of FR-PF-025 MUST be configurable through the platform's existing settings mechanism rather than fixed in the pipeline.

#### Final validation and prefill delivery

- **FR-PF-030**: The single resolved position — whether it arose from the two assessors agreeing or from the resolver agent settling a disagreement — MUST be validated as a position in its own right before it is offered, independently of the per-agent validations that preceded it.
- **FR-PF-031**: Only a resolved position that passes that final validation MUST be offered as a suggestion.
- **FR-PF-032**: A resolved position that fails the final validation MUST produce a prefill with no suggestion carrying the failed-validation reason, and MUST NOT be shown as a suggestion at any reduced confidence.
- **FR-PF-032a**: A prefill run MUST terminate every indicator in one of exactly three outcomes: **delivered** (a suggestion was produced), **unassessable** (evidence could not be located, per FR-PF-018), or **no suggestion** (assessment ran but produced nothing offerable). The escalated outcome MUST be unreachable from a prefill run.
- **FR-PF-032b**: The unassessable outcome MUST retain its existing narrower meaning of evidence that could not be located, so records written before this feature keep the meaning they were written with. Every other no-suggestion reason of FR-PF-034 MUST terminate in the no-suggestion outcome.
- **FR-PF-032c**: The specific reason a prefill carries no suggestion MUST be recorded on the prefill itself rather than encoded in the terminal outcome, so the three outcomes stay stable while the reason taxonomy of FR-PF-034 can grow.
- **FR-PF-032d**: The guarantee that an indicator cannot leave the lifecycle without either a delivered suggestion or a recorded reason MUST continue to hold across the revised set of terminal outcomes.
- **FR-PF-033**: Every indicator in the loaded questionnaire MUST end a completed run with a prefill record — either a suggestion or a no-suggestion prefill with a reason. No indicator MUST be silently absent from the run's results.
- **FR-PF-034**: The reasons a prefill carries no suggestion MUST be individually distinguishable, covering at minimum: no usable evidence, evidence unreachable, unsupported language, access boundary, insufficient validated positions, unresolved disagreement, failed final validation, assessment failure, and budget reached.
- **FR-PF-035**: A prefill MUST record the evidence URL and the source that supplied it, so an assessor can see not only what was suggested but where it came from and how that place was found.

#### Running and re-running

- **FR-PF-036**: An operator MUST be able to trigger prefill generation for a unit against its cycle's loaded questionnaire, and the run MUST proceed in the background rather than holding the operator until it finishes.
- **FR-PF-037**: Prefill generation MUST be re-runnable for a unit at any time, including after assessors have submitted answers.
- **FR-PF-038**: A re-run MUST NOT modify, delete, or re-attribute any existing human submission.
- **FR-PF-039**: Where multiple prefills exist for the same question and unit, the most recent completed one MUST be the one shown to assessors.
- **FR-PF-040**: A prefill run MUST continue through the remaining indicators when an individual indicator fails, and MUST NOT abandon the run because of a single indicator's outcome.
- **FR-PF-041**: A completed run MUST report a per-unit summary of how many indicators produced a suggestion and how many produced each no-suggestion reason.
- **FR-PF-041a**: A prefill run MUST stop dispatching further indicators once its recorded spend for that run passes a configured budget. The indicator already in flight MUST be allowed to finish, so no indicator is ever left half-assessed by the cap.
- **FR-PF-041b**: Indicators a run never reached because the budget was reached MUST receive a no-suggestion prefill carrying the budget-reached reason, distinguishable from every other reason — so a budget stop still leaves every indicator with a prefill record per FR-PF-033, and the run reports as completed rather than failed.
- **FR-PF-041c**: The budget MUST be configurable through the platform's existing settings mechanism. An unset budget MUST mean no cap, preserving the behaviour of runs today.
- **FR-PF-041d**: A run MUST record the spend it reached and the budget in force, so an operator can tell a budget stop from a run that simply finished.
- **FR-PF-041e**: Re-running a unit after a budget stop MUST resume the indicators that were not reached, on the same terms as any other re-run.

#### Programmatic parity

- **FR-PF-042**: Every capability this feature adds or changes MUST be reachable through the existing programmatic interface as well as the portal — retrieving a unit's prefills, declaring an assessor's completion, and publishing under the revised rules — so no outside system is forced back to a browser to finish an assessment it started programmatically.
- **FR-PF-043**: Programmatic prefill retrieval MUST return, per indicator, either the single suggestion or the no-suggestion reason, together with the confidence, justification, evidence URL, supplying source, agreement outcome, and the position not selected where the resolver agent settled one. It MUST be keyed by the same question identifier the interface already uses for every other question-scoped operation.
- **FR-PF-044**: The completion declaration MUST be performable programmatically, naming exactly one assessor role and the acting person, and MUST be refused — naming the outstanding indicators — while any indicator is unanswered.
- **FR-PF-045**: The programmatic publish operation MUST enforce the same completeness gate and the same human-only precedence chain as the portal, and MUST refuse with a stated reason when a required role has not declared completion. A unit published through either surface MUST produce an identical score and breakdown.
- **FR-PF-046**: Prefill retrieval MUST NOT breach the blind A/B guarantee. Because a prefill is shown identically to both roles it carries no role scoping of its own, but the operation MUST NOT expose either role's submissions alongside it.
- **FR-PF-047**: The existing programmatic AI-results operation MUST report the no-suggestion reason taxonomy of FR-PF-034 for a question that produced no suggestion, superseding the blank-field reasons it derives from spec 004 today.
- **FR-PF-048**: The operations added here MUST be gated by the interface's existing access control, with no separate or additional authentication mechanism introduced.

### Key Entities

- **Prefill**: The pipeline's per-question, per-unit output offered to human assessors. Carries either exactly one suggested answer with its confidence, justification, evidence URL, and supplying source, or no suggestion together with the specific reason none is available. Also carries the agreement outcome, the position not selected where there was a disagreement, and which run produced it. It is a suggestion, never an answer.
- **Assessor Position**: One assessor agent's independent output for one indicator on one unit — its answer, confidence, justification, evidence, and validation outcome. Two exist per assessed indicator and both are retained; settling a disagreement selects between them without discarding the unselected one's record.
- **Agreement Outcome**: The recorded comparison of the two positions — agreed, agreed with a confidence gap, resolved by the resolver agent, or unresolved — together with the measured gap. It determines whether the resolver agent is invoked and is surfaced to the assessor as a signal about how much the suggestion can be leaned on. It creates no human task.
- **Resolver Decision**: The resolver agent's output for a contested indicator — its characterization of what the two assessors actually disagreed about, which position it determined to be correct, and the reasoning behind that determination. Produced only where the validated positions disagree on the answer, and retained so a settled dispute stays auditable.
- **Assessor Completion**: One assessor role's explicit declaration that their assessment of a unit is finished — carrying the role, the acting person, and when it was declared. It cannot be created while any indicator is unanswered, and it is what publication checks for. Distinct from the mere fact that every indicator has an answer.
- **Evidence Resolution Record**: The ordered history of which sources were consulted for an indicator, what each returned, and why each was accepted or rejected — the audit trail behind the evidence URL a prefill cites.
- **Prefill Run**: One triggered generation pass over a unit's questionnaire, carrying which unit and cycle it covered, when it ran, its progress and completion, and its per-reason outcome summary. Each indicator it touches ends in exactly one of three terminal outcomes -- delivered, unassessable, or no suggestion -- with the escalated outcome unreachable.

## Success Criteria *(mandatory)*

- **SC-001**: A prefill run over a full questionnaire completes without a single human input, decision, or approval, and adds nothing to any human work queue.
- **SC-002**: Every indicator in a completed run's questionnaire has a prefill record — 100% coverage, with no indicator silently missing and no run left partially reported.
- **SC-003**: An assessor can accept a suggestion, change it, or answer independently of it, and the answer recorded is exactly what they entered in every case, with no additional step required to depart from a suggestion.
- **SC-004**: No question ever acquires an answer that no human submitted — verified across a unit where every question has a prefill and no assessor has answered, which can be neither completed nor published.
- **SC-004a**: Every published unit carries an explicit human answer for 100% of its indicators, so no published score is computed over partial coverage and any two published units are directly comparable.
- **SC-004b**: An assessor is never able to mark a unit complete while an indicator is outstanding, and every refusal names which indicators are outstanding.
- **SC-004c**: A unit with every indicator answered but no completion declaration from a required role is never publishable, and every published unit carries a completion declaration from each required role naming who declared it and when.
- **SC-005**: Assessing an indicator with two agents in parallel takes materially less wall-clock time than assessing it with the same two agents in sequence, and neither agent's output varies with the other's.
- **SC-006**: Across indicators covering agreement, agreement with a confidence gap, and answer disagreement, the resolver agent is invoked on exactly the disagreements and on nothing else; every settled disagreement records what was disputed, which position was chosen, and why; and the unselected position remains visible to the assessor.
- **SC-006a**: Every indicator that produces a suggestion produces exactly one — a completed run yields one prefilled questionnaire per unit, with no indicator presenting the assessor a choice between competing answers.
- **SC-007**: No suggestion is ever shown that did not pass the final validation of the resolved position.
- **SC-007a**: No prefill run ever terminates an indicator in the escalated outcome, and every indicator it terminates carries either a delivered suggestion or a recorded reason -- verified across a run covering all of FR-PF-034's reasons.
- **SC-008**: Every no-suggestion prefill states a reason, and the reason is one of the distinguishable named reasons rather than a generic failure.
- **SC-009**: Across a source-cascade test matrix, the source recorded as supplying the evidence is the earliest usable one in the order in 100% of cases, and no later source was consulted after an earlier one succeeded.
- **SC-010**: After re-running prefill generation for a unit with existing human submissions, 100% of those submissions are unchanged in answer, evidence, notes, and attribution.
- **SC-011**: An assessor can open a unit and answer every question while a prefill run for that unit is in flight, with no submission blocked, delayed, or rejected because of the run.
- **SC-012**: For any question, the record shows what the prefill suggested and whether the assessor's answer matched it, enabling a per-cycle measure of how often prefills were taken — without that record having altered any answer.
- **SC-013**: A non-browser client can read a unit's prefills, declare each required role's completion, and publish — and the score and breakdown it receives are identical to what the portal produces for the same unit.
- **SC-014**: No programmatic operation added or changed by this feature is refused for want of a capability the portal has, and none introduces an access-control path of its own.
- **SC-015**: A run's recorded spend never exceeds its configured budget by more than the cost of the single indicator in flight when the cap was reached, and a run that stops on budget still leaves every indicator of the questionnaire with a prefill record.

## Assumptions

- **Terminology.** "Discrepancy" in this platform means the two *human* assessors disagreed — the existing discrepancy case, its threshold, and the escalation queue that follows. The AI-side comparison is the **agreement outcome**, the agent that settles it is the **resolver agent**, and its output is a **resolver decision**. The word "discrepancy" is deliberately not reused for any AI-side concept, so the two paths cannot be conflated by name. "Adjudicator" likewise keeps its existing meaning: the mechanical comparison of validated positions.
- The two human assessors' blind A/B methodology, their discrepancy threshold, arbitration, and the escalation queue that serves them are unchanged by this feature. Removing AI-side escalation does not touch the human-side escalation those surfaces exist for.
- Requiring an explicit answer per indicator means "could not verify" and "not present" resolve to the same published answer — a negative. This is deliberate and matches how an OSI-style indicator is scored: an affirmative requires evidence, so absence of evidence is a negative rather than a gap. It also means an assessor's negative answer carries no signal about whether they searched hard; that distinction, if wanted, belongs in their notes rather than in the answer.
- Mandatory completion is what removes the AI from publication, so the two are a single decision. If completion were ever relaxed to allow partial units, the question of what fills the gap would return and would need answering again.
- The prefill's existence does not lower the bar for an assessor's answer: they are expected to reach their own judgement on every indicator, and the prefill's role is to shorten how long that takes, not to substitute for it.
- "Past questionnaires", "MSQ", and "internet" correspond to the platform's existing prior-survey knowledge base, MSQ submission ingestion, and search-based link resolution. This feature fixes their order and their role in producing a prefill; it does not introduce new kinds of evidence source.
- Exactly two assessor agents is the configuration this feature specifies. The underlying capacity to run more is not removed, but the agreement and resolution rules here are defined over two positions.
- The per-agent validation that a position must pass is the platform's existing validation of an assessor's answer against its cited evidence. The final validation of the resolved position applies that same standard to it as a position in its own right.
- The resolver agent is a judgement step, not the platform's current mechanical adjudicator. Today adjudication is a deterministic comparison that produces a consensus only on unanimity and otherwise escalates; this feature replaces that escalation with an agent that reads both positions and their evidence and determines which is correct. It decides between the two existing positions — it does not go back to the portal to form a third opinion of its own.
- The resolver agent adds a model call only on contested indicators. Questions where the two assessors agree cost exactly what they cost today.
- A prefill is generated per question per unit. Loading the questionnaire scopes which indicators a run covers; it does not mean the questionnaire is prefilled as a single indivisible artifact.
- Prefill generation is triggered explicitly for a unit rather than running automatically on a schedule or on unit creation.
- The budget of FR-PF-041a is scoped to a single run of a single unit, not to a cycle, a session, or a calendar period. Aggregate spend control across many runs remains an operator concern served by the existing cost ledger.
- The confidence, justification, and evidence a position carries are the values the assessment already produces; this feature specifies how two of them are reconciled, not how either is derived.
- The suggestion an assessor sees today is not the output of the live pipeline — the assessor screen reads the fast heuristic pre-fill rows written for demo seeding, while the live multi-agent pipeline's adjudicated output goes elsewhere. This feature closes that gap: the prefill an assessor sees is the pipeline's own resolved, validated output. The heuristic path may remain as a seeding convenience but is no longer what the assessor screen reads.
- Operators remain able to see AI-side disagreement and failure rates as telemetry. Removing the human work item removes the obligation to act, not the visibility.

## Dependencies

- The existing questionnaire and indicator model, and the loaded indicator set for a cycle.
- The existing evidence-source implementations behind the cascade: prior-survey knowledge base lookup, MSQ submission ingestion, and search-based resolution, together with the usability test applied to what each returns.
- The existing assessor agent, its evidence traversal, and its structured position output including confidence, justification, and observed language.
- The existing validation of an assessor position against its cited evidence.
- The existing adjudication and discrepancy-case machinery, whose comparison of two validated positions is what the resolver agent's invocation condition is derived from, and whose escalation path this feature replaces.
- The existing human assessor portal, the A/B submission model, and its record of what the AI suggested and whether the human took it.
- The existing publication scoring, whose precedence chain this feature narrows to human answers only, and whose publish action this feature gates on complete human coverage.
- The existing per-question human submission model, extended with a per-role, per-unit completion declaration carrying the acting person and time.
- The existing settings mechanism, extended with the confidence tolerance of FR-PF-025 and the per-run budget of FR-PF-041c.
- The existing cost ledger, whose recorded spend is what the budget of FR-PF-041a is measured against.
- The existing background-run and telemetry facilities a prefill run records into.
- The existing programmatic interface of `specs/007-headless-rest-api`, its shared-secret access control, its background job-status model, and its rule that a question is addressed by one stored cycle-scoped identifier throughout.

## Out of Scope

- Any change to the two human assessors' blind A/B methodology, their discrepancy threshold, arbitration, or the escalation queue serving human discrepancy.
- Automatic acceptance of a prefill, bulk "accept all suggestions" actions, or any mechanism by which a prefill becomes an answer without a human submitting it.
- Publishing a unit with partial human coverage, including any senior-reviewer waiver or override of the completeness requirement.
- Distinguishing "assessed as not present" from "could not verify" in the recorded answer — both are a negative, and any nuance belongs in the assessor's notes.
- Introducing new evidence sources beyond past questionnaires, the MSQ, and internet search, or making the cascade order configurable per question.
- Changing how an individual assessor agent traverses evidence, forms a position, or computes its own confidence.
- Running more than two assessor agents per indicator.
- Invoking the resolver agent on questions the two assessors already agreed on, or having it form a fresh independent answer of its own rather than determining which of the two existing positions is correct.
- Scheduled, automatic, or on-creation prefill generation, and any push notification of run completion.
- Cancelling or pausing a prefill run in flight.
- Retroactively regenerating prefills across an entire cycle's units in one action.
- Any change to how a published score is computed from the answers that do exist, beyond removing the AI answer from the precedence chain and gating publication on complete human coverage.
- Authentication or per-user permissions around who may trigger a prefill run.
