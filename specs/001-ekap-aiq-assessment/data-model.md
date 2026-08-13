# Phase 1 Data Model: EKAP AIQ

**Feature**: `specs/001-ekap-aiq-assessment` | **Plan**: [plan.md](./plan.md) | **Date**: 2026-08-13

Derived from the 20 Key Entities in [spec.md](./spec.md). Field types are logical, not storage-specific. Every table carrying assessment history is **append-only** (FR-062): corrections are new rows, never updates.

## Conventions

- `session_id` appears on every record produced during a run (FR-059, FR-060). It is the reconstruction key for FR-061 and the only argument an auditor should need.
- Timestamps are UTC, recorded at the moment of the event, never backfilled.
- "Terminal" for an agent run means: validated pass, **or** failed validation after the validation retry limit. Anything else is non-terminal (FR-067b).
- Actor identity is an opaque attributable string supplied by the surrounding platform (spec, Assumptions — IAM is out of scope).

---

## Core entities

### Survey Cycle
| Field | Type | Notes |
|---|---|---|
| `cycle_id` | id | PK |
| `name` | string | e.g. "2026 Biennial Survey" |
| `questionnaire_ref` | string | Externally authored (Dependencies) |
| `country_set` | list[country_id] | Scope for this cycle |
| `status` | enum | `draft` / `active` / `closed` |

Scopes custom questions (FR-054, FR-057) and supplies prior-cycle URL history to the historical resolution source.

### Assessment Session
| Field | Type | Notes |
|---|---|---|
| `session_id` | id | PK — the audit key (FR-059) |
| `cycle_id` | fk → Survey Cycle | Null for benchmark sessions |
| `mode` | enum | `production` / `benchmark` (FR-093, FR-095) |
| `config_snapshot_id` | fk → Configuration Snapshot | FR-063, FR-075 |
| `started_at` / `ended_at` | timestamp | |
| `status` | enum | `running` / `interrupted` / `complete` |

**Rule**: a `benchmark` session's answers may never be delivered into a cycle's results (FR-095). Enforced at the export boundary (FR-104) *and* at the repository, so a bug in one does not leak.

### Question
| Field | Type | Notes |
|---|---|---|
| `question_id` | id | PK |
| `cycle_id` | fk → Survey Cycle | |
| `text` | string | |
| `answer_type` | enum | Declared type; predominantly binary (FR-012) |
| `is_custom` | bool | FR-054 |
| `author_actor_id` | string | Non-null when `is_custom` |
| `requires_authenticated_access` | bool | FR-107 — routes to human, never to an agent |
| `question_class` | string? | Optional; used for benchmark breakdowns (FR-096) |

**Rule**: `requires_authenticated_access` may not change mid-cycle (FR-111).

### Prior-Survey Link
| Field | Type | Notes |
|---|---|---|
| `link_id` | id | PK |
| `question_id`, `country_id` | fk | |
| `url` | url | |
| `origin_cycle_id`, `origin_session_id` | fk | FR-127 — age visible at reuse |
| `recorded_at` | timestamp | Compared against the max-age bound (FR-128) |

**Rule (FR-124)**: carries a link, never an answer. There is deliberately no `answer` column — the absence is the enforcement.

### MSQ Link Candidate
| Field | Type | Notes |
|---|---|---|
| `candidate_id` | id | PK |
| `submission_id` | fk | The MSQ submission it was extracted from |
| `question_id`, `country_id` | fk | |
| `url` | url | |
| `submitted_at` | timestamp | |

**Rule (FR-126)**: MSQ is read for links only. The reported *values* in a submission are never projected into an answer, so AIQ and MSQ remain two independent readings — which is what makes EKAP's cross-source comparison of them meaningful.

### Target Portal
| Field | Type | Notes |
|---|---|---|
| `portal_id` | id | PK |
| `cycle_id`, `country_id` | fk | Unique together |
| `resolved_url` | url? | Null when resolution failed |
| `supplying_source` | enum? | `msq` / `historical` / `search` (FR-006) |
| `resolution_history` | list[ResolutionAttempt] | Ordered; includes rejected candidates and reasons (FR-005, FR-006) |
| `detected_language` | string? | FR-015 |
| `language_in_supported_set` | bool? | FR-016, FR-017 |

`ResolutionAttempt`: `source`, `order`, `returned`, `usable`, `rejection_reason`.

### Language Decision
| Field | Type | Notes |
|---|---|---|
| `decision_id` | id | PK |
| `portal_id`, `session_id` | fk | |
| `detected_language` | string | |
| `decision` | enum | `authorized` / `declined` / `expired` (FR-018, FR-019) |
| `decided_by_actor_id` | string? | Null when `expired` |
| `resolution_manner` | enum | `explicit` / `window_expired` |
| `decided_at` | timestamp | |

Does not block other units (FR-020) — it gates one portal only.

---

## Assessment records

### Assessor Agent Run
| Field | Type | Notes |
|---|---|---|
| `run_id` | id | PK |
| `session_id`, `question_id`, `portal_id` | fk | |
| `agent_index` | int | 0..N-1; identifies the configuration variant (R7) |
| `round_number` | int | 1 = first round; used by portal measures (FR-035) |
| `answer` | structured | Conforms to `question.answer_type` |
| `confidence` | int 0–100 | FR-013 — recorded before any cross-agent comparison |
| `justification` | text | |
| `evidence_artifact_id` | fk → Evidence Artifact | |
| `validation_retry_count` | int | Tracked separately from adjudication retries (FR-084) |
| `state` | enum | See agent run states below |
| `auth_boundary_observed` | bool | FR-108 |
| `auth_boundary_url` | url? | Non-null when above is true |
| `model_identity` | string | Provider + model + version (FR-116) |

**Agent run states**: `pending` → `assessing` → `assessed` → `validating` → `validated_pass` \| `validation_failed_retryable` → (retry) \| `validation_failed_terminal`.
Terminal = `validated_pass` or `validation_failed_terminal`. All others are non-terminal and are discarded on resume (FR-067b).

**Rule (FR-010, FR-079)**: no field on this record may be read into another agent's input for the same `(question_id, portal_id)` before all of the round's agents are terminal. Enforced by the closed input schema in [contracts/assessor-agent.md](./contracts/assessor-agent.md).

### Evidence Artifact
| Field | Type | Notes |
|---|---|---|
| `artifact_id` | id | PK |
| `resolved_url` | url | FR-021 |
| `capture_ref` | blob ref | Region-scoped visual capture |
| `element_reference` | composite | See below (R5) |
| `element_text` | text | As recorded at capture |
| `element_text_original_language` | text? | FR-026 — retained alongside any translation |
| `element_text_translation` | text? | FR-026 |
| `captured_at` | timestamp | FR-022 |
| `verified_at` | timestamp? | FR-091 — non-null only after successful verification |
| `verifiability_status` | enum | `unverified` / `verified` / `no_longer_verifiable` |

`element_reference`: `{ css_path, text_hash, sibling_index }` (R5).

**Rule (FR-025 vs FR-087 — the distinction the last clarification session had to split)**:
- Verified once, element later gone → `no_longer_verifiable`. Retained with both timestamps. Never deleted or regenerated. A valid point-in-time record.
- Never verified, element absent at validation time → **not** a point-in-time record. It is a quality failure (FR-087) and retries the agent.

The discriminator is solely whether `verified_at` is non-null. This is the single most error-prone rule in the model; it gets a dedicated test.

### Validation Result
| Field | Type | Notes |
|---|---|---|
| `validation_id` | id | PK |
| `run_id` | fk → Assessor Agent Run | Exactly one run (FR-079) |
| `session_id` | fk | |
| `quality_score` | numeric | FR-078 |
| `gaps` | list[string] | Specific gaps; fed to retry as addendum (FR-080) |
| `passed` | bool | Score ≥ configured threshold |
| `retry_number` | int | |
| `verification_outcome` | enum | `confirmed` / `element_absent` / `text_mismatch` / `target_unreachable` |
| `verification_attempts` | int | Bound per FR-088 |

**Rule (FR-088 / SC-020)**: `target_unreachable` must never be recorded as a quality failure, and `element_absent` must never be recorded as an unreachable target. These are separate columns' worth of meaning collapsed into one enum precisely so the pair is exhaustive and a third case cannot silently appear.

**Rule (FR-083)**: a Validation Result never mutates its run. It admits or triggers a retry.

### Adjudication Result
| Field | Type | Notes |
|---|---|---|
| `adjudication_id` | id | PK |
| `session_id`, `question_id`, `portal_id`, `round_number` | fk / int | |
| `input_run_ids` | list[fk] | Only `validated_pass` runs (FR-082) |
| `discrepancy_flagged` | bool | FR-028 |
| `flag_reason` | enum? | `answers_differ` / `confidence_delta` |
| `max_pairwise_confidence_delta` | int | |
| `consensus_answer` | structured? | Null when escalated (FR-033) |
| `consensus_confidence` | int 0–100? | FR-034 — separate from per-agent values, never overwrites them |
| *(no tier field)* | — | Named tiers removed (FR-041). Confidence is the number; the acceptance threshold (FR-134) is the only boundary. |

**Rule (FR-027, SC-016)**: adjudication requires ≥ 2 validated positions. Below that, the pair escalates; it is never adjudicated on one position.

### Discrepancy Case
| Field | Type | Notes |
|---|---|---|
| `case_id` | id | PK |
| `scope` | enum | `question` / `portal` |
| `session_id` | fk | |
| `question_id` / `portal_id` | fk | Per scope |
| `points_of_disagreement` | list[string] | Question scope; feeds the addendum (FR-030) |
| `retry_count` | int | |
| `addenda_issued` | list[text] | FR-031 — must not attribute a position to an identified agent |
| `differing_answer_rate` | float | Portal scope (FR-035) |
| `affirmative_rate_gap` | float | Portal scope |
| `thresholds_in_force` | json | FR-039 — recorded for audit |
| `outcome` | enum | `converged` / `escalated` / `flagged_for_review` |

### Escalation Queue Item
| Field | Type | Notes |
|---|---|---|
| `item_id` | id | PK |
| `session_id` | fk | |
| `reason` | enum | `unresolved_disagreement` / `portal_discrepancy` / `no_usable_url` / `unreachable_portal` / `unverifiable_target` / `requires_authenticated_access` / `language_declined` |
| `context` | json | All agent positions, rounds, validation history |
| `disposition` | structured? | Exactly one recorded, even under concurrent action (FR-049) |
| `disposed_by_actor_id` | string? | |
| `disposed_at` | timestamp? | |

**Rule (FR-049)**: concurrent disposition is resolved by a conditional write on `disposition IS NULL`. The loser is told the item is already resolved — not silently overwritten.

### Assessor Decision
| Field | Type | Notes |
|---|---|---|
| `decision_id` | id | PK |
| `session_id`, `question_id`, `portal_id` | fk | |
| `action` | enum | `approve` / `edit` / `reject_override` |
| `system_proposed_answer` | structured | Preserved unchanged (FR-046) |
| `delivered_answer` | structured | Human-supplied when edited or overridden |
| `rejection_reason` | text? | Required when `reject_override` (FR-047) |
| `actor_id` | string | FR-045 |
| `decided_at` | timestamp | |

**Rule (FR-052)**: a new immutable record per action. Never an update to a prior decision.

---

## Configuration and benchmark

### Configuration Snapshot
| Field | Type | Notes |
|---|---|---|
| `snapshot_id` | id | PK |
| `session_id` | fk | One per session |
| `values` | json | All 16 parameters — see [contracts/configuration.md](./contracts/configuration.md) |
| `captured_at` | timestamp | At session start |

**Rule (FR-075)**: retries read this snapshot, never live configuration. A mid-session `.env` change affects only subsequent sessions.

### Benchmark Set / Ground Truth Answer / Benchmark Run Result

| Entity | Key fields |
|---|---|
| **Benchmark Set** | `set_id`, `name`, `pairs[]`, `labelled_by_class` (bool) |
| **Ground Truth Answer** | `truth_id`, `set_id`, `question_id`, `portal_id`, `correct_answer`, `label_source`, `assigned_by`, `question_class?` |
| **Benchmark Run Result** | `result_id`, `session_id`, `config_snapshot_id`, `overall_accuracy`, `accuracy_by_class`, `accuracy_by_confidence_band`, `discrepancy_flag_rate`, `portal_measures`, `escalations_by_reason` |

**Rule (FR-094, SC-021)** — the hardest containment rule in the model: `Ground Truth Answer` is never joined into any projection reachable by an Assessor Agent, the Validator, or the Adjudicator. Implemented as a separate repository with no read path from `agents/`, so leakage is an import error at development time rather than a contamination discovered after a benchmark run.

**Rule (FR-097)**: accuracy is computed on `consensus_answer` before any Assessor Decision exists for the pair. Human dispositions never enter the figure.

---

## Observability

### Run Telemetry
Three record types, all keyed on `session_id` (FR-113):

| Record | Fields |
|---|---|
| **Stage Event** | `event_id`, `session_id`, `unit_ref`, `stage`, `started_at`, `ended_at`, `outcome` (FR-113, FR-114) |
| **Fetch Record** | `fetch_id`, `session_id`, `domain`, `caller_class` (`assessor_agent` \| `validator`), `requested_at`, `status` (FR-115) |
| **Cost Ledger Entry** | `entry_id`, `session_id`, `stage`, `agent_index?`, `model_identity`, `input_units`, `output_units`, `cost` (FR-116) |

**Rule (FR-117)**: no credential material, no ground truth. **Rule (FR-118)**: read-only; never an input to an assessment decision.

### Answer Export
| Field | Type | Notes |
|---|---|---|
| `export_id` | id | PK |
| `cycle_id` | fk | |
| `produced_at`, `produced_by_actor_id` | timestamp / string | FR-106 |
| `record_ids` | list | The set included (FR-106) |
| `exclusion_report` | list[{question_id, portal_id, reason}] | FR-104 |

Schema of the exported records: [contracts/export-schema.md](./contracts/export-schema.md).

---

## The unit state machine

A **unit** is one `(question_id, portal_id)` pair in one session. This is the only source of resumability truth (FR-065, R8).

```
                  ┌──────────────────────────────────────────────┐
                  │                                              │
  pending ──► resolving_url ──► resolved ──► assessing ──► adjudicating ──► delivered ●
      │             │                            │              │
      │             │                            │              └──► retrying ──┐
      │             │                            │                     │        │
      │             ▼                            ▼                     ▼        │
      │        unassessable ●              escalated ● ◄────────────────┘        │
      │                                          ▲                              │
      └──────────────────────────────────────────┴──────────────────────────────┘
                     (auth-gated, language declined, unreachable)
```

**Terminal states — exhaustively, there are three:**

| State | Reached when | Carries |
|---|---|---|
| `delivered` ● | Consensus answer produced (FR-034) | Answer, confidence (0–100), evidence |
| `escalated` ● | Any escalation reason (FR-109, FR-033, FR-082, FR-088, FR-019) | Reason + full context |
| `unassessable` ● | No usable URL from any source (FR-007) | Resolution history |

**There is no fourth exit.** This is the structural guarantee behind SC-009: a unit cannot leave the machine without either a delivered answer or a recorded reason. Verified by exhaustive enumeration during the post-design constitution re-check.

### Transitions with non-obvious rules

| From → To | Rule |
|---|---|
| `resolving_url` → `unassessable` | Only after every source in the configured chain has been consulted (FR-002) |
| `resolved` → `escalated` | Auth-gated (FR-109), language declined/expired (FR-019), or unreachable after bounded attempts (FR-071) |
| `assessing` → `adjudicating` | Only when **all** N agents for the round are terminal (FR-027) |
| `adjudicating` → `escalated` | Fewer than 2 `validated_pass` runs (FR-082, SC-016) |
| `adjudicating` → `retrying` | Discrepancy flagged and adjudication retry limit not reached (FR-030) |
| `retrying` → `escalated` | Disagreement persists at the adjudication retry limit (FR-033) |
| `delivered` → — | Terminal. Human review produces an Assessor Decision record; it does not move the unit. |

### Resume semantics (FR-067a, FR-067b)

On resume, for each non-terminal unit:

1. Read all Assessor Agent Runs for the current round.
2. **Retain** every run in a terminal state (`validated_pass`, `validation_failed_terminal`) with its Validation Results and retry counters.
3. **Discard** every non-terminal run — including a run with a completed assessment but incomplete validation (R8) — and re-run that agent from scratch.
4. Dispatch only agents with no terminal run for the round.
5. When all N are terminal, proceed to `adjudicating`.

Discarded partial output is never supplied to the Validator, the Adjudicator, or another agent (FR-067b).

The whole of this is a pure function `(unit_state, agent_run_states) → remaining_work` in `domain/`, testable with no browser, model, or network.

### Portal Measure Eligibility

Portal-level measures (FR-035) run over first-round positions. A custom question added mid-run counts **only if every Assessor Agent on that portal assessed it** (FR-058).

Because FR-067a retains partial agent sets across a resume, a unit can be `delivered` while still ineligible for portal measures. Storing eligibility as a flag would let it go stale at exactly the moment it matters. It is therefore a **derived predicate**:

```
eligible(unit) := count(distinct agent_index where round_number = 1
                        and state = 'validated_pass') == configured_agent_count
```

evaluated at measure time, not at unit completion. This is the FR-058 × FR-067a interaction noted in [plan.md](./plan.md).
