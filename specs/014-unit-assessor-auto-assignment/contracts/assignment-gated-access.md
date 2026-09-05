# Contract: Assignment-Gated Access to the Assessor Workspace

**Feature**: [spec.md](../spec.md) · **Design**: [data-model.md](../data-model.md) · **Research**: [research.md](../research.md) R5, R11

Covers **FR-AC-001…005** and **FR-UA-007**. This is the change with the widest blast radius: seven portal routes, two API routers, two templates, and every test that opens a unit.

---

## 1. What is wrong today

[`assessor.py:54-61`](../../../src/portal/assessor.py#L54):

```python
@router.get("/assessor/{cycle_id}/{portal_id}", response_class=HTMLResponse)
def unit_form(request, cycle_id, portal_id,
              role: AssessorRole,              # <- supplied by the caller
              actor_id: str = "assessor-1",    # <- supplied by the caller, defaulted
              error: str | None = None):
```

Role arrives as a query parameter and identity as a defaulted one, so anyone can claim any role on any unit by editing the URL — and there is no assignment to check either against.

There is a sharper defect underneath. [`assessor_picker.html`](../../../src/portal/templates/assessor_picker.html) links to `?role=A` and `?role=B` with **no `actor_id` at all**, so both roles fall through to the `"assessor-1"` default: every submission made through the portal's own navigation is attributed to the same actor for A and for B. Unit-level assignment cannot be layered on top of that, because there is no identity for an assignment check to be about.

The same pattern repeats on submit ([:126-127](../../../src/portal/assessor.py#L126)), complete ([:206-207](../../../src/portal/assessor.py#L206)), and reconcile ([:265-266](../../../src/portal/assessor.py#L265)).

---

## 2. The rule

```
resolve_actor_role(r, cycle_id, portal_id, actor_id) -> AssessorRole | None
```

One function in `src/portal/assignment.py`, returning the role the actor holds on that unit per the current assignment, or `None`. Every route that opens or writes to a unit calls it and refuses on `None`.

| Rule | Requirement |
|---|---|
| Role is the function's return value; a `role` in the request is never used to determine it | **FR-AC-002**, D10 |
| `None` → refuse, disclosing no questionnaire content, submission, or evidence | **FR-AC-001**, **FR-AC-003** |
| A unit with only one role filled is not workable, so the unfilled role resolves to `None` for everyone | FR-UA-005, US2 §5 |
| There is no project-wide fallback: an unstaffed unit refuses everyone | **FR-UA-007** |
| Completion declaration resolves the role the same way | **FR-AC-005** |
| Role-scoped reads stay role-scoped — `latest_human_submission(..., role=...)` is unchanged | **FR-AC-004** |

**FR-AC-004 needs no new code and must acquire none.** Blindness is already a query shape ([assessor.py:82](../../../src/portal/assessor.py#L82)): each role reads only its own submissions, and exactly one route reads across roles — the reconciliation workspace, gated on an open round. This feature changes *who* holds a role, never *what a role can see*. The risk here is regression, not omission.

---

## 3. Portal routes

| Route | Change |
|---|---|
| `GET /assessor` (picker) | Rewritten — §4 |
| `GET /assessor/{cycle_id}/{portal_id}` | `role` parameter **removed**; `actor_id` becomes required (no default); role resolved from the assignment; `403` when unassigned |
| `POST .../question/{question_id}/submit` | `role` form field **removed**; role resolved; refuse when unassigned |
| `POST .../complete` | same; the `AssessorCompletion` is written with the resolved role and `actor_id` (FR-AC-005) |
| `GET .../reconcile` | same; the reconciliation redirect at [:78-82](../../../src/portal/assessor.py#L78) drops `role=` from its query string |
| `POST .../reconcile/{question_id}/joint` | same |

**Refusal shape**: `403` with a plain sentence — *"You are not assigned to this unit."* No unit name, no project name, no counts, no questionnaire (FR-AC-003).

`HumanAssessorSubmission.role` continues to carry the role and `assessor_actor_id` the actor — the entity is unchanged ([data-model.md](../data-model.md) §7). What changes is that both values are now derived rather than accepted.

---

## 4. Picker — `GET /assessor`

Today the picker lists every unit of every project with an "Open as A" and an "Open as B" button. Under unit-level assignment those buttons are meaningless: the role is not the viewer's to choose.

**New shape**: the viewer identifies themselves (`?actor_id=...`, defaulting to a chooser listing the roster), and the page lists only the units they are assigned to, each labelled with the role they hold there.

This makes User Story 2 scenario 4 — the same person as A on one unit and B on another — directly visible, and it removes the last surface that invited a caller to pick a role.

**Honest limitation, to be stated in the UI as well as here**: choosing an identity from a list is not authentication. Anyone can select anyone. Assumption A3 grants this explicitly, and the assessor-facing page should say so rather than imply a login.

---

## 5. API parity

Spec 012's Constitution Check established that neither surface may bypass a rule. Both human-facing API routers derive role through the same `resolve_actor_role`.

| Endpoint | Change |
|---|---|
| `POST` human submission ([human.py:60-84](../../../src/api/routers/human.py#L60)) | `actor_id` in the body is resolved against the assignment. `role` **stays in the schema** and is validated: if it contradicts the assignment, `409` naming the assigned role. Unassigned actor → `403`. |
| `GET` human answers ([human.py:118-179](../../../src/api/routers/human.py#L118)) | `role` query parameter is validated the same way — an assessor may read only their own role's answers on that unit (FR-AC-004) |
| `POST` completion ([completions.py:61-103](../../../src/api/routers/completions.py#L61)) | same validate-and-reject; the stored role is the resolved one (FR-AC-005) |
| Unit creation ([cycles.py:127](../../../src/api/routers/cycles.py#L127)) | routes through `create_units` (FR-IN-003) |

**Why validate rather than drop the field.** Removing `role` from the request bodies would break every existing client for no gain in enforcement — the derived value already wins either way. Validating surfaces a client's wrong assumption as a `409` instead of silently correcting it, which is the more useful failure.

---

## 6. Fallout to fix, not to work around

| Site | Why it breaks | Fix |
|---|---|---|
| [`seed_lifecycle_demo.py`](../../../src/portal/seed_lifecycle_demo.py) | writes `assessor_actor_id="demo-assessor-a"` / `"demo-assessor-b"` ([:124](../../../src/portal/seed_lifecycle_demo.py#L124), [:137](../../../src/portal/seed_lifecycle_demo.py#L137)) and `actor_id=f"demo-assessor-{role.lower()}"` ([:150](../../../src/portal/seed_lifecycle_demo.py#L150)) — strings unrelated to the emails at [:62-63](../../../src/portal/seed_lifecycle_demo.py#L62) | staff its units from the seeded mapping, then submit as the assigned assessors' real ids (A1) |
| [`seed.py`](../../../src/portal/seed.py) | creates portals directly | route through `create_units` |
| Every test that opens a unit with `?role=A` | the parameter is gone | assign the unit, then open as the assigned actor |
| `tests/independence/` | asserts the blind-read guarantee | must keep passing **unchanged** — if a test there needs editing, the change to role-scoped reads was wider than intended |

The `tests/independence/` line is the load-bearing one: it is the regression signal for FR-AC-004.

---

## 7. Contract tests

| Test | Asserts | Requirement |
|---|---|---|
| `test_assigned_assessor_opens_unit_in_assigned_role` | A-role assignee lands in role A without supplying it | FR-AC-002, US2 §1 |
| `test_role_in_request_cannot_override_the_assignment` | B-role assignee passing `role=A` is placed in B (portal) / gets `409` (API) | **FR-AC-002**, US2 §3 |
| `test_unassigned_actor_is_refused` | `403`, and the body contains no question text, submission, or evidence URL | **FR-AC-001**, **FR-AC-003**, SC-007 |
| `test_assessor_on_one_unit_cannot_open_a_sibling_unit` | same project, different unit, disjoint pair | US2 §2 |
| `test_same_person_holds_different_roles_on_different_units` | A on one, B on another, each opens correctly | FR-UA-004, US2 §4 |
| `test_unstaffed_unit_refuses_everyone` | including a person assigned elsewhere in the project — no project-wide fallback | **FR-UA-007**, SC-012 |
| `test_half_staffed_unit_is_not_workable` | one role filled; neither the filled role nor anyone else can assess | FR-UA-005, US2 §5 |
| `test_outgoing_assessor_loses_access_after_reassignment` | `403` after the override | US3 §7 |
| `test_incoming_assessor_sees_prior_submissions_for_the_role` | continues from them | **FR-MO-007**, SC-008 |
| `test_completion_declaration_requires_the_assigned_role` | unassigned actor cannot declare | **FR-AC-005** |
| `tests/independence/` (existing) | passes **unchanged** | **FR-AC-004** |
