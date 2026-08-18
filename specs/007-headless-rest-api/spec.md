# Feature Specification: Headless Assessment REST API

**Feature Directory**: `specs/007-headless-rest-api`
**Created**: 2026-08-18
**Status**: Draft
**Input**: Expose the EKAP AI assessment pipeline as a headless REST API so that any external UI or third-party integration can use it without going through the portal. The system already has a working AI pipeline (link resolution → multiple independent AI assessor agents → validator → adjudicator) and a human assessor workflow (blind A/B reviewers), all of which currently lives behind an HTML/form-based portal that only returns rendered pages and redirects — making it unusable from any non-browser client. The feature must expose project management, question management, unit management, AI assessment triggering, AI assessment status, AI results retrieval, human assessor submission and retrieval, publication, and published-results retrieval over structured JSON endpoints, keeping the existing portal untouched. The AI layer dependencies (model credentials, rate limiter, browser session, cost ledger, fetch log, stage event log) must be wired through the same application lifecycle, sharing the same settings and data store as the portal rather than running as a separate service. Access control for the initial version is a single configured shared API key. The current in-memory tracking of running assessment jobs must be replaced with a persistent job status record so status survives restarts and is queryable programmatically.

## Overview

Every capability the platform has today — creating a survey cycle, defining indicators, registering a country or city unit, running the multi-agent AI assessment, collecting two blind human assessors' answers, and publishing a final score — is reachable only by a human operating a browser. The surfaces that expose these capabilities answer with rendered pages and post-submit redirects, so a non-browser caller has no way to learn whether an operation succeeded, what identifier was created, whether a long-running assessment is still in flight, or what the resulting answers were. Any external interface, partner system, or automated harness that wants to use the assessment engine has to either scrape markup or be rebuilt inside the portal.

This feature adds a second, structured entry point to the *same running system*: the same configuration, the same data store, and the same AI pipeline dependencies, exposed as machine-readable request/response operations. A caller with a valid key can drive a complete assessment lifecycle end to end and read every result, with each operation returning a definite outcome and a stable identifier instead of a page. The existing portal is unchanged and continues to work exactly as it does today — both surfaces act on one shared body of data, so work started through one is visible through the other.

Because a full assessment run against a real indicator set spans hundreds of model calls, triggering an assessment cannot be a wait-for-the-answer operation. It hands back a job reference immediately, and the caller polls a status operation until the run reaches a terminal outcome. Today that in-flight tracking exists only in the memory of the running process: it is invisible to any caller, and a restart erases it, leaving units that were mid-run indistinguishable from units that were never started. This feature makes job status a durable, queryable record so that a caller — and an operator after a restart — can always get a definite answer about what happened to a run.

## Clarifications

### Session 2026-08-18

- Q: For human assessor answer retrieval, should the programmatic interface preserve the portal's blind A/B guarantee? → A: Yes, strictly — every human-answer read must name exactly one assessor role and returns only that role's submissions. No operation ever returns both roles' answers together; a combined view would require a separate, privileged capability that is out of scope here.
- Q: What happens when an AI assessment is triggered for a unit that already has a run in flight? → A: The trigger is idempotent — it succeeds and returns the reference of the already-running job instead of starting a second run, mirroring the portal's existing duplicate-trigger guard.
- Q: Which state does a client see for a run that was in flight when the service stopped? → A: The observable run states are exactly running, done, and failed — no separate "interrupted" state. An interrupted run is reported as failed with a cause identifying the service stop, so a client needs only one rule: any terminal state other than done means re-trigger.
- Q: What must happen when no shared secret is configured? → A: The service starts normally and the portal stays fully usable, while every programmatic operation is refused with a "not configured" response. The interface is never reachable unauthenticated, and a deployment that never sets a secret is a supported portal-only deployment.
- Q: What happens when a client creates something that already exists? → A: Duplicates are refused as conflicts naming the existing entity, with nothing modified — an existing cycle identifier, an indicator code already present in that cycle, or a unit matching an existing unit's cycle and country/city. *(Narrowed during planning: the answer originally allowed the same country or city with a different portal URL to create a second unit. The data store enforces at most one unit per cycle and country/city, so that case is not representable — the conflict is keyed on cycle + country/city alone, independent of URL. See [plan.md](./plan.md) research R9.)*
- Q: Which question identifier does the interface speak, given that a question has both a cycle-scoped stored identifier and a bare indicator code? → A: The stored cycle-scoped question identifier is *the* identifier for every question-scoped operation — AI results, human submissions, and published breakdowns are all keyed by it — and the bare indicator code travels alongside as a separate display field. Clients round-trip the identifier opaquely and never construct one themselves.
- Q: How many assessment runs may be in flight at once across different units? → A: A configured maximum bounds concurrent runs across all units. A trigger that would exceed it is refused with a capacity-reached reason and starts nothing, leaving the client to retry later — no queue and no `pending` state, keeping the three observable states of FR-API-018 intact.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - An external client drives a complete AI assessment without a browser (Priority: P1)

A developer building a separate front end, or an integrator wiring the engine into another system, sets up a survey cycle, defines the indicators to assess, registers a country or city unit with its portal URL, starts the AI assessment for that unit, watches its progress, and reads the resulting per-question answers — entirely through structured calls, never parsing markup or following a redirect to guess an outcome.

**Why this priority**: This is the feature. Without a single uninterrupted programmatic path from "no project" to "here are the AI answers", the engine remains portal-only and no external client can use it at all. Every other story refines or protects this path.

**Independent Test**: Can be fully tested by running the complete sequence — create cycle, add questions, add unit, trigger assessment, poll to completion, retrieve answers — as a non-browser client against a running instance, asserting that every step returns structured data with the identifiers needed for the next step and that no step requires interpreting a rendered page.

**Acceptance Scenarios**:

1. **Given** a running instance and a valid key, **When** the client creates a survey cycle, **Then** the response confirms creation and carries the cycle's identifier and stored attributes, and the new cycle appears in a subsequent list of cycles.
2. **Given** an existing cycle, **When** the client adds an indicator supplying title, what, why, how, evidence locus, module, and benchmark case, **Then** the indicator is stored with all of those fields intact and is returned when the cycle's questions are retrieved.
3. **Given** an existing cycle, **When** the client registers a unit with its type (country or city), display name, and portal URL, **Then** the unit is created with an identifier the client can use to trigger and query assessments, and appears in a subsequent list of that cycle's units.
4. **Given** a cycle with indicators and a registered unit, **When** the client triggers the AI assessment for that unit, **Then** the call returns promptly with a job reference rather than holding the connection open until the run finishes, and the run proceeds in the background.
5. **Given** a triggered assessment, **When** the client polls its status, **Then** the client receives the run's current state (running, done, or failed) together with progress expressed as questions completed out of the cycle's total.
6. **Given** an assessment that has reached the done state, **When** the client retrieves the AI results for that unit, **Then** each assessed question carries its yes/no answer, a confidence score, the justification text, and the evidence URL.
7. **Given** a cycle created programmatically, **When** an operator opens the existing portal, **Then** that cycle, its indicators, its units, and its AI results are visible there — both surfaces read and write the same data.

---

### User Story 2 - Job status survives a restart and is always answerable (Priority: P2)

An integrator triggers a long assessment and then the service is restarted — deployed, crashed, or cycled by an operator. Polling the status of that unit's run still returns a definite answer: what state the run is in, how far it got, and if it did not finish, that it did not finish. The client is never left unable to distinguish "still working" from "never started" from "died halfway".

**Why this priority**: Runs against a real indicator set take long enough that a restart during one is a normal event, not an edge case. A client that cannot tell an abandoned run from a live one either polls forever or re-triggers blindly, so durable status is what makes the asynchronous trigger in User Story 1 usable in practice rather than only in a single uninterrupted process.

**Independent Test**: Trigger an assessment, restart the service while the run is in flight, then poll that unit's status and confirm a definite non-ambiguous state and the progress reached before the interruption are returned — with no reliance on the previous process's memory.

**Acceptance Scenarios**:

1. **Given** an assessment triggered and then interrupted by a service restart, **When** the client polls that unit's status after the restart, **Then** the run is reported as failed with a cause identifying the service stop — never as still running, and never as an "unknown" or missing response implying the run never existed.
2. **Given** an interrupted run, **When** the client re-triggers the assessment for that unit, **Then** a new run starts and picks up only the work the interrupted run had not already completed, and the previous interrupted run remains distinguishable in the record.
3. **Given** a unit that has never had an assessment triggered, **When** the client polls its status, **Then** the response clearly indicates that no run exists for it, distinct from a run that exists and is running.
4. **Given** an assessment that failed part-way through, **When** the client polls its status, **Then** the failed state is reported along with how many questions had completed and enough detail to tell the failure apart from a successful completion.
5. **Given** an assessment already running for a unit, **When** the client triggers that unit's assessment again, **Then** the call succeeds and returns the reference of the run already in flight rather than starting a competing second run.

---

### User Story 3 - A human reviewer's answers are submitted and read programmatically, without breaking blindness (Priority: P2)

An external reviewer interface lets a human assessor working as role A or role B answer a question on a unit, attach an evidence URL and notes, and later reload what they previously submitted — while never being able to see the other role's answers, exactly as in the existing portal.

**Why this priority**: The platform's final scores depend on two independent human assessments, so a programmatic interface that only covers the AI half cannot support a real external review front end. It is second to User Story 1 because the AI path delivers standalone value first, and the blindness constraint makes this the story where getting the rules wrong is most damaging.

**Independent Test**: Submit answers as role A and role B for the same question on the same unit through the interface, then read back each role's answers separately and confirm each read returns only its own role's submissions, with no operation returning both.

**Acceptance Scenarios**:

1. **Given** a registered unit with indicators, **When** a client submits an answer for a question as role A with an evidence URL and notes, **Then** the submission is recorded against that role with its answer, evidence URL, notes, and the acting person's identity, and is visible in the existing portal for that same role.
2. **Given** a submission made without an evidence URL or notes, **When** it is recorded, **Then** it is accepted with those optional details absent rather than rejected.
3. **Given** submissions from both role A and role B on the same question, **When** the client retrieves human answers naming role A, **Then** only role A's submissions are returned and role B's answers do not appear anywhere in the response.
4. **Given** a request to retrieve human answers that does not name a role, **When** it is processed, **Then** it is rejected rather than defaulting to returning both roles.
5. **Given** a role that has answered some of a unit's questions and not others, **When** that role's answers are retrieved, **Then** the response distinguishes questions that role has answered from those it has not.
6. **Given** a role that revises its answer to a question, **When** that role's answers are retrieved, **Then** the current answer is what is returned.

---

### User Story 4 - Publication and published results are reachable programmatically (Priority: P3)

Once a unit's answers are in, a client triggers publication for that unit — computing the final score from the two human assessors' agreement with an AI fallback where no human answer exists — and afterwards reads back the published score together with its per-question breakdown.

**Why this priority**: This closes the lifecycle and lets an external interface present final results, but the assessment and review capabilities deliver value before anything is published, and publication remains available through the existing portal in the meantime.

**Independent Test**: For a unit with a mix of agreeing human answers, differing human answers, and AI-only answers, trigger publication through the interface and confirm the returned score and per-question breakdown match the score the existing portal produces for the same unit.

**Acceptance Scenarios**:

1. **Given** a unit whose questions have answers, **When** the client triggers publication, **Then** a publication record is created attributed to the acting person, and the response reports the computed score.
2. **Given** a published unit, **When** the client retrieves its published results, **Then** the score and a per-question breakdown of the final answers are returned.
3. **Given** a unit where both human assessors agree on a question, one where they differ, and one with only an AI answer, **When** publication is triggered, **Then** the final answer chosen for each of those questions is the same one the existing portal's publish action would choose.
4. **Given** a unit that has never been published, **When** the client retrieves its published results, **Then** the response clearly indicates nothing has been published for it rather than reporting a zero score as if it had.
5. **Given** a unit published more than once, **When** its published results are retrieved, **Then** the most recent publication is what is returned.

---

### User Story 5 - Access is restricted to holders of a configured key (Priority: P2)

An operator configures a single shared secret alongside the platform's other settings. Callers presenting that secret can use every programmatic capability; callers without it are refused and learn nothing about what projects, units, or answers exist.

**Why this priority**: The interface exposes both the assessment data and the ability to spend real model budget, so it cannot ship without gating — but a single shared key is deliberately minimal, and per-user identity is a later concern, which is why this sits below the capability stories rather than above them.

**Independent Test**: Call every programmatic operation with a valid key, with a wrong key, and with no key at all, confirming the first succeeds and the latter two are refused without disclosing any project, unit, question, or answer data.

**Acceptance Scenarios**:

1. **Given** a configured key, **When** a client calls any programmatic operation presenting that key, **Then** the operation proceeds.
2. **Given** a configured key, **When** a client calls any programmatic operation with a wrong key or none, **Then** the call is refused and the response body contains no project, unit, question, answer, or score data.
3. **Given** a refused call to trigger an assessment, **When** it is refused, **Then** no assessment run is started and no model spend is incurred.
4. **Given** a client without a key, **When** it opens the existing portal, **Then** the portal behaves exactly as it does today — the key requirement applies only to the programmatic interface.
5. **Given** no key is configured at all, **When** the service starts, **Then** it starts successfully and the portal continues to work normally, while every programmatic call is refused as not-configured — the interface is never reachable without a key.

### Edge Cases

- A client references a cycle, unit, or question that does not exist: the operation is refused with a response identifying what was not found, rather than creating it implicitly or returning an empty success.
- A client triggers an assessment for a unit that has no portal URL, or for a cycle with no indicators defined: the trigger is refused with a reason, rather than starting a run that can only do nothing.
- Two clients trigger the same unit's assessment at the same moment: exactly one run exists afterwards and both callers receive a reference to it.
- A client triggers every unit in a cycle in a tight loop: runs start up to the configured concurrency cap and every further trigger is refused as capacity-reached, so a single loop cannot commit unbounded model spend.
- A client polls status immediately after triggering, before any question has completed: a running state with zero of N completed is returned, not a missing or failed state.
- A client retrieves AI results while the run is still in flight: the questions completed so far are returned, clearly distinguished from a completed run's full result set, rather than the request being refused outright or the partial state being presented as final.
- A question reached a blocked or escalated terminal outcome rather than a delivered answer (spec 004): its AI result carries no answer, together with the reason it was left blank, rather than being omitted from the results or reported as a negative answer.
- A client retries a create after a timeout, or otherwise creates a cycle whose identifier already exists, adds an indicator code already present in that cycle, or registers a unit matching an existing unit's cycle and country/city: the call is refused as a conflict naming the existing entity and nothing is modified — a retry can never silently overwrite a live project or duplicate a unit.
- The assessment run cannot start because the model provider or its credentials are unavailable: the job reaches the failed state with that cause recorded, rather than sitting in the running state indefinitely.
- Two indicators added under different cycles carry the same indicator code: both are stored and remain retrievable under their own cycle, as the existing portal already allows.

## Functional Requirements *(mandatory)*

#### Interface shape and coexistence

- **FR-API-001**: The system MUST expose a programmatic interface that answers every operation with structured, machine-readable data — never rendered markup and never a redirect the caller must follow to discover the outcome.
- **FR-API-002**: The existing portal surfaces MUST remain functionally unchanged by this feature: every flow an operator can perform in the portal today MUST continue to behave identically.
- **FR-API-003**: The programmatic interface MUST operate on the same configuration and the same stored data as the portal, within the same running service, such that work created or advanced through either surface is immediately visible through the other.
- **FR-API-004**: The dependencies the AI pipeline requires — model provider credentials, per-domain rate limiting, browser session, cost ledger, fetch log, and stage event log — MUST be established through the same running service's startup and shutdown as the portal's, so that an assessment triggered programmatically records the same telemetry and cost accounting as one triggered from the portal.
- **FR-API-005**: Every operation MUST report success or failure explicitly and, on failure, MUST identify the cause in a form a non-human caller can act on.

#### Project, question, and unit management

- **FR-API-006**: A client MUST be able to create a survey cycle (project), supplying at minimum its identifier, name, questionnaire reference, and project type. Creating a cycle whose identifier already exists MUST be refused as a conflict identifying the existing cycle, and MUST leave that cycle unmodified — a create MUST NOT act as an update.
- **FR-API-007**: A client MUST be able to list all survey cycles and retrieve a single cycle's details.
- **FR-API-008**: A client MUST be able to retrieve the full set of indicators (questions) defined for a cycle.
- **FR-API-009**: A client MUST be able to add an indicator to a cycle supplying every field the portal accepts today — title, what, why, how, evidence locus, module, and benchmark case — and those fields MUST be stored and returned without loss. Adding an indicator whose code already exists within the same cycle MUST be refused as a conflict identifying the existing indicator; the same indicator code under a different cycle MUST be accepted.
- **FR-API-010**: A client MUST be able to register a unit (country or city) against a cycle with its unit type, display name, country/city identifier, and portal URL, and MUST be able to list a cycle's units. Registering a unit whose cycle and country/city identifier match an existing unit MUST be refused as a conflict identifying the existing unit, regardless of the portal URL supplied: the data store holds at most one unit per cycle and country/city, so a differing URL cannot create a second unit and MUST NOT be silently discarded as it is today.
- **FR-API-011**: Creating a cycle, indicator, or unit MUST return the identifier by which that entity is subsequently addressed, so a client can chain the whole lifecycle without consulting the portal or the data store directly.
- **FR-API-011a**: A question MUST be addressed by exactly one identifier throughout the interface — its stored cycle-scoped question identifier — and that same identifier MUST key every question-scoped operation and response, including AI results, human submissions and retrievals, and published per-question breakdowns. The bare indicator code MUST also be returned alongside it as a separate display field. A client MUST NOT have to construct, prefix, or otherwise derive a question identifier itself; identifiers returned by the interface MUST be accepted back unchanged.

#### AI assessment triggering and status

- **FR-API-012**: A client MUST be able to trigger the full AI assessment pipeline — link resolution, independent multi-agent scoring, validation, and adjudication — for a single named unit.
- **FR-API-013**: The trigger operation MUST return promptly with a job reference while the run proceeds in the background, and MUST NOT hold the caller open for the duration of the run.
- **FR-API-014**: Triggering an assessment for a unit that already has a run in flight MUST succeed and return the in-flight run's reference, and MUST NOT start a second concurrent run for that unit.
- **FR-API-014a**: The number of assessment runs in flight concurrently across all units MUST be bounded by a configured maximum, set through the same settings mechanism as the platform's other operational parameters. A trigger that would exceed that maximum MUST be refused with a stated capacity-reached reason and MUST NOT start a run, leaving the client to retry later. Excess triggers MUST NOT be queued, and no additional observable run state MUST be introduced for them. A trigger for a unit whose run is already in flight MUST still succeed per FR-API-014 even when the cap is reached, since it starts no new run.
- **FR-API-015**: The trigger MUST be refused, with a stated reason and without starting a run, when the named unit or cycle does not exist, when the unit has no portal URL, or when the cycle has no indicators.
- **FR-API-016**: A client MUST be able to poll the status of a unit's assessment run and receive its state — running, done, or failed — together with progress expressed as the number of questions completed out of the cycle's total.
- **FR-API-017**: Assessment run status MUST be recorded durably rather than held only in the memory of the running process, and MUST remain queryable after the service restarts.
- **FR-API-018**: The run states a caller can observe MUST be exactly three — running, done, and failed — with no separate "interrupted" state. A run that was in flight when the service stopped MUST NOT be reported as running once the service is back up; it MUST be reported as failed, carrying a cause that identifies the service stop and thereby distinguishes an interruption from a genuine pipeline failure.
- **FR-API-019**: Polling the status of a unit for which no run has ever been triggered MUST return a response that distinguishes "never triggered" from any run state.
- **FR-API-020**: A failed run's status MUST record the cause of failure and the progress reached before it failed.
- **FR-API-021**: Re-triggering a unit whose previous run was interrupted or failed MUST start a new run that skips work the previous run already completed, and MUST leave the previous run's record distinguishable from the new one.

#### AI results retrieval

- **FR-API-022**: A client MUST be able to retrieve the AI assessment results for a unit, returning for each assessed question — keyed by the question identifier of FR-API-011a — its yes/no answer, confidence score, justification text, and evidence URL.
- **FR-API-023**: *(Superseded by spec 008 FR-PF-047)* A question with no suggestion MUST appear in the results with no answer and with its programmatic `PrefillReason` reason and display tag, rather than being omitted or reported as a negative answer.
- **FR-API-024**: Retrieving results while a run is still in flight MUST return the results completed so far, clearly marked as incomplete rather than presented as the run's final set.

#### Human assessor submission and retrieval

- **FR-API-025**: A client MUST be able to submit a human assessor's answer for one question on one unit, identifying the question by the identifier of FR-API-011a and naming the assessor role (A or B) and the acting person, with an optional evidence URL and optional notes.
- **FR-API-026**: A submission missing the optional evidence URL or notes MUST be accepted; a submission missing the role, the acting person, or the answer MUST be refused.
- **FR-API-027**: A submitted human answer MUST be recorded on the same terms as one submitted through the portal — same attribution, same relationship to any AI suggestion for that question, and same effect on the unit's A/B discrepancy state — and MUST be visible in the portal for that role.
- **FR-API-028**: A client MUST be able to retrieve the existing human submissions for a unit, and every such retrieval MUST name exactly one assessor role and return only that role's submissions.
- **FR-API-029**: No operation MUST ever return both assessor roles' submissions in a single response, and a retrieval request that omits the role MUST be refused rather than defaulting to returning both.
- **FR-API-030**: A role-scoped retrieval MUST distinguish the unit's questions that role has answered from those it has not, and MUST return the role's current answer where that role has revised a previous submission.

#### Publication and published results

- **FR-API-031**: A client MUST be able to trigger publication for a unit, attributed to the acting person, producing a publication record with a computed score and per-question breakdown.
- **FR-API-032**: *(Final term superseded by spec 008 FR-PF-005)* The final answer chosen for each question at publication MUST be determined by human precedence — an arbitration-resolved answer, then agreement between the two human assessors, then a single human answer — and MUST NOT fall back to AI suggestions or invent an answer where none exists.
- **FR-API-033**: A client MUST be able to retrieve a unit's published score and its per-question breakdown, receiving the most recent publication when a unit has been published more than once.
- **FR-API-034**: Retrieving published results for a unit that has never been published MUST state that explicitly rather than returning a zero or empty score as though it had been published.

#### Access control

- **FR-API-035**: Every operation on the programmatic interface MUST require a caller-presented shared secret that matches the one configured alongside the platform's other settings.
- **FR-API-036**: A call presenting a wrong secret or none MUST be refused, and its response MUST disclose no project, unit, question, answer, or score data.
- **FR-API-037**: A refused call MUST have no side effects — in particular, a refused assessment trigger MUST NOT start a run or incur any model spend.
- **FR-API-038**: The access requirement MUST apply only to the programmatic interface; the existing portal's access behavior MUST be unchanged.
- **FR-API-039**: When no secret is configured, the service MUST still start and the portal MUST remain fully usable, while every programmatic operation MUST be refused with a response stating that programmatic access is not configured. The programmatic interface MUST NOT be reachable unauthenticated under any configuration.

### Key Entities

- **Assessment Job**: A durable record of one triggered AI assessment run for one unit, carrying the reference the client polls, the unit and cycle it covers, its state (running, done, or failed), the count of questions completed against the cycle's total, the cause of any failure, and when it started and last changed. This replaces the current in-memory set of in-flight units, which is invisible to callers and lost on restart.
- **API Credential**: The single configured shared secret that gates the programmatic interface. It carries no per-user identity in this version.
- **AI Result View**: The per-question read-back of what the pipeline concluded for a unit — answer, confidence, justification, evidence URL, and, for a blocked question, the reason it was left blank. It is a projection of existing pipeline output, not new stored data.
- **Published Result View**: The per-unit read-back of the latest publication — the score and the per-question breakdown of final answers, projected from the existing publication record.

## Success Criteria *(mandatory)*

- **SC-001**: A non-browser client can complete the entire lifecycle — create a project, define indicators, register a unit, run the AI assessment, submit both human assessors' answers, publish, and read the published result — without ever interpreting a rendered page, following a redirect to learn an outcome, or touching the data store directly.
- **SC-002**: All ten named capabilities (project management, question management, unit management, assessment triggering, assessment status, AI results, human submission, human retrieval, publication, published results) are reachable programmatically; a client needs the portal for none of them.
- **SC-003**: Triggering an assessment returns its job reference in under two seconds regardless of how many indicators the cycle contains, and the caller can immediately poll a status that reflects the run.
- **SC-004**: After the service is restarted while an assessment is in flight, polling that unit returns a definite state and the progress reached — never an ambiguous or missing answer, and never a run reported as still running when nothing is running.
- **SC-005**: Reported progress for a run is never higher than the cycle's question total and never decreases between consecutive polls.
- **SC-006**: Across every combination of unit, question, and role in the test matrix, a role-scoped human-answer retrieval returns zero submissions belonging to the other role.
- **SC-007**: For a unit with a mix of agreeing human answers, differing human answers, and AI-only answers, the score and per-question breakdown produced by publishing programmatically are identical to those the portal produces for the same unit.
- **SC-008**: 100% of programmatic calls presenting an invalid or absent secret are refused, disclose no assessment data, and leave no side effect — measured across every exposed operation.
- **SC-009**: Every existing portal flow and its existing automated checks continue to pass unchanged after this feature ships.
- **SC-010**: An assessment triggered programmatically produces the same telemetry and cost accounting records as one triggered from the portal, so operators can account for spend regardless of which surface started the run.
- **SC-011**: The number of assessment runs in flight never exceeds the configured maximum, no matter how many triggers a client issues at once, and every refused trigger leaves no run started and no spend incurred.

## Assumptions

- "Project" and "survey cycle" refer to the same existing entity; the programmatic interface exposes it under the platform's existing cycle model rather than introducing a parallel notion of a project.
- The pipeline's existing resumability (a unit already terminal from a prior run is skipped) is what makes re-triggering after an interruption safe. This feature relies on that behavior and does not add its own resume mechanism.
- A run left in flight by a service stop is reported as failed with a service-stopped cause once the service is back up, since the process executing it no longer exists. Clients therefore need only one rule — any terminal state other than done means re-trigger — and re-triggering resumes the remaining work; the feature does not automatically restart interrupted runs on startup.
- Job status granularity is per unit run: the count of that unit's questions that have reached a terminal state, against the cycle's question total. Finer-grained per-stage progress within a single question is not part of the status contract.
- The shared secret is configured through the platform's existing settings/environment mechanism, alongside the settings the pipeline already reads. No key issuance, rotation, or per-client key management is implied. A deployment that never sets a secret is a supported portal-only deployment, not a misconfiguration to be rejected at startup.
- Every capability exposed here already exists behind the portal; this feature is an additional access path over existing behavior, and does not change how the pipeline scores, validates, adjudicates, escalates, or computes a published score.
- The confidence score, justification, and evidence URL returned for an AI result are the values the existing pipeline already produces and stores; no new derivation is introduced.
- Callers are trusted infrastructure holding the shared secret, not end users. Per-user identity, roles, and audit-by-user are deferred, so the acting person on a human submission or publication is a value the caller supplies, exactly as the portal does today.

## Dependencies

- The existing AI pipeline — link resolution, multiple independent assessor agents, validator, and adjudicator — and its existing background-run entry point for a single unit.
- The existing entity and storage layer for cycles, questions, units, agent runs, human submissions, discrepancy cases, and publication records, which both surfaces share.
- The existing settings mechanism the pipeline reads its model, rate-limit, threshold, and telemetry configuration from, extended with the shared secret and the concurrent-run cap.
- The existing telemetry facilities (cost ledger, fetch log, stage event log) that a run records into, and the existing per-domain rate limiter and browser session the pipeline requires.
- The existing publication precedence logic (arbitration → A/B agreement → single human answer → adjudicated AI answer) and the existing A/B discrepancy computation triggered by a human submission.
- Spec 004's blank-field fallback, whose reason tags are what an unanswered question's AI result carries.

## Out of Scope

- Any change to the portal's pages, forms, or flows beyond what is required to share the job status record with the programmatic interface.
- Per-user authentication, user accounts, role-based permissions, per-client keys, key rotation or issuance, and per-user audit trails.
- An operation that returns both assessor roles' answers together, or any other view that would defeat the blind A/B guarantee.
- Programmatic access to capabilities not among the ten named here — in particular MSQ document upload, the escalation queue and its dispositions, benchmark runs, answer export, and the public rankings surface.
- Running the programmatic interface as a separate deployable service, or with its own configuration or data store.
- Push-based delivery of assessment completion (callbacks, webhooks, streamed events); status is discovered by polling.
- Changing the pipeline's scoring, validation, adjudication, retry, escalation, or publication logic, or the values it records.
- Cancelling, pausing, or aborting an in-flight assessment run.
- Updating or deleting an existing cycle, indicator, or unit — including changing a registered unit's portal URL, display name, or type. Creates and reads only.
- Automatically resuming interrupted runs on service startup without a client re-trigger.
- Request-rate limiting, quotas, or usage metering of the programmatic interface itself — beyond the per-domain fetch rate limiting the pipeline already applies and the concurrent-run cap of FR-API-014a.
- Building the external UI that consumes this interface.
