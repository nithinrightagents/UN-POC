# Implementation Plan: EKAP AIQ — AI-Assisted Portal Assessment

**Feature Directory**: `specs/001-ekap-aiq-assessment`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-13
**Status**: Phase 1 complete — design artifacts generated
**Branch**: _not a git repository_ (see Notes)

## Summary

EKAP AIQ produces a **pre-filled survey** for a fixed questionnaire. For each question–portal pair the pipeline runs:

1. **Resolve the link** — prior-survey KB → MSQ → internet search, each of the first two switchable. The sources say *where to look*; they never supply the answer.
2. **Traverse it live** — always, whichever source supplied it. Evidence is captured at traversal.
3. **Assess in parallel** — N ≥ 2 independent Assessor Agents. An agent returning confidence below the threshold (default 75) retries **once**.
4. **Validate** — the Validator re-traverses the link and returns pass or fail; a fail returns a reason and retries, **twice at most**.
5. **Adjudicate** — validated positions are compared mechanically into a consensus answer.
6. **Roll up per portal** — the completed set goes to a human, who confirms, edits, or overrides every answer.

The design is a pipeline of ADK agents over a durable unit-state machine. Every pair is a *unit* whose recorded state — not in-memory progress — decides what work remains. Independence is structural: each Assessor Agent runs in its own ADK session with no shared conversational state, and the Validator is invoked per agent output rather than over the set.

The design is a **pipeline of ADK agents over a durable unit-state machine**. Every question–portal pair is a *unit* whose recorded state — not in-memory progress — decides what work remains. Independence is enforced structurally: each Assessor Agent runs in its own ADK session with no shared conversational state, and the Validator is invoked once per agent output rather than over the set. Correctness is measured only by benchmark mode, which drives the identical pipeline against a labelled set.

**Primary technical challenge**: this system is I/O-bound on a *shared, hard-capped* resource. Verification (FR-086) roughly doubles fetch volume against the same per-domain budget the Assessor Agents draw from (FR-089), across ~39,000 units × N agents per cycle. Throughput is therefore a scheduling problem, not a compute problem, and the per-domain rate limiter is the single most load-bearing component in the design.

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / runtime** | Python 3.11+ | ADK constraint; see [research.md](./research.md) R1 |
| **Agent framework** | Google Agent Development Kit (ADK) | Spec, Implementation Constraints (given) |
| **Model provider** | **Google Vertex AI endpoint, GCP authentication (ADC / service account)**; Gemini family models. Still reached through a provider port. | [research.md](./research.md) R2 — see Risks for the OICT approval question |
| **Model assignment** | **Interim: one flash model for every agent and the Validator**; divergence from temperature + prompt profile only, to be tuned on benchmark evidence | [research.md](./research.md) R7 §Interim — raises the independence risk, see Risks |
| **Configuration** | `.env` read at process start, snapshotted per session | Spec, Implementation Constraints (given); FR-072–FR-075 |
| **Persistence** | Relational store; SQLite for PoC, SQL Server / Azure SQL for EKAP production | [research.md](./research.md) R3 |
| **Session state** | ADK session state, durably persisted (not in-memory) | Spec, Implementation Constraints (given); FR-064–FR-067b |
| **Browser / capture** | Headless browser for render, region-scoped screenshot, and durable element reference | [research.md](./research.md) R4 |
| **Element reference** | CSS-path + text-hash composite, not raw XPath | [research.md](./research.md) R5 |
| **Concurrency model** | `asyncio` with a global per-domain token-bucket limiter shared by Assessor Agent and Validator traffic | [research.md](./research.md) R6 |
| **Review surface** | Web application, WCAG 2.1 AA, English interface | FR-119, FR-120 |
| **Export format** | Newline-delimited JSON + accompanying exclusion report | FR-101–FR-106; [contracts/export-schema.md](./contracts/export-schema.md) |
| **Observability** | Structured stage-transition events + per-session cost ledger | FR-112–FR-118 |
| **Testing** | `pytest`; fixture-driven stage isolation, recorded-page fixtures for deterministic agent tests | [quickstart.md](./quickstart.md) |
| **Target scale** | ~193 countries × ~200 questions × N ≥ 2 agents ≈ 78,000 agent runs + ~78,000 verification fetches per cycle | Spec, Assumptions |

**No unresolved NEEDS CLARIFICATION.** Four open questions carried by the spec (evidence retention, role bands, cycle window, initial language set) are all explicitly non-blocking for design; each maps to a configuration value or an out-of-scope system. They are restated in [research.md](./research.md) §Deferred with the default this design assumes.

### Where this fits in EKAP

The `understanding docs/` package places AIQ inside the wider EKAP platform, and that changes two design decisions:

- **AIQ is a third source, not the answer.** EKAP Process 03 cross-compares MSQ (government self-report) vs OSQ (assessor) vs **AIQ** (automated) and consolidates discrepancies for UN Administrator review. Our export (FR-101–FR-106) is the feed into that comparison — which is why every exported record carries its session identifier and evidence references rather than just an answer.
- **The platform expects an AI audit log in a defined shape.** `EKAP_AOSQInteractions` (InteractionId, SessionId, AssessorId, QuestionId, AgentType, InputRef, OutputRef, ModelVersion, HumanReviewRequired, ReviewedBy, ReviewDecision, Timestamp) is the platform's AI traceability table. Our audit trail is a strict superset; [contracts/ekap-integration.md](./contracts/ekap-integration.md) defines the projection onto it so AIQ can be adopted into EKAP without re-instrumenting.

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md`. No project-specific gates could be evaluated.

In its absence, the design was gated against the spec's own non-negotiables, which function as this feature's constitution. Each is a property that, if violated, invalidates the result rather than merely degrading it.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **Independence** | FR-010, FR-079 | One ADK session per Assessor Agent run; no shared state object; Validator invoked per output; Adjudicator receives outputs only post-completion. Enforced by an assertion at every stage boundary, not by convention. | PASS |
| **Auditability** | FR-059–FR-062 | Single session ID keyed on every record; append-only tables with no UPDATE path in the data access layer. | PASS |
| **No silent resolution** | FR-007, FR-033, FR-082, FR-109 | Every terminal state is either a delivered consensus answer or an escalation carrying a reason. The state machine has no third exit. | PASS |
| **Human authority** | FR-044–FR-046, FR-052 | Human actions are new immutable records; the system-proposed answer is never mutated. | PASS |
| **No ground-truth leakage** | FR-094 | Benchmark labels live in a separate table never joined into any agent-facing projection; enforced at the repository boundary. | PASS |
| **No credential handling** | FR-110 | No credential store, no login step, no secret field on Target Portal. Gated content escalates. | PASS |
| **Configuration externalized** | FR-072–FR-075 | Single settings object loaded from `.env`, snapshotted per session; no literal operational constant in code. | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

```
ekap-aiq/
├── pyproject.toml                  # deps, tool config, entry point `aiq`
├── .env.example                    # every parameter with its default; no secrets
├── README.md
│
├── src/ekap_aiq/
│   ├── __init__.py
│   ├── cli.py                      # `aiq run | resume | config show | export | benchmark`
│   │
│   ├── config/                     # .env loading, settings object, snapshotting
│   │   ├── settings.py             #   typed settings, defaults (FR-072, FR-073)
│   │   ├── validation.py           #   startup rejection rules
│   │   └── snapshot.py             #   per-session snapshot; retries read this (FR-075)
│   │
│   ├── domain/                     # pure logic. NO I/O — no network, no db, no model
│   │   ├── entities.py
│   │   ├── unit_state.py           #   the unit state machine (FR-065)
│   │   ├── resume.py               #   (unit, agent runs) → remaining work (FR-067a/b)
│   │   ├── confidence.py           #   acceptance threshold, ceilings (FR-024, FR-134)
│   │   └── measures.py             #   portal agreement measures (FR-035–FR-037)
│   │
│   ├── persistence/                # the only module that touches storage
│   │   ├── schema.py
│   │   ├── repositories.py         #   append-only: no update/delete path (FR-062)
│   │   └── benchmark_repo.py       #   isolated; no read path from agents/ (FR-094)
│   │
│   ├── linkresolution/             # WHERE TO LOOK — never what the answer is (FR-121–FR-128)
│   │   ├── chain.py                #   ordered chain + fall-through (FR-001–FR-003)
│   │   ├── sources/
│   │   │   ├── prior_survey_kb.py  #     links from previous runs, age-bounded (FR-127, FR-128)
│   │   │   ├── msq.py              #     links only — never answers (FR-126)
│   │   │   └── search.py           #     gov-TLD-restricted discovery (FR-004)
│   │   └── usability.py            #   candidate usable? rejection reasons (FR-005)
│   │
│   ├── portal/                     # traversal — always live, whatever supplied the link
│   │   ├── browser.py              #   headless render
│   │   ├── capture.py              #   region-scoped screenshot (FR-021)
│   │   ├── element_ref.py          #   composite durable reference (research R5)
│   │   ├── language.py             #   detection (FR-015)
│   │   └── boundaries.py           #   interstitial + auth-wall detection (FR-071, FR-108)
│   │
│   ├── ratelimit/                  # ONE shared per-domain budget, both callers (FR-089)
│   │   └── token_bucket.py
│   │
│   ├── agents/
│   │   ├── provider.py             #   Vertex AI port; per-invocation cost (R2, FR-116)
│   │   ├── prompts/                #   versioned prompt profiles (research R7)
│   │   ├── assessor.py             #   N independent agents (FR-008–FR-013)
│   │   ├── confidence_gate.py      #   <threshold → one retry, then deliver (FR-134–FR-139)
│   │   ├── validator.py            #   re-traverses link; pass/fail + reason (FR-076–FR-091)
│   │   └── adjudicator.py          #   mechanical consensus; no model judges (FR-027–FR-039)
│   │
│   ├── orchestration/              # batch scheduler, resume, the three retry loops
│   ├── benchmark/                  # benchmark mode + measures (FR-092–FR-100)
│   ├── export/                     # per-cycle export + exclusion report (FR-101–FR-106)
│   ├── telemetry/                  # stage events, fetch log, cost ledger (FR-112–FR-118)
│   └── review/                     # review surface: API + web app (FR-043–FR-052, FR-119)
│
├── data/
│   ├── questions/                  # Module 2.1 question set + locus tags
│   └── benchmark/                  # labelled set; never joined into agent projections
│
└── tests/
    ├── unit/                       # domain/ — no browser, no model, no network
    ├── contract/                   # agent I/O schemas, export schema, EKAP projection
    ├── integration/                # stage pipelines against recorded page fixtures
    └── independence/               # the assertions that make the method defensible
```

**Four structural choices carry weight:**

- **`domain/` has no I/O.** Resume semantics, the confidence gate, and the portal measures are pure functions, so the trickiest logic is testable without a browser, a model, or a network.
- **`linkresolution/` is named for what it does.** It resolves *links*, and the module name is the guard against the mistake of letting a KB or MSQ record supply an answer (FR-124). Nothing in it returns an answer type.
- **`ratelimit/` is top-level, not a helper inside `portal/`.** Two callers share one budget (FR-089), and that sharing is a correctness requirement — a second instantiation would silently double the request rate against a target site.
- **`persistence/benchmark_repo.py` is separate.** Ground truth has no read path from `agents/`, so leakage (FR-094) is an import error at development time rather than a contamination found after a benchmark run.

## Phase 0 — Research

Complete. See [research.md](./research.md). Nine decisions recorded, each with rationale and alternatives considered:

| # | Decision |
|---|---|
| R1 | Python 3.11+ on ADK |
| R2 | Vertex AI endpoint with GCP auth, reached through a provider port |
| R3 | Relational store, SQLite → SQL Server, append-only by construction |
| R4 | Headless browser for render + region capture |
| R5 | Composite durable element reference (CSS path + normalized text hash) |
| R6 | `asyncio` + shared per-domain token bucket as the throughput governor |
| R7 | Independence realized as session isolation + prompt-seed divergence |
| R8 | Unit state machine as the single source of resumability truth |
| R9 | Authentication-boundary detection heuristics |

## Phase 1 — Design & Contracts

Complete.

- **[data-model.md](./data-model.md)** — 18 entities, their fields, relationships, validation rules, and the full unit state machine including the resume semantics from FR-067a/FR-067b.
- **[contracts/](./contracts/)**
  - [assessor-agent.md](./contracts/assessor-agent.md) — Assessor Agent input/output contract, including what must *not* appear in its input.
  - [validator.md](./contracts/validator.md) — Validator contract and the verification outcome taxonomy that keeps FR-087 and FR-088 distinguishable.
  - [adjudicator.md](./contracts/adjudicator.md) — Adjudication input/output and the discrepancy decision table.
  - [export-schema.md](./contracts/export-schema.md) — per-cycle export record and exclusion report.
  - [configuration.md](./contracts/configuration.md) — all 16 named parameters with defaults, types, and validation.
  - [telemetry.md](./contracts/telemetry.md) — stage event and cost ledger schemas.
  - [ekap-integration.md](./contracts/ekap-integration.md) — projection onto `EKAP_AOSQInteractions` and the Process 03 cross-source feed.
- **[quickstart.md](./quickstart.md)** — runnable validation scenarios, ordered so each user story can be demonstrated independently.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Vertex AI is not on the OICT-approved product list** | ADK + Vertex AI is settled for the PoC. But the EKAP Phase 3 package lists **Azure OpenAI Service (ARB 2023-158)** as the approved AI service, and Vertex AI carries no ARB reference in that registry. Production adoption needs either an ARB submission for Vertex AI or an adapter swap. | R2: model access stays behind a port, so the swap is an adapter, not a redesign of the agent topology whose independence properties were the expensive part. **The ARB decision belongs to UN DESA/OICT** — flagged, not resolved. |
| **Data residency** | Phase 3 §8.2 requires OICT-confirmed data residency for cloud components and contractual safeguards for external services handling UN data. Inference sends portal content to Vertex AI. | Pin `GOOGLE_CLOUD_LOCATION` to a region that satisfies whatever OICT confirms, and treat it as a compliance parameter rather than a performance one. Not a PoC blocker; a production gate. |
| **Throughput vs verification cost** | Verification doubles fetch volume against a fixed per-domain budget (spec Assumptions). SC-011 has no agreed target window, so the constraint cannot yet be sized. | R6: the limiter is instrumented from day one (FR-115) so the actual achievable rate is measured, not estimated, and can be presented when the window is agreed. |
| **False verification failures** | An element that legitimately disappears between capture and verification fails a correct agent (spec, Edge Cases — accepted cost). | Retry re-assesses against the current page. FR-115 telemetry lets the false-failure rate be measured; if it is high, the verification attempt bound is the tuning lever. |
| **Independence degenerating** — *elevated by the interim model choice* | Identically configured agents produce correlated output, which looks like agreement but destroys the signal (FR-011). The interim configuration runs **all agents on one flash model**, removing the strongest divergence axis and leaving temperature and prompt profile — the two R7 rates weakest. | R7 + a dedicated `tests/independence/` suite; SC-003's flag-rate floor is the runtime detector and **fails** the run rather than passing it. The interim posture is recorded in the Configuration Snapshot so a low flag rate is attributable, not mysterious. Escape hatch is a one-line config change moving one agent to a different model tier (FR-074). |
| **Authentication-boundary false negatives** | An agent answers "feature absent" from a public page when the feature sits behind login — passes validation, wrong answer. | R9 heuristics + FR-107 question attribute + FR-111 feedback loop so each escalation improves the next cycle's attribute set. |

## Notes

- **Not a git repository.** There is no branch to report. `git init` is advisable before implementation begins so the append-only audit posture of the data is matched by a versioned history of the code that produced it.
- **Graphify skipped.** `graphify` is installed but there is no source tree to analyze — this feature is greenfield. Re-run it once `src/` exists to populate cross-module dependency context for later phases.

## Post-Design Constitution Re-check

Re-evaluated after the data model and contracts were written. All seven gates still PASS. Two were materially strengthened by the design rather than merely preserved:

- **Independence** moved from a prompt-level convention to a *structural* property: [contracts/assessor-agent.md](./contracts/assessor-agent.md) specifies the agent input as a closed schema with no field capable of carrying another agent's output, so a leak becomes a schema violation rather than a review miss.
- **No silent resolution** was verified by exhaustive enumeration: the state machine in [data-model.md](./data-model.md) was checked so that every terminal state is reachable only via a delivered consensus answer or an escalation carrying a reason. No third exit exists.

One design consequence worth recording: **FR-058 and FR-067a interact.** A custom question added mid-run is included in portal-level measures only if every Assessor Agent assessed it (FR-058), and resume retains partial agent sets (FR-067a). A unit can therefore be *complete* while its portal-level eligibility is still false. The data model resolves this by making portal-measure eligibility a derived predicate over the unit's agent set rather than a stored flag — see [data-model.md](./data-model.md) §Portal Measure Eligibility.
