# Quickstart: Validating Unit-Level Assessor Assignment

**Feature Directory**: `specs/014-unit-assessor-auto-assignment`
**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md) · **Design**: [data-model.md](./data-model.md)

Nine scenarios. **Every one runs offline** — no credentials, no network, no model calls. Assignment is pure record-keeping over the human A/B path, which has no AI in it (spec Out of Scope: "Reintroducing AI-driven prefill or AI-driven assignment recommendation").

## Prerequisites

```bash
pip install -e ".[dev]"
pytest -q                       # baseline: everything green BEFORE any change
```

The baseline matters more than usual here. This feature deletes two routes, retires two entity fields, and removes a request parameter that four assessor routes and two API routers currently accept. Four tests in `tests/unit/test_assessor_assignment.py` assert the retired project-level behaviour outright and **are expected to go red** — recording which tests were green beforehand is what separates that intended breakage from a regression.

---

## Scenario 0 — The roster and mapping ingest, idempotently

*Covers FR-DB-001…005, FR-IN-001 · [contracts/assessor-source-and-ingestion.md](./contracts/assessor-source-and-ingestion.md) §1–2*

```bash
pytest tests/unit/test_assessor_source.py -q      # NEW FILE
```

**Expect**

- A fresh database ingests 24 assessors and 84 mapping entries (40 country, 40 city, 4 defect).
- Running ingestion a second time leaves both row counts unchanged (FR-DB-004).
- A mapping file with a duplicate `(unit_type, unit_code)` raises at load rather than silently keeping one.
- `list_source_assessors()` and `list_source_mapping()` are the **only** functions that read the JSON. Grep the tree: nothing else opens either file.

---

## Scenario 1 — A project's units arrive already staffed

*Covers **US1** · SC-001, SC-010 · FR-IN-002, FR-IN-003*

```bash
pytest tests/unit/test_unit_assignment.py -q      # NEW FILE
```

**Expect**

- Create a national project, add twelve mapped country units, supply **no assessor input at all** — all twelve come back staffed, each with its own pair (SC-001).
- The twelve pairs are not identical to one another: at least two distinct A-role assessors across the set. A single pair repeated everywhere would pass a naive assertion while reproducing exactly the behaviour this feature replaces.
- A thirteenth unit added afterwards is staffed on creation, not on the next page load (FR-IN-003, edge case "a unit added long after ingestion").
- A LOSI project's city units staff the same way from `unit_type = "city"` entries (FR-UA-010).
- Two different projects containing the same country both start from the same mapped pair (US1 §5).

---

## Scenario 2 — The platform substitutes nobody

*Covers **SC-004**, SC-013 · FR-IN-004, FR-DB-006*

```bash
pytest tests/unit/test_unit_assignment.py -k verbatim -q
```

**Expect**

- Every assigned `assessor_id` equals what the mapping names for that unit. Assert on the ids, not on "some assessor was assigned".
- Rewrite the roster's `languages`, `organisation`, and `notes` to nonsense, re-ingest, re-apply: **identical** assignments (FR-DB-006). These fields exist for FR-MO-003's override display and must not be reachable from the assignment path.
- Point the loader at a different `assessors.json` + mapping with the same unit coverage: the same units are staffed and the same units unstaffed for the same reasons — only the people differ (**SC-013**).

---

## Scenario 3 — Gaps and conflicts are visible, never silent

*Covers **US4** · SC-003 · FR-IN-005…009, FR-SV-001*

```bash
pytest tests/unit/test_unit_assignment.py -k unstaffed -q
```

**Expect**, one case per seeded defect entry:

| Unit | Reason reported | Roles assigned |
|---|---|---|
| covered by no entry | `no_mapping_entry` | none — **and no assignment row at all** ([research.md](./research.md) R9) |
| entry names one person twice | `duplicate_assessor` | **none** — not one role filled |
| entry names only role A | `incomplete_mapping_entry` | **none** |
| entry names an id not on the roster | `unknown_assessor` | **none** |
| entry for a unit no project contains | *(nothing — not visited)* | n/a, and no error, no log line |

The "none, not one" column is the assertion that matters: D8 forbids half-assignment, and the natural buggy implementation assigns A and then fails on B.

Then assign the unstaffed units by hand and confirm the already-staffed ones are byte-identical afterwards (US4 §5).

---

## Scenario 4 — Override changes one unit and only one unit

*Covers **US3** · SC-005, SC-006 · FR-MO-001…005, FR-UA-011*

```bash
pytest tests/unit/test_assessor_assignment.py -q   # REWRITTEN FILE
```

**Expect**

- Overriding role B on one unit leaves every sibling unit in the project unchanged.
- Two projects both containing Kenya: overriding one leaves the other's Kenya untouched (**FR-UA-011**, US3 §2).
- An override naming the unit's *other* assessor is refused with `assign_error=duplicate`, and the row is unchanged (FR-MO-004).
- An override naming an id not on the roster is refused with `assign_error=unknown`.
- Clearing a role returns the unit to unstaffed with `cleared_by_administrator` (FR-MO-005).
- Re-running mapping application after an override leaves the override in place (**FR-IN-010**, **SC-006**). This is the one guarantee that makes an external source of assignment tolerable.

---

## Scenario 5 — Reassignment preserves submitted work

*Covers **US3** · SC-008, SC-009 · FR-MO-006…009*

```bash
pytest tests/unit/test_assessor_assignment.py -k reassign -q
```

**Expect**

- Submit answers as the A-role assessor, reassign role A, then: every submission is still retrievable, unaltered, and still attributed to the person who made it. Nothing is deleted or reattributed (**FR-MO-006**).
- The incoming assessor opens the unit and sees those submissions as the role's prior work (**FR-MO-007**, SC-008).
- Completion status and discrepancy state are byte-identical before and after the reassignment, because no submission was written (**FR-MO-009**, US3 §8).
- `assignment_changes` holds one row per role write, carrying outgoing id, incoming id, acting administrator, and time — enough to reconstruct who held each role over which period (**FR-MO-008**, SC-009).

---

## Scenario 6 — Access follows the assignment, not the URL

*Covers **US2** · SC-007, SC-012 · FR-AC-001…003, FR-UA-005, FR-UA-007*

```bash
pytest tests/unit/test_assessor_access.py -q      # NEW FILE
pytest tests/independence -q                       # MUST stay green, unedited
```

**Expect**

- The A-role assignee opens the unit and is placed in role A **without supplying a role**.
- The B-role assignee passing `role=A` is still placed in B (portal) and gets `409` naming the assigned role (API) — **FR-AC-002**.
- An unassigned person gets `403`, and the response body contains no question text, no submission, and no evidence URL. Assert on the body, not just the status (**FR-AC-003**, SC-007).
- Kenya's A-role assessor is refused on Brazil in the same project (US2 §2).
- A half-staffed unit refuses everyone, including the assessor who holds its one filled role (FR-UA-005, US2 §5).
- An unstaffed unit refuses everyone, **including an assessor assigned to a different unit of the same project** — there is no project-wide fallback left (**FR-UA-007**, SC-012).
- The same person, A on one unit and B on another, opens each in the right role (US2 §4).
- Completion declaration is refused to anyone but the assigned holder of the declared role (**FR-AC-005**).

**`tests/independence/` must pass unedited.** It is the regression signal for FR-AC-004: this feature changes who holds a role, never what a role can see. If a test there needs changing, the blind-read boundary moved and it should not have.

---

## Scenario 7 — Migration of projects staffed the old way

*Covers **SC-011** · FR-UA-008*

```bash
pytest tests/integration/test_assignment_migration.py -q   # NEW FILE
```

**Expect**

- Seed a database at the old shape — a cycle whose stored `data` JSON carries `assessor_a_email` / `assessor_b_email`, with units and submitted answers — then start the app.
- Every unit of that project ends up with both roles assigned, `source = migration`.
- **Zero submissions are read or written.** Compare `human_assessor_submissions` row-for-row before and after; role attribution is untouched because it never left the submission row (SC-011).
- Emails with no roster match produce a roster record rather than an unstaffed unit — no in-flight work is orphaned.
- Starting the app a second time migrates nothing further (idempotent).
- **The trap**: a migration that reads the cycle through `get_cycle()` finds `None` for both emails and silently migrates nothing, because the reduced dataclass no longer declares those fields ([data-model.md](./data-model.md) §8). The test must start from a *stored* legacy blob, not from a constructed `SurveyCycle`, or it will pass against a broken migration.

---

## Scenario 8 — The lock is re-homed, not removed

*Covers [research.md](./research.md) R4 — the item `/speckit-clarify` deferred*

```bash
pytest tests/unit/test_assessor_assignment.py -k freeze -q
```

**Expect**

- A fully staffed project with no submissions yet: adding units, adding questions, retiring questions all still **work**. Under the old model, staffing the project locked it.
- After the first human submission on any unit: all fifteen guarded routes redirect with `?lock_error=1`.
- Overriding an assessor still works after work has started — the freeze covers units and questions, not staffing (User Story 3's mid-cycle replacement depends on this).
- No `SurveyCycle` anywhere reaches `status == "locked"`.

---

## Full-suite gate

```bash
pytest -q
ruff check src tests
graphify update .                # keep graphify-out/ current -- CLAUDE.md
```

Green means: no test outside the intended set changed behaviour, `tests/independence/` never needed editing, and `tests/contract/test_assessor_input.py` still holds. If `tests/independence/` went red at any point, stop — that is the blind-assessment guarantee, and no amount of assignment work is worth trading it.

## Manual walkthrough

```bash
python -m portal.webapp        # or the project's usual serve entry point
```

1. `/admin/assessors` — the ingested roster is listed, with no create or delete control.
2. Create a national project. `/admin/projects/{id}` reports *"N of 193 units staffed"*, and mapped units show their own pairs while the rest show *"No entry in the assessor database for this unit."*
3. There is **no** "Assign Assessors" card and no "Assign & Lock" button anywhere.
4. Override one unit's Assessor B from the unit row; the select shows each candidate's name, email, and organisation (FR-MO-003). Only that row changes.
5. `/assessor` asks who you are, then lists only your units and the role you hold on each — with a visible note that selecting an identity is not authentication (A3).
6. Open a unit you are not assigned to by editing the URL: refused, with nothing disclosed.
