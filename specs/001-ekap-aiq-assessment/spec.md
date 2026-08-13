# Feature Specification: EKAP AIQ — AI-Assisted Portal Assessment

**Feature Directory**: `specs/001-ekap-aiq-assessment`
**Created**: 2026-08-13
**Status**: Draft
**Input**: User description of EKAP AIQ — an AI-assisted assessment system automating the blind multi-assessor methodology for evaluating national government online service portals against a standardized questionnaire.

## Overview

Assessment of national government online service portals is currently performed manually: two in-country volunteers independently evaluate each indicator for their country, and a coordinator resolves the cases where they disagree. The method is sound — independence between assessors is what makes the result defensible — but it does not scale across the full country set and questionnaire, and the evidence each volunteer records is inconsistent in form and quality.

EKAP AIQ removes the manual crawl-and-read burden while preserving the two properties that make the existing method credible: **independence** between assessors, and **auditability** of every answer. The system produces evidence-backed draft answers; humans remain the deciding authority on every answer that is delivered.

The system does not score or rank countries. It produces validated answers to questionnaire items; downstream index computation is a separate concern.

## Terminology

These terms are used consistently throughout and must not be interchanged.

| Term | Meaning |
|------|---------|
| **Assessor Agent** | An AI component that independently evaluates one question against one target portal and produces an answer, confidence, justification, and evidence. There are N of these per question–portal pair, N ≥ 2. |
| **Assessor** | The human in the loop. Reviews pre-filled answers once a portal's questions are complete, and approves, edits, or rejects-and-overrides each one. Also works the escalation queue, answers language decisions, and may add custom questions. |
| **Validator** | An AI component that checks one Assessor Agent's output for quality and independently verifies its cited evidence online. Judges the Assessor Agent's work, never the question itself. |
| **Adjudicator** | The component that compares the N Assessor Agents' validated outputs, detects discrepancy, and produces a consensus answer and consensus confidence. |

"Assessor Agent" always denotes the AI; "Assessor" alone always denotes the human. Where a requirement concerns both, both terms appear explicitly.

## Clarifications

### Session 2026-08-13

- Q: Is there a workflow for comparing system answers against known correct answers? → A: Not in the spec — confirmed gap. SC-002, SC-003 and SC-008 depend on a benchmark comparison that no functional requirement provides. Whether it becomes a system capability remains open.
- Q: What checks an Assessor Agent's output for quality? → A: The Validator evaluates each Assessor Agent's output on its own merits before adjudication; quality gaps below a configured threshold trigger a per-agent retry (FR-076 through FR-085).
- Q: How is configuration supplied? → A: Environment configuration (`.env`), read at process start. FR-074 relaxed to permit a restart to pick up changes, while still forbidding code edits or rebuilds.
- Q: Does the Validator re-fetch the page, or judge only the captured artifact? → A: It independently fetches the cited URL and attempts to locate the Assessor Agent's cited evidence online; failure to find it fails validation (FR-086 through FR-091). Verification traffic shares the Assessor Agent rate-limit budget, and unreachable targets are attributed separately from quality failures.
- Q: Is comparing answers to known correct answers a system capability, an export, or manual? → A: A system capability — benchmark mode running the same pipeline against a stored labelled set, computing accuracy and related measures pre-human-review and comparing runs across configuration changes (FR-092 through FR-100).
- Q: What accuracy floor must consensus answers meet on the benchmark set, pre-human-review? → A: 80% overall, pooled across all benchmark pairs. Accuracy by question class and by numeric confidence band is reported but not gated (SC-002).
- Q: "Assessor" refers to both the AI and the human — which is which? → A: **Assessor Agent** is the AI; **Assessor** is the human in the loop who approves once a portal's pre-fill is complete. Terminology section added; all 179 occurrences disambiguated.
- Q: When does the human review a portal's answers? → A: Once every question for that portal has reached a terminal state — per portal over the complete pre-filled set, not question-by-question (FR-043a). Escalated questions appear within the set marked as such (FR-043b), and in-run touchpoints such as language decisions do not wait on portal completion (FR-043c).
- Q: Which defined state does a partially-assessed unit reach on resume (FR-067)? → A: Retain Assessor Agent Runs that reached a terminal state and run only the missing agents; any agent interrupted mid-run or mid-validation is re-run from scratch (FR-067a, FR-067b). Retaining terminal runs preserves independence and avoids re-spending the shared per-domain budget (FR-089).
- Q: How do delivered answers leave the system? → A: A per-cycle export of delivered answers as a structured dataset — answer, consensus confidence, evidence references, session identifier, and human attribution — generated on demand (FR-101 through FR-106). Publication and index computation remain out of scope; the export is the handoff boundary.
- Q: How is content behind a portal login handled? → A: Both a questionnaire attribute and runtime detection (FR-107 through FR-111). Questions known to require authenticated access are marked and routed straight to humans; an Assessor Agent that meets an authentication boundary at run time escalates rather than answering from the public page. The system never holds portal credentials.
- Q: What observability does the system need? → A: Run progress and outcomes, a structured stage-transition event record keyed on the session identifier with per-stage timings and per-domain fetch counts, and per-session model invocation and cost accounting attributable to stage and Assessor Agent (FR-112 through FR-118). This is what makes SC-011 and SC-012 measurable.
- Q: Which questions does the proof of concept assess? → A: **Module 2.1 — Institutional Framework only**, recorded verbatim in [poc-question-set.md](./poc-question-set.md). 16 question rows covering 26 indicator IDs; rows 12 and 13 expand into six sector variants each, so the set is modelled as 26 question records. All are binary existence checks. The full questionnaire remains the production target.
- Q: Where does the **link** come from? → A: An ordered chain of three link sources — (1) prior-survey KB, (2) MSQ submissions, (3) live internet search — each of the first two independently switchable by configuration (FR-121 through FR-128). **In all three cases the link is traversed live and the answer comes from what is found there**; no source ever supplies the answer itself (FR-124). This refines FR-001 through FR-007 rather than adding a second chain.
- Q: Is a "judge agent" a new component? → A: No — it is the **Validator** already specified (FR-076 through FR-091). No third agent type is introduced; the Adjudicator's comparison remains mechanical, with no model deciding which Assessor Agent is right.
- Q: How is confidence presented? → A: As a **numeric 0–100 percentage everywhere** — review surface, escalation queue, logs, telemetry, export. Named high/medium/low tiers are **removed**, and 75 becomes the single boundary on the scale, replacing the former 80 high-confidence line (FR-041, FR-042).
- Q: What happens when an Assessor Agent's own confidence is low? → A: A configurable acceptance threshold defaulting to 75, checked before validation. Below it, that agent is retried once with an addendum directing it to seek better evidence — never to report a higher number (FR-134 through FR-139). Still below after the retry, the answer is **delivered marked as low confidence, not escalated**; every answer reaches a human anyway, so low confidence is triage signal rather than a failure state.
- Q: On the live tier, how far may an Assessor Agent roam from the national portal? → A: Per-question evidence-locus attribute — `national_portal_only` or `any_government_domain` — set from each indicator's own wording (FR-129 through FR-133). Questions whose wording requires the portal are answered negative when the evidence exists only elsewhere; questions that merely assert existence may be evidenced from any government domain.
- Q: What constrains where assessed content is processed, and what may be sent to an external model service? → A: **Deferred — proof of concept.** Security and data-residency standards are not being set at this stage. No requirement is added. Recorded as a pre-production gate, not as a resolved question (see Out of Scope).
- Q: What accessibility and localization does the review surface need? → A: WCAG 2.1 Level AA conformance; interface language English only (FR-119, FR-120). Evidence and referenced element text remain in the portal's original language regardless (FR-026).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Assessor reviews a pre-filled answer (Priority: P1)

An Assessor opens a question for a given country and is presented with a proposed answer, a plain-language justification, a confidence level, and the evidence supporting it: the target URL that was assessed, a visual capture of the relevant region of that page, and a durable reference to the specific page element and its text. The assessor approves the answer, edits it, or rejects it and supplies their own. Every action is attributed to that person and timestamped.

**Why this priority**: This is the entire value proposition made visible. Without a review surface that presents a complete, self-contained evidence set, the automation produces nothing a human can responsibly sign off on. It is also the one story that can be demonstrated against seeded data with no assessment pipeline running at all.

**Independent Test**: Seed one pre-computed assessment with a complete evidence set. Verify that the review surface renders answer, justification, confidence, and all three evidence components; that approve, edit, and reject-and-override each persist correctly; and that each resulting record carries the acting person's identity and a timestamp.

**Acceptance Scenarios**:

1. **Given** a completed assessment with complete evidence, **When** an Assessor opens the question, **Then** the proposed answer, justification, numeric confidence as a percentage, resolved URL, visual capture, and referenced page element with its text are all displayed without the Assessor navigating to any external tool.
2. **Given** a displayed assessment, **When** the Assessor approves it, **Then** the answer is recorded as human-approved with the Assessor's identity and the approval timestamp, and the original system-proposed answer remains retrievable.
3. **Given** a displayed assessment, **When** the Assessor edits the answer and saves, **Then** the edited answer is recorded as the delivered answer, the original system-proposed answer is preserved unchanged, and the edit is attributed and timestamped.
4. **Given** a displayed assessment, **When** the Assessor rejects it and supplies an overriding answer, **Then** the override is recorded as the delivered answer with the rejection reason, and both the system answer and the override are retrievable from the audit trail.
5. **Given** an assessment where evidence capture failed or evidence is unresolvable, **When** the Assessor opens the question, **Then** the answer's confidence is capped below the acceptance threshold and the missing or broken evidence is explicitly identified.
6. **Given** any reviewed question, **When** the Assessor requests detail, **Then** each individual Assessor Agent's position and the adjudication outcome are visible.

---

### User Story 2 - System produces independent draft answers (Priority: P2)

For each question and target portal, N independent Assessor Agents evaluate the portal, where N is at least 2, is configurable, and defaults to 2. No Assessor Agent has visibility into any other agent's reasoning, answer, confidence, or evidence while it runs. Each returns a structured answer, a numeric confidence value, a justification, and cited evidence.

**Why this priority**: The independence property is what the existing manual methodology is built on and what the automation must not silently discard. Assessors configured identically and producing correlated outputs do not satisfy this story even if their individual answers are correct — correlated agreement is indistinguishable from a single Assessor Agent run twice, and it destroys the signal that discrepancy detection depends on.

**Independent Test**: Run the configured Assessor Agent set against a fixed portal and question set with no adjudication stage. Verify that each Assessor Agent produced a complete, independently-formed result; that no assessor's inputs contained another Assessor Agent's output; and that the population of results shows a non-degenerate spread (see SC-008).

**Acceptance Scenarios**:

1. **Given** a resolved target portal and a question, **When** the assessment runs with N=2, **Then** two Assessor Agent results are produced, each with a structured answer, numeric confidence, justification, and cited evidence.
2. **Given** Assessor Agent count configured to a value greater than 2, **When** the assessment runs, **Then** that many independent results are produced and all are retained.
3. **Given** any Assessor Agent Run, **When** its inputs are inspected in the audit trail, **Then** no other Assessor Agent's answer, confidence, justification, or evidence appears among them.
4. **Given** a completed Assessor Agent Run, **When** its confidence value is examined, **Then** that value is derived only from evidence quality and source authority observed by that assessor, and is recorded before any cross-assessor comparison occurs.
5. **Given** an Assessor Agent count configured below 2, **When** a run is started, **Then** the run is rejected with a clear message rather than silently proceeding with a single assessor.
6. **Given** a completed Assessor Agent output, **When** validation runs, **Then** the Validator independently fetches the cited URL, locates the referenced element, confirms its text matches what was recorded, and produces a quality score with any specific gaps found; the output is admitted to adjudication only if the score meets the configured validation quality threshold.
6a. **Given** a reachable page on which the referenced element cannot be located, or is located with text that does not match, **When** verification runs, **Then** validation fails with the specific discrepancy recorded as the quality gap.
6b. **Given** a target that is unreachable at verification time, **When** verification runs, **Then** the Assessor Agent's output is not failed on that basis; verification is deferred and re-attempted, and the pair escalates as an unverifiable target if the bound is exhausted.
6c. **Given** a successful verification, **When** it completes, **Then** the evidence carries a verification timestamp and a record that it was confirmed against the live page.
6d. **Given** any verification fetch, **When** it is issued, **Then** it observes the same access policies and per-domain rate limits as Assessor Agent fetches and counts against the same budget.
7. **Given** an output that fails validation below the validation retry limit, **When** the retry is issued, **Then** only that Assessor Agent is re-run, the identified quality gaps are supplied as an addendum, and no other assessor's run is affected.
8. **Given** any validation run, **When** its inputs are inspected, **Then** they contain exactly one Assessor Agent's output and no other Assessor Agent's output for the same question–portal pair.
9. **Given** an output that still fails validation after the validation retry limit, **When** validation concludes, **Then** the output is not admitted to adjudication as a valid position, and the question–portal pair is escalated if fewer than two validated outputs remain.
10. **Given** a validation retry, **When** the adjudication retry counter is inspected, **Then** it is unchanged — the two limits are tracked separately.
11. **Given** a question marked as requiring authenticated access, **When** the batch runs, **Then** it is never dispatched to any Assessor Agent and is routed directly to the human queue for each in-scope portal.
12. **Given** an unmarked question whose evidence turns out to sit behind a sign-in wall, **When** an Assessor Agent reaches that boundary, **Then** no answer is produced from the publicly reachable pages, the boundary URL is recorded, and the pair escalates as requiring authenticated access rather than as an unreachable target or a quality failure.

---

### User Story 3 - Disagreements are detected and resolved (Priority: P3)

The Adjudicator compares the N Assessor Agent results. A discrepancy is flagged when the answers differ, or when the maximum pairwise confidence delta exceeds a configurable threshold defaulting to 10 points. Flagged cases are re-run with an addendum stating the specific points of disagreement. If disagreement persists after a configurable retry limit defaulting to 2, the case is escalated to a human queue rather than being resolved silently.

**Why this priority**: Adjudication converts N independent opinions into one deliverable answer, and the escalation path is what prevents the system from manufacturing false consensus. It depends on P2 producing genuinely independent inputs, which is why it follows.

**Independent Test**: Feed the Adjudicator fixed sets of pre-computed Assessor Agent results covering agreement, answer disagreement, confidence-only disagreement, retry convergence, and retry exhaustion. Verify the flag decision, the retry behaviour, and the escalation outcome for each without running any live assessment.

**Acceptance Scenarios**:

1. **Given** N Assessor Agent results with identical answers and a maximum pairwise confidence delta at or below the threshold, **When** adjudication runs, **Then** no discrepancy is flagged and a consensus answer with a consensus confidence value is produced.
2. **Given** N Assessor Agent results whose answers differ, **When** adjudication runs, **Then** a discrepancy is flagged regardless of the confidence values.
3. **Given** N Assessor Agent results with identical answers but a maximum pairwise confidence delta above the threshold, **When** adjudication runs, **Then** a discrepancy is flagged.
4. **Given** a flagged discrepancy below the retry limit, **When** the case is re-run, **Then** each Assessor Agent receives an addendum enumerating the specific points of disagreement, and the addendum does not attribute any position to an identified assessor.
5. **Given** a re-run in which the Assessor Agents converge, **When** adjudication runs again, **Then** a consensus answer is produced and the full retry history remains in the audit trail.
6. **Given** disagreement persisting after the configured retry limit, **When** the limit is reached, **Then** an escalation queue item is created carrying the disagreement summary and every Assessor Agent's position, and no consensus answer is delivered automatically.
7. **Given** a discrepancy threshold changed at run time, **When** the next adjudication runs, **Then** the new threshold is applied and the effective value is recorded with the session.
8. **Given** a portal whose questions have all been assessed, **When** portal-level agreement is computed, **Then** both the differing-answer rate and the affirmative-rate gap are computed from the Assessor Agents' first-round positions and recorded with the portal's assessment.
9. **Given** two Assessor Agents whose first-round answers differed on more than the configured proportion of a portal's questions, **When** portal-level adjudication runs, **Then** the portal is flagged as a single case for human review even if every one of those questions later converged on retry, and no already-consensus question is re-run or discarded.
10. **Given** two Assessor Agents with identical affirmative-answer rates who nonetheless disagreed on more than the configured proportion of questions, **When** portal-level adjudication runs, **Then** the portal is flagged on the differing-answer rate despite the affirmative-rate gap being zero.
11. **Given** a portal-level flag, **When** a reviewer opens the case, **Then** both agreement measures, the thresholds in force, and the per-question breakdown that produced them are shown.

---

### User Story 4 - Target URLs are resolved from prioritized sources (Priority: P4)

Portal URLs are resolved through an ordered chain across three source types: official government self-reported submissions, a historical database of prior-cycle URLs, and live search discovery restricted to government top-level domains. The ordering is a run-time configuration choice offering three named modes. A later source is consulted only when every earlier source has failed to yield a usable URL.

**Why this priority**: Every assessment depends on having a target, and the provenance of that target is itself part of the evidence trail. It is placed after adjudication because the assessment and review path can be exercised end-to-end against manually supplied URLs, but no production run is possible without it.

**Independent Test**: Configure each of the three named modes in turn and drive resolution against fixtures where each source type independently succeeds, returns nothing, or returns an unusable candidate. Verify the consultation order, the short-circuit behaviour, and the recorded provenance for each case.

**Acceptance Scenarios**:

1. **Given** a resolution mode and a country whose first-priority source yields a usable URL, **When** resolution runs, **Then** that URL is used and no later source in the chain is consulted.
2. **Given** a country whose first-priority source yields nothing usable, **When** resolution runs, **Then** the next source in the configured order is consulted, and so on down the chain.
3. **Given** any of the three named modes selected at run time, **When** resolution runs, **Then** the sources are consulted in that mode's defined order.
4. **Given** live search discovery is reached, **When** it runs, **Then** only results on government top-level domains are considered as candidates.
5. **Given** a completed resolution, **When** the audit trail is inspected, **Then** it shows every source consulted in order, what each returned, which source supplied the URL used, and the reason any candidate was rejected.
6. **Given** a country for which no source in the chain yields a usable URL, **When** resolution completes, **Then** the affected questions are recorded as unassessable with the reason and routed to the escalation queue, and no speculative answer is produced.
7. **Given** a resolved portal whose detected primary language is in the supported set, **When** assessment begins, **Then** it proceeds without prompting a human.
8. **Given** a resolved portal whose detected primary language is outside the supported set, **When** assessment is about to begin, **Then** a decision is raised to a human naming the detected language and offering a best-effort attempt, and the rest of the batch continues unblocked.
9. **Given** a human authorizes a best-effort attempt, **When** the portal is assessed, **Then** every resulting answer is marked as an out-of-set-language best-effort result, its confidence does not exceed the configured ceiling, and its evidence retains the referenced element text in the original language alongside any translation.
10. **Given** a human declines the attempt or the response window expires, **When** the decision resolves, **Then** the portal is escalated with the detected language recorded as the reason, and the decision and its manner of resolution are recorded.

---

### User Story 5 - Assessors extend the questionnaire (Priority: P5)

An Assessor adds an ad-hoc question to an active assessment. The question is marked as custom, scoped to the active survey cycle, and flows through the same assessment, adjudication, and review path as a standard question.

**Why this priority**: This is an extension to an already-working pipeline. It is genuinely useful — Assessors encounter portal features the standard questionnaire does not cover — but nothing else depends on it.

**Independent Test**: Add a custom question to an active assessment and verify it is marked custom, is confined to the active cycle, is assessed by the same Assessor Agent set, is adjudicated by the same rules, and appears in the review queue indistinguishably in workflow from a standard question.

**Acceptance Scenarios**:

1. **Given** an active assessment, **When** an Assessor adds a custom question, **Then** it is persisted, flagged as custom, attributed to its author, and scoped to the active survey cycle.
2. **Given** a custom question, **When** assessment runs, **Then** it is evaluated by the same configured Assessor Agent count, adjudicated by the same rules, and enters the same review path as standard questions.
3. **Given** a custom question added while a batch is mid-run, **When** it is added, **Then** it is enqueued for assessment against the in-scope portals without re-assessing or invalidating already-completed work.
4. **Given** a subsequent survey cycle, **When** its questionnaire is assembled, **Then** custom questions from a prior cycle are not automatically included.

---

### Edge Cases

- **No usable URL from any source in the chain**: the affected questions are recorded as unassessable with the resolution history attached, and are routed to the escalation queue. No answer is produced at all.
- **Portal reachable but non-responsive, or behind an interstitial**: the system makes a bounded number of attempts, then records the portal as unreachable with the observed reason (timeout, interstitial, challenge page) and escalates. It does not produce an answer inferred from the interstitial.
- **Feature only verifiable from inside an account**: the portal is reachable and the public pages render, but the indicator can only be confirmed behind a sign-in wall or a national identity gateway. The Assessor Agent must not answer from what is publicly visible — a genuine, verifiable screenshot of a public page is exactly how a wrong "feature absent" answer would pass validation. The pair escalates as requiring authenticated access (FR-109) and a human assesses it. If the question is one already known to be gated, it never reaches an Assessor Agent at all (FR-107).
- **Portal in a language outside the supported set**: the system neither silently attempts it nor silently escalates it. It surfaces a decision to a human — naming the detected language and stating it is outside the supported set — and offers a best-effort attempt. If authorized, the portal is assessed and every resulting answer is marked as an out-of-set-language best-effort result with its confidence capped. If declined or unanswered within the configured window, the portal is escalated. The pending decision does not hold up the rest of the batch.
- **Assessor Agents agree on the answer but diverge sharply on confidence**: this is a flagged discrepancy and follows the standard retry-then-escalate path (Acceptance Scenario 3.3). Agreement on the answer alone is not sufficient to deliver.
- **Assessor Agents disagree on many questions but their overall affirmative rates match**: each answers yes to 50 of 100 while disagreeing on 40 individual questions. The affirmative-rate gap is zero and would not flag on its own; the differing-answer rate is 40% and does flag. This is why the differing-answer rate is the primary portal-level measure (FR-036).
- **Heavy first-round disagreement on a portal where every question later converged on retry**: the portal is still flagged at portal level, because the measures are taken on first-round positions. Convergence on retry does not erase the fact that the two Assessor Agents initially read the portal very differently, and that is the case the existing methodology sends back for joint review.
- **An Assessor Agent output passes validation but is factually wrong**: expected and not a validation defect. The Validator has no ground truth; it establishes that an answer is complete, evidence-supported and coherent, not that it is true. Two assessors can each cite genuine page evidence, pass validation, agree with each other, and still both be wrong. Detecting that is the job of benchmark comparison against known answers, not of the Validator.
- **All Assessor Agents' outputs fail validation after the validation retry limit**: fewer than two validated positions remain, so the question–portal pair is escalated rather than adjudicated on a single position or on unvalidated output.
- **Validation fails repeatedly for one Assessor Agent while the others pass**: only the failing Assessor Agent is retried. If it never passes, the pair escalates when the validated count drops below two; the passing assessors' work is retained and recorded.
- **Assessor Agents converge on retry onto an answer the human then overrides**: the human override is the delivered answer. The full pre-override history — every assessor position, both rounds, the adjudication outcome — is preserved and is the primary signal for reviewing assessor quality.
- **Custom question added mid-run**: handled per Acceptance Scenario 5.3. Completed work is not invalidated.
- **Configuration changed between the initial run and a retry**: retries execute under the configuration snapshot taken when the session started, so a retry is comparable to the run that triggered it. Configuration changes take effect for subsequent sessions, and both the snapshot and the change are recorded.
- **Evidence capture succeeds but the referenced element later disappears**: treatment depends on whether the evidence ever passed verification. If it was confirmed against the live page at validation time and disappears afterwards, it remains a valid point-in-time record — marked no longer verifiable against the current page, never deleted or regenerated, capture and verification timestamps retained (FR-025). If it was never locatable at validation time, that is a quality failure and the assessor is retried (FR-087).
- **Element already gone by the time the Validator checks, minutes after capture**: fails verification and triggers a retry, even though the Assessor Agent may have been correct at capture time. This is an accepted false-failure cost of independent verification. The retry re-assesses against the current page, which is the state a human reviewer would also see.
- **Target unreachable at verification time although it was reachable during assessment**: not treated as an Assessor Agent quality failure. Verification is deferred and re-attempted; if the target stays unreachable, the pair escalates as an unverifiable target with that reason recorded distinctly (FR-088).
- **A batch is interrupted with some Assessor Agents complete for a unit**: on resume the unit reaches a defined state deterministically, with no unit assessed twice and no duplicate records. Agents whose runs reached a terminal state are retained with their validation history; only the missing agents run (FR-067a). An agent caught mid-run or mid-validation is discarded and re-run from scratch, and its partial output never reaches the Validator, the Adjudicator, or another Assessor Agent (FR-067b). Retained runs are kept rather than re-run because each was formed without sight of the others — discarding them would spend the shared per-domain budget (FR-089) again without improving independence.
- **Two humans open the same escalation item concurrently**: only one disposition is recorded as delivered; the second is informed the item is already resolved rather than silently overwriting it.

## Requirements *(mandatory)*

### Functional Requirements

#### Target URL resolution

- **FR-001**: System MUST resolve a target portal URL for each country within a survey cycle through an ordered chain across three source types: official government self-reported submissions, a historical database of prior-cycle URLs, and live search discovery.
- **FR-002**: System MUST consult a source in the chain only after every earlier source has yielded no usable URL.
- **FR-003**: System MUST offer exactly three named resolution modes, each defining a different ordering of the three source types, selectable at run time.
- **FR-004**: System MUST restrict live search discovery candidates to government top-level domains.
- **FR-005**: System MUST define and apply an explicit test for whether a candidate URL is usable, and MUST record the reason any candidate was rejected.
- **FR-006**: System MUST record, for every resolution, each source consulted in order, what each returned, and which source supplied the URL that was used.
- **FR-007**: When no source yields a usable URL, system MUST record the affected questions as unassessable with the resolution history attached and route them to the escalation queue, and MUST NOT produce an answer.

#### Link resolution sources

This group refines the ordered chain of FR-001 through FR-007. The three sources supply **candidate links** — where to look. They never supply the answer. Whichever source produces the link, that link is then traversed live, and the answer comes from what is found there.

- **FR-121**: The three link sources MUST be: (1) a **prior-survey knowledge base** of links recorded by previous assessment runs, (2) **MSQ** government submissions, read for any relevant links they contain, (3) **live internet search** restricted to government top-level domains (FR-004). Their consultation order is the resolution mode of FR-003.
- **FR-122**: The prior-survey KB source and the MSQ source MUST each be independently enabled or disabled by run-time configuration. With both disabled, every link is resolved by live search.
- **FR-123**: Every resolved link MUST record which source supplied it and, for the KB and MSQ sources, the identifier and date of the record it came from.
- **FR-124**: **A link obtained from any source MUST be traversed live before any answer is produced from it.** No source may supply an answer, and no answer may be derived from the content of a KB entry or an MSQ submission. The KB and MSQ shorten the search for *where to look*; they never substitute for looking.
- **FR-125**: Evidence MUST always be captured from the live traversal (FR-021) regardless of which source supplied the link. A link that cannot be traversed, or that does not yield the required evidence, MUST NOT be treated as usable (FR-005), and resolution MUST fall through to the next enabled source.
- **FR-126**: MSQ MUST be used **only** as a link source. An AIQ answer MUST NOT be derived from an MSQ-reported value, so that downstream cross-source comparison of AIQ against MSQ compares two independent readings rather than one reading of the other.
- **FR-127**: The prior-survey KB MUST record, for each link, the survey cycle and session it originated from, so that a link's age is visible at the point it is reused.
- **FR-128**: A configurable maximum age MUST govern prior-survey KB links. A link older than that bound MUST NOT satisfy the KB source, and resolution MUST fall through to the next enabled source.

#### Independent assessment

- **FR-008**: System MUST evaluate each question–portal pair with N independent Assessor Agents, where N is configurable at run time, is at least 2, and defaults to 2.
- **FR-009**: System MUST reject a run configured with fewer than 2 Assessor Agents.
- **FR-010**: System MUST NOT expose any Assessor Agent's answer, confidence, justification, or evidence to another Assessor Agent evaluating the same question–portal pair before all of that round's Assessor Agents have completed.
- **FR-011**: Assessor Agents MUST be configured so as to be meaningfully independent; identical configurations producing correlated outputs do not satisfy this requirement, and independence is evidenced by the discrepancy flag rate remaining within the configured band (SC-003, SC-008).
- **FR-012**: Each Assessor Agent MUST return a structured answer conforming to the question's declared answer type, a numeric confidence value, a plain-language justification, and cited evidence.
- **FR-013**: Per-agent confidence MUST be derived solely from evidence quality and source authority observed by that Assessor Agent, MUST be recorded before any cross-agent comparison, and MUST NOT depend on any other Assessor Agent's output.

#### Authentication-gated content

Some indicators can only be verified from inside an account — a sign-in wall, an account-only area, or a national identity gateway. This is the class of work the existing methodology depends on in-country volunteers for, and it is the one class the system deliberately does not automate.

- **FR-107**: A Question MUST be able to carry an attribute marking it as requiring authenticated access to the portal. A question so marked MUST NOT be dispatched to Assessor Agents and MUST be routed directly to the human queue for each portal in scope, with that reason recorded.
- **FR-108**: When an Assessor Agent determines that the evidence needed to answer a question lies behind an authentication boundary, it MUST NOT produce an answer inferred from the publicly reachable pages, and MUST record the observation together with the URL at which the boundary was met.
- **FR-109**: A question–portal pair for which any Assessor Agent reports an authentication boundary MUST be routed to the escalation queue with the reason recorded as requiring authenticated access — recorded distinctly from an unreachable target (FR-088) and from an Assessor Agent quality failure (FR-087).
- **FR-110**: System MUST NOT hold, request, store, or use portal login credentials. Assessing authentication-gated content is a human activity.
- **FR-111**: Every escalation raised under FR-109 MUST be recorded against the question so that its FR-107 attribute can be reviewed for a subsequent survey cycle. The attribute MUST NOT be changed automatically, and MUST NOT change mid-cycle.

#### Evidence locus

Questionnaire wording is not uniform about where a thing must appear. Some indicators require it on the national portal; others merely assert that it exists, and the artifact commonly lives on a parliament, ministry, or agency site. Treating both alike produces two opposite errors: missing real legislation, or crediting a portal for content it does not carry.

- **FR-129**: Each Question MUST carry an evidence-locus attribute with one of two values: `national_portal_only` or `any_government_domain`. The value MUST be derived from the indicator's own wording and MUST be recorded with the question.
- **FR-130**: For a `national_portal_only` question, evidence MUST be located on the resolved target portal or its subdomains. Evidence found only elsewhere MUST NOT satisfy the question; the answer is recorded as negative, and where such evidence was observed off-portal it MUST be recorded as an observation so a reviewer can see why the answer is negative.
- **FR-131**: For an `any_government_domain` question, an Assessor Agent MAY follow beyond the resolved portal to other government domains. Candidate domains MUST be restricted to government top-level domains on the same basis as FR-004, and the evidence MUST record the domain actually reached, which may differ from the resolved portal URL.
- **FR-132**: Per-domain rate limits and site access policies (FR-068, FR-069, FR-089) MUST be applied to **every** domain visited, not only to the resolved portal domain.
- **FR-133**: The evidence-locus attribute MUST NOT change mid-cycle, on the same basis as FR-107, so that every portal in a cycle is assessed against the same locus rule for a given question.

#### Language handling

- **FR-014**: System MUST maintain a configurable set of supported assessment languages, defined as those the configured Assessor Agents handle reliably. The set is configuration, not a fixed property of the system, and is revised as assessor capability changes.
- **FR-015**: System MUST detect the primary language of a resolved target portal and record it as part of the portal's record.
- **FR-016**: When the detected language is in the supported set, system MUST assess the portal without further prompting.
- **FR-017**: When the detected language is not in the supported set, system MUST NOT silently escalate the portal and MUST NOT silently attempt it. System MUST raise a decision point to a human stating the detected language, that it falls outside the supported set, and offering a best-effort attempt.
- **FR-018**: When a human authorizes a best-effort attempt, system MUST assess the portal, mark every resulting answer as an out-of-set-language best-effort result, and cap the confidence of those answers at a configurable ceiling.
- **FR-019**: When a human declines the best-effort attempt, or does not respond within a configurable window, system MUST route the portal to the escalation queue with the detected language recorded as the reason.
- **FR-020**: A pending language decision MUST NOT block assessment of other units in the batch.

#### Evidence

- **FR-021**: Every answer MUST carry evidence comprising the resolved URL, a visual capture scoped to the relevant region of the page, and a durable reference to the specific page element together with that element's text.
- **FR-022**: Evidence artifacts MUST record the timestamp at which they were captured.
- **FR-023**: Evidence artifacts MUST be retrievable and viewable at review time without the reviewer visiting the live portal or opening any external tool.
- **FR-024**: When any required evidence component is missing or unresolvable, system MUST cap the answer's confidence below the acceptance threshold (FR-134) and MUST identify the missing or broken component explicitly.
- **FR-025**: When a referenced page element that previously passed verification (FR-091) can no longer be located on the live page, system MUST retain the original evidence with its capture and verification timestamps and mark it as no longer verifiable against the current page, and MUST NOT delete or silently replace it. This applies only after successful verification; evidence that failed verification at validation time is a quality failure under FR-087, not a point-in-time record.
- **FR-026**: For an out-of-set-language best-effort assessment, evidence MUST retain the referenced element's text in its original language alongside any translation used, so that a reviewer can check the translation.

#### Confidence acceptance gate

An agent that is unsure of its own answer is worth one more look before its output is validated or compared. The gate is placed immediately after the agent completes and **before** validation, so an output about to be re-run does not first consume a Validator fetch against the shared per-domain budget (FR-089).

- **FR-134**: System MUST apply a configurable per-agent confidence acceptance threshold, defaulting to 75. An Assessor Agent output whose confidence falls at or above the threshold proceeds to validation unchanged.
- **FR-135**: An output below the threshold MUST trigger a confidence retry of that Assessor Agent only, on the same per-agent basis as FR-081.
- **FR-136**: The confidence retry addendum MUST direct the agent to seek additional, more specific, or more authoritative evidence. It MUST NOT request, suggest, or require a higher confidence value, so that FR-013 continues to hold — confidence must remain derived from observed evidence quality and source authority, never from having been asked for a larger number.
- **FR-137**: The confidence retry limit MUST be configurable, MUST default to 1, and MUST be tracked separately from both the validation retry limit (FR-084) and the adjudication retry limit (FR-032). A confidence retry MUST NOT increment or reset either of the other counters.
- **FR-138**: When an output remains below the acceptance threshold after the confidence retry limit is reached, system MUST admit it to validation and adjudication unchanged and MUST NOT escalate the pair on that basis alone. The resulting answer is delivered marked as low confidence.
- **FR-139**: A delivered answer whose consensus confidence falls below the acceptance threshold MUST be visibly marked as low confidence wherever it is presented for review and wherever it is exported, so that a reviewer can triage on it.

#### Output validation

The Validator evaluates each Assessor Agent's output on its own merits before adjudication compares agents to each other. Validation is a quality gate, not a correctness check: the Validator has no ground truth and cannot establish whether an answer is true, only whether it is complete, evidence-supported, and internally coherent.

> **Note on requirement numbering**: FR IDs are stable identifiers, not sequence positions. This group was added after the surrounding sections were numbered, so its IDs run from FR-076 while sitting in its logical place in the pipeline. Existing IDs are never reassigned.

- **FR-076**: System MUST validate each Assessor Agent's output independently, after that agent completes and before adjudication, using a Validator distinct from the Assessor Agents.
- **FR-077**: Validation MUST assess at minimum: that every required evidence component is present (FR-021); that the cited evidence is independently locatable online at the location the Assessor Agent recorded (FR-086); that the cited evidence supports the stated answer; that the justification is consistent with both the answer and the evidence; and that the stated confidence is proportionate to the observed evidence quality.
- **FR-078**: Validation MUST produce a numeric quality score together with the specific quality gaps found. An output fails validation when its score falls below the configured validation quality threshold.
- **FR-079**: The Validator MUST evaluate exactly one Assessor Agent's output at a time and MUST NOT be given any other Assessor Agent's output for the same question–portal pair, so that agent independence (FR-010) is preserved through the validation stage.
- **FR-080**: When validation fails and the validation retry limit has not been reached, system MUST re-run that Assessor Agent with the identified quality gaps supplied as an addendum.
- **FR-081**: The validation retry loop MUST operate per Assessor Agent; retrying one agent's output MUST NOT re-run any other agent.
- **FR-082**: When an output still fails validation after the validation retry limit, system MUST NOT admit it to adjudication as a valid position, and MUST route the question–portal pair to the escalation queue when fewer than two validated outputs remain.
- **FR-083**: Validation MUST NOT alter an Assessor Agent's answer, confidence, justification, or evidence. It either admits the output unchanged or triggers a retry.
- **FR-084**: The validation retry limit MUST be configurable and MUST be tracked separately from the adjudication retry limit (FR-032); a validation retry MUST NOT increment or reset the adjudication retry counter.
- **FR-085**: Every validation outcome — quality score, gaps found, pass or fail, and retry number — MUST be recorded against the session identifier (FR-059) and MUST be visible to the Assessor at review time alongside that agent's position.

##### Independent evidence verification

- **FR-086**: The Validator MUST independently fetch the resolved URL, attempt to locate the referenced page element using the durable reference the Assessor Agent recorded, and confirm that the element's text matches what was recorded.
- **FR-087**: When the Validator reaches the page but cannot locate the referenced element, or locates it but its text does not match what was recorded, validation MUST fail with the specific discrepancy recorded as the quality gap.
- **FR-088**: When the target is unreachable at verification time — timeout, interstitial, or transient error — validation MUST NOT fail the Assessor Agent's output on that basis. Verification MUST be deferred and re-attempted up to the configured verification attempt bound. If the target remains unreachable after that bound, the question–portal pair MUST be routed to escalation with the reason recorded as an unverifiable target, distinctly from an agent quality failure.
- **FR-089**: Validator fetches MUST observe the same target-site access policies and per-domain rate limits as Assessor Agent fetches (FR-068, FR-069) and MUST be counted against the same per-domain budget.
- **FR-090**: The Validator MUST confine its reading of the fetched page to locating and confirming the cited evidence. It MUST NOT form, record, or act on an independent answer to the question — the Validator judges the Assessor Agent's work, never the question itself.
- **FR-091**: On successful verification, the evidence MUST be stamped with a verification timestamp and the fact that it was confirmed against the live page. FR-025's treatment of a later-disappearing element applies only to evidence that passed verification at validation time; it does not excuse evidence that failed verification when first checked.

#### Per-question adjudication and discrepancy handling

- **FR-027**: System MUST adjudicate a question–portal pair only after all N Assessor Agents for that round have completed and been validated.
- **FR-028**: System MUST flag a per-question discrepancy when the Assessor Agents' answers differ, or when the maximum pairwise difference between their confidence values exceeds the configured per-question confidence threshold.
- **FR-029**: The per-question confidence threshold MUST be configurable at run time and MUST default to 10 points.
- **FR-030**: On a flagged discrepancy below the adjudication retry limit, system MUST re-run the Assessor Agents with an addendum enumerating the specific points of disagreement.
- **FR-031**: The retry addendum MUST NOT attribute any position to an identified Assessor Agent, so that independence is preserved across rounds.
- **FR-032**: The adjudication retry limit MUST be configurable at run time and MUST default to 2.
- **FR-033**: When disagreement persists after the adjudication retry limit is reached, system MUST create an escalation queue item carrying the disagreement summary and every Assessor Agent's position from every round, and MUST NOT deliver a consensus answer for that pair automatically.
- **FR-034**: System MUST compute a consensus confidence value after adjudication that reflects agreement across Assessor Agents in addition to the per-agent confidence values, recorded separately from and without altering the per-agent values.

#### Portal-level discrepancy handling

Portal-level discrepancy is not a separate detector finding disagreements that per-question adjudication misses — it compares the same Assessor Agents over the same questions. It is an aggregate quality measure over a portal's assessment as a whole, and it is taken on first-round positions so that it survives retry convergence.

- **FR-035**: System MUST compute portal-level agreement measures across the full question set assessed for a portal, using each Assessor Agent's **first-round** position for each question, before any retry is applied. Measures MUST comprise at minimum the proportion of questions on which the Assessor Agents' first-round answers differ, and the difference between each agent's rate of affirmative answers.
- **FR-036**: The differing-answer rate MUST be the primary portal-level measure. The affirmative-rate gap MUST be recorded alongside it but MUST NOT be the sole configured trigger for a flag, because two Assessor Agents can return identical affirmative rates while disagreeing on a large proportion of individual questions.
- **FR-037**: System MUST flag a portal-level discrepancy when either measure exceeds its own configured threshold, both thresholds being configurable at run time and defaulting to 10% for the differing-answer rate and 10 percentage points for the affirmative-rate gap.
- **FR-038**: A portal-level flag MUST route the portal's assessment to human review as a single case, distinct from and in addition to any per-question escalations already raised for that portal, and MUST be raised even when every per-question disagreement on that portal subsequently converged on retry.
- **FR-039**: A portal-level flag MUST NOT trigger automatic re-runs of questions that already reached consensus and MUST NOT discard their results; the measures and the thresholds in force MUST be recorded with the portal's assessment for audit.

#### Confidence representation

- **FR-040**: System MUST express confidence as a numeric value on a single fixed scale used consistently by per-agent and consensus values.
- **FR-041**: System MUST NOT categorize confidence into named tiers. There are no high, medium, or low bands. A single configurable **confidence acceptance threshold** (FR-134, default 75) is the only boundary the system draws on the scale, separating answers that met the threshold from those that did not.
- **FR-042**: Confidence MUST be displayed as its numeric value on the 0–100 scale, presented as a percentage, wherever it appears — the review surface, the escalation queue, logs, telemetry, and the export. A named label MUST NOT be substituted for the number.

#### Human review

- **FR-043**: System MUST present, for each question awaiting review, the proposed answer, its justification, its numeric confidence as a percentage, the resolved URL, the source that supplied that URL, and the complete evidence set.
- **FR-043a**: A target portal MUST become available for Assessor review only once every question for that portal has reached a terminal pipeline state — either a delivered consensus answer or an escalation. Review is presented per portal over its complete pre-filled question set, not question-by-question as individual answers complete.
- **FR-043b**: Questions that terminated in escalation MUST appear within the portal's review set marked as escalated with their reason, so that one unresolved question does not withhold the rest of the portal from review.
- **FR-043c**: Human touchpoints that occur *during* a run — language decisions (FR-017) and escalation queue items — MUST remain available before portal review unlocks, and MUST NOT wait on portal completion.
- **FR-044**: System MUST allow an Assessor to approve, edit, or reject-and-override any proposed answer.
- **FR-045**: System MUST attribute every human action to the acting person and record the time it occurred.
- **FR-046**: System MUST preserve the original system-proposed answer unchanged when a human edits or overrides it, and MUST record the human-supplied answer as the delivered answer.
- **FR-047**: System MUST capture a reason when an answer is rejected and overridden.
- **FR-048**: System MUST make each individual Assessor Agent's position and the adjudication outcome visible to the reviewer after adjudication has completed.
- **FR-049**: System MUST present escalation queue items with the disagreement summary and all Assessor Agent positions, and MUST record exactly one delivered disposition per item even when multiple people act concurrently.
- **FR-050**: System MUST present a portal-level discrepancy case with both agreement measures, their configured thresholds, and the per-question breakdown that produced them.
- **FR-051**: System MUST mark out-of-set-language best-effort answers as such wherever they are presented for review.
- **FR-052**: Human review actions MUST be recorded as new immutable records rather than by mutating existing ones.

- **FR-119**: The review surface — the answer review screens, the escalation queue, the language-decision prompt, and the portal-level discrepancy case view — MUST conform to WCAG 2.1 Level AA.
- **FR-120**: The review surface's interface language is English. Evidence, referenced element text, and any answer text originating from the target portal MUST be presented in the portal's original language regardless of the interface language, with any translation shown alongside rather than in place of it (FR-026).

#### Custom questions

- **FR-053**: System MUST allow an Assessor to add an ad-hoc question to an active assessment.
- **FR-054**: Custom questions MUST be flagged as custom, attributed to their author, and scoped to the survey cycle in which they were created.
- **FR-055**: Custom questions MUST flow through the same assessment, adjudication, and review path as standard questions.
- **FR-056**: A custom question added mid-run MUST be enqueued against the in-scope portals without re-assessing, duplicating, or invalidating already-completed work.
- **FR-057**: Custom questions MUST NOT be carried into a subsequent survey cycle automatically.
- **FR-058**: Custom questions added mid-run MUST be included in the portal-level agreement measures only if they were assessed for every Assessor Agent on that portal, so that the measures are not skewed by partial coverage.

#### Audit trail

- **FR-059**: Every record produced for a batch — URL resolution, language detection and any language decision, each Assessor Agent Run, each adjudication, each retry, each escalation, and each human action — MUST be keyed on a single session identifier.
- **FR-060**: Retries and parallel Assessor Agent Runs MUST attach to that same session identifier and MUST NOT produce records disconnected from it.
- **FR-061**: For any delivered answer, the audit trail MUST allow reconstruction of: the sources consulted and the URL resolution outcome; the detected language and any human language decision; each Assessor Agent's answer, confidence, justification, and evidence for every round; the adjudication outcome of every round; every retry and its addendum; any escalation; and the human decision.
- **FR-062**: Audit records MUST be append-only.
- **FR-063**: System MUST record the effective configuration in force for each session.

#### Batching, resumability, and crawling

- **FR-064**: Batch size MUST be configurable at run time.
- **FR-065**: Each question–portal unit MUST carry an explicit state that determines whether it requires work, so that resumption is decided from recorded state rather than by re-running.
- **FR-066**: An interrupted batch MUST resume without re-assessing units already completed and without creating duplicate records.
- **FR-067**: A unit interrupted with some but not all of its Assessor Agents complete MUST reach a defined state on resume deterministically, and MUST NOT contribute more than one set of results to adjudication.
- **FR-067a**: On resume, system MUST retain every Assessor Agent Run for that unit that reached a terminal state — validated pass, or failed validation after the validation retry limit — together with its Validation Results and retry counters, and MUST run only the Assessor Agents that have no terminal run for that round.
- **FR-067b**: An Assessor Agent Run interrupted before reaching a terminal state — mid-assessment, mid-validation, or mid-validation-retry — MUST be discarded and re-run from scratch for that agent, and its discarded partial output MUST NOT be supplied to adjudication, to the Validator, or to any other Assessor Agent.
- **FR-068**: System MUST honour the access policies published by target sites.
- **FR-069**: System MUST apply a configurable request rate limit per domain.
- **FR-070**: System MUST identify itself to target sites with a stable, attributable identifier.
- **FR-071**: When a portal is reachable but non-responsive or presents an interstitial, system MUST make a bounded number of attempts, then record the portal as unreachable with the observed reason and route affected questions to escalation, and MUST NOT infer an answer from the interstitial.

#### Benchmark evaluation

Benchmark evaluation measures whether answers are *correct*, which validation cannot establish. It is the only mechanism in the system with access to known-correct answers, and it is what makes SC-002, SC-003 and SC-008 verifiable.

- **FR-092**: System MUST store a labelled benchmark set: question–portal pairs each carrying a known correct answer, the source of that label, and the person or process that assigned it.
- **FR-093**: System MUST support running an assessment session in benchmark mode against a benchmark set, using the same URL resolution, assessment, validation, adjudication, and portal-level pipeline as a production run. A benchmark run MUST NOT use a separate or simplified path, since results from a different path would not be evidence about the production pipeline.
- **FR-094**: Ground truth answers MUST NOT be exposed to any Assessor Agent, to the Validator, or to the Adjudicator at any point during a benchmark run.
- **FR-095**: Benchmark sessions MUST be marked as such, and their answers MUST NOT be delivered into any survey cycle's results.
- **FR-096**: On completion of a benchmark run, system MUST compute and report at minimum: overall consensus accuracy against ground truth; accuracy broken down by question class where the benchmark is labelled by class; accuracy grouped by numeric confidence band, the bands being reporting buckets over the 0–100 scale rather than named tiers (FR-041); the per-question discrepancy flag rate; the portal-level agreement measures; and counts of escalations by reason.
- **FR-097**: Accuracy MUST be computed on the consensus answer prior to any human review, and a benchmark run MUST NOT incorporate human dispositions into its accuracy figure.
- **FR-098**: A benchmark report MUST record the configuration snapshot in force for that run (FR-063), so that results are comparable across configuration changes.
- **FR-099**: System MUST retain benchmark run results and MUST support comparing a run against any previous run, reporting the change in each measure.
- **FR-100**: Benchmark runs MUST be resumable and auditable on the same terms as production runs (FR-059, FR-065).

#### Observability

The audit trail (FR-059 through FR-063) answers "how did this answer come about". Observability answers "how is the run going, and what is it costing" — and it is what makes SC-011 and SC-012 measurable rather than aspirational. Alerting thresholds, retention, and where these signals are surfaced are planning decisions.

- **FR-112**: System MUST report, for an in-progress or completed session, the count of question–portal units in each pipeline state, the count of escalations broken down by reason, and the count of failures by stage.
- **FR-113**: System MUST record a structured event for every pipeline stage transition — URL resolution, language detection, each Assessor Agent Run, each validation and verification, each adjudication, each retry, each escalation, and each human action — keyed on the session identifier (FR-059).
- **FR-114**: Each stage-transition event MUST record the time the stage started and ended, so that per-stage duration and end-to-end unit duration are derivable without inference.
- **FR-115**: System MUST record every outbound fetch against its target domain, distinguishing Assessor Agent fetches from Validator verification fetches (FR-089), so that per-domain rate-limit conformance (SC-012) is demonstrable from recorded data rather than asserted.
- **FR-116**: System MUST record, per session, the model invocations made and their cost, attributable to the pipeline stage and to the individual Assessor Agent or Validator that made them.
- **FR-117**: Observability records MUST NOT contain portal credentials (FR-110) and MUST NOT expose ground truth answers from a benchmark run (FR-094).
- **FR-118**: Observability records MUST NOT be the mechanism by which any assessment decision is made; they are a read-only account of the run and MUST NOT alter any audit record.

#### Answer export

The export is the handoff boundary: it is how delivered answers leave the system. It does not publish them and does not compute anything from them — both remain out of scope.

- **FR-101**: System MUST produce, on demand, a machine-readable export of the delivered answers for a survey cycle, covering the questions and portals in scope for that cycle.
- **FR-102**: Each exported record MUST carry at minimum: the country and its resolved portal URL with the source that supplied it; the question identifier and whether it is standard or custom; the delivered answer; the consensus confidence value on the 0–100 scale; whether the delivered answer was system-proposed, human-edited, or human-overridden; the acting person's identity and the time they acted; whether it is an out-of-set-language best-effort result; and the session identifier from which the full history is reconstructable (FR-061).
- **FR-103**: Each exported record MUST carry references sufficient to retrieve that answer's evidence artifacts. Producing an export MUST NOT delete, detach, or alter any evidence artifact.
- **FR-104**: Export MUST include only answers in a delivered state. Questions still awaiting human review, unresolved escalations, and every answer from a benchmark session (FR-095) MUST be excluded, and the excluded questions MUST be reported alongside the export with the reason for each, so that a consumer can see where coverage is incomplete.
- **FR-105**: Export MUST NOT compute a score, rank, or composite index from the delivered answers, and MUST NOT alter any delivered answer or audit record.
- **FR-106**: Each export MUST be recorded against the survey cycle with the time it was produced, the person or process that produced it, and the set of records it contained.

#### Configuration

- **FR-072**: Every operational parameter MUST be externalized configuration rather than a value fixed in code. At minimum this comprises: prior-survey KB link source enabled; MSQ link source enabled; prior-survey KB maximum link age; confidence acceptance threshold; confidence retry limit; Assessor Agent count; batch size; adjudication retry limit; validation retry limit; validation quality threshold; per-question confidence threshold; portal-level differing-answer-rate threshold; portal-level affirmative-rate-gap threshold; the confidence ceiling applied to out-of-set-language best-effort answers; the supported language set; per-domain rate limits; the bounded attempt count for unresponsive portals; the language-decision response window; the verification attempt bound for unreachable targets; and the URL resolution mode.
- **FR-073**: System MUST expose the full set of parameters in FR-072, each with its current effective value and its default, so that an operator can see how a session was configured without inspecting the system's internals.
- **FR-074**: Changing any parameter MUST take effect without a code change, and MUST NOT require editing application source. A process restart to pick up changed configuration is acceptable; a rebuild or code edit is not.
- **FR-075**: Retries MUST execute under the configuration snapshot taken when their session started; a configuration change made mid-session MUST take effect only for subsequent sessions and MUST be recorded.

### Key Entities

- **Prior-Survey Link**: A link recorded by a previous assessment run — the question, portal, URL, and the cycle and session it originated in. Consulted as a link source only; carries no answer, and is never rewritten by the run that reads it.
- **MSQ Link Candidate**: A link extracted from a government MSQ submission, with the submission it came from and its date. Read for links only — the reported values in the submission are never used as answers (FR-126).
- **Survey Cycle**: A named assessment edition with its own questionnaire and country set. Scopes custom questions and provides the prior-cycle URL history that a later cycle draws on.
- **Assessment Session**: One batch execution. Carries the session identifier that every downstream record is keyed on, and the configuration snapshot in force for that batch.
- **Question**: A questionnaire item with a declared answer type. Either standard (belonging to the cycle's questionnaire) or custom (author-attributed, cycle-scoped, added ad hoc). Carries an attribute marking whether answering it requires authenticated access to the portal, in which case it is answered by a human rather than dispatched to Assessor Agents. Also carries an evidence-locus attribute (`national_portal_only` or `any_government_domain`) governing how far evidence may be sought from the resolved portal.
- **Target Portal**: The national online service portal for a country in a cycle, together with its resolved URL, the source that supplied it, the full resolution history including rejected candidates, its detected primary language, and whether that language is inside the supported set.
- **Language Decision**: A human decision on whether to attempt a portal whose language falls outside the supported set. Holds the detected language, the decision, the deciding person, the timestamp, and whether the decision was made explicitly or by the response window expiring.
- **Assessor Agent Run**: One Assessor Agent's independent evaluation of one question against one target portal in one round. Holds the structured answer, per-agent confidence, justification, and the evidence cited, plus the round number.
- **Validation Result**: The Validator's outcome for one Assessor Agent Run — the quality score, the specific gaps found, the pass or fail decision, and the validation retry number. Recorded per run and never modifies it.
- **Evidence Artifact**: The resolved URL, the region-scoped visual capture, and the durable page-element reference with its text, with a capture timestamp and a verifiability status against the current live page.
- **Adjudication Result**: The comparison of a round's validated Assessor Agent Runs, holding the flag decision, the consensus answer where one was reached, and the consensus confidence.
- **Discrepancy Case**: A flagged disagreement at either scope. A per-question case holds the specific points of disagreement, the retry count, the addendum issued for each retry, and the outcome. A portal-level case holds both agreement measures, the thresholds in force, and the per-question breakdown that produced them.
- **Escalation Queue Item**: A case requiring human resolution — unresolved disagreement, portal-level discrepancy, no usable URL, unreachable portal, an unverifiable target, content behind an authentication boundary, or a declined out-of-set language — carrying the reason and all context needed to decide.
- **Configuration Snapshot**: The effective value of every run-time parameter at the moment a session started. Bound to the session, governs its retries, and is retained for audit.
- **Benchmark Set**: A named collection of question–portal pairs with known correct answers, optionally labelled by question class. Used only by benchmark runs.
- **Ground Truth Answer**: The known correct answer for one question–portal pair in a benchmark set, with the source of the label and who or what assigned it. Never visible to Assessor Agents, the Validator, or the Adjudicator.
- **Benchmark Run Result**: The measures computed for one benchmark session — overall accuracy, accuracy by question class and by numeric confidence band, discrepancy flag rate, portal-level measures, escalation counts by reason — bound to the configuration snapshot that produced them and comparable against prior runs.
- **Run Telemetry**: The operational account of one session — stage-transition events with start and end times, unit counts by pipeline state, escalation and failure counts by reason, per-domain fetch counts split between Assessor Agent and Validator traffic, and model invocation cost by stage and agent. Read-only; never an input to an assessment decision.
- **Answer Export**: A generated machine-readable snapshot of one survey cycle's delivered answers, each with its confidence, provenance, evidence references, human attribution, and session identifier, together with the list of questions excluded from it and the reason for each. Records when it was produced and by whom; never alters what it draws from.
- **Assessor Decision**: An Assessor's approve, edit, or reject-and-override action on a proposed answer, attributed and timestamped, retaining both the system-proposed answer and the human-supplied one.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An Assessor can review a question and dispose of it — approve, edit, or reject-and-override — using only the information presented on the review surface, opening no external tool and visiting no live portal. Verified by task observation across a representative sample of questions with a 100% completion rate without external navigation.
- **SC-002**: On a labelled benchmark set of questions with known correct answers, consensus answers match ground truth on at least **80% of question–portal pairs overall**, measured before any human review. Accuracy broken down by question class and by numeric confidence band is computed and reported alongside (FR-096) but is not itself a gate.
- **SC-003**: The per-question discrepancy flag rate, computed by a benchmark run (FR-096), falls within the configured acceptable band, defaulting to 5–25%. A rate at or below the configured non-independence floor, defaulting to 5%, is treated as a failure indicating the Assessor Agents are not independent, not as a success. Both bounds are run-time configuration per FR-072 and are tuned as benchmark evidence accumulates.
- **SC-004**: 100% of delivered answers carry a complete, resolvable evidence set; zero answers with missing or broken evidence are ever surfaced with confidence at or above the acceptance threshold. Confidence is displayed as a 0–100 percentage in 100% of surfaces, with zero named-tier labels substituted for the number.
- **SC-005**: For 100% of delivered answers, an auditor can reconstruct the full history end to end — sources consulted, each Assessor Agent's position in each round, adjudication outcome, every retry, and the human decision — from the session identifier alone.
- **SC-006**: A run interrupted at any point resumes with zero duplicated units and zero lost units; the set of completed units after resumption equals the set that an uninterrupted run of the same batch would produce. For units interrupted mid-round, 100% of terminal-state Assessor Agent Runs are retained and zero are re-run, and 100% of non-terminal runs are discarded and re-run, with zero discarded partial outputs reaching adjudication.
- **SC-007**: 100% of records generated for a batch — including every retry and every parallel Assessor Agent Run — are reachable from that batch's single session identifier, with no orphaned records.
- **SC-008**: Assessor independence is demonstrable from a benchmark run: the distribution of per-agent answers and confidence values is non-degenerate, and the discrepancy flag rate satisfies SC-003.
- **SC-009**: Every case the system cannot answer — no usable URL, unreachable portal, unsupported language, authentication-gated content, or unresolved disagreement after the retry limit — appears in the human escalation queue with its reason; zero such cases are silently resolved or silently dropped.
- **SC-010**: Every parameter listed in FR-072 can be changed at run time and takes effect on the next session with no code change and no redeployment, and its effective value for any past session is retrievable from that session's configuration snapshot.
- **SC-011**: Assessment throughput is sufficient to complete a full cycle — every country in the cycle against the full questionnaire — within the cycle's assessment window, with the human review queue as the only remaining constraint. Measured from the recorded per-stage and end-to-end durations (FR-114), not estimated.
- **SC-012**: Zero recorded violations of target-site access policies or configured per-domain rate limits across a full cycle run, demonstrated from the recorded per-domain fetch log (FR-115) rather than asserted.
- **SC-013**: Portal-level discrepancy is computed from first-round positions and recorded for every assessed portal. On a constructed benchmark where two Assessor Agents' first-round answers differ on more than the configured proportion of a portal's questions, the portal is flagged for human review even when every one of those questions subsequently converged on retry, and zero already-consensus questions are re-run or discarded.
- **SC-014**: No portal whose language falls outside the supported set is assessed without a recorded human authorization, and no such portal is escalated without the human having first been offered the best-effort attempt. 100% of out-of-set-language answers are marked as best-effort and observe the configured confidence ceiling.
- **SC-015**: 100% of Assessor Agent outputs are validated before adjudication; zero unvalidated or validation-failed outputs contribute a position to any adjudication.
- **SC-016**: Zero question–portal pairs are adjudicated on fewer than two validated positions; every pair falling below that threshold appears in the escalation queue with its validation history.
- **SC-017**: Validation preserves independence: across a full run, zero validation invocations received more than one Assessor Agent's output for the same question–portal pair.
- **SC-018**: 100% of answers reaching adjudication carry evidence that was independently located at its cited URL and element reference and confirmed against the live page, with a verification timestamp recorded. Zero answers reach adjudication on unverified evidence.
- **SC-019**: Validator traffic observes the same per-domain rate limits and access policies as Assessor Agent traffic, counted against a single shared per-domain budget; zero violations attributable to verification fetches across a full cycle run.
- **SC-020**: Verification failures are correctly attributed: zero cases where an unreachable target was recorded as an Assessor Agent quality failure, and zero cases where a genuinely absent element was recorded as an unreachable target.
- **SC-021**: Benchmark runs are uncontaminated: ground truth reaches zero Assessor Agent, Validator, or Adjudicator invocations; zero benchmark answers appear in any survey cycle's delivered results; and a benchmark run exercises the same pipeline as a production run.
- **SC-022**: Any two benchmark runs can be compared, with the change in each reported measure and the configuration difference between them shown, so that the effect of a parameter or model change is attributable.
- **SC-023**: For any survey cycle, an export can be produced whose record count equals that cycle's count of delivered answers, containing zero answers awaiting review, zero unresolved escalations, and zero benchmark answers; every excluded question appears in the accompanying exclusion report with its reason; and 100% of exported records resolve back to their session identifier and their evidence artifacts.
- **SC-024**: Zero delivered answers originate from publicly reachable pages for a question–portal pair at which an authentication boundary was observed; 100% of such pairs appear in the escalation queue with that reason recorded distinctly from an unreachable target; zero questions marked as requiring authenticated access are dispatched to an Assessor Agent; and the system stores zero portal credentials.
- **SC-025**: For any session, the unit count in each pipeline state, escalation counts by reason, per-stage and end-to-end durations, per-domain fetch counts split between Assessor Agent and Validator traffic, and model invocation cost attributable to stage and agent are all retrievable from the session identifier alone. Zero observability records contain portal credentials or benchmark ground truth.
- **SC-026**: The review surface passes a WCAG 2.1 Level AA audit with zero unresolved Level A or AA failures, and 100% of presented evidence text retains the portal's original language with any translation shown alongside it.
- **SC-027**: Every resolved link records the source that supplied it. 100% of delivered answers derive from a live traversal of that link with evidence captured at traversal time — zero answers are derived from the content of a prior-survey KB entry or an MSQ submission. Zero MSQ values appear as AIQ answers.
- **SC-028**: Zero question–portal pairs are escalated solely because an agent's confidence stayed below the acceptance threshold; 100% of such answers are delivered and visibly marked as low confidence. Zero confidence-retry addenda request or suggest a higher confidence value, and the three retry counters — confidence, validation, adjudication — remain independently tracked across a full run.

## Assumptions

These are informed defaults adopted where the input left a detail open. Each is a decision that can be revisited without reshaping the specification.

- **Confidence is a number, not a label**: Confidence is a numeric value from 0 to 100, displayed as a percentage everywhere it appears (FR-042). The system draws exactly one boundary on that scale — the acceptance threshold, defaulting to 75 (FR-134) — and named tiers were removed rather than kept alongside it. Two labels for one number invite the reader to trust the label and stop reading the number, and the earlier arrangement had an accepted answer at 77 displaying as "medium", which is precisely the confusion worth designing out. A side benefit: the word "tier" no longer has a second meaning anywhere in this specification.
- **Scale**: A cycle covers on the order of 193 countries against a questionnaire of roughly 200 items, on a biennial schedule — approximately 39,000 question–portal units per cycle, each evaluated by at least 2 Assessor Agents. SC-011 is stated against the cycle window rather than a fixed rate so that it stays valid as these numbers move.
- **Evidence retention**: Evidence artifacts are retained for at least two full survey cycles, so that a cycle's answers remain auditable while the following cycle is being assessed and prior-cycle URLs remain available to the historical resolution source. Storage location is deferred to planning.
- **Roles**: The specification distinguishes only the acting capabilities it needs — reviewing and disposing of answers, working the escalation queue, adding custom questions, and changing run-time configuration. Identity and access management, including how these capabilities are bound to named role bands, is out of scope; the audit trail requires only that every action carries an attributable actor identity.
- **Link sources shorten the search, never the assessment**: The prior-survey KB and MSQ exist to answer *where to look*, not *what the answer is* (FR-124). Every link is traversed live and every answer comes from evidence captured at traversal, whichever source supplied the link. This keeps two properties that would otherwise be lost. AIQ stays genuinely independent of MSQ, so EKAP's cross-source comparison of the two compares two readings rather than one reading of the other (FR-126). And a stale link degrades to a failed traversal and falls through to the next source (FR-125), rather than silently propagating a previous cycle's answer into this one — the KB ages links, not conclusions.
- **Proof-of-concept question set**: The PoC assesses **Module 2.1 — Institutional Framework only**, recorded in [poc-question-set.md](./poc-question-set.md): 16 question rows covering 26 indicator IDs, all binary existence checks. Rows 12 and 13 each apply one question form across six sectors and are expanded into individual question records, since each sector carries its own indicator ID and is separately scored — collapsing a row into one answer would lose per-sector results the index consumes. Requirements are written against the full questionnaire and are unchanged; the PoC narrows the question set, not the pipeline.
- **Answer types**: Questionnaire items are predominantly binary, but the specification treats the answer as a structured value conforming to the question's declared type, so that non-binary items are accommodated without change.
- **Adjudication timing**: Adjudication is a distinct stage that runs after all of a round's Assessor Agents have completed and been validated (FR-027, FR-076). Incremental adjudication as results arrive is excluded because it would let earlier results influence the treatment of later ones.
- **Validation is a quality gate, not a correctness check**: The Validator has no ground truth. It establishes that an answer is complete, that its cited evidence genuinely exists where the assessor said it does, and that it is internally coherent — not that it is correct. Two assessors can cite real, independently verified evidence, pass validation, agree with each other, and still both be wrong. Correctness is measured only by comparison against a labelled benchmark, which is a separate concern and is tracked as an open question.
- **Verification doubles crawl volume**: Independent verification (FR-086) means roughly one validator fetch per Assessor Agent Run, on top of Assessor Agent traffic, against a fixed per-domain budget shared between them (FR-089). This is a deliberate accuracy-for-throughput trade and is the main pressure on SC-011. If cycle throughput proves insufficient, the levers are batch scheduling and rate-limit headroom, not skipping verification.
- **Benchmark set**: *Constructing* the labelled set — deciding the correct answer for each question–portal pair — remains a project activity requiring human judgment. *Storing* it, running the pipeline against it, and computing the comparison are system capabilities (FR-092 through FR-100). The system does not author ground truth; it consumes it.
- **Authentication-gated content stays human**: The system does not log in to portals and holds no credentials (FR-110). Gated questions therefore produce no consensus answer, so they contribute to escalation counts rather than to benchmark accuracy (FR-096, FR-097), and the residual volume of them sets a floor on how much human assessment remains per cycle. This is the class of work the existing volunteer methodology exists to cover, and automating it is a deliberate non-goal rather than an unresolved gap.
- **Language coverage**: The supported language set is derived from the languages the configured Assessor Agents handle reliably, established by evaluation rather than by assertion, and held as configuration (FR-014). Portals outside that set are neither auto-skipped nor auto-attempted — a human is asked whether to try anyway, and a best-effort attempt is marked and confidence-capped (FR-017 through FR-019). The set is expected to cover the large majority of the country set; the residual determines the size of the language-decision queue. Establishing the initial set is a project activity — a language-coverage evaluation of the candidate Assessor Agents — not a system capability, and it is a prerequisite for a first production run rather than for planning.
- **Confidence ceiling for best-effort answers**: Defaults to 74 — one point below the acceptance threshold — so an answer derived through translation never clears the threshold on its own. Configurable per FR-072, and must be revisited if the acceptance threshold moves, since the two are coupled.
- **Two scopes of discrepancy**: Per-question and portal-level discrepancy compare the same Assessor Agents over the same questions; portal-level is an aggregate view of the same signal, not an independent detector of disagreements per-question adjudication misses. It earns a separate mechanism because it is taken on first-round positions and therefore survives retry convergence: a portal whose assessors initially read it very differently is flagged for joint human review even after every individual question has been reconciled. Per-question flags drive retries; portal-level flags drive human review of the portal as a whole. This mirrors the existing manual methodology, in which a coordinator both resolves individual disagreements and sends back whole assessments whose overall results diverged too far.

## Dependencies

- A labelled benchmark set of questions with known correct answers, required to evaluate SC-002, SC-003, and SC-008.
- Official government self-reported submission data for the active cycle, as the first candidate source type for URL resolution.
- A historical database of prior-cycle portal URLs.
- A search capability able to restrict results to government top-level domains.
- The standardized questionnaire for the active cycle, authored externally to this system.
- An identity source providing attributable actor identities for the audit trail, supplied by the surrounding platform.
- A durable session store capable of persisting run state across process restarts, required by the resumability requirements.
- A language-coverage evaluation of the configured Assessor Agent models, required to populate the initial supported language set.

## Implementation Constraints (given)

These are pre-decided and are recorded here so that planning inherits them. They are constraints on the solution, not requirements to be validated — the functional requirements above are deliberately stated without reference to them, so that each remains testable against whatever composition is ultimately built.

- **Agent orchestration is built on the Agent Development Kit (ADK)**. The N independent Assessor Agents, the Validator, the Adjudicator, the URL resolution chain, and the evidence capture step are all realized as ADK components. Assessor independence (FR-010, FR-079) is therefore an ADK composition property: independent assessors must not share conversational state, the Validator must be invoked per Assessor Agent output rather than over the set, and the Adjudicator must receive outputs only after all have completed and been validated.
- **Configuration is supplied through environment configuration (`.env`)**, read at process start. This satisfies FR-072 and FR-074 as written — no code edit or rebuild is needed to change a parameter — but note that it means a parameter change is picked up on process restart rather than instantaneously. FR-074 was written to permit this. If live reconfiguration without restart is later required, FR-074 and this constraint both need revisiting.
- **Session identity maps onto ADK session state.** The single session identifier required by FR-059 and FR-060 is expected to be carried as ADK session state so that parallel Assessor Agent invocations and retries attach to one connected trail rather than each opening a fresh context.
- **Resumability (FR-064 through FR-067) requires durable session persistence**, not in-memory session state, since an interrupted batch must resume from recorded unit state after process restart.
- **The supported language set (FR-014) is determined by the language coverage of the models configured behind the ADK Assessor Agents**, established by evaluation rather than assertion, and revised when models change.

Candidate models are not fixed in this specification. Model selection, the ADK agent topology, and how Assessor Agent independence is realized concretely are all planning decisions.

## Out of Scope

- Scoring or ranking countries, and computing any composite index from delivered answers.
- Questionnaire authoring — the standard questionnaire is an input. Adding ad-hoc custom questions (P5) is in scope; designing the standard questionnaire is not.
- Identity and access management: authentication, authorization, and role administration. The system consumes actor identities and does not manage them.
- **Security, data-residency, and external-processing standards — deferred, not cleared.** This build is a proof of concept and sets no requirement governing where assessed content is processed or what may be transmitted to an external model service. The system does transmit portal content to a model provider in order to function, so this is a **prerequisite gate for any production run**, not a permanent exclusion. It is recorded here so that a later reader does not mistake silence for a considered decision.
- Migration of historical assessment data. The historical URL database is read as a resolution source; migrating prior-cycle answers is a separate effort.
- The public-facing knowledge base and any publication of results. Exporting a cycle's delivered answers is in scope (FR-101 through FR-106); distributing or publishing that export is not.

## Open Questions

Resolved answers should be folded back into this specification.

1. ~~**Confidence tier band boundaries**~~ — **resolved**. Named tiers were removed; confidence is displayed as a 0–100 percentage with a single acceptance threshold at 75 (FR-041, FR-042, FR-134).
3. **Evidence retention period and storage location** — two cycles is assumed; the governing retention policy and storage location need confirmation. *(Non-blocking for specification; needed at planning.)*
4. **Role bands** — the concrete assessor and administrator role definitions live with the identity system, which is out of scope here, but the capability boundaries must line up. *(Non-blocking.)*
5. **Total volume and cycle assessment window** — 193 countries × ~200 questions × biennial is assumed from project background, but SC-011's "cycle's assessment window" still has no agreed value. The measurement now exists (FR-114), so only the target is missing. *(Non-blocking for planning; SC-011 cannot be gated until the window is agreed.)*
6. **Initial supported language set** — the set itself is configuration, but its initial contents depend on a language-coverage evaluation of the candidate Assessor Agents. *(Non-blocking for planning; prerequisite for a first production run.)*

**Resolved since first draft**: the discrepancy-flag band (SC-003, configurable, 5–25% acceptable with a 5% non-independence floor); language coverage (FR-014 through FR-020); the accuracy floor (SC-002, 80% overall, breakdowns reported but not gated); output validation by a Validator agent with independent evidence verification (FR-076 through FR-091); and benchmark evaluation as a system capability (FR-092 through FR-100). The second clarification session added partial-run resume semantics (FR-067a, FR-067b), authentication-gated content handling (FR-107 through FR-111), observability (FR-112 through FR-118), answer export (FR-101 through FR-106), and review-surface accessibility (FR-119, FR-120). The specification carries no unresolved clarification markers.
