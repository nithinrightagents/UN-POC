# Contract: Validator

**Satisfies**: FR-076–FR-091 | **Data model**: [../data-model.md](../data-model.md) §Validation Result

One invocation evaluates **exactly one** Assessor Agent Run. The Validator judges the agent's work; it never judges the question (FR-090).

## Input schema — closed

```jsonc
{
  "session_id": "string",
  "run_id": "string",
  "question": { "question_id": "string", "text": "string", "answer_type": "..." },
  "agent_output": { /* exactly one Assessor Agent Run output */ }
}
```

**One run, always.** The schema admits no second `agent_output` for the same `(question_id, portal_id)` (FR-079, SC-017). Independence survives the validation stage because the stage cannot physically see across it.

The Validator is **not** given: any other agent's output, the consensus answer, ground truth (FR-094), or the question's expected answer.

## Output schema

```jsonc
{
  "validation_id": "string",
  "run_id": "string",
  "quality_score": 0.82,
  "gaps": ["justification does not reference the cited element"],
  "passed": true,
  "retry_number": 0,
  "verification_outcome": "confirmed | element_absent | text_mismatch | target_unreachable",
  "verification_attempts": 1,
  "verified_at": "2026-08-13T10:22:31Z"
}
```

## What validation assesses (FR-077)

1. Every required evidence component is present (FR-021).
2. The cited evidence is **independently locatable online** at the recorded location (FR-086).
3. The cited evidence supports the stated answer.
4. The justification is consistent with both the answer and the evidence.
5. The stated confidence is proportionate to observed evidence quality.

`passed` is `quality_score ≥ validation_quality_threshold` (FR-078).

## Independent verification (FR-086–FR-091)

The Validator **re-fetches the live page**. It does not judge the captured artifact alone.

Resolution follows the composite element reference (research R5):

| Selector | Text hash | Outcome | Effect |
|---|---|---|---|
| hit | match | `confirmed` | Pass; stamp `verified_at` (FR-091) |
| miss | match elsewhere | `confirmed` | Page reshuffled, evidence intact; reference updated |
| hit | mismatch | `text_mismatch` | **Fail** with the specific discrepancy as the gap (FR-087) |
| miss | miss | `element_absent` | **Fail** with the specific discrepancy as the gap (FR-087) |
| page unreachable | — | `target_unreachable` | **Not a failure** — defer and re-attempt (FR-088) |

### The attribution rule (FR-088, SC-020)

`target_unreachable` must never be recorded as an agent quality failure, and `element_absent` must never be recorded as an unreachable target. These are different facts about different subjects: one is about the agent's work, the other about the network.

When the target stays unreachable after `verification_attempt_bound`, the **unit** escalates as an unverifiable target — the agent is not blamed and not retried on that basis.

### Rate limiting (FR-089)

Verification fetches acquire from the **same per-domain token bucket** as Assessor Agent fetches and are recorded with `caller_class = "validator"` (FR-115). This is a correctness requirement, not a courtesy: SC-019 requires zero violations attributable to verification traffic, measured against a single shared budget.

## Invariants

| # | Invariant | Requirement |
|---|---|---|
| V1 | Never alters the agent's answer, confidence, justification, or evidence — admits or retries only | FR-083 |
| V2 | Never forms, records, or acts on its own answer to the question | FR-090 |
| V3 | Sees exactly one agent's output per invocation | FR-079, SC-017 |
| V4 | Validation retries increment `validation_retry_count` only — never the adjudication counter | FR-084 |
| V5 | Retrying one agent never re-runs another | FR-081 |
| V6 | `verified_at` is stamped only on `confirmed` | FR-091 |

**V6 carries more weight than it appears to.** `verified_at` is the sole discriminator between FR-025 (a later-disappearing element is a valid point-in-time record) and FR-087 (a never-verified element is a quality failure). Stamping it on a non-confirmed outcome silently converts quality failures into permanent records — the exact contradiction the previous clarification session had to split apart.

## Retry and escalation

- Fail below `validation_retry_limit` → re-run **that agent only**, gaps supplied as `validation_gaps` addendum (FR-080, FR-081).
- Fail at the limit → run state `validation_failed_terminal`; not admitted to adjudication (FR-082).
- Fewer than 2 `validated_pass` runs remain → unit escalates (FR-082, SC-016).

## Known accepted cost

An element that legitimately disappears between capture and verification fails a correct agent (spec, Edge Cases). This is accepted: the retry re-assesses against the current page, which is the state a human reviewer would also see. FR-115 telemetry makes the false-failure rate measurable; `verification_attempt_bound` is the tuning lever.
