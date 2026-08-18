# Implementation Plan: Decoupled AI Prefill

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-08-18
**Status**: Phase 1 complete — design artifacts generated
**Branch**: `main` (see Notes)

## Summary

Most of what the spec describes already runs. The ordered cascade is built ([chain.py:35-83](../../src/shared/tools/linkresolution/chain.py#L35-L83)), the two assessors already run concurrently ([scheduler.py:301-303](../../src/orchestration/scheduler.py#L301-L303)), and each already passes its own validation retry loop. The work is not to build a pipeline — it is to change what the pipeline *does at its two exits*.

Today those exits are wrong in exactly two places, and both are places where the AI reaches into the human's side:

1. **On disagreement the pipeline escalates.** `run_adjudication_retry_loop` re-runs both agents up to a limit and then writes an `escalation_queue_items` row — a task in a person's queue ([scheduler.py:369-390](../../src/orchestration/scheduler.py#L369-L390)). This feature replaces that with a **resolver agent** that reads both positions and determines which is correct, and the run continues.
2. **At publication the AI answers.** `final_answer` falls back to the pipeline's consensus and then to a heuristic seed row when no human answered ([finalize.py:33-45](../../src/api/finalize.py#L33-L45)). Both branches are deleted, and what makes that safe is **mandatory completion**: an assessor must give an explicit yes or no on every indicator and explicitly declare their work complete before the unit can be published.

Around those two changes sit three smaller ones with real reach: a **second validation gate** over the resolved position, a **per-run spend cap** (nothing limits spend today — [cost_ledger.py](../../src/core/telemetry/cost_ledger.py) records and never enforces), and **wiring the assessor screen to the pipeline** instead of to the `agent_index == -1` heuristic rows it reads today ([assessor.py:52-56](../../src/portal/assessor.py#L52-L56)).

**Primary technical challenge**: this is a *subtraction* problem. Adding a feature to this codebase is easy; removing a terminal outcome from a state machine with an exhaustive-coverage assertion, and removing two branches from a shared publication chain, is where it bites. Five files hardcode the three-terminal set, one invariant test asserts it explicitly, and the demo seeds publish units that the new gate will start refusing. Each is enumerated in [research.md](./research.md) rather than left to be discovered.

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / runtime** | Python 3.11+, unchanged | existing `pyproject.toml` |
| **New dependencies** | **None.** The resolver uses the existing `ModelProvider`; everything else is stdlib + what is already declared | `pyproject.toml` |
| **New package** | `src/agents/resolver/` — `agent.py`, `node.py`, `schema.py`, following the existing `agents/*` shape | [research.md](./research.md) R5 |
| **New modules** | `src/agents/adjudicator/agreement.py` (pure `classify_agreement`), `src/orchestration/budget.py` (`RunBudget`) | [research.md](./research.md) R3, R7 |
| **Modified — pipeline** | `orchestration/scheduler.py` (exits rewritten), `shared/state/{entities,unit_state,reason_tags,resume}.py`, `review/unlock.py` | [data-model.md](./data-model.md) §3, §4 |
| **Modified — surfaces** | `portal/assessor.py`, `portal/admin.py`, `api/finalize.py`, `api/routers/{human,publication,assessments}.py`, `api/jobs.py`, templates `assessor_unit.html` + `admin_project_detail.html` | [contracts/](./contracts/) |
| **Modified — plumbing** | `shared/persistence/{schema,repositories}.py` (+2 tables, +6 methods), `shared/config/{settings,validation}.py` (+2 params), `portal/seed.py`, `review/seed_demo.py` | [data-model.md](./data-model.md) |
| **Unchanged (deliberately)** | `agents/adjudicator/agent.py`, `agents/assessor/**`, `agents/validator/**`, `shared/tools/linkresolution/**`, `portal/discrepancy.py`, `review/escalations.py`, `export/**`, `benchmark/**` | [research.md](./research.md) R3, R4 |
| **New configuration** | `prefill_confidence_gap_tolerance` (default 10), `prefill_run_budget` (default 0.0 = uncapped) | [data-model.md](./data-model.md) §7 |
| **Persistence** | Two new append-only tables — `prefills`, `assessor_completions`. `assessment_jobs` reused unchanged as the Prefill Run. `init_db` runs `CREATE TABLE IF NOT EXISTS` on every serve, so no migration tooling is needed | [data-model.md](./data-model.md) §1–2, [research.md](./research.md) R2, R12 |
| **Auth** | Nothing new. The two added endpoints sit under spec 007's existing router-level `X-API-Key` dependency | FR-PF-048 |
| **Testing** | `pytest` against temp-file SQLite with model calls stubbed — six new `tests/unit/test_prefill_*.py` / `test_agreement_and_resolver.py` / `test_assessor_completion.py`, plus extensions to `test_api_publication.py`. Scenarios 1–7 need no credentials and no network | [quickstart.md](./quickstart.md) |
| **Target scale** | Unchanged per indicator except on contested ones (+1 resolver call) and at the final gate (+1 validator call per indicator reaching it). The removed adjudication retry loop *saves* up to `adjudication_retry_limit × assessor_agent_count` calls per contested indicator | [research.md](./research.md) R4, R5, R6 |

**No unresolved NEEDS CLARIFICATION.** The `/speckit-clarify` session (2026-08-18) settled five spec-level questions; Phase 0 resolved the remaining implementation unknowns as R1–R12. Two of clarify's three Outstanding items are addressed below; the third (an absolute wall-clock target) is deliberately left to a measured baseline — [quickstart.md](./quickstart.md) scenario 8 records it.

### The three clarify Outstanding items

- **Absolute performance target** — still open, and correctly so. SC-005's comparative assertion is testable now; an absolute number guessed before a 111-indicator run has ever been timed would be fiction. Scenario 8 produces the baseline; `tasks.md` should record it once measured.
- **Concurrency of prefill runs** — resolved by R12: a prefill run *is* an `assessment_jobs` row, so spec 007's `max_concurrent_assessment_runs` cap and its per-unit partial unique index govern portal-triggered runs already. No new decision needed.
- **Migration of existing published records** — resolved by [contracts/completion-and-publication.md](./contracts/completion-and-publication.md) §7: no migration, deliberately. `publication_records` is append-only and the public surface reads the latest row, so a republish supersedes naturally. A backfill would be the codebase's only mutation of an audit table.

### Cross-spec supersessions made explicit

Three, all of which should be annotated in the superseded specs during implementation, following the "supersede the framing, not the file" convention specs 005 and 006 already use here:

| Superseded | By | Effect |
|---|---|---|
| `specs/007-headless-rest-api` FR-API-032, final term | FR-PF-005 | AI answers leave the publication precedence chain |
| `specs/007-headless-rest-api` FR-API-023 | FR-PF-047 | A no-suggestion question reports `PrefillReason`, not spec 004's blank-field reasons |
| `specs/001-ekap-aiq-assessment` FR-028 | FR-PF-025 | A confidence gap no longer blocks delivery; it reduces confidence and the agreed answer stands |

The third is the one most likely to be missed, because it is not stated as a supersession in the spec — it follows from FR-PF-025 and only becomes visible when you read `adjudicate()`'s FR-028 branch. [research.md](./research.md) R3 handles it by mapping `adjudicate()`'s output rather than editing it, so spec 001's function keeps its meaning and its tests.

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md`, as with specs 001, 003, 004, and 007. Following those plans' precedent, the design is gated against the spec's own non-negotiables and this codebase's tested invariants.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **The AI creates no human work** (FR-PF-002, SC-001) | No escalation, arbitration, or review item from an AI-side outcome | Every inbound edge to `UnitState.ESCALATED` is removed from `_ALLOWED`, so the `escalate()` closure that writes `escalation_queue_items` becomes unreachable from the pipeline. Not a convention — a transition-table fact | PASS |
| **The AI never answers** (FR-PF-003–005, SC-004) | No published answer without a human submission | Both AI branches deleted from the shared `final_answer`; both publishers import it, so neither can drift | PASS |
| **Exhaustive terminal coverage** (spec 001 SC-009) | Every unit leaves the machine with an answer or a recorded reason | Four terminals instead of three; `assert_exhaustive_terminal_coverage()` *gains* a reachability assertion for the three prefill terminals. Strictly stronger than today | PASS — with an amended test, see Risks |
| **Append-only persistence** (spec 001 FR-062) | No UPDATE/DELETE against audit tables | Both new tables are append-only. Completeness is *derived*, not stored, precisely so FR-PF-005e/005g need no mutation (R8). No existing table gains a new mutation path | PASS |
| **No silent resolution** (spec 001 FR-007/FR-033, spec 004 FR-BF-002) | Never invent an answer nobody gave | Strengthened: `final_answer`'s "never invents an answer" was previously untrue in exactly the AI-fallback case. `ResolverDecision.selected_run_id` must name a supplied position or be `undetermined`, making an arbitrary pick inexpressible | PASS |
| **Configuration externalized** (spec 001 FR-072–FR-075) | No operational constant hidden in code | Both new parameters go through `Settings` + `_ENV_MAP` + `validate_settings`, appearing in `aiq config show` like every other | PASS |
| **Blind A/B integrity** (spec 005, spec 007 FR-API-028/029) | No cross-role read | The prefill carries no role field and is identical for A and B (FR-PF-012), so it cannot leak a position. The new endpoints return no submissions at all — deliberately *no* `role` parameter, so no caller can assume a scoping that does not exist | PASS |
| **No credentials in stored records** (spec 001 FR-110) | Secrets must not reach the database or logs | Neither new setting is a secret; `as_dict()` masking is unaffected. No new credential path | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

```
src/
├── agents/
│   ├── resolver/                     # NEW package — settles answer disagreements
│   │   ├── __init__.py
│   │   ├── agent.py                  # ResolverAgent(provider=...)  — NO browser, by design
│   │   ├── node.py                   # resolve_disagreement(): stage_events + cost_ledger
│   │   └── schema.py                 # ResolverDecision (undetermined is first-class)
│   ├── adjudicator/
│   │   ├── agent.py                  # UNCHANGED — mechanical, still tested as-is (R3)
│   │   └── agreement.py              # NEW — classify_agreement(), pure, maps adjudicate()
│   └── prefill/heuristic.py          # kept for the demo seed; no longer read by any screen
│
├── orchestration/
│   ├── scheduler.py                  # MODIFIED — the two exits rewritten:
│   │                                 #   escalate() → prefill(); adjudication retry loop
│   │                                 #   bypassed; resolver + final gate added
│   ├── budget.py                     # NEW — RunBudget, checked in run_batch.bounded()
│   └── routers/retry_loops.py        # UNCHANGED — validation loop untouched;
│                                     #   _describe_disagreement reused by the resolver
│
├── shared/
│   ├── state/
│   │   ├── entities.py               # MODIFIED — +UnitState.NO_SUGGESTION, +PrefillReason,
│   │   │                             #   +Prefill/AssessorCompletion; EscalationReason frozen
│   │   ├── unit_state.py             # MODIFIED — ESCALATED edges removed, NO_SUGGESTION added,
│   │   │                             #   +reachability assertion
│   │   ├── reason_tags.py            # MODIFIED — +prefill_reason_tag(); reason_tag() untouched
│   │   └── resume.py                 # MODIFIED — terminal set imported, not re-listed
│   ├── config/
│   │   ├── settings.py               # MODIFIED — +2 params, +_ENV_MAP entries
│   │   └── validation.py             # MODIFIED — tolerance >= 0, budget >= 0.0
│   └── persistence/
│       ├── schema.py                 # MODIFIED — +prefills, +assessor_completions, +3 indexes
│       └── repositories.py           # MODIFIED — insert/latest prefill, list by run,
│                                     #   insert/latest completion, list completions
│
├── api/
│   ├── finalize.py                   # MODIFIED — 2 AI branches deleted;
│   │                                 #   +publication_readiness() (shared by both publishers)
│   ├── jobs.py                       # MODIFIED — NO_SUGGESTION counts as terminal
│   ├── schemas.py                    # MODIFIED — +prefill, completion, readiness models
│   └── routers/
│       ├── prefills.py               # NEW — GET .../prefills
│       ├── completions.py            # NEW — POST + GET .../completions
│       ├── human.py                  # MODIFIED — suggestion linkage from latest_prefill()
│       ├── publication.py            # MODIFIED — readiness gate before publishing
│       └── assessments.py            # MODIFIED — PrefillReason in results; terminal set
│
├── portal/
│   ├── assessor.py                   # MODIFIED — reads prefills; +completion action;
│   │                                 #   +progress indicator
│   ├── admin.py                      # MODIFIED — publish gated; terminal set widened
│   ├── seed.py                       # MODIFIED — writes prefills + completions
│   └── templates/
│       ├── assessor_unit.html        # MODIFIED — contested display, reasons, complete button
│       └── admin_project_detail.html # MODIFIED — readiness state, run summary
│
└── review/
    ├── seed_demo.py                  # MODIFIED — completions for published units
    └── unlock.py                     # MODIFIED — terminal set imported, not re-listed

tests/unit/
├── test_prefill_pipeline.py          # NEW — unattended run; the three §7 properties
├── test_prefill_reasons.py           # NEW — nine reasons × terminal pairing
├── test_agreement_and_resolver.py    # NEW — classification table + resolver invocation count
├── test_final_validation_gate.py     # NEW — gate always runs; no fallback past it
├── test_assessor_completion.py       # NEW — declaration, revision, indicator-added revert
├── test_prefill_reruns.py            # NEW — SC-010, SC-011
├── test_prefill_budget.py            # NEW — SC-015, incl. two concurrent same-cycle units
├── test_api_publication.py           # EXTENDED — gate + parity under the new chain
└── domain/test_unit_state.py         # AMENDED — four terminals + reachability (see Risks)
```

**What is explicitly NOT touched, and why that boundary matters:**

- **`agents/adjudicator/agent.py`** — the deterministic comparison keeps its exact behaviour and its test file. Every historical `adjudication_results` row therefore keeps its meaning on re-read (R3). This is the boundary that makes the FR-028 supersession safe.
- **`agents/assessor/**`, `agents/validator/**`** — how a position is formed and how it is validated are Out of Scope. The validator is *called* once more (R6), not changed.
- **`shared/tools/linkresolution/**`** — the cascade already satisfies FR-PF-014–016 exactly. Not one line changes; only what happens after it returns `None`.
- **`portal/discrepancy.py`, `review/escalations.py`** — the human A/B discrepancy path, its threshold, its cases, and its queue are untouched. This is the boundary the terminology decision (clarification #5) exists to protect.
- **`export/`, `benchmark/`** — no endpoint or run path touches them.

## Phase 0 — Research

Complete. See [research.md](./research.md). Twelve decisions, each with rationale and alternatives:

| # | Decision |
|---|---|
| R1 | Fourth terminal `no_suggestion`; `escalated` retained but edge-orphaned. Five hardcoded terminal triples must widen; one invariant test must be amended |
| R2 | New append-only `prefills` table — `units` is upserted and cannot hold run history or unreached indicators |
| R3 | `classify_agreement()` maps `adjudicate()`'s output; `adjudicate()` itself is not modified |
| R4 | The prefill path bypasses `run_adjudication_retry_loop` — both of its triggers are now settled elsewhere |
| R5 | The resolver is a new model-backed agent with no browser, so a third independent opinion is inexpressible |
| R6 | The final gate is a single `validator_node` call — the retry loop is per-agent and a resolved position has no agent |
| R7 | Per-run budget via an in-process accumulator; a `total_cost()` delta is wrong because a session spans concurrent units |
| R8 | Completion = declaration row **AND** derived coverage; the conjunction makes FR-PF-005e/005g free |
| R9 | Precedence and gate land once in the already-shared `api/finalize.py`, so SC-013 holds by construction |
| R10 | All three `agent_index == -1` readers move together, or SC-012's measure is corrupted |
| R11 | New `PrefillReason` enum; `EscalationReason` frozen so historical rows and spec 004 keep working |
| R12 | A prefill run *is* an `assessment_jobs` row; the per-reason summary is derived, never stored |

## Phase 1 — Design & Contracts

Complete.

- **[data-model.md](./data-model.md)** — the `prefills` and `assessor_completions` DDL with their validation rules, the revised `UnitState` transition table, the nine-member `PrefillReason` enum with its terminal pairing, `AgreementOutcome`/`ResolverDecision` as in-memory shapes, the two configuration parameters, four read projections, and the list of entities deliberately unchanged.
- **[contracts/prefill-pipeline.md](./contracts/prefill-pipeline.md)** — the pipeline as a diagram in which no arrow leaves into a human queue, `classify_agreement`'s decision table, the resolver's output contract and its three coercions to `undetermined`, the single-pass final gate, budget enforcement point by point, and the three properties every failure path must satisfy.
- **[contracts/completion-and-publication.md](./contracts/completion-and-publication.md)** — the precedence chain before and after, `publication_readiness`, the completion preconditions *in evaluation order*, the unchanged publish arithmetic and why its denominator now means something different, the assessor screen's obligations, and the seed-data consequence.
- **[contracts/rest-api-additions.md](./contracts/rest-api-additions.md)** — two new endpoints and three changed ones with full bodies, why the prefill endpoint deliberately takes no `role` parameter, two new error codes, and the FR-PF-042 parity checklist as a two-column table.
- **[quickstart.md](./quickstart.md)** — nine validation scenarios mapped to the six user stories and SC-001…015; scenarios 1–7 need no credentials and no network, scenario 8 is the single paid run and produces the missing performance baseline, scenario 9 covers the seeds.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Amending `test_exactly_three_terminal_states` is amending a spec 001 invariant test.** It is the visible artifact of SC-009 and the natural instinct on seeing it fail is to make it pass | A careless amendment could weaken the guarantee to "some terminal is reachable", which a delivery-only machine would satisfy | Sequence it as its own reviewable task with the *strengthened* assertion — the three prefill terminals must each be reachable from `PENDING`. The amended test is stronger than the original, and the commit message should say so. [research.md](./research.md) R1 |
| **Five files hardcode the three-terminal set** (`resume.py`, `unlock.py`, `admin.py`, `jobs.py`, `assessments.py`). Missing one produces a unit that is terminal to the state machine but non-terminal to a consumer | A missed site makes a `no_suggestion` unit look perpetually in-progress: resume would re-dispatch it, job progress would never reach 100%, results would report incomplete | All five are enumerated with line numbers in R1. Each should *import* `TERMINAL_UNIT_STATES` rather than re-list it, so a grep for the literal triple returns zero hits afterwards — that grep is the completion check |
| **The demo seeds publish units the new gate will refuse.** They write neither completions nor full both-role coverage, and they are outside the unit test suite | `aiq seed` + publish breaks after this change, discovered by a person clicking rather than by CI | [contracts/completion-and-publication.md](./contracts/completion-and-publication.md) §6 states the three seed obligations; [quickstart.md](./quickstart.md) scenario 9 exercises them explicitly. Worth a smoke test in CI, since it is the only path the suite does not cover |
| **Bypassing the adjudication retry loop changes `aiq run`, not only the portal.** `process_unit` is shared with the CLI | Anyone relying on `adjudication_retry_limit` sees it silently stop mattering; the CLI's escalation output disappears | R4 states the blast radius plainly. The setting should be documented as no longer governing any live path — and either deprecated with a warning or removed, not left to look active |
| **The final gate adds a validator call per indicator** on top of the resolver's per contested indicator | On a 111-indicator questionnaire that is +111 validator calls per unit — the feature's largest cost increase, arriving at the same time as unattended runs | The budget cap (R7) bounds it, and distinct `stage` labels (`final_validation`, `resolution`) make both increments separable in `by_stage_and_agent()`. Scenario 8 measures the real number before it is rolled out widely |
| **The resolver is a new model call on the contested path, with no ground truth for "correct"** | A resolver that systematically favours one position would bias every contested indicator, and nothing in the pipeline would notice | `agents/verify.py` and the benchmark harness already exist for exactly this shape of question. A resolver selection-rate check against `benchmark_run_results` belongs in `tasks.md` as an acceptance step, not as a later idea |
| **`assessment_jobs`'s startup sweep is single-process-correct only** (inherited from spec 007 R5) | With unattended runs now the normal case rather than the exception, a multi-worker deployment would fail healthy runs more often | Unchanged precondition, repeated here because this feature raises its exposure. `aiq serve` is single-process today ([cli.py:136](../../src/cli.py#L136), no `workers` argument) |

## Notes

- **Branch**: work continues on `main`, matching specs 001/003/004/007 — no `before_plan` git hook is configured (`.specify/extensions.yml` does not exist).
- **No setup script found**: `.specify/` contains only `feature.json`. There is no `scripts/`, no `templates/`, and no `memory/constitution.md`, so `FEATURE_SPEC`/`IMPL_PLAN`/`SPECS_DIR` were resolved from `.specify/feature.json` (`specs/008-decoupled-ai-prefill`) and the source tree was read directly — the same fallback specs 004 and 007 recorded.
- **Graphify skipped.** The CLI is installed, but running it would write a `graphify-out/` directory into the user's repository, and this feature's affected surface was established by targeted reads of the exact call sites. A structural map would not have surfaced the four findings that actually shaped this plan — the `answers_differ`/`confidence_delta` split inside `adjudicate()`, the shared `session_id` that breaks a `total_cost()` delta, the five hardcoded terminal triples, and the fact that `test_exactly_three_terminal_states` pins the set by literal — because all four are semantic, not structural. Same call specs 003, 004, and 007 made.

## Post-Design Constitution Re-check

Re-evaluated after [data-model.md](./data-model.md) and [contracts/](./contracts/) were written. All eight gates still PASS. Four are worth recording as *verified* rather than assumed:

- **"The AI creates no human work" is now structural, not procedural.** The check was whether FR-PF-002 depends on nobody calling `escalate()`. It does not: with every inbound edge to `ESCALATED` removed from `_ALLOWED`, a call would raise `IllegalTransitionError` before reaching `repo.insert_escalation`. The only remaining writer of `escalation_queue_items` is [discrepancy.py:118-131](../../src/portal/discrepancy.py#L118-L131) — the human A/B path, which is exactly where it belongs.
- **Append-only survives the completion feature**, which was the gate most at risk. FR-PF-005e ("reverts to incomplete") reads like it needs a mutation. It does not, because completeness is the conjunction of a declaration row and live coverage (R8) — a new indicator drops the coverage half with nothing written or deleted. Verified by checking that no design path calls an update or delete against either new table.
- **Blind A/B integrity was re-checked against the new endpoints specifically.** The prefill read returns no `role` parameter and no submissions, so there is no query shape that could merge roles. The completions read returns per-role *counts* and outstanding ids, never answers — deliberately, since a role's answers are exactly what the other role must not see.
- **"No silent resolution" got stronger, not weaker.** [finalize.py:17-19](../../src/api/finalize.py#L17-L19)'s docstring already claimed "never invents an answer nobody gave" while lines 33–45 did exactly that when no human had answered. Deleting those branches makes the docstring true. The claim should not be re-added as a comment celebrating the fix — it was always the stated contract.

Three design interactions worth recording for `tasks.md` sequencing:

1. **R1 (fourth terminal) must land before anything that writes a prefill.** `process_unit` cannot transition to `NO_SUGGESTION` until `_ALLOWED` permits it, and the five consumer sites will misreport in the window between. Sequence: enum + transition table + amended test + all five consumers as **one** task, then the pipeline rewrite. Splitting them leaves the tree in a state where a prefill run half-works, which is worse than either endpoint.
2. **R9 (precedence + gate) and R8 (completion) must land together, in that order within one change.** Deleting the AI fallbacks without the gate in place is the one genuinely dangerous intermediate state in this feature: published scores would silently switch to partial-coverage denominators — precisely the comparability failure D1 exists to prevent, arriving unannounced. The gate must be enforced before, or in the same commit as, the deletion.
3. **R10 (both prefill readers) is independent of everything else and can proceed in parallel**, but its two halves cannot be split. The display path and the submit path's suggestion linkage read the same lookup; moving only the display would record `ai_suggestion_accepted` against a suggestion the assessor never saw, corrupting SC-012's measure silently and retroactively.
