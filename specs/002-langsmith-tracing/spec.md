# Feature Specification: LangSmith Pipeline Tracing

**Feature**: `002-langsmith-tracing`
**Status**: Draft
**Created**: 2026-08-13

---

## Overview

The EKAP AIQ pipeline today produces internal observability via a custom SQLite telemetry system (stage events, cost ledger, fetch log). While sufficient for persistence, this provides no real-time visibility into what each model call received as input, what it returned, how long each nested stage took, or what the full tree of parallel/retry activity looked like for a single pipeline run.

This feature integrates **LangSmith distributed tracing** so that every pipeline execution — called a "run" in this specification — is captured as a **single root trace** in LangSmith, with the exact hierarchical flow of the pipeline as child spans. Parallel assessor agents run concurrently in the same trace. Retries at any layer (confidence gate, validation, adjudication) appear as sibling child spans under their respective parent. The cost, token counts, prompts, and model responses for each model invocation are attached to the correct span. The entire trace is explorable in the LangSmith UI within seconds of a run completing.

---

## Clarifications

### Session 2026-08-13

- Q: When a unit is resumed after a crash, should it appear as a continuation of the original trace or a new independent root trace? → A: New independent root trace, linked to the original only via `session_id` tag (Option B).
- Q: If LangSmith is enabled but the API is unreachable or returns errors mid-run, what should the pipeline do? → A: Silently continue — LangSmith failure is non-fatal; emit a WARNING log line and proceed (Option A).
- Q: Should full prompt content (including scraped page text) be sent to LangSmith as-is, or scrubbed before upload? → A: Full prompt sent as-is, no scrubbing — content is publicly accessible government portal data; document the public-data assumption explicitly (Option A).
- Q: What is the acceptable per-unit latency overhead that tracing (when enabled) is allowed to add? → A: No explicit budget — tracing overhead is best-effort, immaterial at PoC scale; add a note to revisit at production scale (Option A).
- Q: Beyond session_id grouping, should traces be automatically tagged or organized into a LangSmith Dataset or Experiment for cross-run comparison? → A: session_id tag only — no dataset or experiment tagging; manual filtering in LangSmith UI is sufficient at PoC scale (Option A).

---

## Actors

- **Pipeline operator** — runs `aiq assess` or `aiq run` from the CLI; wants to inspect what happened in each run from the LangSmith web UI without trawling logs.
- **Developer / researcher** — wants to compare prompts, model outputs, and confidence scores across runs and experiments in LangSmith.
- **The pipeline itself** — emits trace data automatically; no manual instrumentation per agent invocation is required after this feature lands.

---

## Functional Requirements

### FR-T-001: One run = one root trace
Each invocation of `process_unit` (one question x one portal pair) MUST be represented as exactly one root LangSmith trace, regardless of how many assessor agents ran, how many retries occurred, or whether the run was resumed from a crashed state.

**Resumed runs**: When a previously crashed or interrupted unit is resumed under a new CLI invocation, the resumed execution MUST produce a **new independent root trace** (distinct trace ID). It MUST NOT attempt to graft onto or extend the prior trace. The two traces are linked solely by the shared `session_id` tag, which remains consistent across the original and resumed invocations. This keeps trace identity simple and crash-resilient, without requiring the LangSmith trace ID to survive persistence across process restarts.

The root trace MUST carry:
- `session_id`
- `question_id`
- `portal_id`
- `run_id` (the internal pipeline session)
- Final outcome (DELIVERED, ESCALATED, UNASSESSABLE, etc.)
- Total wall-clock duration of the unit

### FR-T-002: Exact pipeline stage hierarchy in the trace
The trace MUST reflect the real execution tree. The required span hierarchy is:

```
process_unit [root]
├── url_resolution
├── language_detection  (conditional: only when page is reachable)
├── assessor_agent[0]   (parallel with other agent spans)
│   ├── confidence_gate_attempt[0]   (first attempt)
│   ├── confidence_gate_attempt[1]   (retry, if triggered)
│   ├── validation_attempt[0]
│   └── validation_attempt[1]        (retry, if triggered)
├── assessor_agent[1]   (parallel)
│   ├── confidence_gate_attempt[0]
│   └── validation_attempt[0]
├── adjudication[round=1]
├── adjudication_retry[round=2]      (if triggered)
│   ├── assessor_agent[0]            (re-run for disagreement addendum)
│   │   └── validation_attempt[0]
│   └── assessor_agent[1]
│       └── validation_attempt[0]
└── adjudication[round=2]            (final outcome)
```

No span may be silently dropped. Every code path that the pipeline executes must produce a corresponding span in the trace.

### FR-T-003: Model invocations carry full prompt and response data
Every call to the model provider MUST attach to its enclosing span:
- The system instruction sent
- The full prompt sent
- The raw model response text
- Input token count
- Output token count
- Estimated cost (in USD)
- Model identifier (e.g., `vertexai/gemini-2.0-flash`)
- Temperature used

This data MUST be visible from the LangSmith span detail view without any additional query.

**Data content policy**: Prompt content (including scraped page text) MUST be uploaded to LangSmith in full, without truncation or redaction. This is explicitly acceptable because all scraped content originates from publicly accessible government portals. No citizen PII is expected in this content. The LangSmith project is private to the assessment team. If future portal content is found to contain PII, this policy MUST be revisited before production use.

### FR-T-004: Retry spans are distinguishable and attributable
Each retry MUST be a distinct child span (not merged with its parent or prior attempt), tagged with:
- Retry type: `confidence_retry`, `validation_retry`, `adjudication_retry`
- Retry number (0-indexed attempt count)
- Agent index (for agent-level retries)
- Round number (for adjudication retries)

This allows operators to immediately see "Agent 1 required 2 validation retries" in the LangSmith trace tree.

### FR-T-005: Parallel agent spans are concurrent siblings
When two or more assessor agents run concurrently (via asyncio), their spans MUST appear as concurrent sibling children of the `process_unit` root span, with overlapping timestamps that reflect real parallel execution — not sequential spans.

### FR-T-006: Escalation and failure paths are traced
Units that escalate (no usable URL, auth boundary, language declined, unresolved disagreement) MUST produce a complete trace up to the escalation point, with the escalation reason attached to the root span as metadata. A crashed or incomplete run MUST NOT suppress the already-emitted spans.

### FR-T-007: Tracing is opt-in via environment configuration
LangSmith tracing MUST be disabled by default and activated solely by setting `LANGCHAIN_TRACING_V2=true` and providing a `LANGSMITH_API_KEY` in the environment. When disabled, the pipeline MUST run identically to its current behavior with zero overhead. No code change should be needed to toggle tracing on/off; it is purely configuration-driven.

**LangSmith API failure handling**: When tracing is enabled, any failure to deliver trace data to the LangSmith API (network timeout, 5xx error, connection refused) MUST be treated as **non-fatal**. The pipeline MUST continue executing and producing its normal assessment output. A single `WARNING`-level log line MUST be emitted describing the failure (e.g., `LangSmith trace upload failed: <reason>`). The failed span data MAY be silently dropped — no retry of failed trace uploads is required. Under no circumstances should a LangSmith outage cause an assessment run to abort, raise an unhandled exception, or produce incorrect output.

### FR-T-008: Batch-level trace grouping
When `run_batch` executes multiple units, each unit's root trace MUST be tagged with the same `session_id` so that all traces from a single batch run can be filtered together in the LangSmith UI. Optionally, a `LANGSMITH_PROJECT` environment variable MAY name the LangSmith project; it defaults to `ekap-aiq`.

**Trace organization scope**: Grouping by `session_id` tag is the only required organizational structure at PoC scale. Traces MUST NOT be automatically added to LangSmith Datasets or Experiments. No additional run-date or prompt-profile tags are required beyond what is already carried in the root span metadata. Cross-run comparison is performed manually via the LangSmith UI filter. Dataset and Experiment wiring is explicitly deferred to a future evaluation feature.

### FR-T-009: Existing custom telemetry is preserved
The SQLite-backed `StageEventLog`, `CostLedger`, and `FetchLog` MUST continue to function identically. LangSmith tracing is additive — it does not replace the existing telemetry system.

### FR-T-010: .env.example documents all required LangSmith variables
The following keys MUST be added to `.env.example` with placeholder values and explanatory comments:
- `LANGCHAIN_TRACING_V2`
- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`
- `LANGCHAIN_ENDPOINT` (optional, for self-hosted LangSmith)

---

## User Scenarios and Testing

### Scenario 1: Operator inspects a successful 2-agent run in LangSmith
**Given** a run completes with 2 assessor agents, both validated, and adjudication produces consensus
**When** the operator opens the LangSmith trace for that run
**Then** they see:
- A root span named `process_unit` covering the full wall-clock duration
- Two concurrent `assessor_agent` spans with non-overlapping model call spans inside
- One `adjudication` span after both agent spans complete
- All model prompts and responses visible in each model call span

### Scenario 2: Operator diagnoses a validation retry failure
**Given** Agent 0 fails its first validation and triggers a retry
**When** the operator views the LangSmith trace
**Then** they see:
- `assessor_agent[0]` contains two `validation_attempt` spans
- The first `validation_attempt` is tagged `retry_number=0, passed=false`
- The second is tagged `retry_number=1, passed=true`
- Token and cost data are present on both

### Scenario 3: Adjudication retry loop appears correctly
**Given** agents disagree on round 1, triggering an adjudication retry on round 2
**When** the operator views the LangSmith trace
**Then** they see:
- An `adjudication[round=1]` span tagged `discrepancy_flagged=true`
- A second set of `assessor_agent` spans for round 2 under the adjudication retry
- A final `adjudication[round=2]` span with the resolved outcome

### Scenario 4: Tracing is off without API key
**Given** `LANGSMITH_API_KEY` is not set
**When** a run executes
**Then** no trace data is emitted, no external network calls are made to LangSmith, and the pipeline output is byte-for-byte identical to the pre-feature behavior.

### Scenario 5: Escalation appears in trace
**Given** link resolution returns no usable URL
**When** the operator views the LangSmith trace
**Then** they see:
- A root `process_unit` span
- A `url_resolution` child span tagged with the failure reason
- The root span outcome is `UNASSESSABLE`
- No further child spans are present

---

## Key Entities

| Entity | LangSmith representation |
|---|---|
| `process_unit` invocation | Root Run (LangSmith trace) |
| Pipeline stage (url_resolution, etc.) | Child Run (type: chain) |
| Model provider call | Child Run (type: llm) |
| Retry attempt | Child Run sibling to the prior attempt |
| Confidence gate attempt | Child Run under its assessor span |
| Batch session | LangSmith project + `session_id` tag shared across all unit traces |

---

## Success Criteria

1. Every `process_unit` invocation that completes or errors produces exactly one trace in LangSmith, with no orphan spans and no missing stages.
2. The full span tree for a 2-agent, 1-adjudication-retry run contains at least 12 distinct spans with no duplicates or collapsed siblings.
3. Every model invocation span contains the full prompt text and raw response visible in the LangSmith UI without additional data retrieval.
4. A developer can filter all traces from a single batch run using only the `session_id` tag in LangSmith, within 30 seconds of run completion.
5. Disabling tracing (by removing the API key) produces zero latency regression and zero external calls — verifiable by test with network isolation.
5a. When tracing is enabled, no explicit latency budget is imposed at PoC scale. Tracing overhead is expected to be immaterial relative to browser fetch and model call durations (seconds to minutes per unit). This constraint MUST be formally defined before any production deployment.
6. All existing unit, contract, and integration tests pass without modification after this feature is implemented.
7. The `.env.example` addition and `pyproject.toml` dependency addition are the only changes required for a new developer to activate LangSmith tracing.

---

## Assumptions

- The project will use the `langsmith` Python SDK directly (not LangChain) via its `@traceable` decorator and `trace` context manager, which works with any Python code regardless of which LLM framework is used.
- Async context propagation will be handled via `langsmith`'s built-in async trace context, which correctly scopes spans across `asyncio.gather` calls.
- LangSmith's free tier is sufficient for the PoC volume; no cost-control guardrails for LangSmith API usage are required at this stage.
- The existing `StageEventLog.timed()` context manager wrapping points in `scheduler.py`, `retry_loops.py`, and `assessor.py` are the correct integration boundary — LangSmith spans will be added alongside (not replacing) these.
- The `LANGSMITH_API_KEY` will never be committed to version control; `.env.example` uses a placeholder string only.
- All portal page content scraped during assessment is publicly accessible data with no citizen PII. Full prompt upload to LangSmith is therefore acceptable without redaction. This assumption MUST be re-evaluated before any production deployment targeting portals with authenticated or restricted content.

---

## Dependencies

- New dependency: `langsmith>=0.1.0` added to `pyproject.toml`
- New environment variables: `LANGCHAIN_TRACING_V2`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGCHAIN_ENDPOINT`
- No schema changes to the existing SQLite database
- No changes to any existing public API or CLI interface

---

## Out of Scope

- Replacing the existing SQLite telemetry with LangSmith (both coexist)
- LangSmith evaluation datasets or automated LLM evals (future feature)
- Tracing for the `aiq serve` review surface or the export/benchmark modules
- Per-token streaming traces
- Custom LangSmith feedback submission from the review UI
- LangSmith Dataset creation or Experiment tagging for cross-run evaluation (deferred to future evaluation feature)
- Additional run-date or prompt-profile metadata tags beyond what is carried in root span attributes
