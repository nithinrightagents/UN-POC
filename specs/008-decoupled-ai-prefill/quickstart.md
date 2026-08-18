# Quickstart: Validating Decoupled AI Prefill

**Feature Directory**: `specs/008-decoupled-ai-prefill`
**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

Nine scenarios. **Scenarios 1–7 need no credentials and no network** — they use a temp-file SQLite database with the pipeline's model calls stubbed, the same approach spec 007's suite takes. Only scenario 8 spends model budget. Scenario 9 is a data check against the live database.

## Prerequisites

```bash
pip install -e ".[dev]"
pytest -q                       # baseline: everything green BEFORE any change
```

The baseline run matters more than usual here. This feature amends a spec 001 invariant test ([research.md](./research.md) R1) and removes two branches from the shared publication chain (R9); a red baseline would make it impossible to tell an intended break from a regression.

---

## Scenario 1 — The run finishes alone and creates no human work

*Covers US2 · SC-001 · FR-PF-001, FR-PF-002*

```bash
pytest tests/unit/test_prefill_pipeline.py -k unattended -q
```

Build a unit whose indicators cover, at minimum: two agents agreeing, agreeing with a wide confidence gap, disagreeing and resolvable, disagreeing and unresolvable, no usable evidence, and one validated position only. Run it with every model call stubbed and no human interaction.

**Expect**

- The run reaches a terminal job state on its own.
- `count(escalation_queue_items)` created during the run is **0**.
- No unit the run touched is in `UnitState.ESCALATED`.
- `count(prefills WHERE run_id = R) == count(questions)`.

These are the three properties of [contracts/prefill-pipeline.md](./contracts/prefill-pipeline.md) §7. One fixture proves all of them for every reason at once.

---

## Scenario 2 — Every no-suggestion reason is distinguishable

*Covers US5 · SC-008, SC-007a · FR-PF-034, FR-PF-032a–d*

```bash
pytest tests/unit/test_prefill_reasons.py -q
```

Drive each of the nine `PrefillReason` members and assert, per indicator, the terminal state and reason pairing from [data-model.md](./data-model.md) §4.

**Expect**

- Nine distinct reasons, each with a non-generic rendered label from `prefill_reason_tag()`.
- `no_usable_evidence` — and only it — terminates `unassessable` (FR-PF-032b).
- Every other reason terminates `no_suggestion`.
- `prefill_reason_tag()` raises `KeyError` for an unmapped member, matching `reason_tag()`'s deliberate contract.

---

## Scenario 3 — Agreement, gaps, and the resolver

*Covers US4 · SC-006, SC-006a · FR-PF-023–029*

```bash
pytest tests/unit/test_agreement_and_resolver.py -q
```

`classify_agreement` is pure, so most of this is table-driven with no I/O at all.

**Expect**

| Input | Outcome | Resolver called |
|---|---|---|
| both yes, gap 2 | `uncontested`, answer yes | **no** |
| both yes, gap 30 | `agreed_with_gap`, answer **still yes**, confidence reduced | **no** |
| yes vs no | `disputed` → resolver selects → that answer | **yes, once** |
| yes vs no, resolver undetermined | no suggestion, `unresolved_disagreement` | yes, once |
| yes vs no, resolver names an unknown run | no suggestion, `unresolved_disagreement` | yes, once |
| one validated position | no suggestion, `insufficient_positions` | **no** |

Then assert across the whole run: the resolver call count equals the number of `answers_differ` indicators exactly (FR-PF-026a), and **every** indicator that produced a suggestion produced exactly one answer, never a list (SC-006a).

Also assert that `adjudicate()`'s own behaviour is unchanged — `tests/unit/test_adjudicator.py` must pass untouched ([research.md](./research.md) R3).

---

## Scenario 4 — The second gate, and no fallback past it

*Covers US5 · SC-007 · FR-PF-030–032*

```bash
pytest tests/unit/test_final_validation_gate.py -q
```

**Expect**

- The gate runs on `uncontested` positions too, not only resolver-settled ones (FR-PF-030).
- A failing gate produces `failed_final_validation` with no suggestion at any confidence.
- When the resolver picked position 1 and the gate rejects it, the result is **not** a fallback to position 2 (the spec's explicit edge case).
- The gate is a single validator call — assert the validator was invoked exactly once for the resolved position, proving no retry loop was entered (R6).

---

## Scenario 5 — Mandatory completion

*Covers US1 · SC-004b, SC-004c · FR-PF-005a–005h*

```bash
pytest tests/unit/test_assessor_completion.py -q
```

**Expect**

| Action | Result |
|---|---|
| Declare with 3 indicators unanswered | refused; the 3 `question_id`s are named |
| Answer all, do not declare | unit **not** publishable (SC-004c) |
| Answer all, declare | declaration records role, actor, timestamp |
| Revise an answer after declaring | still complete (FR-PF-005g) |
| Add an indicator after declaring | reverts to incomplete (FR-PF-005e) |
| Declare twice | both allowed; newest wins; no row mutated |

The last three are the conjunction of [research.md](./research.md) R8 doing its work — check that no code path updates or deletes an `assessor_completions` row.

---

## Scenario 6 — Publication is human-only and complete-only

*Covers SC-004, SC-004a, SC-013 · FR-PF-003–005, FR-PF-045*

```bash
pytest tests/unit/test_api_publication.py -q      # extended, not replaced
```

**Expect**

- A unit where every question has a prefill and no human answered: `final_answer` returns `None` for every question, and publish is refused. Nothing is published (SC-004).
- A published unit's `breakdown` has exactly `len(questions)` entries — the denominator is the full indicator set (SC-004a).
- Portal publish and API publish produce byte-identical `score` and `breakdown` for the same unit (SC-013).
- Publish refused before both roles declare, with `blocking_reason` naming the role.

The parity assertion is a regression guard, not the guarantee — both surfaces call the same shared functions ([research.md](./research.md) R9).

---

## Scenario 7 — Re-running, concurrency, and the budget

*Covers US6 · SC-010, SC-011, SC-015 · FR-PF-037–041e*

```bash
pytest tests/unit/test_prefill_reruns.py tests/unit/test_prefill_budget.py -q
```

**Re-run**: submit human answers, re-run generation, then assert every submission is unchanged in answer, evidence, notes, and attribution (SC-010), and that the newest completed run's prefills are what a read returns (FR-PF-039).

**Concurrent**: with a run in flight, submit an answer and assert it succeeds; open the unit and assert completed indicators show suggestions while the rest show empty ones (SC-011).

**Budget**: set `AIQ_PREFILL_RUN_BUDGET` to a value the third indicator will cross.

- The indicator in flight completes; no further indicator is dispatched (FR-PF-041a).
- Unreached indicators carry `budget_reached` prefills (FR-PF-041b).
- The job state is `completed`, not `failed`.
- `spend_reached` exceeds `budget_in_force` by at most the cost of the one in-flight indicator (SC-015).
- Re-running resumes exactly the unreached indicators (FR-PF-041e).
- `AIQ_PREFILL_RUN_BUDGET=0` runs uncapped, matching today's behaviour (FR-PF-041c).

The budget test must run **two concurrent units of the same cycle** — that is the case the naive `total_cost()` implementation gets wrong, since they share a `session_id` ([research.md](./research.md) R7).

---

## Scenario 8 — One real end-to-end run *(costs model budget)*

*Covers US1, US2, US3 · SC-005, SC-009 · FR-PF-014–018*

```bash
aiq serve
# → http://127.0.0.1:8080/admin — create a cycle, register a unit,
#   add ~5 indicators, click "Run AI Assessment"
```

**Expect**

- The run completes unattended. The admin escalation page gains nothing from it.
- The assessor screen shows the **pipeline's** suggestions, not heuristic rows — verify by checking a suggestion's justification is a real model output, and that `prefills` has rows for the run ([research.md](./research.md) R10).
- A contested indicator shows one suggestion plus the unselected position.
- `supplying_source` is the earliest usable source in the cascade order for every indicator, with no later source consulted after an earlier one succeeded (SC-009). `resolution_history` on the unit is the evidence.
- Parallel timing (SC-005): compare `stage_events` for the two assessor spans on one indicator — they overlap. Elapsed unit time is materially below the sum of the two.

Then, in the assessor screen: leave one indicator blank and try to complete — refused, naming it. Answer it, complete both roles, publish. The published score's denominator equals the indicator count.

Record the wall-clock time for the run. It is the measured baseline the spec's Outstanding item about an absolute performance target needs, and it should be written into `tasks.md` once known.

---

## Scenario 9 — Seed and demo data still work

*Covers [contracts/completion-and-publication.md](./contracts/completion-and-publication.md) §6*

```bash
rm -f ./data/quickstart.db
AIQ_DATABASE_PATH=./data/quickstart.db aiq seed
AIQ_DATABASE_PATH=./data/quickstart.db aiq serve
```

**Expect**

- Seeded units that were previously published are still publishable — meaning the seed now writes both roles' submissions for every question **and** an `assessor_completions` row per role.
- The seeded assessor screen shows suggestions, meaning the seed writes `prefills` rows rather than only `agent_index == -1` heuristic rows.

This scenario exists because the seeds are outside the unit test suite and are the most likely place for this feature to break something quietly.

---

## Full suite

```bash
pytest -q
```

Exactly one pre-existing test is expected to have **changed**, not merely still pass: `tests/unit/domain/test_unit_state.py::test_exactly_three_terminal_states`, amended to four terminals with a new reachability assertion ([research.md](./research.md) R1). Any other pre-existing failure is a regression.
