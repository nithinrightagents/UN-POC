# Contract: Unit Assignment, Administrator Override, and Staffing Visibility

**Feature**: [spec.md](../spec.md) · **Design**: [data-model.md](../data-model.md) · **Research**: [research.md](../research.md) R2, R4, R8, R10, R12

Covers **FR-UA-001…011**, **FR-MO-001…009**, **FR-SV-001…003**. This is the administrator-facing half of the feature.

---

## 1. Routes removed

| Route | Why |
|---|---|
| `POST /admin/projects/{cycle_id}/assign-assessors` ([admin.py:692](../../../src/portal/admin.py#L692)) | The project-level pair is retired — FR-UA-006, D1 |
| `POST /admin/projects/{cycle_id}/unassign-assessors` ([admin.py:709](../../../src/portal/admin.py#L709)) | Same; unstaffing is now per unit — FR-MO-005 |

The `?assign_error=1` query parameter on `project_detail` ([admin.py:284](../../../src/portal/admin.py#L284)) goes with them.

---

## 2. Routes added

### `POST /admin/projects/{cycle_id}/units/{portal_id}/assessors`

The single override endpoint. Covers assign, replace, and clear (FR-MO-001, FR-MO-005).

**Form fields**

| Field | Values |
|---|---|
| `role` | `A` \| `B` |
| `assessor_id` | a roster `assessor_id`, or empty string to clear the role |
| `actor_id` | the acting administrator |

**Behaviour**

```
303 -> /admin/projects/{cycle_id}                       on success
303 -> /admin/projects/{cycle_id}?assign_error=duplicate    role would duplicate the other role
303 -> /admin/projects/{cycle_id}?assign_error=unknown      assessor_id not on the roster
404                                                     unknown project or unit
```

| Rule | Requirement |
|---|---|
| Writes with `source = ADMINISTRATOR`, `set_by_actor_id = actor_id`, `set_at = now` | FR-MO-001 |
| Refuses when the chosen assessor already holds the *other* role on this unit, with a stated reason | **FR-MO-004**, FR-UA-002 |
| Uses the **same validator** as mapping application — distinctness cannot differ between the two paths | FR-UA-002 ("whether ingested or manual") |
| Clearing sets the role to `None` and `ingest_defect = CLEARED_BY_ADMINISTRATOR` | FR-MO-005 |
| Affects exactly one `(cycle_id, portal_id)` row | FR-MO-001, FR-UA-011, SC-005 |
| Writes one `assignment_changes` row: previous id, new id, `source='administrator'`, actor, time | **FR-MO-008**, SC-009 |
| Read-modify-write inside `begin_immediate()` | edge case: two concurrent administrators |
| Never available while the project is unknown; **always** available otherwise, staffed or not, before or during assessment | FR-MO-001, D7 |

**Not guarded by the work-started freeze.** Reassigning an assessor mid-cycle is the explicit motivation for User Story 3, and unlike a unit or question change it does not alter the indicator set that `recompute_portal_discrepancy` and `AssessorCompletion.indicator_count_at_declaration` assume fixed. Overriding after work has begun changes nothing about the unit's completion status or discrepancy state (**FR-MO-009**) because it writes no submission — a property worth asserting in a test rather than assuming.

### `GET /admin/assessors`

The roster view (FR-DB-007). Lists every ingested assessor with display name, email, organisation, languages, and notes. Read-only: **no create, edit, deactivate, or delete** — assessor lifecycle management is out of scope by the spec's own Out of Scope section, and belongs with the real assessor database.

---

## 3. Routes changed

### `GET /admin/projects/{cycle_id}` — project detail

`_build_unit_rows` ([admin.py:81](../../../src/portal/admin.py#L81)) gains two keys per row, and the route gains one project-level value:

```python
unit_rows.append({
    ...,                      # existing: portal, msq, publication, discrepancy,
                              # reconciliation_state, badge_html, readiness, disputes_detail
    "assignment": assignment,     # UnitAssessorAssignment | None
    "staffing": staffing,         # {"is_staffed": bool, "reason": UnstaffedReason | None}
})
```

The project's assignments are loaded **once** before the loop and indexed by `portal_id`, and the roster once, so the per-unit cost is two dict lookups. `_build_unit_rows` is already the most expensive path in the admin surface — it walks submissions, comparison, discrepancy, reconciliation state, and readiness per unit — and this must not add queries to that loop.

`staffing_summary(r, cycle_id)` is passed to the template for the header count (FR-SV-002).

### `POST /admin/projects/{cycle_id}/units` and `.../units/bulk-add`

Two changes:

1. Call `create_units(...)` instead of `r.insert_portal(s)` (FR-IN-003).
2. **Drop the `unit_type` form field.** `unit_type` is derived from `cycle.project_type` — `"country"` for `NATIONAL_OSI`, `"city"` for `LOSI_CITY` — exactly as [`cycles.py:127-132`](../../../src/api/routers/cycles.py#L127) already does.

This is what enforces **FR-UA-009**. Today [`admin.py:661`](../../../src/portal/admin.py#L661) reads `unit_type` from the form with a `"country"` default, independent of the project's type, so a mixed project is currently constructible through the portal. Deriving rather than validating makes it unrepresentable. Existing tests that post `unit_type` keep passing — FastAPI ignores unexpected form fields.

### The fifteen guarded routes

`_blocked_if_locked` ([admin.py:56](../../../src/portal/admin.py#L56)) becomes `_blocked_if_work_started` (R4):

```python
def _blocked_if_work_started(r, cycle_id) -> RedirectResponse | None:
    """Units and questions freeze once assessment has actually begun --
    a mid-assessment unit/question change would silently skew
    recompute_portal_discrepancy() and
    AssessorCompletion.indicator_count_at_declaration, which both assume a
    fixed question set per unit."""
    if r.has_any_human_activity(session_id_for_cycle(cycle_id)):
        return RedirectResponse(f"/admin/projects/{cycle_id}?lock_error=1", status_code=303)
    return None
```

The **first parameter changes** from the already-fetched `SurveyCycle | None` to the `Repository`, because the new trigger is a query rather than a field read. Return type, redirect target, and `?lock_error=1` are unchanged, so each of the fifteen call sites changes in the name it calls and its first argument — and the eleven that currently pass `r.get_cycle(cycle_id)` drop that fetch entirely. `session_id_for_cycle` is an existing pure helper in [`portal/common.py`](../../../src/portal/common.py#L17), so the guard creates no session as a side effect. `SurveyCycle.status` is never set to `"locked"` again.

New repository method:

```python
def has_any_human_activity(self, session_id: str) -> bool:
    """True once any assessor has submitted or declared completion in this session."""
```

One `SELECT 1 ... LIMIT 1` against each of `human_assessor_submissions` and `assessor_completions`, both already indexed on `session_id` ([schema.py:306, 309](../../../src/shared/persistence/schema.py#L306)).

---

## 4. Template changes — `admin_project_detail.html`

| Block | Change |
|---|---|
| The "Assign Assessors / Assessors Assigned" card ([:130-176](../../../src/portal/templates/admin_project_detail.html#L130)) | **Replaced** by a staffing summary card: *"38 of 40 units staffed"*, with the unstaffed count linking to the unit table. No email inputs, no Assign & Lock button, no Unassign & Reopen button. |
| Unit table | Two new columns — Assessor A and Assessor B. Each cell shows the assigned person's display name and email, or an unstaffed marker with the reason in plain words (FR-SV-001). |
| Unit row actions | A per-role override control: a `<select>` of roster assessors showing name, email, and organisation (**FR-MO-003**), with an empty option to clear, posting to the override route. |
| Hidden `unit_type` inputs in the add-unit forms | **Deleted** (§3, FR-UA-009). |

Reasons render as sentences, not enum values: *"No entry in the assessor database for this unit."* / *"The assessor database names the same person for both roles."* / *"The assessor database names an assessor who is not on record."* / *"Only one role is named in the assessor database."* / *"Cleared by an administrator."*

Every view reads current state on each request, so a change is visible on the redirect that follows it (**FR-SV-003**) — there is no cache to invalidate.

---

## 5. Contract tests

| Test | Asserts | Requirement |
|---|---|---|
| `test_override_changes_only_the_targeted_unit` | sibling units in the same project unchanged | FR-MO-001, SC-005 |
| `test_override_in_one_project_leaves_the_same_unit_in_another_alone` | two projects, same country, one overridden | **FR-UA-011**, US3 §2 |
| `test_override_naming_same_person_for_both_roles_is_refused` | redirect with `assign_error=duplicate`, row unchanged | **FR-MO-004**, FR-UA-002 |
| `test_override_with_unknown_assessor_is_refused` | `assign_error=unknown` | FR-MO-001 |
| `test_clear_role_returns_unit_to_unstaffed` | `is_staffed` false, reason `CLEARED_BY_ADMINISTRATOR` | FR-MO-005 |
| `test_every_assignment_change_is_recorded` | one `assignment_changes` row per role write, with actor and time | **FR-MO-008**, SC-009 |
| `test_reassignment_preserves_submissions` | submit as A, reassign A, assert every submission still readable and unaltered | **FR-MO-006**, SC-008 |
| `test_reassignment_leaves_completion_and_discrepancy_unchanged` | snapshot before/after | **FR-MO-009**, US3 §8 |
| `test_project_view_reports_staffed_and_unstaffed_counts` | header count matches the rows | FR-SV-002 |
| `test_unstaffed_unit_shows_its_reason` | one test per `UnstaffedReason` | FR-SV-001, SC-003 |
| `test_added_unit_takes_project_type_classification` | LOSI project, added unit is `"city"`; national project, `"country"`; posting a contradicting `unit_type` has no effect | **FR-UA-009** |
| `test_work_started_freeze_replaces_the_assignment_lock` | units/questions editable while staffed but idle; frozen after the first submission | R4 |
| `test_no_project_level_assessor_route_remains` | both retired routes return 404/405 | FR-UA-006 |

`tests/unit/test_assessor_assignment.py` is rewritten wholesale: all four of its current tests assert the retired project-level behaviour (assign → `status == "locked"` → mutations blocked → unassign reopens), and two of them are the lock tests that R4 re-homes onto the work-started trigger.
