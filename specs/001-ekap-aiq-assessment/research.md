# Phase 0 Research: EKAP AIQ

**Feature**: `specs/001-ekap-aiq-assessment` | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-13

Nine decisions. Each records what was chosen, why, and what was rejected. Decisions the spec already fixed as givens (ADK, `.env`, durable session state) are not re-litigated here; where they force a downstream choice, that choice is recorded.

---

## R1 — Runtime: Python 3.11+

**Decision**: Python 3.11 or later.

**Rationale**: ADK is the given orchestration framework and Python is its primary surface. 3.11+ specifically for `asyncio.TaskGroup` and `except*`, which matter because the orchestrator fans out N agent runs per unit and needs structured cancellation when a unit is abandoned mid-round — exactly the case FR-067b has to handle deterministically. On 3.10 that has to be hand-rolled with `gather(return_exceptions=True)` and manual cleanup, which is where partial-state bugs live.

**Alternatives considered**:
- *Java ADK* — viable, and closer to a UN enterprise stack, but the headless-browser and page-parsing ecosystem is weaker and the team-facing cost is higher for a PoC.
- *Python 3.10* — rejected on the structured-cancellation point above.

---

## R2 — Model access: Vertex AI with GCP auth, behind a provider port

**Decision** *(updated 2026-08-13 — provider now fixed by the stakeholder)*: Generative models are served by a **Google Vertex AI endpoint authenticated with GCP credentials** (Application Default Credentials, or a service account in non-interactive environments). Model invocation still goes through a single `ModelProvider` port; no agent module imports a vendor SDK directly. Model identity and version are recorded per invocation (FR-116).

**Rationale**: Vertex AI is the native inference backend for ADK, which the spec fixes as a given — ADK's `GOOGLE_GENAI_USE_VERTEXAI` / `GOOGLE_CLOUD_PROJECT` / `GOOGLE_CLOUD_LOCATION` path means the agent topology needs no adaptation layer to reach it. GCP auth via ADC also keeps credentials out of `.env` and out of the config snapshot, which matters because the snapshot is retained for audit (FR-063) and read back by anyone reconstructing a session.

**The port survives the decision.** Now that the provider is settled, keeping an abstraction may look like speculative generality — it is not, for two reasons specific to this system:

1. **The OICT approval question is still open** (see below). If production has to move to an approved endpoint, the swap must not touch the agent code whose independence properties were the expensive part to establish.
2. **The port is where FR-116 cost accounting and FR-011 configuration divergence both attach.** Removing it would scatter both across every agent module.

**Open compliance question — not resolved by this decision.** The EKAP Phase 3 Technical Design Package lists Azure OpenAI Service (ARB 2023-158) as the OICT-approved AI service; **Vertex AI carries no ARB reference in that registry**. Choosing Vertex settles the PoC binding but sharpens rather than closes the production question: EKAP adoption needs either an ARB submission for Vertex AI or an adapter swap. Procurement and ARB approval are explicitly UN processes that this material does not pre-empt (Phase 3, Disclaimers). Flagged in [plan.md](./plan.md) Risks and [contracts/ekap-integration.md](./contracts/ekap-integration.md).

**Data residency** (Phase 3 §8.2) becomes a live parameter rather than an abstract concern: `GOOGLE_CLOUD_LOCATION` determines where portal content is processed, so it is a compliance setting, not a latency setting.

**Alternatives considered**:
- *Azure OpenAI now* — would pre-satisfy the ARB position, but requires a non-native adapter under ADK and was not the stakeholder's choice.
- *Direct SDK binding, no port* — rejected; see the two reasons above.
- *Vertex AI via API key* — rejected; GCP auth with ADC/service accounts avoids putting a long-lived secret in `.env` alongside audited configuration.

---

## R3 — Persistence: relational, append-only by construction

**Decision**: A relational store. SQLite for PoC and local validation; SQL Server / Azure SQL for EKAP production. Audit tables are append-only, enforced by the repository layer exposing no update or delete path — not by trusting callers.

**Rationale**: FR-062 (append-only), FR-059 (single session key), and FR-061 (full reconstruction) describe an event log with heavy relational join requirements — reconstruct every agent position, every round, every retry, every human action for one delivered answer. That is a relational query, not a document scan. EKAP's own data layer is SQL Server (Phase 3, §5), and the `EKAP_AOSQInteractions` shape we must eventually project onto is relational, so matching the paradigm removes a translation layer at adoption time.

SQLite for the PoC because resumability (FR-066) must be tested by killing the process, and a zero-setup durable file store makes that a one-line test rather than a fixture.

**Alternatives considered**:
- *Document store* — rejected; reconstruction queries in FR-061 span six record types.
- *Event-sourcing framework* — rejected as over-scoped; append-only tables plus a session key give the required property without the machinery.
- *In-memory with periodic flush* — rejected outright; the spec's Implementation Constraints explicitly require durable rather than in-memory session persistence.

---

## R4 — Portal access: headless browser, not HTTP fetch

**Decision**: A headless browser for page acquisition, region-scoped screenshot capture, and element resolution. Not a plain HTTP client with HTML parsing.

**Rationale**: FR-021 requires *a visual capture scoped to the relevant region of the page*. That is not derivable from HTML source — it needs layout, which needs a rendering engine. Government portals are also heavily client-rendered; a raw fetch would systematically under-report features on exactly the more advanced portals, biasing results toward "feature absent" in a way that correlates with portal maturity. That is a methodological defect, not a performance one.

The same engine serves language detection (FR-015), interstitial and challenge-page detection (FR-071), and authentication-boundary detection (R9).

**Alternatives considered**:
- *HTTP client + HTML parser* — rejected on region capture and client-rendering bias.
- *Third-party screenshot API* — rejected; adds an external dependency that would carry UN data to an unapproved processor (Phase 3 §8.2 requires contractual safeguards for external services handling UN data), and puts a third party inside the rate-limit budget we are required to control (FR-089).

---

## R5 — Durable element reference: composite, not raw XPath

**Decision**: The durable page-element reference (FR-021) is a composite record: a stabilized CSS selector path, the element's normalized text, a hash of that text, and the element's position among its matching siblings. Verification (FR-086) resolves by selector first, then falls back to text-hash search across the document.

**Rationale**: FR-086 requires the Validator to *independently locate* the element on a fresh fetch, and FR-087 makes failure to do so a quality failure that retries the agent. A bare XPath is brittle against any DOM reshuffle — it would generate false quality failures at a rate that swamps the real signal, and each false failure costs a full agent re-run plus another fetch against the shared budget.

The composite makes the two failure modes distinguishable, which the spec requires as separate outcomes:
- selector fails **and** text-hash fails → element genuinely absent → FR-087 quality failure.
- selector fails **but** text-hash matches → page reshuffled, evidence intact → verification passes, reference updated.

**Alternatives considered**:
- *Raw XPath* — rejected on brittleness; would inflate FR-087 failures with false positives.
- *Text-only matching* — rejected; ambiguous on pages repeating a phrase, and gives no positional evidence.
- *Visual/coordinate anchoring* — rejected; less stable than the DOM across viewport and device-pixel variation.

---

## R6 — Concurrency: asyncio with a shared per-domain token bucket

**Decision**: `asyncio` throughout, with a single global rate limiter keyed by domain. **Assessor Agent fetches and Validator verification fetches acquire from the same bucket** (FR-089). Batch concurrency is bounded by unit, not by fetch.

**Rationale**: This is the system's throughput governor and the design's most load-bearing component. The workload is I/O-bound — page loads and model calls — so threads buy nothing over async. What matters is that the budget is genuinely shared: FR-089 and SC-019 require verification traffic to count against the same per-domain budget, and the spec's Assumptions name this as the main pressure on SC-011.

Two consequences drove the module layout in [plan.md](./plan.md):

1. The limiter is a top-level module, not a helper inside `portal/`, because two independent callers must not be able to instantiate their own.
2. Every acquisition is recorded with its caller class (FR-115), so SC-012 and SC-019 are demonstrated from data rather than asserted.

Concurrency is bounded per *unit* rather than per fetch so that a unit's N agents plus their verifications complete together, which keeps the round boundary that FR-027 depends on from stretching indefinitely.

**Alternatives considered**:
- *Thread pool* — rejected; no benefit for I/O-bound work, and shared-limiter correctness is harder under threads.
- *Per-caller limiters* — rejected; directly violates FR-089's single shared budget.
- *Distributed queue (Celery/RQ)* — rejected as premature for the PoC. The unit state machine (R8) already makes work re-drivable, so a queue can be introduced later without redesign.

---

## R7 — Independence: session isolation plus configuration divergence

**Decision**: Independence is realized on two axes, both required:

1. **Structural isolation** — each Assessor Agent run executes in its own ADK session with no shared conversational state. Agent input is a closed schema ([contracts/assessor-agent.md](./contracts/assessor-agent.md)) containing no field able to carry another agent's output.
2. **Configuration divergence** — agents differ by deliberate configuration: model or model version, temperature, and system-prompt framing, assigned per agent index and recorded in the session snapshot.

**Divergence axes available under Vertex AI** (R2). Since all agents share one provider, cross-vendor divergence is off the table and divergence has to come from within the Gemini family:

| Axis | Strength | Note |
|---|---|---|
| Different model tiers (Pro-class vs Flash-class) | **Strongest available** | Genuinely different capability profiles, so genuinely different reads of an ambiguous portal |
| Different model versions | Moderate | Useful, but versions within a family correlate more than tiers do |
| System-prompt framing | Moderate | Two defensible evaluative stances, not two phrasings of one |
| Temperature | Weak on its own | Normally a supplement, never the primary axis |

Mixing tiers has a side effect worth naming: per-agent cost differs substantially, which is exactly what the FR-116 per-agent cost ledger exists to expose. If a cheaper tier turns out to carry the flag rate, that is an argument the telemetry can make.

### Interim configuration: one flash model for all agents

*(Stakeholder decision, 2026-08-13 — to be tuned once benchmark evidence exists.)*

The first configuration runs **every Assessor Agent on the same flash model**, with divergence supplied by temperature and prompt profile only. This removes the strongest axis and leaves the two the table above rates weakest, which has a specific and predictable consequence:

**SC-003's non-independence floor becomes the load-bearing check.** A discrepancy flag rate at or below the configured floor (default 5%) is a **failure** under SC-003, not a success — it indicates the agents are not independent. This configuration is the one most likely to produce exactly that, so the first benchmark run should be read as a test of the configuration as much as of the pipeline.

Two things follow for implementation, and both are cheap now and awkward later:

1. **The interim posture is recorded, not assumed.** `AIQ_ALLOW_IDENTICAL_AGENT_MODELS` is captured in the Configuration Snapshot (FR-063), so a session run this way is identifiable afterwards and shows up as a difference in any cross-run benchmark comparison (FR-098, FR-099).
2. **Prompt profiles are named and versioned from the start**, not inlined as string literals. With models identical, the prompt profile is carrying most of the divergence, so it needs to be a tunable artifact rather than something buried in agent code. The tuning the stakeholder anticipates will mostly be tuning *this*.

The escape hatch, should the flag rate come in below the floor, is to move one agent to a different model tier — a one-line configuration change under FR-074, requiring no code edit. That the fix is this cheap is the reason the interim choice is a reasonable one to start from.

**Rationale**: FR-011 states plainly that identical configurations producing correlated outputs *do not satisfy* the requirement. Structural isolation alone gives that failure: two identical agents, isolated but identically configured, produce correlated output that is indistinguishable from one agent run twice — and the spec says this destroys the signal adjudication depends on.

So isolation is necessary but not sufficient. Divergence supplies the variance; isolation guarantees the variance is not contaminated. SC-003's flag-rate floor (default 5%) is the runtime detector for divergence having collapsed, and per the spec it **fails the run rather than passing it** — a suspiciously high agreement rate is a defect signal, not a quality signal. This inverts the usual reading of an agreement metric and needs to survive into implementation, so it is asserted in `tests/independence/`.

**Alternatives considered**:
- *Isolation only, identical config* — rejected; explicitly disallowed by FR-011.
- *Different vendors per agent* — strongest possible divergence, but no longer available: R2 fixes a single provider. Model-tier divergence within the Gemini family is the substitute.
- *Randomized seeds only* — rejected as too weak; same model and prompt at varied seed stays highly correlated.

---

## R8 — Resumability: the unit state machine is the only truth

**Decision**: Every question–portal unit carries an explicit persisted state. Resume reads state and derives remaining work; it never re-runs to discover progress. Agent-level granularity per FR-067a/FR-067b: terminal agent runs are retained, non-terminal ones discarded and re-run.

**Rationale**: FR-065 requires resumption decided from recorded state rather than by re-running, and the clarification session fixed the partial-unit semantics. Making state the only truth has a testability payoff that justifies the modelling cost: the entire resume behaviour becomes unit-testable in `domain/` with no browser, no model, and no network — the state machine is a pure function from (unit state, agent run states) to remaining work.

The subtle case, and the one worth a dedicated test: an agent interrupted *mid-validation-retry* has a terminal assessment but a non-terminal validation. FR-067b makes the whole agent run non-terminal, so it is discarded and re-run from scratch. Retaining the assessment while re-running only validation would be cheaper but would produce a validation result for an assessment formed under a partially-applied retry addendum, which is not a state the pipeline otherwise produces.

**Alternatives considered**:
- *Round-atomic resume (discard the whole round)* — simpler, and was offered as an option during clarification; rejected by the stakeholder in favour of agent-level retention, on budget and independence grounds.
- *Checkpoint files* — rejected; a second source of truth alongside the database is exactly how duplicate records (FR-066) appear.

---

## R9 — Authentication-boundary detection

**Decision**: Detection combines three signals, any of which routes the pair to escalation under FR-109 rather than producing an answer:

1. **Navigational** — the path to the evidence crosses a sign-in form, an identity-provider redirect, or a national identity gateway.
2. **Structural** — the target region is present but rendered in a logged-out state (disabled controls, "sign in to continue" affordances, an account-required notice).
3. **Declared** — the question carries the FR-107 attribute, in which case the pair never reaches an agent at all.

**Rationale**: This is the failure mode the source material calls the core challenge, and it is adversarial in a specific way: the wrong answer is *well-evidenced*. An agent that sees a public page, screenshots it, and answers "feature absent" produces evidence that verifies cleanly and passes the Validator, because the Validator confirms the evidence exists — not that it is the right evidence (spec, Assumptions). Neither validation nor adjudication catches it; two agents can reach it independently and agree.

So detection has to happen at the assessment stage, and the bias must be toward escalation: a false escalation costs one human review, while a false "absent" enters the delivered results with a clean audit trail behind it. FR-111 closes the loop by recording each escalation against the question so the attribute set improves each cycle.

**Alternatives considered**:
- *Attribute only* — rejected; gating varies by country for the same question, so a static attribute is incomplete by construction.
- *Runtime detection only* — rejected; discards knowledge the questionnaire authors already hold and spends a full agent run to rediscover it.
- *Credentialed access* — rejected by FR-110, and it would put the system in the business of holding government account credentials for 193 countries.

---

## Deferred

Carried from the spec's Open Questions. None blocks design; each is recorded with the default this design assumes so implementation is not stalled.

| # | Open question | Design assumption | Resolve by |
|---|---|---|---|
| 3 | Evidence retention & storage location | ≥ 2 survey cycles; local filesystem for PoC, object storage in production | Before first production run |
| 4 | Role bands | Actor identity is an opaque attributable string; IAM is out of scope | EKAP RBAC model (Phase 3 §6.10) |
| 5 | Cycle assessment window | No target assumed. FR-114 measures actual throughput so the window can be set from evidence | Needed to gate SC-011 |
| 6 | Initial supported language set | Empty at first boot; populated from a language-coverage evaluation | Prerequisite for first production run |

**One deferral is worth flagging as more than bookkeeping**: #5. SC-011 is a mandatory success criterion with no target value, and this design's dominant constraint — shared per-domain budget against doubled fetch volume — is precisely what that criterion would test. The instrumentation (FR-114, FR-115) is built in so the number can be produced from a real run rather than estimated, but until the window is agreed, SC-011 cannot pass or fail.
