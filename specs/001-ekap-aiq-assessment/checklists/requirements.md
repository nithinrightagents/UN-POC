# Specification Quality Checklist: EKAP AIQ — AI-Assisted Portal Assessment

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-13
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

## Validation Notes

**Iteration 4 (2026-08-13, post-`/speckit-clarify`)** — **16 of 16 items pass.** Spec carries 103 functional requirements, 22 success criteria, 16 key entities, 55 acceptance scenarios, 15 edge cases, a terminology section, and stated implementation constraints.

### Clarify session outcomes

Five clarifications were resolved and integrated. Three were raised by the stakeholder unprompted and turned out to be the highest-impact items in the session.

| Clarification | Effect on spec |
|---|---|
| Validator agent checks each Assessor Agent's output | New group FR-076–FR-085; Validation Result entity; SC-015–SC-017 |
| Validator independently re-fetches cited evidence online | New group FR-086–FR-091; SC-018–SC-020; forced a split in FR-025 |
| Benchmark comparison is a system capability | New group FR-092–FR-100; three new entities; SC-021–SC-022; made SC-002/003/008 verifiable |
| Accuracy floor = 80% overall, breakdowns reported not gated | SC-002 resolved; last marker cleared |
| "Assessor Agent" = AI, "Assessor" = human; review unlocks per portal | Terminology section; 179 occurrences disambiguated; FR-043a–FR-043c |

### Defects found and corrected during the scan

- **Benchmark gap** (stakeholder-identified): SC-002, SC-003 and SC-008 depended on a comparison no requirement provided. The "success criteria are measurable" item was passing on a technicality — the criteria were phrased measurably but nothing produced the measurement. Closed by FR-092–FR-100.
- **FR-025 contradiction**: independent verification made a missing element a *failure*, while FR-025 made it a valid point-in-time *record*. Both could not hold. Resolved by splitting on whether verification ever passed (FR-025, FR-091).
- **Terminology collision**: "assessor" denoted both the AI component and the human reviewer across 179 occurrences, including the adjacent entities `Assessor Run` (AI) and `Assessor Decision` (human). Resolved to `Assessor Agent` / `Assessor`; `Assessor Run` renamed to `Assessor Agent Run`.
- **Stale cross-references**: two references broken by earlier renumbering (FR-028→FR-041 for tier bands, FR-019→FR-027 for adjudication timing). Repaired. FR IDs are now declared stable identifiers rather than sequence positions, so later insertions append rather than renumber.
- **FR-074 vs `.env`**: the requirement forbade redeployment for a config change, but `.env` is read at process start. Relaxed to forbid code edits and rebuilds while permitting a restart.

### Scope additions the clarifications introduced

Independent verification roughly doubles crawl volume against a fixed shared per-domain budget (FR-089), making it the main pressure on SC-011. Benchmark mode adds a second run type through the same pipeline. Both are deliberate and recorded in Assumptions.

One item was added without being requested and is flagged for removal if unwanted: **FR-096 reports accuracy broken down by confidence tier**. It is the same computation as the other breakdowns and indicates whether confidence tiers are usable for review triage. Reported only, never gated.

### Deferred — not asked, quota reached

| Area | Why deferred |
|---|---|
| Partial-Assessor-Agent resume semantics (FR-067) | "MUST reach a defined state deterministically" does not say *which* state — complete the remaining agents, or discard partials and re-run. Now more intricate with validation retries in the pipeline. Best resolved during data-model design in `/speckit-plan`. |
| Answer export / handoff boundary | Publication is out of scope, but nothing states how validated answers leave the system. A scope-boundary gap. |
| Cycle assessment window | SC-011 measures against "the cycle's assessment window", which is undefined; ties to open question 5. |
| Observability and accessibility | No logging, metrics, or accessibility requirements. Plan-level for a UN-facing system, but should not be forgotten. |

### Changes since iteration 1

Two of the three clarification markers were resolved by stakeholder answers.

**Discrepancy band (was marker 2)** — resolved, and the answer surfaced a genuine gap. The stakeholder described discrepancy as an aggregate comparison across a country's whole questionnaire ("assessor 1 has 50/100 yes, assessor 2 has more than 60/100 yes"), whereas iteration 1 specified only per-question discrepancy. `project_context.md` corroborates the aggregate form: the existing methodology uses "automated discrepancy detection with a configurable threshold (e.g., 5%)" at country level. The two checks catch different failures — assessors can disagree on many individual questions while landing on the same aggregate count — so both are now specified as independent checks with independent thresholds:

- Per-question: FR-027 through FR-034 (drives retries)
- Portal-level: FR-035 through FR-039 (drives human review of the portal as a whole; explicitly does not re-run already-consensus questions)
- SC-003 now states a configurable 5–25% acceptable band with a 5% non-independence floor; SC-013 added to test that portal-level detection catches what per-question adjudication misses.

**Language coverage (was marker 3)** — resolved as a configured supported-language set (FR-014) with a human decision point rather than automatic escalation: portals outside the set surface a prompt offering a best-effort attempt (FR-017), which if authorized is marked as best-effort and confidence-capped (FR-018), and if declined or unanswered is escalated (FR-019). The pending decision does not block the batch (FR-020). SC-014 added.

**"Have params for everything"** — taken as a general directive, not just for discrepancy. A dedicated Configuration section (FR-072 through FR-075) now enumerates fourteen named run-time parameters and requires them to be inspectable with current and default values. A Configuration Snapshot entity was added so any past session's effective settings remain auditable.

### Outstanding item

**1 [NEEDS CLARIFICATION] marker remains.**

| # | Location | Question | Status |
|---|----------|----------|--------|
| 1 | SC-002 | Accuracy floor for consensus answers on the benchmark set, pre-human-review | Re-asked in simplified terms; awaiting answer |

Blocking for acceptance only — SC-002 cannot be evaluated without an agreed target. Not blocking for `/speckit-plan`, since no requirement's design depends on the value.

### Resolved as documented assumptions

Defensible defaults exist for each; none require stakeholder input before planning:

- **Confidence tier bands** → 0–100 scale, high 80–100 / medium 50–79 / low 0–49, configurable per FR-041.
- **Best-effort confidence ceiling** → top of the medium tier, so a translated answer is never shown as high confidence.
- **Evidence retention** → at least two full survey cycles. Storage location deferred to planning.
- **Role bands** → identity and access management is out of scope; only an attributable actor identity per action is required.
- **Total volume** → ~193 countries × ~200 questions, biennial, from project background. SC-011 is expressed against the cycle window rather than a fixed throughput rate so it survives revision of those figures.
- **Initial supported language set** → contents depend on a language-coverage evaluation of the candidate assessors. A project activity and a prerequisite for a first production run, not for planning.

### Iteration 3 (2026-08-13) — correction to portal-level discrepancy

Iteration 2 justified portal-level discrepancy as catching divergence that per-question adjudication misses. **That was wrong, and SC-013 as written was untestable.** Both checks compare the same two assessors over the same questions; portal-level is an aggregate view of the same signal, not an independent detector. The specific defect: SC-013 posited assessors reaching per-question consensus on every question while their affirmative rates differed — impossible, since agreement on every question makes the yes-counts identical and the gap zero.

Corrected in this iteration:

- **Measures now taken on first-round positions** (FR-035), before retries. This is what gives portal-level a role per-question adjudication cannot fill: a portal whose assessors initially read it very differently is flagged for joint human review even after every individual disagreement has been reconciled by retry. Convergence on retry does not erase a poor first read — and this is precisely the case the existing manual methodology sends back for joint review.
- **Differing-answer rate is now the primary measure** (FR-036). The affirmative-rate gap the stakeholder described can miss disagreement entirely: two assessors each answering yes to 50 of 100 while disagreeing on 40 individual questions produce a gap of zero against a 40% differing-answer rate. The gap is retained and recorded, but may not be the sole configured trigger.
- SC-013, P3 acceptance scenarios 8–11, the related edge cases, and the "two scopes of discrepancy" assumption were all rewritten to match.

### Note on technology-neutrality and the ADK constraint

Two competing pressures were resolved as follows.

The stakeholder has specified that the build will be an ADK implementation. That is now recorded in a dedicated **Implementation Constraints (given)** section rather than being threaded through the functional requirements, and four consequences are drawn out explicitly: assessor independence becomes an ADK composition property, the single session identifier maps onto ADK session state, resumability requires durable rather than in-memory session persistence, and the supported language set follows the coverage of the models configured behind the ADK assessors.

The 75 functional requirements remain implementation-neutral. This is deliberate: each must stay testable against whatever agent topology is actually built, and a requirements document the UN will read should not go stale when a model or framework version changes. The checklist item "no implementation details" is therefore still assessed as passing — the constraint is stated once, in a section explicitly labelled as a given rather than as a requirement to validate.

Candidate model names remain out of the spec. Model selection and ADK agent topology are `/speckit-plan` decisions.

## Notes

- The single remaining marker requires a spec update before this checklist can be fully closed.
- `/speckit-plan` may proceed now; `/speckit-clarify` is the path to closing SC-002.
