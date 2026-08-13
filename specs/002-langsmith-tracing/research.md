# Research: LangSmith Pipeline Tracing

**Feature**: `002-langsmith-tracing`
**Date**: 2026-08-13

---

## R-01: LangSmith SDK async trace context propagation

### Decision
Use `langsmith.trace()` as an async context manager for pipeline stages, with `@traceable` on `ModelProvider.generate()`. For parallel `asyncio.gather` calls, use `langsmith.get_current_run_tree()` to capture the parent run handle *before* entering `gather`, then pass it explicitly into each coroutine via `langsmith.trace(..., parent=parent_run)`.

### Rationale
The `langsmith` SDK (>=0.1.0) uses Python `contextvars` for implicit context propagation. `asyncio.gather` spawns tasks that do NOT automatically inherit the caller's `contextvar` state in all Python versions — the context is copied at task creation time if using `asyncio.create_task`, but `asyncio.gather` on coroutines directly does inherit the context correctly in Python 3.11+. Given the project targets Python 3.11+ (`pyproject.toml: requires-python = ">=3.11"`), implicit propagation via `asyncio.gather` on coroutines works correctly. Explicit parent passing is a safe fallback and is used at the `run_batch` → `process_unit` boundary as a belt-and-suspenders measure.

### Alternatives considered
- **OpenTelemetry + LangSmith OTLP export**: More complex setup, no benefit for this use case. Rejected.
- **LangChain wrappers around `google-genai`**: Would require replacing `ModelProvider` with LangChain model classes. Violates the constraint that this is additive. Rejected.
- **Manual run ID threading via kwargs**: Error-prone, invasive. The `contextvars`-based approach is cleaner. Rejected.

---

## R-02: Span type mapping for LangSmith UI

### Decision
| Pipeline element | `langsmith.trace()` `run_type` |
|---|---|
| `process_unit` (root) | `"chain"` |
| `url_resolution`, `language_detection`, `adjudication` | `"chain"` |
| `assessor_agent[N]` wrapper | `"chain"` |
| `confidence_gate_attempt[N]` | `"chain"` |
| `validation_attempt[N]` | `"chain"` |
| `ModelProvider.generate()` | `"llm"` |

### Rationale
LangSmith uses `run_type` to render icons and group in the UI. `"llm"` type unlocks the prompt/response diff view and token display. `"chain"` is the generic container type for orchestration steps. Using `"tool"` for browser fetches was considered but rejected — browser fetches are infrastructure, not user-visible operations worth surfacing at the tool level in this PoC.

### Alternatives considered
- `"tool"` for browser fetches: adds noise without value at PoC scale. Deferred.

---

## R-03: Non-fatal error handling for LangSmith SDK

### Decision
Wrap every `langsmith.trace()` context exit in a `try/except Exception` guard in a thin `safe_trace()` helper. On any exception during span finalization, emit `logging.warning(f"LangSmith trace upload failed: {e}")` and swallow the exception. The `langsmith` SDK itself already performs background uploads on a daemon thread — individual upload failures do not propagate to the calling code by default. The explicit guard is belt-and-suspenders for SDK initialization errors (e.g., bad API key format).

### Rationale
Per clarification Q2: LangSmith failure is non-fatal. The SDK's default behavior already handles most transient failures transparently. The `safe_trace()` helper ensures even SDK-level exceptions (not just network errors) are caught.

### Alternatives considered
- SDK-level `LANGCHAIN_TRACING_V2` toggle disables all tracing at zero overhead when unset — this is the primary "off switch" and requires no code change.

---

## R-04: `ModelProvider.generate()` instrumentation strategy

### Decision
Add a `@traceable(run_type="llm", name="model_call")` decorator to `ModelProvider.generate()`. The decorator captures inputs (function arguments) and outputs (return value) automatically. Additionally, use `langsmith.get_current_run_tree()` inside the method to attach extra metadata: `input_tokens`, `output_tokens`, `cost`, `model_identity`, `temperature` as `extra` fields on the run.

### Rationale
`@traceable` is the lowest-overhead instrumentation — one decorator, zero changes to call sites. Input/output capture is automatic. The `extra` metadata dict is surfaced in the LangSmith UI's "Metadata" tab, giving operators full cost and token visibility without cluttering the primary input/output view.

### Alternatives considered
- Manual `langsmith.Client().create_run()` / `update_run()` calls: more control, significantly more code. Not needed given `@traceable` sufficiency. Rejected.

---

## R-05: `process_unit` root span boundary

### Decision
Wrap the entire body of `process_unit()` in `async with langsmith.trace("process_unit", run_type="chain", inputs={...}, tags=[session_id, question_id, portal_id]) as root_run:`. Set `metadata` with `session_id`, `question_id`, `portal_id`. On exit (normal or exception), patch the root run with `outputs={"outcome": final_state.value}`.

### Rationale
The `langsmith.trace()` async context manager correctly spans async code and propagates context into all child `await` calls. Entering it before any pipeline logic and exiting after the final `advance()` ensures the root span covers 100% of the unit's wall-clock duration with no gaps.

### Alternatives considered
- Decorator on `process_unit`: cannot easily access the dynamic final state for the output. Context manager is more flexible.

---

## R-06: Confidence gate span hierarchy

### Decision
In `run_with_confidence_gate()`, wrap each `await assess_once(addendum)` call in `async with langsmith.trace(f"confidence_gate_attempt", run_type="chain", inputs={"retry_count": retry_count, "has_addendum": addendum is not None}):`. This creates one child span per attempt, nested under the `assessor_agent[N]` span that is the parent in the current context.

### Rationale
`confidence_gate.py` calls `assess_once` which itself calls `ModelProvider.generate()` — so the `@traceable` on `generate()` will automatically nest inside the confidence gate span, which in turn is nested under the assessor agent span. The hierarchy is correct by construction.

---

## R-07: Environment variable and configuration wiring

### Decision
Add `langsmith>=0.1.0` to `pyproject.toml` dependencies. The SDK reads `LANGCHAIN_TRACING_V2`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGCHAIN_ENDPOINT` directly from the environment (standard behavior). No changes to `Settings` class or `load_settings()` are needed — the SDK self-configures from environment. Add all four variables to `.env.example` with placeholder values and explanatory comments.

### Rationale
Zero-config approach. The SDK's environment variable convention is well-established. Adding them to `Settings` would introduce coupling between pipeline config and observability config with no benefit.

---

## R-08: Existing tests compatibility

### Decision
All existing tests will pass without modification because:
1. `LANGCHAIN_TRACING_V2` is not set in test environments → SDK no-ops.
2. `@traceable` is a pure pass-through decorator when tracing is disabled.
3. No existing function signatures change.
4. No new required constructor arguments or dependencies are introduced to tested classes.

### Rationale
The opt-in env-var model (FR-T-007) is the primary compatibility guarantee. Confirmed by the SDK's documented behavior: when `LANGCHAIN_TRACING_V2` is not `"true"`, all `langsmith` decorators and context managers are zero-overhead no-ops.
