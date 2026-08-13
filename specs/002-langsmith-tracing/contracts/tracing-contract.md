# Contract: LangSmith Tracing Integration

**Feature**: `002-langsmith-tracing`
**Type**: Internal SDK Integration Contract
**Date**: 2026-08-13

---

## Purpose

This contract defines the observable behaviour of the LangSmith tracing integration as seen by:
1. **Pipeline operators** — what they see in the LangSmith UI
2. **Tests** — what assertions can be made about span structure
3. **Future developers** — what invariants must be preserved when modifying the pipeline

---

## Environment Contract

### Required for tracing to activate
```
LANGCHAIN_TRACING_V2=true
LANGSMITH_API_KEY=<valid LangSmith API key>
```

### Optional
```
LANGSMITH_PROJECT=ekap-aiq        # defaults to "ekap-aiq" if unset
LANGCHAIN_ENDPOINT=<custom URL>   # for self-hosted LangSmith only
```

### Zero-tracing guarantee
When `LANGCHAIN_TRACING_V2` is absent or not `"true"`, the pipeline MUST behave identically to pre-tracing behaviour:
- No HTTP connections to LangSmith are opened
- No `langsmith` SDK state is mutated
- No latency overhead is introduced
- All `@traceable` decorators and `langsmith.trace()` context managers are zero-cost no-ops

---

## Span Naming Contract

All span names are fixed strings. Breaking changes to span names MUST be treated as a contract change requiring a version bump.

| Span name pattern | Context |
|---|---|
| `"process_unit"` | Root span; exactly one per `process_unit()` call |
| `"url_resolution"` | Child of root; exactly one per unit |
| `"language_detection"` | Child of root; present only when page is reachable |
| `"assessor_agent[{N}]"` | Child of root; one per agent index per round |
| `"confidence_gate_attempt[{N}]"` | Child of `assessor_agent`; N is 0-indexed retry count |
| `"model_call"` | Child of whichever span is active; one per `ModelProvider.generate()` call |
| `"validation_attempt[{N}]"` | Child of `assessor_agent`; N is retry_number |
| `"adjudication[round={N}]"` | Child of root; one per adjudication round |

---

## Metadata / Tag Contract

### Root span tags
- MUST include `session_id` as a tag (string, not key-value pair) for UI filterability

### Root span metadata
```json
{
  "session_id": "<string>",
  "question_id": "<string>",
  "portal_id": "<string>"
}
```

### `model_call` span metadata
```json
{
  "input_tokens": "<int>",
  "output_tokens": "<int>",
  "cost_usd": "<float>",
  "model_identity": "vertexai/<model-name>",
  "temperature": "<float>"
}
```

### Retry span metadata
All retry spans MUST include:
```json
{
  "retry_type": "confidence_retry | validation_retry | adjudication_retry",
  "retry_number": "<int, 0-indexed>",
  "agent_index": "<int>  (where applicable)",
  "round_number": "<int> (for adjudication)"
}
```

---

## Error Contract

### LangSmith API failure
- MUST NOT raise an exception into the pipeline
- MUST emit exactly one `logging.WARNING` message matching: `"LangSmith trace upload failed: ..."` 
- Pipeline MUST continue and produce correct assessment output

### Span exit on pipeline exception
- If the pipeline raises an exception inside a `langsmith.trace()` block, the SDK MUST record the span with `error` set to the exception message
- The exception MUST re-raise normally (not swallowed)

---

## Structural Invariants (testable assertions)

1. **One root per unit**: For any completed `process_unit` execution, exactly one span with `name == "process_unit"` and `parent_run_id == None` exists in LangSmith.

2. **Session grouping**: All root spans produced by a single `run_batch` call share the same `session_id` tag.

3. **Parallel concurrency**: For a 2-agent run, `assessor_agent[0]` and `assessor_agent[1]` spans have overlapping `[start_time, end_time]` intervals.

4. **Model call nesting**: Every `model_call` span has a non-null `parent_run_id` pointing to either a `confidence_gate_attempt`, `validation_attempt`, or `adjudication` span. A `model_call` span MUST NEVER be a root span.

5. **No orphan spans**: Every non-root span has a `parent_run_id` that resolves to a span in the same trace.

6. **Retry siblings**: All `confidence_gate_attempt` spans for the same agent are siblings (same `parent_run_id`), not nested inside each other.

---

## Backward Compatibility

- This contract does NOT change any existing public interfaces
- Existing `StageEventLog`, `CostLedger`, `FetchLog` contracts are unchanged
- No existing CLI commands, arguments, or output formats change
- No existing test signatures change
