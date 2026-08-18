# Specification Quality Checklist: Decoupled AI Prefill

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-18
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

## Notes

### Iteration 1 — issues found and fixed

1. *Clarifications section misattributed decisions to the user.* Three underspecified points were originally written in the `Q: … → A: …` form that records answers a user gave; they were the spec author's proposals. Rewritten as a **Decisions Taken** section naming each decision, its rationale, and the requirement it drives, then put to the requester.

2. *Cross-spec conflict was unstated.* Removing the AI answer from the publication precedence chain contradicts `specs/007-headless-rest-api/spec.md` FR-API-032. FR-PF-005 now states the supersession explicitly.

3. *A material gap in the current system was undocumented.* The assessor screen reads heuristic pre-fill rows written for demo seeding, not the live multi-agent pipeline's output. Left implicit, a planner would assume the wiring exists. Added to Assumptions.

### Iteration 2 — requester decisions incorporated

4. **D2 resolved — a dedicated agent settles disagreements, not a mechanical pick.** The spec originally proposed resolving answer disagreements by comparing validated evidence strength with confidence as a tie-break. The requester specified a dedicated agent (named the **resolver agent** in iteration 3) that examines what the disagreement is and determines which position is correct. Rewrote FR-PF-023–029 (adding FR-PF-026a–d and FR-PF-028a), User Story 4, the Overview, Key Entities (added the resolver-decision entity), SC-006/006a, two edge cases, and the Out of Scope entry that had previously excluded a third agent outright.

5. **D1 resolved — mandatory completion, which dissolves the question.** The requester's answer ("the AI prefills the answer, then the human can't leave it blank, he has to say no") removes the gap the AI fallback existed to fill rather than choosing among ways to handle it. Added FR-PF-005a–005e, FR-PF-009a, SC-004a/004b, four edge cases, three assumptions, two Out of Scope entries, and a new Overview paragraph. FR-PF-009 was corrected — it had permitted "submit no answer at all", which mandatory completion contradicts.

6. *Correction carried into the spec.* Iteration 1's D1 text claimed removing the AI fallback "will lower published scores". That was wrong: [admin.py:224](../../../src/portal/admin.py#L224) computes `score = affirmative / len(breakdown)` where `breakdown` holds only answered questions, so unanswered questions leave the denominator too and the score can rise. The real consequence is loss of comparability between units with different completion rates, which is what D1's final text states — and what mandatory completion prevents.

### Verified against the running code

- Precedence chain and both AI fallbacks: [finalize.py:14-46](../../../src/api/finalize.py#L14-L46) — confirms the AI is the last *two* fallbacks (pipeline consensus, then the `agent_index == -1` heuristic row), not one. FR-PF-005 removes both.
- Score denominator: [admin.py:213-231](../../../src/portal/admin.py#L213-L231).
- Source cascade order and rejection recording: [chain.py:35-83](../../../src/shared/tools/linkresolution/chain.py#L35-L83) — already matches FR-PF-014–016.
- Parallel assessor dispatch: [scheduler.py:301-303](../../../src/orchestration/scheduler.py#L301-L303) — already concurrent.
- Current adjudication and its escalation path: [adjudicator/agent.py](../../../src/agents/adjudicator/agent.py), [scheduler.py:369-390](../../../src/orchestration/scheduler.py#L369-L390) — deterministic, escalates on any answer difference. This is what FR-PF-026 replaces.
- Assessor screen reads only heuristic rows: [assessor.py:52-56](../../../src/portal/assessor.py#L52-L56).

### Scope observation for planning (not a spec defect)

Much of the pipeline already exists — the ordered cascade, two parallel independent assessors, and per-agent validation retry are built and working. The genuine deltas are:

| Delta | Requirements | Existing code affected |
|---|---|---|
| Resolver agent replaces escalate-on-disagreement | FR-PF-026, 026a–d | `scheduler.py`, new agent module |
| No AI-side human work items | FR-PF-002 | `scheduler.py` escalation calls |
| Second validation over the resolved position | FR-PF-030–032 | new gate |
| Named no-suggestion reason taxonomy | FR-PF-034 | `EscalationReason` → prefill reasons |
| Assessor screen reads pipeline output, not heuristic rows | FR-PF-008, 013 | `portal/assessor.py` |
| Mandatory completion per indicator | FR-PF-005a–005e | `portal/assessor.py`, submission model |
| AI removed from precedence; publish gated on coverage | FR-PF-005, 005d | `api/finalize.py`, `portal/admin.py`, `api/routers/publication.py` |

FR-PF-005 changes behavior spec 007 already promises, so `specs/007-headless-rest-api/spec.md` FR-API-032 should be annotated as superseded during planning — the same "supersede the framing, not the file" convention specs 005 and 006 already use in this repo.

### Iteration 3 — `/speckit-clarify` session 2026-08-18

Five clarifications asked and integrated. Checklist re-validated against the updated spec: **16/16 → 16/16 items passing**, no state changes, no regressions.

| # | Ambiguity | Resolution | Spec impact |
|---|---|---|---|
| 1 | Lifecycle terminal outcome for a no-suggestion prefill. The machine in [unit_state.py:15-25](../../../src/shared/state/unit_state.py#L15-L25) has exactly three terminals with an exhaustive-coverage assertion at [:47](../../../src/shared/state/unit_state.py#L47) behind spec 001 SC-009 — removing AI escalation could not simply delete one. | A distinct no-suggestion terminal. `unassessable` keeps its narrower "evidence not located" meaning so historical rows do not change meaning; `escalated` becomes unreachable from a prefill run. | FR-PF-032a–032d, SC-007a, Prefill Run entity |
| 2 | What makes an assessor's work on a unit "complete" — FR-PF-005c/005d relied on the notion without defining it. | An explicit, attributed, timestamped act by the assessor; never inferred from every indicator happening to carry an answer. Publication checks for the declaration. | FR-PF-005d rewritten, FR-PF-005f–005h, US1 scenarios 9–11, SC-004c, new *Assessor Completion* entity |
| 3 | Whether spec 007's programmatic interface keeps pace. | Full parity. Forced rather than optional: publication now requires a completion declaration, so an interface unable to make one could never publish again — its publish endpoint would silently break. | New *Programmatic parity* section (FR-PF-042–048), SC-013/014, D1 note that FR-API-023 is superseded too |
| 4 | No spend control exists anywhere — [cost_ledger.py](../../../src/core/telemetry/cost_ledger.py) records but never limits, and this feature makes runs fully unattended. | Per-run configured budget. The in-flight indicator finishes, no further indicators dispatch, unreached ones get a budget-reached prefill, re-run resumes. Unset budget = no cap, preserving today's behaviour. | FR-PF-041a–041e, FR-PF-034 reason added, SC-015, edge case, settings + ledger dependencies |
| 5 | "Discrepancy" already means *humans disagreed* ([discrepancy.py](../../../src/portal/discrepancy.py), `DiscrepancyCase`, escalation queue). Reusing it for the AI-side agent risked a planner wiring the new agent into the human path. | Renamed to **resolver agent**; comparison is the **agreement outcome**, output is a **resolver decision**. "Adjudicator" also avoided — taken by the existing mechanical comparison. | 35 renames across the spec; *Agreement Outcome* and *Resolver Decision* entities; terminology assumption added |

**Coverage after this session:** Domain/lifecycle, Interaction flow, Integration, and Terminology moved Partial → Resolved. Non-functional reliability moved Missing → Resolved via the budget cap.

**Remaining Outstanding (low impact, deliberately not asked):**

- *Performance target.* SC-005 says parallel assessment takes "materially less" wall-clock time than sequential — a comparative assertion that is verifiable, but there is no absolute target for how long a 111-indicator run should take. Better set during planning against a measured baseline than guessed now.
- *Concurrency of prefill runs.* Spec 007 FR-API-014a already caps concurrent runs; whether that same cap governs portal-triggered prefill runs is a planning-level wiring detail, not a spec ambiguity.
- *Migration of existing published records.* The live `data/aiq.db` holds 2 publication records against 1073 human submissions — demo/seed data only, so backfilling under the new precedence chain is an operational step for planning, not a requirements decision.
