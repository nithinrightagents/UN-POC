# Contract: EKAP Platform Integration

**Source**: `understanding docs/EKAP - Phase 3 - Technical Design Package`, `EKAP - Phase 4 - End-to-End Operational & Governance System Map v1.7`

This contract is **advisory for the PoC and binding for EKAP adoption**. Nothing in the feature spec requires it; it exists so that AIQ can be adopted into EKAP without re-instrumenting the parts that are expensive to change later. Where it conflicts with [spec.md](../spec.md), the spec governs and the conflict is flagged rather than silently resolved.

## Where AIQ sits

The Phase 4 system map names **AIQ — Automated Survey Execution** as a distinct role (Process 02, Role C: Agentic) whose output feeds **Process 03 — Validation & Intelligence**, where it is cross-compared against the other two instruments:

| Source | What it is | Who produces it |
|---|---|---|
| **MSQ** | Government self-report | Government Actor |
| **OSQ** | Assessor evaluation | Human assessors |
| **AIQ** | Automated assessment | *This system* |

Process 03 computes variance across the three and raises discrepancy cases for UN Administrator review. **AIQ is a third opinion, not the answer** — which is the design reason every exported record carries `session_id` and `evidence_refs` ([export-schema.md](./export-schema.md)): when the cross-source comparison shows a variance, a human has to drill into why, and an answer without its evidence chain is not drillable.

## Projection onto `EKAP_AOSQInteractions`

EKAP's AI traceability table is the platform's mandated audit surface for AI activity (Phase 3 §5, §6.7, §8.3). Our audit trail is a strict superset. The projection:

| EKAP column | AIQ source | Note |
|---|---|---|
| `InteractionId` | `run_id` / `validation_id` / `adjudication_id` | One row per AI invocation |
| `SessionId` | `session_id` | Direct — FR-059 already requires a single session key |
| `AssessorId` | `agent_index` + `model_identity` | AIQ agents are not registered human assessors |
| `QuestionId` | `question_id` | Direct |
| `AgentType` | `PRE_ASSESSMENT` \| `QA` | Assessor Agent → `PRE_ASSESSMENT`; Validator → `QA` |
| `InputRef` | Agent input record ref | |
| `OutputRef` | Agent output record ref | |
| `ModelVersion` | `model_identity` | FR-116 already records this per invocation |
| `HumanReviewRequired` | `true` always | Every AIQ answer goes to an Assessor (FR-043a) |
| `ReviewedBy` | `Assessor Decision.actor_id` | |
| `ReviewDecision` | `Assessor Decision.action` | approve / edit / reject_override |
| `Timestamp` | Stage event `started_at` | |

**Note on `AgentType`**: EKAP defines three AOSQ functions — pre-assessment, companion, quality assurance. AIQ implements pre-assessment and quality assurance. It implements **no companion agent** — nothing in AIQ assists a human during their own evaluation. If EKAP expects a companion agent, that is separate scope.

## Alignment points

| EKAP requirement | AIQ status |
|---|---|
| Human-in-the-loop mandatory; AI supports, never replaces expert judgement (§6.7) | **Satisfied** — FR-044–FR-046; every answer is human-disposed, overrides are the delivered answer |
| All AI interactions logged for traceability (§6.7, §8.3) | **Satisfied and exceeded** — FR-059–FR-062 append-only, reconstructable per FR-061 |
| No AI involvement in official index scoring (§6.7) | **Satisfied** — the spec puts scoring and index computation out of scope; FR-105 forbids the export computing anything |
| Evidence attachments linked to specific answers (§6.12) | **Satisfied** — FR-021, evidence refs in the export |
| Discrepancy cases with before/after values and resolution trail (§6.2) | **Satisfied** — Discrepancy Case and Assessor Decision retain both system and human answers |
| Accessibility per applicable UN standards (§9.3) | **Satisfied** — FR-119, WCAG 2.1 AA |
| Multilingual support per UN language requirements (§9.3) | **Partial, deliberately** — FR-120 fixes the review interface to English. Evidence text is always retained in the portal's original language. If EKAP requires a multilingual review interface, that is a scope addition and needs a spec change. |

## Open conflicts — not resolved here

### 1. AI service approval (the significant one)

- **Spec, Implementation Constraints**: agent orchestration is built on ADK — a given.
- **Stakeholder decision (2026-08-13)**: generative models are served by a **Google Vertex AI endpoint with GCP authentication** ([research.md](../research.md) R2).
- **EKAP Phase 3 §4.5, §8.3**: Azure OpenAI Service (ARB 2023-158) is the sole OICT-approved AI service, and *"all AI services operate within OICT-approved boundaries"*. **Vertex AI carries no ARB reference in that registry.**

The provider decision settles the PoC and is native to ADK, but it does not close the compliance gap — it sharpens it. EKAP adoption needs **one of**:

1. an ARB submission and approval for Vertex AI, or
2. an adapter swap to an approved endpoint at production time.

R2 keeps model access behind a port precisely so option 2 stays an adapter change rather than a redesign of the agent topology. **The decision belongs to UN DESA and UN OICT** — the Phase 3 package is explicit that procurement and ARB approval are formal UN processes this material does not pre-empt. Flagged, not decided.

### 2. Identity

EKAP authenticates via **UNHQ Active Directory, explicitly not Azure AD**, with VPN for administrative access (§6.10, §8.2). The spec puts IAM out of scope and consumes an opaque actor identity. Compatible as written — but the review surface will need to accept UNHQ AD identities at adoption, and `actor_id` should not acquire any structure that assumes otherwise.

### 3. Data residency

Phase 3 §8.2 requires data residency confirmation with OICT for all cloud-hosted components, and contractual safeguards for any external service handling UN data. Model inference sends portal content to Vertex AI, so `GOOGLE_CLOUD_LOCATION` is the setting that determines where UN-assessed content is processed.

Treat it as a compliance parameter, not a performance one ([configuration.md](./configuration.md)). **A live production question, not a PoC blocker** — but it wants an answer from OICT before a full cycle runs, and it constrains the region choice at least as much as ARB approval constrains the provider choice.

## What the PoC should preserve

Even though this contract is advisory now, three things are cheap to hold to and expensive to retrofit:

1. **`session_id` on every AI invocation record** — already required by FR-059.
2. **`model_identity` per invocation** — already required by FR-116.
3. **Assessor Agent and Validator invocations distinguishable by type** — already implied by the stage taxonomy in [telemetry.md](./telemetry.md).

All three fall out of requirements the spec already carries, so no PoC work is spent on EKAP adoption specifically. That is the intended outcome.
