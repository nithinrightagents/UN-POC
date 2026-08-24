# Contract: The Badge, Project Tolerance, and Programmatic Parity

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](../spec.md) · **Research**: [research.md](../research.md) · **Data model**: [data-model.md](../data-model.md)

Covers FR-DR-040…045, FR-DR-060…066, FR-DR-070…071, SC-004, SC-009, SC-010.

---

## 1. The badge

### What exists today

[admin_project_detail.html:367-385](../../../src/portal/templates/admin_project_detail.html#L367-L385) renders **two** states from a `compute_portal_discrepancy` result already passed into the template ([admin.py:143](../../../src/portal/admin.py#L143)):

```jinja
{% if row.discrepancy.outcome == "flagged_for_arbitration" %}
  <span class="badge badge--flag">… Flagged for Arbitration</span>
{% else %}
  <span class="badge badge--yes">… Within &le;5% Threshold</span>
{% endif %}
```

Two defects, both visible in those five lines:

1. **`≤5%` is hard-coded.** A project running at any other tolerance displays a figure that is not its tolerance — the exact failure FR-DR-043 forbids, and one that gets worse the moment tolerance becomes configurable.
2. **0% and 4% are the same badge.** Full consensus is indistinguishable from tolerated disagreement, so SC-004's at-a-glance requirement fails for the case a reviewer most wants to see.

### What it becomes

Five states, driven by `unit_reconciliation_state` (§7 of [data-model.md](../data-model.md)) rather than by `outcome`:

| State | Colour | Text | Icon |
|---|---|---|---|
| `full_consensus` | green | `Full consensus — 0%` | check |
| `within_tolerance` | amber | `{rate}% — within {tolerance}% tolerance` | check |
| `above_tolerance_in_progress` | red | `{rate}% — above {tolerance}%, assessment in progress` | alert |
| `reconciliation_open` | red | `{rate}% — reconciliation open` | alert |
| `persistent_discrepancy` | red | `{rate}% — reconciliation exhausted, awaiting Senior Reviewer` | alert |
| `awaiting_second_assessment` | neutral | `Awaiting second assessment` (no rate — FR-DR-044) | — |

Every state names the tolerance **in force for that project** (FR-DR-043) and shows the compared count (FR-DR-045), so a 100%-over-one-indicator unit is not read as a catastrophe. Colour is never the only signal — text and icon carry it too (FR-DR-042), which is also what keeps the zero-emoji and contrast gates satisfiable.

### The write-nothing guarantee

The route must keep calling `compute_portal_discrepancy`, never `recompute_` (FR-DR-007, FR-DR-040, SC-010). The read-only variant exists for exactly this and says so in its docstring ([discrepancy.py:51-55](../../../src/portal/discrepancy.py#L51)).

**There are two call sites, not one.** `project_detail` at [admin.py:143](../../../src/portal/admin.py#L143) and the publish route's re-render at [admin.py:335](../../../src/portal/admin.py#L335) build the same `unit_rows` structure by near-duplicated code. Both must produce the same five-state shape or the badge changes meaning when a publish is refused. The duplication is pre-existing; extracting the row-building into one helper is the cheap fix and makes the guarantee structural instead of remembered.

SC-010 is testable directly: count rows in `discrepancy_cases` and `escalation_queue_items`, load the project page fifty times, count again, assert unchanged.

---

## 2. Project tolerance

### Setting it

| | |
|---|---|
| Route | `POST /admin/projects/{cycle_id}/tolerance` |
| Fields | `tolerance` (percent, 0–100), `actor_id` (defaults to `senior-reviewer`, matching [admin.py:318](../../../src/portal/admin.py#L318)) |
| Validation | outside 0–100 → rejected, previous value stands (FR-DR-064) |
| Effect | writes `SurveyCycle.discrepancy_rate_threshold`, appends a `tolerance_changes` row with the previous value (FR-DR-066) |
| Restart | none. The value is read per comparison, not at startup (FR-DR-062) |

`0` is valid and means every disagreement flags (FR-DR-065). It must not be coerced to "unset" — the distinction between `None` (inherit) and `0.0` (tolerate nothing) is the entire reason the field is nullable.

### Reading it

One helper, `effective_tolerance(repo, cycle_id, settings)`: project value where set, else `settings.human_discrepancy_rate_threshold` (FR-DR-061).

**Six call sites currently pass the setting as a literal** and must migrate together — [assessor.py:189](../../../src/portal/assessor.py#L189), [admin.py:145](../../../src/portal/admin.py#L145), [admin.py:337](../../../src/portal/admin.py#L337), [human.py:98](../../../src/api/routers/human.py#L98), and [seed.py:153, :157](../../../src/portal/seed.py#L153). A half-migration judges a unit under one tolerance and displays it under another. After the change, a grep for `settings.human_discrepancy_rate_threshold` outside `effective_tolerance` returns zero hits; that grep is the completion check.

### Recording it

`thresholds_in_force` on each `DiscrepancyCase` already carries the tolerance the comparison was judged under ([discrepancy.py:67](../../../src/portal/discrepancy.py#L67)) — FR-DR-063 is satisfied by the existing engine and needs only to keep being satisfied. Historical cases keep reporting their own tolerance, not the project's current one.

### Isolation

SC-009 requires that changing one project's tolerance affects no other. This holds structurally — the value lives on the `SurveyCycle` — but it must be *tested*, because the natural regression is a helper that falls back to a module-level cached value shared across projects.

---

## 3. Programmatic parity

### Changed: the completion route

`api/routers/completions.py` gains the same recomputation call that `complete_unit` gains ([contracts/detection-and-rounds.md](./detection-and-rounds.md) §1). Without it, a unit assessed entirely through the API reaches mutual completion and **never opens a round** — the precise bypass FR-DR-070 forbids. The submission path already recomputes ([human.py:93](../../../src/api/routers/human.py#L93)); after this feature that is no longer the path that matters.

### New: `GET /cycles/{cycle_id}/units/{portal_id}/discrepancy`

Sits under the existing router-level `X-API-Key` dependency; no new auth (FR-DR-071).

```json
{
  "portal_id": "DK",
  "state": "reconciliation_open",
  "differing_answer_rate": 0.12,
  "compared_count": 25,
  "disputed_question_ids": ["PF-003", "PF-011", "PF-017"],
  "tolerance_in_force": 0.05,
  "rounds_consumed": 1,
  "automatic_round_used": true,
  "open_round_id": "rnd_…"
}
```

`state` is the same six-value vocabulary the badge uses, from the same function — so the API and the portal cannot disagree about a unit's state.

**No answers, from either role.** Disputed *identifiers*, never disputed *values*. Returning the two sides here would be the obvious convenience and would open a cross-role read on an unauthenticated-by-parameter endpoint. See [contracts/reconciliation-workspace.md](./reconciliation-workspace.md) §4.

`awaiting_second_assessment` returns `null` for the rate rather than `0.0`; zero means full consensus and the two must never be conflated (FR-DR-044).

### Parity checklist

| Behaviour | Portal | REST |
|---|---|---|
| recompute on submission | [assessor.py:184](../../../src/portal/assessor.py#L184) ✓ | [human.py:93](../../../src/api/routers/human.py#L93) ✓ |
| recompute on completion | **new** | **new** |
| completion gate before opening | shared — inside `recompute_portal_discrepancy` | shared |
| one automatic round per unit | shared — enforced by table + index | shared |
| tolerance resolution | shared — `effective_tolerance` | shared |
| state vocabulary | shared — `unit_reconciliation_state` | shared |

Every row after the first two is shared code rather than parallel implementations. That is deliberate: spec 008 established the parity guarantee by making both publishers call one `final_answer`, and the same discipline is what makes FR-DR-070 hold by construction instead of by review.

---

## 4. Seed obligations

[`seed_demo_data`](../../../src/portal/seed.py#L107) already recomputes twice and writes both completions. Once the completion gate lands, the **order** matters: the completions must be inserted *before* the final recomputation, or the seeded flagged unit records its disagreement without opening a round, and the demo shows a red badge with no reconciliation to enter.

Worth seeding deliberately, since nothing else in the tree constructs them: one unit at full consensus, one within tolerance, one with an open round, and one in persistent discrepancy. That is also the fixture the badge test and the workspace route test both need.
