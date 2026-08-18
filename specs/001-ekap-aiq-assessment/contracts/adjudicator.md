# Contract: Adjudicator

**Satisfies**: FR-027–FR-039 | **Data model**: [../data-model.md](../data-model.md) §Adjudication Result, §Discrepancy Case

Two scopes, deliberately separate. **Per-question** adjudication drives retries. **Portal-level** adjudication drives human review of a portal as a whole. They compare the same agents over the same questions — portal-level is an aggregate view of the same signal, not an independent detector (spec, Assumptions).

---

## Per-question adjudication

### Input

```jsonc
{
  "session_id": "string",
  "question_id": "string",
  "portal_id": "string",
  "round_number": 1,
  "validated_runs": [ /* ≥ 2 runs, all state = validated_pass */ ]
}
```

**Precondition (FR-027, FR-082, SC-016)**: all N agents for the round are terminal, and `len(validated_runs) ≥ 2`. Below two, the Adjudicator is not invoked at all — the unit escalates. There is no path that adjudicates a single position.

### Output

```jsonc
{
  "adjudication_id": "string",
  "discrepancy_flagged": false,
  "flag_reason": null,                  // "answers_differ" | "confidence_delta"
  "max_pairwise_confidence_delta": 4,
  "consensus_answer": <structured>,     // null when escalating
  "consensus_confidence": 84,
  "below_acceptance_threshold": false
}
```

### Decision table (FR-028) *(Per-question retry loops superseded by spec 008 FR-PF-025: two-assessor arbitration & resolver)*

| Answers | Max pairwise confidence delta | Flagged | Reason |
|---|---|---|---|
| identical | ≤ threshold | no | — |
| identical | > threshold | **yes** | `confidence_delta` |
| differ | any | **yes** | `answers_differ` |

Threshold is `per_question_confidence_threshold`, default 10 points (FR-029), read from the session's Configuration Snapshot (FR-075) — never from live configuration.

Agreement on the answer alone is not sufficient to deliver: two agents that agree on the answer but diverge sharply on confidence are disagreeing about how well the portal evidences it, and that is a real disagreement (spec, Edge Cases).

### Retry loop

1. Flagged and `retry_count < adjudication_retry_limit` (default 2, FR-032) → re-run agents with a `disagreement_points` addendum (FR-030).
2. The addendum **must not attribute any position to an identified agent** (FR-031). Independence has to survive across rounds, not just within one.
3. Converged → consensus produced; full retry history retained (FR-061).
4. Still disagreeing at the limit → escalate with the disagreement summary and **every agent's position from every round** (FR-033). No consensus answer is delivered automatically.

### Consensus confidence (FR-034)

Reflects cross-agent agreement **in addition to** per-agent confidence. Recorded separately; per-agent values are never altered. It is displayed as a 0–100 percentage with no tier label (FR-042), subject to:

- FR-024 — capped below the acceptance threshold when any evidence component is missing or unresolvable.
- FR-018 — out-of-set-language best-effort answers are capped at the configured ceiling.

---

## Portal-level adjudication

Runs once a portal's question set is complete.

### Input

```jsonc
{
  "session_id": "string",
  "portal_id": "string",
  "first_round_positions": [ /* every agent's round-1 position, per question */ ]
}
```

**First-round positions only** (FR-035), before any retry. This is what gives portal-level a role per-question adjudication cannot fill: a portal whose agents initially read it very differently is flagged for joint human review **even after every individual question converged on retry**. Convergence does not erase a poor first read, and that is precisely the case the existing manual methodology sends back for joint review.

Only questions eligible under FR-058 are included — see [../data-model.md](../data-model.md) §Portal Measure Eligibility.

### Output

```jsonc
{
  "case_id": "string",
  "differing_answer_rate": 0.40,
  "affirmative_rate_gap": 0.00,
  "thresholds_in_force": { "differing_answer_rate": 0.10, "affirmative_rate_gap": 0.10 },
  "flagged": true,
  "triggering_measure": "differing_answer_rate",
  "per_question_breakdown": [ /* ... */ ]
}
```

### Measures (FR-035–FR-037)

| Measure | Definition | Default threshold | Role |
|---|---|---|---|
| **Differing-answer rate** | Proportion of questions where first-round answers differ | 10% | **Primary** (FR-036) |
| **Affirmative-rate gap** | Difference between agents' rates of affirmative answers | 10 pp | Recorded, never the sole trigger |

Flag when **either** exceeds its own threshold (FR-037).

The affirmative-rate gap cannot be the sole trigger because it can miss disagreement entirely: two agents each answering yes to 50 of 100 questions while disagreeing on 40 of them produce a gap of exactly zero against a differing-answer rate of 40%. That worked example is why FR-036 designates the differing-answer rate primary, and it is the shape of the test that guards it.

### Effect of a flag (FR-038, FR-039)

- Routes the portal to human review as a **single case**, distinct from and additional to any per-question escalations already raised.
- **Must not** trigger re-runs of questions that already reached consensus, and must not discard their results.
- Measures and the thresholds in force are recorded with the portal's assessment for audit.
