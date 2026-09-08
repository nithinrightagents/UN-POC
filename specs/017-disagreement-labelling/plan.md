# Implementation Plan: Disagreement Labelling for Human Assessor Discrepancies

**Feature Directory**: `specs/017-disagreement-labelling`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-09-07
**Status**: Phase 1 complete — design artifacts generated
**Branch**: `phase-2-ai-implement`

## Summary

The boolean discrepancy engine is complete and correct. `_compare()` returns the disputed set, `recompute_portal_discrepancy` writes the case and opens the round, `compute_portal_discrepancy` is the read-only twin for display, and both completion declarations already call the engine. Nothing in this feature needs any of that to change.

What is missing is that a dispute is currently just a question id in a list. A Senior Reviewer opening the arbitration workspace sees "these two answers differ" for each of eleven indicators and has to read four blocks of free text per indicator to find out that eight of them are one assessor hitting a login wall. This feature attaches a label naming the relation between the two positions, and aggregates one of those labels per question across units to surface systematically ambiguous indicators — the aggregate is the durable output, and it has never been computable because disagreement is only ever counted per unit.

**The design's organising constraint is that this must be removable.** Three new tables, two new modules, no field added to any existing entity, and `src/portal/discrepancy.py` never appears in the diff. That last property is not a nicety: SC-002 asks for identical rates, flags, rounds, escalations and published answers with labelling unavailable, and an untouched engine file is the cheapest possible proof.

**Primary technical challenge**: the portal has no path that calls a model. Spec 013 removed the last one. The two completion handlers are synchronous, `ModelProvider.generate` is async, and a completion must not wait on a model. [research.md](./research.md) R3 resolves it against the `live_prefill.py` precedent — a `BackgroundTasks`-scheduled async runner with its own SQLite connection — but this is the part of the feature that is architecture rather than logic, and the part most likely to be got wrong by doing the obvious thing instead.

**Secondary, and easier to miss**: the spec said the pre-pass compares "registrable domain", which is wrong for government hosts in a way that produces confidently incorrect labels — `dvla.gov.uk` and `hmrc.gov.uk` share one. A3 and FR-DL-030 have been amended to compare normalised hosts instead, treating a subdomain as the same source as its parent. See R4.

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / runtime** | Python 3.11+, unchanged | existing `pyproject.toml` |
| **New dependencies** | **None.** FastAPI + Jinja2 + SQLite + the existing `google-genai` path | [research.md](./research.md) R4 |
| **New modules** | `src/portal/disagreement_labels.py` (pass, pre-pass, projection), `src/portal/label_classifier.py` (the model boundary) | [contracts/](./contracts/) |
| **Modified — portal** | `portal/assessor.py` (+2 params, +1 dispatch call), `portal/admin.py` (+2 routes, label rendering) | [contracts/labelling-pass.md](./contracts/labelling-pass.md) §1 |
| **Modified — api** | `api/routers/completions.py` (+2 params, +1 dispatch call), `api/routers/human.py` or a new labels router (+3 read endpoints) | [contracts/surfaces-and-measures.md](./contracts/surfaces-and-measures.md) §4 |
| **Modified — shared** | `shared/persistence/{schema,repositories}.py` (+3 tables, +5 indexes, +6 methods), `shared/state/entities.py` (+2 enums, +3 dataclasses), `shared/config/settings.py` (+3 settings) | [data-model.md](./data-model.md) |
| **Modified templates** | `admin_escalations.html`, `admin_project_detail.html`, +1 new ambiguity template | [contracts/surfaces-and-measures.md](./contracts/surfaces-and-measures.md) §1 |
| **Unchanged (deliberately)** | **`portal/discrepancy.py`**, `portal/reconciliation.py`, `api/finalize.py`, `agents/**`, `orchestration/**`, `core/llm_factory.py`, `assessor_reconcile.html`, `assessor_unit.html` | [research.md](./research.md) R1, R10 |
| **Model** | `gemini-2.5-flash-lite`, `temperature=0.0`, `response_schema` constrained to four enum values, one call per dispute over the same sole entry point | [contracts/classifier-contract.md](./contracts/classifier-contract.md) |
| **Concurrency / dispatch** | `BackgroundTasks` → async runner with its own connection, on the `live_prefill.py` precedent. Once-guard is a `UNIQUE` index, not a read-then-write check | R3, R5 |
| **Persistence** | Three new tables, all append-only, no status column, every state derived. `init_db` runs `CREATE TABLE IF NOT EXISTS` on every serve, so no migration tooling | [data-model.md](./data-model.md) §1–3 |
| **Auth** | Nothing new and nothing claimed. The Senior Reviewer / Administrator distinction is which route calls which query, and is presentational | FR-DL-067, spec Known Limitations |
| **Cost** | `CostLedger` with `stage="disagreement_labelling"`, `agent_index=None`. Deterministic labels cost nothing | R9, FR-DL-090 |
| **Testing** | `pytest` against temp-file SQLite. **Ten of eleven scenarios run offline** with injected fake providers; one optional live scenario | [quickstart.md](./quickstart.md) |
| **Target scale** | One model call per disagreement per unit, once. A 140-indicator unit with 11 disputes costs 11 flash-lite calls, of which the pre-pass typically removes a third | FR-DL-091, A8 |

**No unresolved NEEDS CLARIFICATION.** The `/speckit-clarify` session (2026-09-07) settled five spec-level questions; Phase 0 resolved the implementation unknowns as R1–R12.

### The clarify Deferred item

One, and it stays deferred: **no latency target for how soon a label appears after dispatch.** FR-DL-044 already guarantees labelling never delays a submission, and FR-DL-008 wants labels present by sign-off in the ordinary course — which, with a background task firing at the completion request, means seconds. Nothing user-facing depends on a number, and this follows the house precedent of deferring performance figures rather than inventing them.

### What changed between the spec and this plan

Two things, both recorded rather than absorbed:

| Spec says | Plan does | Why |
|---|---|---|
| Pre-pass compared "registrable domain" (A3, FR-DL-030) | normalised host with dot-boundary suffix matching | eTLD+1 makes every `.gov.uk` agency one source. **The spec has been amended to match** — A3 and FR-DL-030 now say normalised host. R4 |
| — | a `label-drain` CLI completes a dispatched-but-unfinished pass | FR-DL-007 forbids a *new* pass on a later event; finishing an existing one is not a new pass. R6 |

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md`, as with every preceding spec in this repository. Following that precedent, the design is gated against the spec's own non-negotiables and this codebase's tested invariants.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **AI is never a sign-off step** (D1, D8, user's standing constraint) | No model output may gate, divert or qualify a process outcome | The boolean comparison decides everything. FR-DL-047 keeps every dispute in the round regardless of label; FR-DL-066 keeps sign-off independent of labelling state, tested by byte-identical readiness output | PASS |
| **Assessor-vs-assessor, never assessor-vs-truth** (D3, FR-DL-037) | The classifier must not hold a position of its own | `label_classifier.py` does not import `Prefill`. Only `ai_suggestion_accepted` — a bare boolean — survives. Tested by asserting a distinctive prefill justification is absent from the rendered payload | PASS |
| **Display writes nothing** (FR-DL-045, spec 012 precedent) | A GET must not create rows or invoke a model | `unit_labelling_state` and `indicator_ambiguity` are pure reads. Dispatch is reachable only from the two completion handlers. The three API endpoints are reads | PASS |
| **Append-only audit** (spec 001 FR-062) | No UPDATE/DELETE against audit tables | Three append-only tables, no status column, all four states derived (R5). Attempts are rows, so the cap is a `COUNT(*)`. Tested by grep and by row counts never decreasing | PASS |
| **Blind A/B integrity** (spec 005) | Blindness is a query shape | This feature adds no assessor-facing surface at all. `assessor_reconcile.html` and `assessor_unit.html` do not appear in the diff, and a test renders both and asserts no label string appears | PASS |
| **Configuration externalized** (spec 001 FR-072–075) | No operational constant hidden in code | Model, temperature and enable flag are `AIQ_*` settings. `LABEL_PROMPT_VERSION` is deliberately *not* a setting — it identifies the instruction text and must change with it | PASS |
| **One model entry point** (llm_factory docstring) | No module imports `google.genai` directly | `label_classifier.py` takes a provider and calls `generate()`. `llm_factory.py` is unmodified, so the OICT-approval question stays an adapter swap | PASS |
| **Parity between portal and REST** (spec 007/008) | Neither surface may bypass a rule | Both completion handlers call the same `dispatch_labelling_pass` with the same arguments, differing only in `dispatched_by`. Tested against identical row output | PASS |
| **The numeric path is untouched** (SC-002) | Labelling cannot move a rate or a flag | `src/portal/discrepancy.py` is not in the diff. Scenario 0 asserts identical serialised rows across a labelled and an unlabelled run | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

```
src/
├── portal/
│   ├── discrepancy.py                # UNCHANGED — deliberately. _compare is imported
│   │                                 #   read-only, as admin.py and cycles.py already do
│   ├── disagreement_labels.py        # NEW — dispatch guard, deterministic pre-pass,
│   │                                 #   the async runner, unit_labelling_state,
│   │                                 #   labelling_counts, indicator_ambiguity
│   ├── label_classifier.py           # NEW — the model boundary: payload, digest,
│   │                                 #   response schema, parse-time validation.
│   │                                 #   Does not import Prefill
│   ├── assessor.py                   # MODIFIED — complete_unit gains Request +
│   │                                 #   BackgroundTasks and one dispatch call
│   ├── admin.py                      # MODIFIED — two ambiguity routes; escalations
│   │                                 #   and project-detail views read the projection
│   ├── reconciliation.py             # UNCHANGED
│   └── templates/
│       ├── admin_escalations.html    # MODIFIED — badge + observations per dispute
│       ├── admin_project_detail.html # MODIFIED — per-unit label composition
│       ├── admin_indicator_ambiguity.html   # NEW
│       ├── assessor_reconcile.html   # UNCHANGED — FR-DL-065
│       └── assessor_unit.html        # UNCHANGED — FR-DL-065
├── api/
│   ├── routers/completions.py        # MODIFIED — same two params, same dispatch call
│   ├── routers/labels.py             # NEW — three read-only endpoints
│   └── finalize.py                   # UNCHANGED — FR-DL-066
├── shared/
│   ├── state/entities.py             # MODIFIED — DisagreementLabel, SideObservation,
│   │                                 #   LabellingPass, DisagreementLabelRecord,
│   │                                 #   LabellingAttempt
│   ├── persistence/schema.py         # MODIFIED — 3 tables, 5 indexes
│   ├── persistence/repositories.py   # MODIFIED — 6 methods
│   └── config/settings.py            # MODIFIED — 3 settings + env mapping
├── core/llm_factory.py               # UNCHANGED
└── cli.py                            # MODIFIED — label-drain

tests/unit/
├── test_disagreement_labels_isolation.py   # NEW — Scenario 0
├── test_labelling_dispatch.py              # NEW — Scenario 1
├── test_label_deterministic.py             # NEW — Scenario 2
├── test_label_classifier_input.py          # NEW — Scenario 3
├── test_label_classifier_output.py         # NEW — Scenario 4
├── test_label_retry_exhaustion.py          # NEW — Scenario 5
├── test_label_provenance.py                # NEW — Scenario 6
├── test_label_surfaces.py                  # NEW — Scenario 7
├── test_indicator_ambiguity.py             # NEW — Scenario 8
└── test_label_api_parity.py                # NEW — Scenario 9
```

## Phase 0 — Research

Complete. Twelve findings in [research.md](./research.md).

The three that change the implementation's shape: **R1** (the engine is not modified, and the dispatch therefore does not live inside it), **R3** (the portal has no synchronous model path, and `BackgroundTasks` plus an own-connection async runner is the precedent-backed answer), **R5** (append-only forces three tables and a derived state model rather than a status column).

The one that changes the spec: **R4**, registrable domain.

## Phase 1 — Design & Contracts

Complete.

- [data-model.md](./data-model.md) — three tables, two enums, three dataclasses, the classifier payload and its digest, the deterministic rule, configuration, and the list of entities deliberately unchanged.
- [contracts/labelling-pass.md](./contracts/labelling-pass.md) — dispatch preconditions, the runner's per-dispute algorithm, the state projection, counts, the CLI, and seven prohibitions each backed by a test.
- [contracts/classifier-contract.md](./contracts/classifier-contract.md) — payload construction, ordering, digest, response schema, the four contractual properties of the instruction, cost recording, and testing without a provider.
- [contracts/surfaces-and-measures.md](./contracts/surfaces-and-measures.md) — where labels appear and where they must not, the four rendered states, the ambiguity measure and its base, parity, three read endpoints, and sign-off as a negative contract.
- [quickstart.md](./quickstart.md) — eleven scenarios with a requirement coverage map; ten offline.

## Risks

| Risk | Assessment |
|---|---|
| **~~The spec's "registrable domain" is wrong~~ — amended 2026-09-07** | eTLD+1 makes every UK government agency one source, so two assessors on genuinely different portals would have got a confident `DIFFERENT_SOURCES`. A3 and FR-DL-030 now specify normalised-host comparison with subdomain-as-same-source, and FR-DL-030 additionally requires the comparison to resolve toward *same source* when uncertain, so an unclear case costs a model call rather than producing a wrong label. Residual risk: none in the rule, some in the implementation — Scenario 2's table is the check. R4 |
| **`DIFFERENT_CONTENT` versus `DIFFERENT_JUDGEMENT` is the classifier's hardest call, and the measure depends on it** | Already named in the spec's Known Limitations. Mitigated by making `NOT_ENOUGH_NOTES` the required answer under uncertainty (FR-DL-034), which protects the measure at the cost of coverage. Quickstart Scenario 10 exists solely to check this against real notes before any ranking is trusted — no fake can tell you |
| **A background task is lost on process restart** | A pass dispatched but not run leaves disputes `awaiting`, visible in `labelling_counts` (FR-DL-092), and `label-drain` completes it. This is why R6's distinction between finishing a pass and dispatching a new one is load-bearing rather than pedantic |
| **The single-process guard makes `BackgroundTasks` safe today and would not survive multi-worker** | `webapp.py` already refuses to start with `WEB_CONCURRENCY > 1`, for the same class of reason. This feature inherits that constraint rather than adding one, but it does depend on it |
| **Notes reach the model provider verbatim** | Stated, not mitigated — A9 and Known Limitations, recorded for OICT review. FR-DL-039 closes the payload shape so the surface cannot widen without a spec change, and Scenario 3 tests the closure |
| **Labels acquire authority they were never given** | The whole point of D1 and FR-DL-063. The design's answer is structural: no assessor sees a label, no process path branches on one, and sign-off cannot reference one. The residual risk is human and belongs in how the workspace is introduced to reviewers, not in code |
| **Cross-cycle roll-up depends on `indicator_id` matching between editions** | `Question` is cycle-bound with no cross-edition identity (R11). Two cycles roll up only where `indicator_id` agrees. A pre-existing data-model limit; the measure states its base so a partial roll-up is visible rather than silently wrong |

## Notes

**On branch**: work continues on `phase-2-ai-implement`. No `before_plan` hook ran — `.specify/extensions.yml` does not exist — so no branch was created for this feature.

**On the engine's test coverage**: `src/portal/discrepancy.py` had no test file as of spec 012's research, and spec 012 added `tests/unit/test_portal_discrepancy.py` to close that. This feature depends on `_compare`'s exact return shape, so that file is the baseline to run before starting; the Prerequisites in [quickstart.md](./quickstart.md) say so.

**On what is deliberately not built**: an Administrator bulk re-attempt over exhausted disputes. The spec puts it in Known Limitations as an easy later addition, and nothing in this design would have to change to accommodate one — `label-drain` is already most of it, minus the decision to reset an exhausted dispute, which is a policy question rather than a mechanism.

## Post-Design Constitution Re-check

Re-evaluated after Phase 1. All nine gates still PASS. Three are stronger after design than they were before it:

- **AI is never a sign-off step** gained FR-DL-066 as a *negative contract with a test* — two units identical but for labelling state produce byte-identical readiness output. Before design, this rested on nothing referencing labels; now it rests on an assertion.
- **Assessor-vs-assessor** moved from a rule to a structural property: `label_classifier.py` does not import `Prefill`, so the leak the user corrected mid-specification cannot be reintroduced by someone adding a field without reading the spec.
- **The numeric path is untouched** became checkable by `git diff --stat -- src/portal/discrepancy.py`, which is a stronger statement than any test could make.

One gate is weaker than it reads and is recorded as such rather than claimed: **FR-DL-067's Senior Reviewer / Administrator boundary is presentational only.** The platform models exactly two roles, both assessors; there is no permission model to enforce a reviewer-side distinction. The spec says this in Known Limitations and Out of Scope excludes building one. The design does not pretend otherwise — the boundary is which route calls `indicator_ambiguity` with a `cycle_id` and which calls it without.
