# Contract: Telemetry

**Satisfies**: FR-112–FR-118, SC-025 | **Data model**: [../data-model.md](../data-model.md) §Run Telemetry

The audit trail answers *how did this answer come about*. Telemetry answers *how is the run going, and what is it costing*. It is what makes SC-011 and SC-012 measurable rather than aspirational.

All records key on `session_id` (FR-113). Alerting thresholds, retention, and where these surface are planning decisions, not contract.

## Stage Event (FR-113, FR-114)

One record per pipeline stage transition.

```jsonc
{
  "event_id": "string",
  "session_id": "sess-2026-08-11-003",
  "unit_ref": { "question_id": "OSQ-1.14", "portal_id": "EE-2026" },
  "stage": "assessor_run",
  "agent_index": 1,                          // when stage is agent-scoped
  "round_number": 1,
  "started_at": "2026-08-11T09:11:02.104Z",
  "ended_at": "2026-08-11T09:12:04.882Z",
  "outcome": "success"                       // success | failure | deferred | escalated
}
```

**Stages**: `url_resolution`, `language_detection`, `assessor_run`, `validation`, `verification`, `adjudication`, `portal_adjudication`, `retry`, `escalation`, `human_action`.

Both `started_at` and `ended_at` are recorded so per-stage duration and end-to-end unit duration are **derivable without inference** (FR-114). Recording only a single timestamp per event would force durations to be reconstructed by pairing adjacent events, which breaks under concurrency — and concurrency is the normal case here.

## Fetch Record (FR-115)

One record per outbound fetch. This is the evidence base for SC-012 and SC-019.

```jsonc
{
  "fetch_id": "string",
  "session_id": "sess-2026-08-11-003",
  "domain": "eesti.ee",
  "caller_class": "validator",               // assessor_agent | validator
  "requested_at": "2026-08-11T09:12:01.220Z",
  "granted_at": "2026-08-11T09:12:03.115Z",  // after limiter acquisition
  "status": "ok"                             // ok | timeout | interstitial | error
}
```

`caller_class` is mandatory and is the whole point of the record. SC-019 requires zero violations *attributable to verification fetches*, measured against a single shared per-domain budget — which is unanswerable unless every acquisition records which caller took it.

The gap between `requested_at` and `granted_at` is limiter wait time. Aggregated per domain, it is the direct measurement of the throughput constraint the design is dominated by (research R6), and the number to present when the SC-011 cycle window is finally agreed.

## Cost Ledger Entry (FR-116)

One record per model invocation.

```jsonc
{
  "entry_id": "string",
  "session_id": "sess-2026-08-11-003",
  "stage": "assessor_run",
  "agent_index": 1,
  "model_identity": "provider/model@version",
  "input_units": 4821,
  "output_units": 337,
  "cost": 0.0142
}
```

Attributable to stage **and** to the individual Assessor Agent or Validator. Per-agent attribution matters beyond accounting: when agents are configured to diverge (research R7), it shows what the divergence costs, which is the input to any future decision about how many agents a cycle can afford.

## Run Summary (FR-112)

Derived, for an in-progress or completed session:

```jsonc
{
  "session_id": "sess-2026-08-11-003",
  "units_by_state": { "pending": 120, "assessing": 45, "delivered": 8210, "escalated": 402, "unassessable": 12 },
  "escalations_by_reason": { "requires_authenticated_access": 190, "unresolved_disagreement": 88, "no_usable_url": 12, "...": 0 },
  "failures_by_stage": { "validation": 340, "verification": 96 }
}
```

## Invariants

| # | Invariant | Requirement |
|---|---|---|
| T1 | No portal credentials in any telemetry record | FR-117, FR-110 |
| T2 | No benchmark ground truth in any telemetry record | FR-117, FR-094 |
| T3 | Telemetry is **never** an input to an assessment decision | FR-118 |
| T4 | Telemetry never alters an audit record | FR-118 |
| T5 | Every record carries `session_id` | FR-113, SC-025 |

**T3 is a containment rule, not a style preference.** Telemetry aggregates across agents by construction — a run summary knows what every agent produced. Letting any of it reach an agent, the Validator, or the Adjudicator would breach independence (FR-010) through a side channel that the closed input schemas would not catch, because it would arrive as legitimately-obtained operational context rather than as another agent's output. The `telemetry/` module therefore has no import path into `agents/`.
