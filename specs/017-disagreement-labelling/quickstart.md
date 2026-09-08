# Quickstart: Validating Disagreement Labelling

**Feature Directory**: `specs/017-disagreement-labelling`
**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Research**: [research.md](./research.md)

Eleven scenarios. **Ten of the eleven run offline** — the deterministic pre-pass needs no model, and every classifier path is driven by an injected fake, following the `NoCallProvider` pattern already in `tests/unit/test_resolve_only.py`. Scenario 10 is the only one that spends money, and it is optional.

## Prerequisites

```bash
pip install -e ".[dev]"
pytest -q                       # baseline: everything green BEFORE any change
```

The baseline matters for a specific reason here. This feature's central claim is that the numeric path is unchanged (SC-002), and the cheapest proof is that `src/portal/discrepancy.py` never appears in the diff. Record the baseline so any movement in the existing discrepancy and reconciliation tests is visible immediately:

```bash
pytest tests/unit/test_portal_discrepancy.py tests/unit/test_assessor_completion.py -q
git diff --stat -- src/portal/discrepancy.py     # must stay empty for the whole feature
```

---

## Scenario 0 — The engine is untouched

*Covers D1, FR-DL-040 to FR-DL-047, SC-002*

```bash
pytest tests/unit/test_disagreement_labels_isolation.py -q
```

**Expect**

- `git diff -- src/portal/discrepancy.py` is empty.
- A unit assessed twice — once with labelling enabled and a working fake provider, once with `AIQ_DISAGREEMENT_LABELLING_ENABLED=false` — produces identical `discrepancy_cases`, `escalation_queue_items`, `reconciliation_rounds` and published answers. Compare the serialised rows, not summaries.
- A unit whose every dispute is `exhausted` opens the same automatic round, over the same disputed set, as one whose every dispute is labelled (FR-DL-047).
- `publication_readiness` output is byte-identical between the two (FR-DL-066).

---

## Scenario 1 — The pass runs once, at the second completion

*Covers FR-DL-006, FR-DL-007, FR-DL-008*

```bash
pytest tests/unit/test_labelling_dispatch.py -q
```

**Expect**

- Submissions alone create no pass. Assessor A completes: still none. Assessor B completes: exactly one `labelling_passes` row.
- Recompute the unit ten times, change the tolerance, close a reconciliation round, sign off, publish — still exactly one row (FR-DL-007).
- Amend a submission after the pass: no second pass, no new label, and the existing label rows are unchanged (FR-DL-053).
- A unit with no disagreements produces no pass at all.
- With `ai_runtime` unset, no pass row and **no attempt rows** — the unit is `never_labelled`, not `exhausted` (R6).

---

## Scenario 2 — The deterministic pre-pass, and no model call

*Covers FR-DL-030 to FR-DL-032, SC-009, R4*

```bash
pytest tests/unit/test_label_deterministic.py -q
```

Run with `NoCallProvider`, which fails the test if the model is invoked.

| A cites | B cites | Expect |
|---|---|---|
| `https://www.gov.br/x` | `https://gov.br/y` | same source → classifier reached |
| `https://gov.sg` | `https://e-services.gov.sg/a` | same source → classifier reached |
| `https://dvla.gov.uk` | `https://hmrc.gov.uk` | `DIFFERENT_SOURCES`, no model call |
| `https://mof.gov.ke` | *(nothing)* | `ONE_FOUND_NOTHING`, no model call |
| *(nothing)* | *(nothing)* | classifier reached |
| `not a url` | *(nothing)* | classifier reached — an unparseable URL is no evidence, so this is not `ONE_FOUND_NOTHING` |

**Also expect**: both deterministic labels record `established_by="deterministic"` and name no model (FR-DL-051).

---

## Scenario 3 — The classifier sees exactly what it should

*Covers FR-DL-036 to FR-DL-039, D3, D4*

```bash
pytest tests/unit/test_label_classifier_input.py -q
```

Use a capturing fake that records the rendered payload and returns a canned label.

**Expect**

- The payload contains the indicator text, two positions, and the interval. Nothing else.
- It contains no `role`, no `assessor_actor_id`, no `ai_suggested_answer`, no `Prefill` field. Assert on the serialised string, not on the object.
- Set a `Prefill` with a distinctive justification for the question; assert that string is absent from the payload (FR-DL-037).
- `src/portal/label_classifier.py` does not import `Prefill` — a stronger guarantee than not passing it.
- Swapping which assessor is A and which is B, with identical content, produces the **same** payload and the same `input_digest` (FR-DL-038).
- Position order follows content, not role: the position with the lexicographically smaller `(evidence_url, notes)` is always first.

---

## Scenario 4 — Only the four labels, and uncertainty is named

*Covers FR-DL-033 to FR-DL-035*

```bash
pytest tests/unit/test_label_classifier_output.py -q
```

**Expect**

- The response schema's enum is exactly the four classifier labels; `different_sources` and `one_found_nothing` are absent.
- A fake returning `"different_sources"` is rejected, nothing is stored, and one `labelling_attempts` row with `failure="schema_rejected"` is written.
- A fake returning malformed JSON, or a missing key, is likewise rejected and recorded.
- A fake returning `not_enough_notes` stores it as a substantive label — it is an answer, not a failure, and must not be conflated with `awaiting` (FR-DL-034).

---

## Scenario 5 — Three attempts, then a visible permanent state

*Covers FR-DL-057 to FR-DL-059, FR-DL-064*

```bash
pytest tests/unit/test_label_retry_exhaustion.py -q
```

**Expect**

- A provider that always raises produces one attempt row per run. After three runs: three attempt rows, no label, state `exhausted`.
- A fourth run makes **no** model call and writes no fourth attempt.
- `awaiting` and `exhausted` are distinct states and render as distinct strings.
- Amending a submission does **not** bring an exhausted dispute back into scope (FR-DL-059) — the deliberate divergence from the pre-clarification design.
- A provider that fails twice then succeeds produces two attempt rows and one label.
- `aiq label drain` completes a pass that was dispatched while the provider was down, without creating a pass row.

---

## Scenario 6 — Append-only, and provenance on every label

*Covers FR-DL-050 to FR-DL-056, SC-004*

```bash
pytest tests/unit/test_label_provenance.py -q
```

**Expect**

- Every label carries `established_by`, `input_digest`, `stated_reason`, `created_at`; classifier labels also carry `model_identity` and `prompt_version`.
- No `UPDATE` or `DELETE` statement exists against the three tables — assert by grepping the module, and by asserting row counts never decrease across a full lifecycle.
- Total model calls for a unit never exceed its dispute count, across viewing, recompute, amendment, reconciliation, sign-off and publication (SC-004). Count calls on the fake.
- Changing `LABEL_PROMPT_VERSION` changes the digest for identical submissions.

---

## Scenario 7 — Surfaces show labels, and assessors never do

*Covers FR-DL-060 to FR-DL-065, FR-DL-068, SC-003*

```bash
pytest tests/unit/test_label_surfaces.py -q
```

**Expect**

- `admin_escalations.html` renders a badge for each disputed indicator, with per-side observations against the correct side.
- `assessor_reconcile.html` and `assessor_unit.html`, rendered for the same unit, contain **no** badge string and no observation string (FR-DL-065).
- No rendered surface contains a word asserting which assessor was right — assert against a list of forbidden strings ("correct", "wrong", "should have") in label-adjacent markup (SC-003, FR-DL-063).
- A unit with a submission amended after labelling renders the badge plus the changed-since notice (FR-DL-068).
- Loading each admin page 50 times creates no rows and makes no model calls (FR-DL-045).

---

## Scenario 8 — The measures, and their base

*Covers FR-DL-070 to FR-DL-075, SC-006, SC-007*

```bash
pytest tests/unit/test_indicator_ambiguity.py -q
```

**Expect**

- An indicator disputed in eight units, six of them `DIFFERENT_JUDGEMENT`, ranks above one disputed in eight with six `ONE_BLOCKED`.
- `DIFFERENT_CONTENT` does not count toward the measure — the split that keeps portal volatility out of it (FR-DL-071).
- `units_measured` and `labelled_share` are present on every row, including when only part of the cycle is labelled (FR-DL-072, FR-DL-073).
- `indicator_ambiguity(cycle_id=X)` and `indicator_ambiguity()` return the per-project and cross-project views from the same code path (FR-DL-075).
- The `NOT_ENOUGH_NOTES` proportion is reportable for a cycle (FR-DL-074, SC-007).

---

## Scenario 9 — Parity, counts, and cost

*Covers FR-DL-080, FR-DL-081, FR-DL-090 to FR-DL-092*

```bash
pytest tests/unit/test_label_api_parity.py -q
```

**Expect**

- Completion declared through the API and through the portal produce identical pass and label rows, differing only in `dispatched_by`.
- The three read endpoints return the projection and write nothing.
- `cost_ledger_entries` gains rows with `stage="disagreement_labelling"` and `agent_index IS NULL`, distinguishable from prefill rows by stage alone (FR-DL-090).
- Deterministic labels add **no** ledger rows.
- `labelling_counts` reports a rising `awaiting` under a down provider and a rising `exhausted` after three runs (FR-DL-092).

---

## Scenario 10 — One live call (optional, costs money)

*Covers A5, and the only thing a fake cannot tell you*

```bash
export AIQ_DISAGREEMENT_LABEL_MODEL=gemini-2.5-flash-lite
aiq label drain --cycle <cycle_id> --limit 5
```

**Expect**

- Five disputes labelled, each with `model_identity` beginning `vertexai/`.
- Read the five `stated_reason` values against the notes. This is the only check that tells you whether the instruction distinguishes **Saw different things** from **Judged differently** in practice — the hardest call the classifier makes, and the one the ambiguity measure depends on ([spec.md](./spec.md) Known Limitations).
- Ledger cost for the five is recorded and plausible.

Run this before trusting any ambiguity ranking. A measure built on a classifier that cannot draw its central distinction is worse than no measure.

---

## Coverage map

| Requirement group | Scenario |
|---|---|
| Engine isolation, sign-off (FR-DL-040–047, 066) | 0 |
| Trigger and once-only (FR-DL-001–008, 053) | 1 |
| Deterministic pre-pass (FR-DL-030–032) | 2 |
| Classifier input boundary (FR-DL-036–039) | 3 |
| Label set and rejection (FR-DL-033–035) | 4 |
| Retry and exhaustion (FR-DL-057–059, 064) | 5 |
| Provenance and append-only (FR-DL-050–056) | 6 |
| Surfacing and assessor exclusion (FR-DL-060–065, 068) | 7 |
| Measures (FR-DL-070–075) | 8 |
| Parity, API, operability (FR-DL-080–081, 090–092) | 9 |
| Classifier quality in practice (A5) | 10 |
