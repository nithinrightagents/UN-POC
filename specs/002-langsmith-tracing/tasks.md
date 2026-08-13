# Tasks: LangSmith Pipeline Tracing

**Feature**: `002-langsmith-tracing`
**Spec**: [spec.md](spec.md)
**Plan artifacts**: [research.md](research.md) | [data-model.md](data-model.md) | [contracts/tracing-contract.md](contracts/tracing-contract.md) | [quickstart.md](quickstart.md)
**Generated**: 2026-08-13

---

## Implementation Strategy

MVP-first delivery in three increments:
1. **Increment 1** (Phase 1-2): Infrastructure only — `langsmith_tracing.py` helper module + dependency + env vars. Zero pipeline changes. Tracing is a no-op. All tests still pass.
2. **Increment 2** (Phase 3): Wire tracing into the pipeline at every integration point. Full span hierarchy live.
3. **Increment 3** (Phase 4): Polish — model call metadata enrichment, non-fatal error guard, validation.

---

## Phase 1: Setup & Dependencies

> Goal: Add `langsmith` as a dependency and expose all required configuration. Zero code changes to pipeline logic.

- [x] T001 Add `langsmith>=0.1.0` to `dependencies` list in `pyproject.toml`
- [x] T002 Add LangSmith section to `.env.example` with `LANGCHAIN_TRACING_V2`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT`, `LANGCHAIN_ENDPOINT` keys, placeholder values, and explanatory comments
- [x] T003 [P] Install updated dependencies in virtualenv: run `pip install -e .` from project root to verify `langsmith` resolves without conflicts

---

## Phase 2: Foundational — `langsmith_tracing.py` Helper Module

> Goal: Create the single centralized tracing helper module that all pipeline call sites will use. This module is the only place `langsmith` is imported. All helpers are zero-overhead no-ops when `LANGCHAIN_TRACING_V2` is not `"true"`.
>
> **Must complete before Phase 3.** All Phase 3 tasks import from this module.

- [x] T004 Create `src/ekap_aiq/telemetry/langsmith_tracing.py` — module scaffold with module docstring explaining the no-op contract and the `safe_trace()` design
- [x] T005 Implement `safe_trace(name, run_type, inputs, metadata, tags, parent)` async context manager in `src/ekap_aiq/telemetry/langsmith_tracing.py` — wraps `langsmith.trace()` with a `try/except Exception` guard that emits `logging.warning("LangSmith trace upload failed: {e}")` and swallows the exception; is a true no-op (no `langsmith` import executed) when `LANGCHAIN_TRACING_V2 != "true"`
- [x] T006 Implement `unit_trace(session_id, question_id, portal_id, question_text, portal_url)` async context manager in `src/ekap_aiq/telemetry/langsmith_tracing.py` — factory for the `process_unit` root span; `run_type="chain"`, `tags=[session_id]`, `metadata={session_id, question_id, portal_id}`; yields the active run handle for downstream patching of `outputs`
- [x] T007 Implement `agent_trace(agent_index, round_number, model, temperature, profile)` async context manager in `src/ekap_aiq/telemetry/langsmith_tracing.py` — child span for `assessor_agent[N]`; `name=f"assessor_agent[{agent_index}]"`, `run_type="chain"`, `metadata={agent_index, round_number, run_id}`
- [x] T008 Implement `confidence_gate_trace(retry_count, has_addendum, addendum_kind)` async context manager in `src/ekap_aiq/telemetry/langsmith_tracing.py` — child span for `confidence_gate_attempt[N]`; `name=f"confidence_gate_attempt[{retry_count}]"`, `run_type="chain"`
- [x] T009 Implement `validation_trace(retry_number, agent_index, round_number)` async context manager in `src/ekap_aiq/telemetry/langsmith_tracing.py` — child span for `validation_attempt[N]`; `name=f"validation_attempt[{retry_number}]"`, `run_type="chain"`, `metadata={retry_type: "validation_retry", retry_number, agent_index, round_number}`
- [x] T010 Implement `adjudication_trace(round_number, is_retry)` async context manager in `src/ekap_aiq/telemetry/langsmith_tracing.py` — child span for `adjudication[round=N]`; `name=f"adjudication[round={round_number}]"`, `run_type="chain"`, `metadata={retry_type: "adjudication_retry", round_number}` when `is_retry=True`
- [x] T011 Export all public symbols from `src/ekap_aiq/telemetry/__init__.py` — add `unit_trace`, `agent_trace`, `confidence_gate_trace`, `validation_trace`, `adjudication_trace`, `safe_trace` to `__all__`

---

## Phase 3: Pipeline Wiring — Span Integration Points

> Goal: Instrument every pipeline stage so the full span hierarchy specified in FR-T-002 appears in LangSmith. Each task is an independent call-site change. Tasks T012–T017 can be parallelised across files.

### US1 — Root span: `process_unit`

- [x] T012 [US1] Wrap the entire body of `process_unit()` in `src/ekap_aiq/orchestration/scheduler.py` with `async with unit_trace(session_id, question.question_id, portal_id, question.text, resolved_url) as root_run:` — enter before the first `if current_state_ref[0] == UnitState.PENDING:` check, exit after final `return UnitOutcome(...)` call; patch `root_run` outputs with `{"outcome": outcome.final_state.value, "detail": outcome.detail}` before returning
- [x] T013 [US1] Patch escalation paths in `process_unit()` in `src/ekap_aiq/orchestration/scheduler.py` — in the `escalate()` inner function, attach `escalation_reason` to the root run metadata so escalation reason is visible on the root span; ensure the context manager exits cleanly on all escalation return paths

### US2 — Stage child spans: link resolution and language detection

- [x] T014 [P] [US2] Wrap `resolve_link(...)` call in `process_unit()` in `src/ekap_aiq/orchestration/scheduler.py` with `async with safe_trace("url_resolution", run_type="chain", inputs={question_id, portal_id}, metadata={}):` — place inside the existing `if current_state_ref[0] == UnitState.RESOLVING_LINK` block, wrapping exactly the `await resolve_link(...)` call; set outputs to `{resolved_url, supplying_source, outcome}` on exit
- [x] T015 [P] [US2] Wrap `detect_language(...)` call in `process_unit()` in `src/ekap_aiq/orchestration/scheduler.py` with `async with safe_trace("language_detection", run_type="chain", inputs={question_id, portal_id, resolved_url}):` — place inside the existing `with stage_log.timed("language_detection", ...)` block alongside (not replacing) the existing timed context manager; set outputs to `{detected_language, requires_decision, outcome}` on exit

### US3 — Assessor agent spans with confidence gate children

- [x] T016 [P] [US3] Wrap the body of `run_assessor_agent()` in `src/ekap_aiq/agents/assessor.py` with `async with agent_trace(agent_index, round_number, model, temperature, profile):` — enter before `async def assess_once(...)` definition, exit after `return run`; set outputs to `{answer, confidence, state, auth_boundary_observed}` before returning
- [x] T017 [P] [US3] Wrap each `await assess_once(addendum)` call in `run_with_confidence_gate()` in `src/ekap_aiq/agents/confidence_gate.py` with `async with confidence_gate_trace(retry_count, has_addendum=addendum is not None, addendum_kind=addendum.kind if addendum else None):` — the span must open before `output = await assess_once(addendum)` and close after; set outputs to `{confidence: output.confidence, accepted: gate.accepted, below_threshold: below}` on exit

### US4 — Validation attempt spans

- [x] T018 [US4] Wrap each validation call in `run_validation_retry_loop()` in `src/ekap_aiq/orchestration/retry_loops.py` with `async with validation_trace(retry_number, agent_index, round_number):` — enter before `validation = await validate_agent_output(...)`, exit after; set outputs to `{passed: validation.passed, quality_score: validation.quality_score, gaps_count: len(validation.gaps), verification_outcome: validation.verification_outcome.value}` on exit; ensure this wraps both the initial call (retry_number=0) and all retry calls in the while loop

### US5 — Adjudication spans

- [x] T019 [US5] Wrap each adjudication decision in `run_adjudication_retry_loop()` in `src/ekap_aiq/orchestration/retry_loops.py` with `async with adjudication_trace(round_number, is_retry=(retry_count > 0)):` — enter before `decision = adjudicate(current_runs, ...)`, exit after `result = build_adjudication_result(...)`; set outputs to `{consensus_answer: decision.consensus_answer, consensus_confidence: decision.consensus_confidence, discrepancy_flagged: decision.discrepancy_flagged, flag_reason: decision.flag_reason}` on exit

### US6 — Model call span: `ModelProvider.generate()`

- [x] T020 [P] [US6] Add `@traceable(run_type="llm", name="model_call")` decorator to `ModelProvider.generate()` in `src/ekap_aiq/agents/provider.py` — import `traceable` from `langsmith`; the decorator automatically captures `model`, `system_instruction`, `prompt`, `temperature` as inputs and `ModelResponse` as output
- [x] T021 [P] [US6] Enrich the `model_call` span with token and cost metadata in `ModelProvider.generate()` in `src/ekap_aiq/agents/provider.py` — after computing `input_tokens` and `output_tokens`, call `langsmith.get_current_run_tree()` to get the active run and call `.patch(metadata={input_tokens, output_tokens, cost_usd: estimate_cost(...), model_identity, temperature})` — guard with `if run_tree is not None:` to remain safe when tracing is disabled

---

## Phase 4: Polish & Cross-Cutting Concerns

> Goal: Robustness, validation, and documentation hygiene. Can be done after Phase 3 is working end-to-end.

- [x] T022 Verify `src/ekap_aiq/telemetry/langsmith_tracing.py` `safe_trace()` guard correctly suppresses all `langsmith` SDK exceptions — manually test by setting an invalid `LANGSMITH_API_KEY` and confirming only a `WARNING` log line appears; pipeline must still produce correct output
- [x] T023 [P] Verify backward compatibility: run the full test suite (`pytest tests/ -v`) with `LANGCHAIN_TRACING_V2` unset — confirm all tests pass with zero modifications; any failure is a blocking regression
- [x] T024 [P] Verify parallel span timestamps: run `aiq run --batch-size 1` with 2 agents and inspect the LangSmith trace — confirm `assessor_agent[0]` and `assessor_agent[1]` spans have overlapping `start_time`/`end_time` intervals proving async parallelism is reflected correctly
- [x] T025 Verify span count for a clean delivered run: confirm the LangSmith trace contains ≥ 10 distinct spans for a 2-agent, no-retry, delivered unit (root + url_resolution + language_detection + 2x assessor + 2x confidence_gate + 2x model_call in assessor + 2x validation + 2x model_call in validation + adjudication)
- [x] T026 [P] Update `src/ekap_aiq/telemetry/__init__.py` docstring to document the new LangSmith tracing symbols and their purpose
- [x] T027 [P] Add `# LangSmith tracing` inline comment at each call site in `scheduler.py`, `assessor.py`, `confidence_gate.py`, `retry_loops.py`, and `provider.py` — one-line comment immediately above each `async with ..._trace(...)` block explaining which FR it satisfies (e.g., `# FR-T-002: url_resolution child span`)

---

## Dependency Graph

```
T001 → T003
T002 (independent)
T004 → T005 → T006 → T007 → T008 → T009 → T010 → T011
T011 → T012 → T013
T011 → T014, T015 (parallel after T011)
T011 → T016 → T017 (T017 depends on T016 being in place)
T011 → T018
T011 → T019
T011 → T020 → T021
T013, T014, T015, T018, T019, T021 → T022 → T023, T024, T025 (parallel)
T023, T024, T025 → T026, T027 (parallel)
```

---

## Parallel Execution Opportunities

| Group | Tasks | Can run in parallel after |
|---|---|---|
| Setup | T002, T003 | T001 |
| Phase 2 sequential | T004–T011 | T001 |
| Phase 3 call sites | T014, T015, T016, T020 | T011 |
| Phase 3 dependent | T017 (after T016), T018, T019, T021 (after T020) | respective predecessors |
| Phase 4 validation | T023, T024, T025 | T022 |
| Phase 4 docs | T026, T027 | T023 |

---

## Story → Task Mapping

| User Story | Requirement | Tasks | Independent test criteria |
|---|---|---|---|
| US1 | FR-T-001, FR-T-006, FR-T-008 | T012, T013 | One root `process_unit` span in LangSmith per unit run; `session_id` tag present |
| US2 | FR-T-002 (url + lang) | T014, T015 | `url_resolution` and `language_detection` child spans visible; outputs contain resolution outcome |
| US3 | FR-T-002 (assessor + conf), FR-T-004, FR-T-005 | T016, T017 | Parallel `assessor_agent[0/1]` spans with overlapping timestamps; `confidence_gate_attempt` children present |
| US4 | FR-T-002 (validation), FR-T-004 | T018 | `validation_attempt[N]` siblings under each assessor span; retry_number tag correct |
| US5 | FR-T-002 (adjudication), FR-T-004 | T019 | `adjudication[round=N]` span present; `discrepancy_flagged` in outputs |
| US6 | FR-T-003 | T020, T021 | `model_call` spans contain full prompt, response, tokens, cost in LangSmith UI |

---

## MVP Scope

Increment 1 (unblocking): **T001–T003** — dependency and env vars only  
Increment 2 (core value): **T004–T021** — full span hierarchy live  
Increment 3 (hardening): **T022–T027** — robustness and docs

Minimum viable trace (root + model calls visible): **T001–T011, T012, T020** — proves tracing is wired with 5 spans; validates SDK propagation works before adding all child spans.
