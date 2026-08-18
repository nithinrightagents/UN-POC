# Phase 0 Research: Decoupled AI Prefill

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-18

Twelve decisions. Each was an open implementation question after `/speckit-clarify`; none restates the spec. The recurring theme is that this feature's genuine work is **subtractive** — removing AI escalation, removing the AI from publication — and subtraction from a codebase with exhaustiveness assertions is riskier than addition, because the assertions are what break.

---

## R1 — A fourth terminal unit state, with `escalated` retained but unreachable

**Decision.** Add `UnitState.NO_SUGGESTION = "no_suggestion"` as a fourth terminal state. `UnitState.ESCALATED` stays in the enum and stays terminal, but every edge into it is removed from `_ALLOWED`, making it reachable only by historical rows. `TERMINAL_UNIT_STATES` becomes a four-member frozenset.

**Rationale.** FR-PF-032a fixes three outcomes for a prefill run and FR-PF-032b requires `unassessable` to keep its narrower "evidence could not be located" meaning, so the new outcome cannot be folded into either existing one. Deleting `ESCALATED` outright is not available: `data/aiq.db` holds units in that state, `review/seed_demo.py` writes six of them deliberately, and `shared/state/reason_tags.py:16` keys the whole spec 004 blank-field surface off it. Removing only its *inbound* edges satisfies FR-PF-032a's "unreachable from a prefill run" while leaving every historical row readable and every existing reason tag valid.

**What this breaks, deliberately.** [test_unit_state.py:22](../../tests/unit/domain/test_unit_state.py#L22) asserts the terminal set is exactly `{DELIVERED, ESCALATED, UNASSESSABLE}`. That assertion is spec 001 SC-009's test and it **must be amended** — the single most reviewable change in the feature, and it belongs in its own task. The amendment is not a weakening: `assert_exhaustive_terminal_coverage()` should *gain* a reachability check asserting each of the three prefill terminals is reachable from `PENDING`, which is what keeps FR-PF-032d meaningful once a terminal exists that nothing reaches.

**Every hardcoded terminal triple must be widened** — found by grep, all five:

| Site | Current | Needs |
|---|---|---|
| [resume.py:41](../../src/shared/state/resume.py#L41) | `in (DELIVERED, ESCALATED, UNASSESSABLE)` | + `NO_SUGGESTION` |
| [unlock.py:23](../../src/review/unlock.py#L23) | `_TERMINAL = {...}` | + `NO_SUGGESTION` |
| [admin.py:88](../../src/portal/admin.py#L88) | inline `terminal = {...}` | + `NO_SUGGESTION` |
| [jobs.py:86](../../src/api/jobs.py#L86) | progress derivation | + `NO_SUGGESTION` |
| [assessments.py:133](../../src/api/routers/assessments.py#L133) | results completeness | + `NO_SUGGESTION` |

Each should import `TERMINAL_UNIT_STATES` rather than re-listing members, so a fifth terminal never repeats this exercise. `reason_tags.py`'s `BLOCKED_UNIT_STATES` also gains it (R11).

**Alternatives considered.** *Reuse `UNASSESSABLE` for every no-suggestion outcome* — rejected by FR-PF-032b: it would silently reclassify existing rows. *Keep three terminals and carry "no suggestion" only on the prefill record* — rejected because `process_unit` must reach some terminal state, and the only remaining candidate is `ESCALATED`, whose `escalate()` closure writes an `escalation_queue_items` row that FR-PF-002 forbids. *Delete `ESCALATED`* — rejected as data-destructive.

---

## R2 — Prefills live in a new append-only table, not in `units.data`

**Decision.** New table `prefills`, one row per (run, question, unit), append-only. Reads take the newest row belonging to the newest *completed* run.

**Rationale.** Three requirements make `units.data` unusable. FR-PF-039 needs the most recent completed prefill when several runs exist — `units` is upserted ([repositories.py:169](../../src/shared/persistence/repositories.py#L169)) and keeps exactly one state per unit. FR-PF-033 requires a prefill record for indicators a run never dispatched, including budget-stopped ones (FR-PF-041b), which have no meaningful unit state to carry. FR-PF-041's per-reason summary needs to be groupable by run. A separate table gives all three and preserves spec 001 FR-062's append-only discipline, which `units` itself only escapes by documented exception.

**Alternatives.** *Extend `assessor_agent_runs` with a synthetic index* — rejected: that is exactly the `agent_index == -1` hack this feature exists to remove (R10). *Reuse `adjudication_results`* — rejected: it has no row for units that never reached adjudication, which is most no-suggestion cases.

---

## R3 — Agreement classification is a new pure module *over* `adjudicate()`, which is not modified

**Decision.** `adjudicate()` in [adjudicator/agent.py](../../src/agents/adjudicator/agent.py) stays byte-identical. A new pure function `classify_agreement(validated_runs, tolerance) -> AgreementOutcome` calls it and maps its `AdjudicationDecision` onto FR-PF-023–027's three outcomes.

**Rationale.** FR-PF-025 changes what a confidence gap *means*: today `flag_reason == "confidence_delta"` blocks delivery entirely (the FR-028 branch returns `consensus_answer=None`); under FR-PF-025 the agreed answer stands with a reduced confidence. That is a direct behavioural supersession of spec 001 FR-028. Editing `adjudicate()` in place would rewrite a deterministic function with its own test file ([test_adjudicator.py](../../tests/unit/test_adjudicator.py)) and would change what every historical `adjudication_results` row means on re-read. Mapping its output instead leaves the recorded audit trail's meaning stable and puts the new policy in one testable place.

The mapping:

| `AdjudicationDecision` | `AgreementOutcome.kind` | Answer | Resolver invoked |
|---|---|---|---|
| `discrepancy_flagged=False` | `uncontested` | `consensus_answer` | no (FR-PF-024) |
| `flag_reason="confidence_delta"` | `agreed_with_gap` | the agreed answer, re-derived from the positions | no (FR-PF-025) |
| `flag_reason="answers_differ"` | `disputed` | none yet | yes (FR-PF-026) |

`agreed_with_gap` must re-derive the answer itself, because `adjudicate()` deliberately returns `None` on that branch. Confidence is `compute_consensus_confidence()` minus a gap penalty, so FR-PF-025's "MUST reduce the prefill's confidence" is arithmetic, not a judgement call.

**Alternative.** *Add a `confidence_gap_blocks_delivery` flag to `adjudicate()`* — rejected: a boolean parameter that flips a decision table's semantics is the shape of change that makes the table untrustworthy to read.

---

## R4 — The prefill path bypasses `run_adjudication_retry_loop` entirely

**Decision.** `process_unit` no longer calls `run_adjudication_retry_loop`. It classifies agreement once (R3) and routes `disputed` to the resolver. `settings.adjudication_retry_limit` no longer governs any live path.

**Rationale.** The loop has exactly two triggers and this feature settles both differently. On `confidence_delta`, FR-PF-025 says the agreed answer "MUST still yield" — a retry re-runs both agents and can return different answers, so retrying would violate it. On `answers_differ`, FR-PF-026 assigns the outcome to the resolver. With both triggers reassigned the loop is unreachable by construction; leaving the call site in place would spend up to `adjudication_retry_limit × assessor_agent_count` extra model calls before the resolver ever saw the dispute — precisely the cost the spec's "resolver adds a call only on contested indicators" assumption rules out.

**Blast radius, stated plainly.** `run_batch`/`process_unit` are shared with the CLI (`aiq run`), so this changes `aiq run` too, not only portal- and API-triggered runs. That is intended and consistent — after this feature there is one pipeline and its output is a prefill on every path. It belongs in the CLI help text and `README.md` rather than being discovered.

`run_adjudication_retry_loop` and `_describe_disagreement` stay in [retry_loops.py](../../src/orchestration/routers/retry_loops.py): `_describe_disagreement` is reused verbatim to build the resolver's input (it already describes *what* differs without revealing *who* said it — the same anonymisation the resolver wants), and the validation retry loop in that module is untouched and still strictly per-agent.

---

## R5 — The resolver is a new model-backed agent under `agents/resolver/`

**Decision.** New package `agents/resolver/` (`agent.py`, `node.py`, `schema.py`) following the existing `agents/*` shape: a `BaseAgent` subclass, a node function that records a `stage_events` row and a `cost_ledger` entry, and a structured output schema. It receives both validated positions with their evidence, justifications, and confidences, and returns a `ResolverDecision`: the disagreement characterization, the selected `run_id`, the reasoning, and a confidence.

**Rationale.** FR-PF-026 requires judgement ("determine which position is correct"), which `AdjudicatorAgent` explicitly is not — its docstring states it is "Mechanical, not a model call". Reusing that name would make the codebase claim two contradictory things. FR-PF-026a's invocation condition (`answers_differ` only) and the Out of Scope entry forbidding a third independent opinion both fall out of the interface: the agent is handed exactly two positions and must return one of their `run_id`s, so it has no way to invent a third answer.

**Failure is a first-class outcome.** FR-PF-026d requires "cannot determine" to be expressible, so the schema carries an explicit `undetermined` result rather than forcing a pick. A provider error, a timeout, and a returned `run_id` matching neither position all map to the same `unresolved_disagreement` reason — never to an arbitrary choice.

**Cost.** One call per contested indicator. The contested rate is observable today from `adjudication_results` rows with `flag_reason='answers_differ'`, so the added spend is measurable before rollout rather than estimated.

---

## R6 — The final gate is a single `ValidatorAgent` call, not the validation retry loop

**Decision.** FR-PF-030's second gate calls `validator_node` once against the resolved position. No retry, no addendum, no re-assessment.

**Rationale.** `run_validation_retry_loop` is defined per *agent* — FR-081, restated in its own docstring: "retrying agent_index never touches any other agent's run". A resolved position has no agent index; it is a selection between two positions that already passed that same validator. Retrying it would mean re-running an assessor, producing a third position and reopening the agreement question the resolver just closed. A single pass applies FR-PF-030's "same standard, as a position in its own right" exactly.

**On failure**, FR-PF-032 is explicit that there is no fallback to the rejected position and no reduced-confidence delivery — the indicator terminates `no_suggestion` with `failed_final_validation`. The spec's edge case about a resolver-selected position failing the gate is therefore a plain code path, not a special case.

**Cost.** One extra validator call per indicator that reaches the gate — the feature's largest unavoidable increase. It must be separable in the ledger from the resolver's, so the two node functions use distinct `stage` labels (`final_validation`, `resolution`).

---

## R7 — Per-run budget via an in-process accumulator, not a ledger query

**Decision.** A `RunBudget` object created per run, threaded through `run_batch` into `process_unit`, wrapping the `CostLedger`: every `record()` also increments a per-run total. `run_batch`'s `bounded()` checks it **before** acquiring a unit and, when exhausted, writes a `budget_reached` prefill and returns without dispatching.

**Rationale.** The obvious implementation — snapshot `total_cost()` at run start and subtract — is wrong here. `ensure_session()` returns one session per *cycle*, so two units of the same cycle running concurrently (the default `max_concurrent_assessment_runs` is 2) share a `session_id` and would each see the other's spend. Adding a `job_id` column to `cost_ledger_entries` would attribute correctly, but `init_db` only runs `CREATE TABLE IF NOT EXISTS`, so existing databases would never gain the column and the repo has no migration tooling. An in-process counter is exact, concurrent-safe, and needs no schema change.

Checking before dispatch rather than during gives FR-PF-041a's "the indicator in flight finishes" for free — there is no cancellation path to write, and no indicator can be left half-assessed.

**Alternative.** *Enforce inside `process_unit` at each model call* — rejected: it would abandon an indicator mid-assessment, which FR-PF-041a forbids.

**Setting.** `prefill_run_budget: float = 0.0`, where `0.0` means uncapped — matching FR-PF-041c and the existing `api_key: str = ""` convention for an unset value. `validate_settings` rejects negatives.

---

## R8 — Completion is a declaration row; completeness is *derived*

**Decision.** New append-only table `assessor_completions` (`session_id`, `cycle_id`, `portal_id`, `role`, `actor_id`, `declared_at`, `indicator_count_at_declaration`). A unit is complete for role R iff a declaration exists for (session, unit, R) **and** every question currently in the cycle has a latest submission from R.

**Rationale.** The conjunction is what makes FR-PF-005e and FR-PF-005g free rather than fiddly. Adding an indicator after a declaration (005e) drops the coverage half and the unit reverts to incomplete, with no row to update or delete. Revising an answer after declaring (005g) leaves both halves true and the unit stays complete. A stored `is_complete` boolean would need explicit invalidation on every indicator insert — a write path in `admin.py` and `api/routers/cycles.py` that is easy to add and easy to forget, and that would mutate an audit table to do it.

The declaration alone is not enough (clarification #2 is explicit that completion is never inferred from coverage), and coverage alone is not enough either — hence the conjunction, not either half.

**`indicator_count_at_declaration`** is audit only. It never decides completeness; the live question list does. It is what lets an operator see that a unit reverted because the questionnaire grew, rather than because someone deleted an answer.

---

## R9 — The precedence change lands once, in the already-shared `api/finalize.py`

**Decision.** Delete both AI branches from `final_answer()` ([finalize.py:33-45](../../src/api/finalize.py#L33-L45)). Add `publication_readiness(repo, session_id, cycle_id, portal_id)` returning per-role declaration status and the outstanding indicator list; both [admin.py](../../src/portal/admin.py)'s `publish_unit` and [publication.py](../../src/api/routers/publication.py)'s `publish_unit` call it and refuse when it is not ready.

**Rationale.** Spec 007 already extracted `final_answer` into a shared module precisely so the two publish paths could not drift (its R10). This feature inherits that property for free — SC-013's "identical score and breakdown" holds by construction rather than by a parity test, and the parity test becomes a regression guard instead of the guarantee.

**The denominator changes meaning, and that is the point.** [admin.py:224](../../src/portal/admin.py#L224) computes `score = affirmative / len(breakdown)` where `breakdown` holds only questions with a non-`None` final answer. Today partial coverage silently shrinks the denominator. With the gate in place `len(breakdown) == len(questions)` always, so the published score is a whole-questionnaire score by construction. Neither publisher's arithmetic changes — only what can reach it.

**Required roles: both A and B.** The precedence chain reads both, so both must declare. The live database holds 1073 submissions but only 2 publication records, all demo seed data — so [seed_demo.py](../../src/review/seed_demo.py) and [seed.py](../../src/portal/seed.py) must now write declarations for the units they publish, or the demo publishes will start refusing. That is a real task, not an incidental one.

---

## R10 — Both prefill readers move off `agent_index == -1` together

**Decision.** Add `Repository.latest_prefill(session_id, question_id, portal_id)`. Replace the `agent_index == -1` scan at [assessor.py:52-56](../../src/portal/assessor.py#L52-L56), [assessor.py:79-85](../../src/portal/assessor.py#L79-L85) (the submit path's suggestion linkage), and [human.py:71-76](../../src/api/routers/human.py#L71-L76) in one change.

**Rationale.** All three sites read heuristic seed rows, not the live pipeline — the gap the spec's assumptions call out. They must move together because `HumanAssessorSubmission.ai_suggested_answer` and `ai_suggestion_accepted` (FR-PF-011) are written by the submit paths from the same lookup the display path uses; moving only the display would record acceptance against a suggestion the assessor never saw, quietly corrupting SC-012's measure.

[heuristic.py](../../src/agents/prefill/heuristic.py) itself stays, still used by `portal/seed.py` for a fast free demo seed — but its rows are no longer read by any assessor-facing surface, so the seed must write `prefills` rows instead or the demo will show empty suggestions.

---

## R11 — `PrefillReason` is a new enum; `EscalationReason` is frozen, not extended

**Decision.** New `PrefillReason` enum in `shared/state/entities.py` with FR-PF-034's nine members. New `prefill_reason_tag()` in [reason_tags.py](../../src/shared/state/reason_tags.py) alongside the existing `reason_tag()`, which is left untouched.

**Rationale.** `reason_tag()` raises `KeyError` for any unknown value by deliberate design ("a future untagged reason must fail loudly in tests, not render a generic label live"). Adding members to `EscalationReason` would be safe only if every new one also got a template — but the deeper problem is naming: `budget_reached` and `insufficient_positions` are not escalations, and putting them there would re-couple the two concepts this feature separates. The existing enum keeps its seven members, so [test_reason_tags.py](../../tests/unit/test_reason_tags.py) and [test_blank_field_fallback.py](../../tests/unit/test_blank_field_fallback.py) keep passing against historical rows.

One overlap is real: FR-PF-018's `no_usable_evidence` terminates `unassessable`, the same terminal `EscalationReason.NO_USABLE_URL` produces today. Both must render, so `prefill_reason_tag()` handles the new taxonomy and `reason_tag()` continues to handle historical `escalation_reason` values — the reader picks by which field the record carries.

FR-PF-047's AI-results change is then a lookup swap in `api/routers/assessments.py`, not a re-derivation.

---

## R12 — A prefill run *is* a spec 007 `assessment_jobs` row; the summary is derived

**Decision.** Reuse `assessment_jobs` unchanged as the Prefill Run entity. FR-PF-041's per-reason summary is computed at read time by grouping the run's `prefills` rows, never stored.

**Rationale.** The table already carries which unit and cycle, when it ran, its progress, and its terminal state, with a partial unique index giving FR-PF-036's one-run-per-unit and the spec's "only one run proceeds, and both triggers report the same run" edge case for free. Deriving the summary follows the reasoning spec 007's R7 used for progress: a stored count can drift from the rows it counts, a derived one cannot, and it is monotonic by construction.

Two fields go into the job's `data` JSON rather than as columns: `budget_in_force` and `spend_reached` (FR-PF-041d). They are per-run scalars written once at terminal recording, so a JSON field is the right shape and needs no DDL change.

**Constraint inherited.** Spec 007's startup sweep is only correct single-process, and it fails every `running` job it finds. That precondition now also governs prefill runs. Nothing here makes it worse, but the risk table repeats it because this feature makes unattended runs the normal case rather than the exception.
