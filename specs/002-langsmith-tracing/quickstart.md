# Quickstart: Validating LangSmith Tracing

**Feature**: `002-langsmith-tracing`
**Date**: 2026-08-13

---

## Prerequisites

1. LangSmith account with API key: https://smith.langchain.com/
2. `langsmith` installed: `pip install -e ".[dev]"` (after adding to `pyproject.toml`)
3. `.env` configured with LangSmith keys (see `.env.example` LangSmith section)
4. Existing `aiq` prerequisites (GCP auth, database initialized)

---

## Setup: Enable Tracing

Add to your `.env` file:

```
LANGCHAIN_TRACING_V2=true
LANGSMITH_API_KEY=lsv2_pt_<your-key>
LANGSMITH_PROJECT=ekap-aiq
```

---

## Scenario 1: Confirm tracing activates and produces a root span

```bash
# Initialize DB if not already done
aiq db init

# Run a single unit (seed fixture data first if needed)
aiq seed questions
aiq seed portals
aiq run --batch-size 1 --no-adjudicate
```

**Expected outcome in LangSmith UI** (https://smith.langchain.com/):
- Navigate to Project `ekap-aiq`
- One trace appears named `process_unit`
- Root span metadata shows `session_id`, `question_id`, `portal_id`
- Child spans visible: `url_resolution`, at minimum

---

## Scenario 2: Confirm full span tree for a complete 2-agent run

```bash
aiq run --batch-size 1
```

**Expected outcome**:
- Root trace `process_unit` with outcome `DELIVERED` or `ESCALATED`
- Two `assessor_agent[0]` and `assessor_agent[1]` sibling spans with **overlapping timestamps** (parallel execution evidence)
- Each assessor span contains at minimum: `confidence_gate_attempt[0]`, `model_call`, `validation_attempt[0]`, inner `model_call`
- One `adjudication[round=1]` span after both agents complete
- Total span count ≥ 10 for a clean 2-agent, no-retry run

---

## Scenario 3: Confirm retry spans appear

Trigger a validation retry by running against a portal likely to produce low-confidence output. Alternatively, temporarily lower `AIQ_VALIDATION_QUALITY_THRESHOLD` to `0.0` in `.env` to force retries:

```bash
# Temporarily force retries for testing
AIQ_VALIDATION_QUALITY_THRESHOLD=0.99 aiq run --batch-size 1
```

**Expected outcome**:
- An `assessor_agent[0]` span containing two `validation_attempt` siblings: `validation_attempt[0]` (passed=false) and `validation_attempt[1]`
- Each `validation_attempt` span has its own inner `model_call` span

---

## Scenario 4: Confirm tracing is a no-op when disabled

```bash
# Remove or unset LANGCHAIN_TRACING_V2
LANGCHAIN_TRACING_V2=false aiq run --batch-size 1
```

**Expected outcome**:
- Run completes normally with identical output to pre-tracing behaviour
- No new traces appear in LangSmith UI
- No errors or warnings related to LangSmith in output

---

## Scenario 5: Confirm batch grouping by `session_id`

```bash
aiq run --batch-size 5
```

**Expected outcome in LangSmith**:
- Filter traces by tag containing the session ID printed in CLI output
- All 5 unit traces appear under the same filter
- Each trace is a separate root span (not nested)

---

## Scenario 6: Confirm escalation paths are traced

Force an unresolvable URL scenario:
```bash
# Seed a portal with a known-bad URL and run
aiq run --batch-size 1
```

**Expected outcome**:
- Root `process_unit` span with `outcome=UNASSESSABLE`
- Child `url_resolution` span with failure metadata
- No `assessor_agent` spans present

---

## Span Count Reference

| Scenario | Minimum expected span count |
|---|---|
| Escalated at link resolution | 2 (root + url_resolution) |
| Clean 2-agent, no retries, delivered | 10-12 |
| 2-agent, 1 validation retry per agent | 14-16 |
| 2-agent, 1 adjudication retry | 18-22 |

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| No traces in LangSmith | `LANGCHAIN_TRACING_V2` not set to `"true"` or `LANGSMITH_API_KEY` missing/invalid |
| WARNING: "LangSmith trace upload failed" in logs | Network connectivity issue; pipeline still runs correctly |
| Spans appear sequential not parallel | Check Python version ≥ 3.11; asyncio context propagation requires 3.11+ |
| Root span missing `session_id` tag | Ensure `tags=[session_id]` is passed in `unit_trace()` call |

---

## References

- [Tracing Contract](contracts/tracing-contract.md)
- [Data Model](data-model.md)
- [Research](research.md)
- [Spec](spec.md)
