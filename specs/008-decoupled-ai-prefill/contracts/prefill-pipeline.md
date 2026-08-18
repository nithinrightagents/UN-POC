# Contract: The Prefill Pipeline

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Spec**: [spec.md](../spec.md) · **Research**: [research.md](../research.md) · **Data model**: [data-model.md](../data-model.md)

What `process_unit` does after this feature, stated as a contract rather than as a diff. Every path ends in a `prefills` row and no path writes an `escalation_queue_items` row.

---

## 1. The pipeline, stage by stage

```
load questionnaire (unchanged)
   │
   ├─ budget check ─────────── exhausted ──► prefill(budget_reached)        no_suggestion
   │
   ▼
resolve_link  (prior_survey_kb → msq → search, unchanged)
   │
   ├─ no usable URL ─────────────────────► prefill(no_usable_evidence)      unassessable
   ├─ requires_authenticated_access ─────► prefill(access_boundary)         no_suggestion
   │
   ▼
2 assessor agents, concurrent  (asyncio.gather, unchanged)
   │  each runs its own confidence gate + validation retry loop (unchanged)
   │
   ├─ majority language unsupported ─────► prefill(unsupported_language)    no_suggestion
   ├─ all agents hit a login wall ───────► prefill(access_boundary)         no_suggestion
   ├─ both agents raised ────────────────► prefill(assessment_failure)      no_suggestion
   ├─ evidence unfetchable ──────────────► prefill(evidence_unreachable)    no_suggestion
   ├─ < 2 VALIDATED_PASS ────────────────► prefill(insufficient_positions)  no_suggestion
   │
   ▼
classify_agreement(positions, tolerance)          ← NEW, pure (R3)
   │
   ├─ uncontested ──────────────┐
   ├─ agreed_with_gap ──────────┤ resolved position
   │                            │
   └─ disputed ──► resolver agent (NEW, R5)
                      │
                      ├─ undetermined ──► prefill(unresolved_disagreement)  no_suggestion
                      └─ selected ───────┘
                                         │
                                         ▼
                          final validation, single pass (R6)
                                         │
                     ├─ fail ──► prefill(failed_final_validation)           no_suggestion
                     └─ pass ──► prefill(answer, confidence, evidence)      delivered
```

Nowhere in this diagram does an arrow leave the pipeline into a human queue. That is SC-001 and FR-PF-002 as a picture.

---

## 2. Agreement classification

```python
def classify_agreement(
    validated_runs: list[AssessorAgentRun],
    per_question_confidence_threshold: int,
    gap_tolerance: int,
) -> AgreementOutcome
```

Pure, no I/O, no model call. Calls the untouched `adjudicate()` and maps its result:

| Precondition | `kind` | `answer` | `confidence` | Resolver |
|---|---|---|---|---|
| `len(validated_runs) < 2` | — | — | — | **not called at all**; caller emits `insufficient_positions` (FR-PF-028) |
| `discrepancy_flagged = False` | `uncontested` | `decision.consensus_answer` | `decision.consensus_confidence` | no (FR-PF-024) |
| `flag_reason = "confidence_delta"` | `agreed_with_gap` | the single distinct answer across positions | consensus confidence **minus a gap penalty** | no (FR-PF-025) |
| `flag_reason = "answers_differ"` | `disputed` | `None` | `None` | **yes** (FR-PF-026) |

`confidence_gap` is `decision.max_pairwise_confidence_delta` in every branch, recorded even when zero (FR-PF-025's "the gap MUST be recorded").

**The gap penalty.** `agreed_with_gap` confidence is `compute_consensus_confidence(confidences, gap) - gap`, floored at 0. FR-PF-025 requires the gap to *reduce* confidence; subtracting the gap itself makes the reduction proportional to the disagreement and needs no new tunable. `gap_tolerance` decides only whether the outcome is labelled `agreed_with_gap` rather than `uncontested`.

**Invariant.** `classify_agreement` never returns `disputed` when the positions share an answer, and never returns `uncontested` or `agreed_with_gap` when they do not. This is the whole of FR-PF-026a — the resolver's invocation condition is a property of this function, not a condition someone checks at the call site.

---

## 3. The resolver agent

```python
async def resolve_disagreement(
    state: dict,               # question, portal_url, both positions with evidence
    agent: ResolverAgent,
    *, settings, provider, fetch_log, stage_log, cost_ledger,
) -> ResolverDecision
```

**Input.** Both positions with answer, confidence, justification, evidence URL, and element text, plus the disagreement description from the existing `_describe_disagreement()` — which already states *what* differs without stating *who* said it.

**Output contract.**

| Field | Rule |
|---|---|
| `selected_run_id` | MUST be one of the two input `run_id`s, or `None` |
| `undetermined` | `True` ⟺ `selected_run_id is None` |
| `disagreement_characterization` | non-empty (FR-PF-026b) |
| `reasoning` | non-empty (FR-PF-026b) |

**Coercion to `undetermined`** — three cases, all mapped to `unresolved_disagreement` (FR-PF-026d):

1. `selected_run_id` matches neither input position.
2. The provider raised, timed out, or returned unparseable structure.
3. The model explicitly declined.

There is deliberately no fourth branch that picks a position when the resolver fails. FR-PF-026d forbids it and the schema makes it inexpressible.

**What the resolver may not do.** It selects between two supplied positions; it has no browser, no fetch tool, and no path to form an independent answer. This is enforced by the constructor signature — `ResolverAgent(provider=...)` takes no `browser`, unlike `AssessorAgent(provider=..., browser=...)` — so the Out of Scope entry forbidding a fresh third opinion is a wiring fact rather than a prompt instruction.

**Telemetry.** `stage_events` label `resolution`; `cost_ledger` entries recorded with `stage="resolution"` and `agent_index=None`, so contested-question spend is separable from assessor spend in `by_stage_and_agent()`.

---

## 4. The final validation gate

```python
final = await validator_node(
    {"run_id": selected.run_id, "session_id": ..., "question_text": ...,
     "output": resolved_position_output, "element_reference": ...,
     "retry_number": 0},
    validator_agent, settings=..., provider=..., browser=..., ...,
)
```

One call. `retry_number=0` always. No addendum, no re-assessment, no loop ([research.md](../research.md) R6).

| Result | Prefill |
|---|---|
| `passed = True` | `suggested = 1`, `delivered` |
| `passed = False` | `suggested = 0`, `failed_final_validation`, `no_suggestion` |
| validator raised | `suggested = 0`, `failed_final_validation`, `no_suggestion` |

The gate runs on every resolved position, including `uncontested` ones. FR-PF-030 says "whether it arose from the two assessors agreeing or from the resolver settling a disagreement" — skipping it for uncontested positions would be the natural optimisation and is explicitly not permitted.

A `ValidationResult` row is written for the gate exactly as for per-agent validation, so the audit trail shape does not change. Its `stage_events` label is `final_validation`, distinct from `validation`.

---

## 5. Budget enforcement

```python
class RunBudget:
    limit: float          # 0.0 = uncapped
    spent: float          # in-process accumulator
    def record(self, cost: float) -> None
    def exhausted(self) -> bool     # limit > 0 and spent >= limit
```

**Checked once, in `run_batch.bounded()`, before acquiring the semaphore.** Not inside `process_unit`, not per model call ([research.md](../research.md) R7).

| Moment | Behaviour | Requirement |
|---|---|---|
| Budget not yet reached | dispatch normally | — |
| Budget reached, indicator in flight | that indicator runs to completion | FR-PF-041a |
| Budget reached, indicator not yet dispatched | write `budget_reached` prefill, do not dispatch | FR-PF-041b |
| Run ends | record `budget_in_force` and `spend_reached` on the job | FR-PF-041d |
| Run ends after a budget stop | job state is `completed`, **not** `failed` | FR-PF-041b |
| Re-run after a budget stop | unreached units are still non-terminal, so `process_unit`'s existing "already terminal" skip resumes exactly them | FR-PF-041e |

FR-PF-041e needs no new code: units that were never dispatched were never advanced past `PENDING`, and resumability is spec 001's existing behaviour.

**`limit = 0.0` means uncapped** — `exhausted()` short-circuits, so an unconfigured deployment behaves exactly as today (FR-PF-041c).

---

## 6. Concurrency and re-running

| Guarantee | Mechanism | Requirement |
|---|---|---|
| One run per unit; a second trigger reports the same run | `assessment_jobs` partial unique index (spec 007) | FR-PF-036, edge case |
| A run never blocks an assessor | assessors read `prefills` and write `human_assessor_submissions`; the run writes `prefills` and `units`. Disjoint tables | FR-PF-006, SC-011 |
| A re-run alters no human submission | `prefills` is append-only; the run has no write path to `human_assessor_submissions` | FR-PF-038, SC-010 |
| The newest completed run's prefills are what shows | `latest_prefill()` orders by `created_at DESC` restricted to completed runs | FR-PF-039 |
| One failing indicator does not end the run | already true — `run_batch`'s `TaskGroup` per-unit isolation plus `process_unit`'s per-unit terminal states | FR-PF-040 |

**In-flight reads are consistent, not blocked.** An assessor opening a unit mid-run sees prefills for indicators that already wrote a row and empty suggestions for the rest. `latest_prefill()` restricted to *completed* runs would hide in-flight rows entirely; restricting to completed runs **only when a completed run exists** gives the spec's behaviour in both cases — the first run's partial output is visible, a re-run does not flicker between old and new.

---

## 7. What every failure path must satisfy

Three properties, each directly testable and each covering a whole class of paths rather than a single branch:

1. **Coverage.** After a completed run, `count(prefills WHERE run_id = R) == count(questions in cycle)`. (SC-002, FR-PF-033)
2. **No human work.** After a completed run, `count(escalation_queue_items created during R) == 0`. (SC-001, FR-PF-002)
3. **No escalated terminal.** After a completed run, no unit it touched is in `UnitState.ESCALATED`. (SC-007a, FR-PF-032a)

These are the three assertions a single end-to-end fixture proves, and they hold for every reason in the taxonomy rather than being re-asserted per reason.
