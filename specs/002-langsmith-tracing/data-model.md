# Data Model: LangSmith Pipeline Tracing

**Feature**: `002-langsmith-tracing`
**Date**: 2026-08-13

---

## Overview

This feature introduces no new persistent entities to the SQLite database. All new data lives transiently in the LangSmith backend, transmitted via the `langsmith` SDK. The data model below describes the **LangSmith Run** schema as produced by the EKAP AIQ pipeline — this is what operators see in the LangSmith UI.

---

## LangSmith Run (Span) Schema

All pipeline spans are LangSmith `Run` objects. The SDK handles serialization and upload. The following documents the fields the pipeline explicitly populates.

### Root Run: `process_unit`

| Field | Type | Value | Source |
|---|---|---|---|
| `name` | string | `"process_unit"` | hardcoded |
| `run_type` | enum | `"chain"` | hardcoded |
| `inputs` | dict | `{session_id, question_id, portal_id, question_text, portal_url}` | `process_unit()` args |
| `outputs` | dict | `{outcome, detail}` | final `UnitOutcome` |
| `tags` | list[str] | `[session_id]` | `run_batch` / `process_unit` |
| `metadata` | dict | `{session_id, question_id, portal_id, resumed: bool}` | `process_unit()` |
| `error` | string or null | set if unhandled exception | SDK automatic |
| `start_time` | datetime | wall-clock entry time | SDK automatic |
| `end_time` | datetime | wall-clock exit time | SDK automatic |

### Child Run: `url_resolution`

| Field | Type | Value |
|---|---|---|
| `name` | string | `"url_resolution"` |
| `run_type` | enum | `"chain"` |
| `inputs` | dict | `{question_id, portal_id}` |
| `outputs` | dict | `{resolved_url, supplying_source, resolution_history_count, outcome}` |
| `metadata` | dict | `{escalation_reason}` if no usable URL |

### Child Run: `language_detection`

| Field | Type | Value |
|---|---|---|
| `name` | string | `"language_detection"` |
| `run_type` | enum | `"chain"` |
| `inputs` | dict | `{question_id, portal_id, resolved_url}` |
| `outputs` | dict | `{detected_language, requires_decision, outcome}` |

### Child Run: `assessor_agent[N]`

| Field | Type | Value |
|---|---|---|
| `name` | string | `"assessor_agent[{agent_index}]"` |
| `run_type` | enum | `"chain"` |
| `inputs` | dict | `{agent_index, round_number, model, temperature, profile}` |
| `outputs` | dict | `{answer, confidence, state, auth_boundary_observed}` |
| `metadata` | dict | `{agent_index, round_number, run_id}` |

### Child Run: `confidence_gate_attempt[N]`

| Field | Type | Value |
|---|---|---|
| `name` | string | `"confidence_gate_attempt[{retry_count}]"` |
| `run_type` | enum | `"chain"` |
| `inputs` | dict | `{retry_count, has_addendum, addendum_kind}` |
| `outputs` | dict | `{confidence, accepted, below_threshold}` |

### Child Run: `model_call` (from `ModelProvider.generate`)

| Field | Type | Value |
|---|---|---|
| `name` | string | `"model_call"` |
| `run_type` | enum | `"llm"` |
| `inputs` | dict | `{model, system_instruction, prompt, temperature}` |
| `outputs` | dict | `{text, model_identity}` |
| `metadata` | dict | `{input_tokens, output_tokens, cost_usd, model_identity}` |

### Child Run: `validation_attempt[N]`

| Field | Type | Value |
|---|---|---|
| `name` | string | `"validation_attempt[{retry_number}]"` |
| `run_type` | enum | `"chain"` |
| `inputs` | dict | `{retry_number, agent_index, round_number}` |
| `outputs` | dict | `{passed, quality_score, gaps_count, verification_outcome}` |
| `metadata` | dict | `{retry_type: "validation_retry", retry_number, agent_index, round_number}` |

### Child Run: `adjudication[round=N]`

| Field | Type | Value |
|---|---|---|
| `name` | string | `"adjudication[round={round_number}]"` |
| `run_type` | enum | `"chain"` |
| `inputs` | dict | `{round_number, validated_run_count}` |
| `outputs` | dict | `{consensus_answer, consensus_confidence, discrepancy_flagged, flag_reason}` |
| `metadata` | dict | `{retry_type: "adjudication_retry", round_number}` if retry round |

---

## Span Hierarchy (Full)

```
process_unit [root, chain]
  tags: [session_id]
  metadata: {session_id, question_id, portal_id}
  │
  ├── url_resolution [chain]
  │     outputs: {resolved_url, outcome}
  │
  ├── language_detection [chain, conditional]
  │     outputs: {detected_language, requires_decision}
  │
  ├── assessor_agent[0] [chain]          ← parallel
  │   metadata: {agent_index:0, round_number:1}
  │   ├── confidence_gate_attempt[0] [chain]
  │   │   └── model_call [llm]
  │   │         metadata: {input_tokens, output_tokens, cost_usd}
  │   ├── confidence_gate_attempt[1] [chain, if retry]
  │   │   └── model_call [llm]
  │   ├── validation_attempt[0] [chain]
  │   │   └── model_call [llm]  ← validator model call
  │   └── validation_attempt[1] [chain, if retry]
  │       └── model_call [llm]
  │
  ├── assessor_agent[1] [chain]          ← parallel sibling
  │   metadata: {agent_index:1, round_number:1}
  │   ├── confidence_gate_attempt[0] [chain]
  │   │   └── model_call [llm]
  │   └── validation_attempt[0] [chain]
  │       └── model_call [llm]
  │
  ├── adjudication[round=1] [chain]
  │     outputs: {discrepancy_flagged: true}  ← if retry triggered
  │
  ├── assessor_agent[0] [chain, adjudication retry round 2]
  │   └── ...
  ├── assessor_agent[1] [chain, adjudication retry round 2]
  │   └── ...
  │
  └── adjudication[round=2] [chain]
        outputs: {consensus_answer, consensus_confidence}
```

---

## No SQLite Schema Changes

This feature introduces **zero changes** to the existing database schema. `StageEventLog`, `CostLedger`, and `FetchLog` tables are unchanged and continue to be populated identically. LangSmith spans are entirely orthogonal to the SQLite persistence layer.

---

## New Module: `ekap_aiq/telemetry/langsmith_tracing.py`

This new module centralizes all LangSmith instrumentation helpers:

| Symbol | Type | Purpose |
|---|---|---|
| `safe_trace(name, run_type, inputs, metadata, tags)` | async context manager | Wraps `langsmith.trace()` with non-fatal error handling |
| `unit_trace(session_id, question_id, portal_id, ...)` | async context manager | Root span factory for `process_unit` |
| `agent_trace(agent_index, round_number, ...)` | async context manager | Child span for each assessor agent |
| `confidence_gate_trace(retry_count, ...)` | async context manager | Child span for each confidence gate attempt |
| `validation_trace(retry_number, agent_index, ...)` | async context manager | Child span for each validation attempt |
| `adjudication_trace(round_number, ...)` | async context manager | Child span for each adjudication attempt |

All helpers are no-ops when `LANGCHAIN_TRACING_V2` is not `"true"`.
