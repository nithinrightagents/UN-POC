# Contract: The Reconciliation Workspace and the Blindness Boundary

**Feature Directory**: `specs/012-portal-discrepancy-reconciliation`
**Spec**: [spec.md](../spec.md) · **Research**: [research.md](../research.md)

Covers FR-DR-010…026, FR-DR-015, FR-DR-017, FR-DR-018, SC-003, SC-011.

---

## 1. Routes

| Route | Method | Purpose |
|---|---|---|
| `/assessor/{cycle_id}/{portal_id}/reconcile` | GET | the workspace, for one role |
| `/assessor/{cycle_id}/{portal_id}/reconcile/{question_id}/joint` | POST | commit one joint answer |

Both take `role` and `actor_id` the same way [`unit_form`](../../../src/portal/assessor.py#L52-L60) does. They are unauthenticated parameters — see §5.

`unit_form` itself gains a redirect: a unit whose `unit_reconciliation_state` is `reconciliation_open` sends both roles to `/reconcile` instead of rendering the questionnaire (FR-DR-010). A unit that is above tolerance in any *other* state renders the questionnaire exactly as today (FR-DR-008, FR-DR-035) — including a persistent-discrepancy unit, whose assessors are told the disagreement is with the Senior Reviewer and are not given a workspace.

---

## 2. What the workspace GET returns

```
Preconditions, in order:
  1. cycle and unit exist                      → else 404, as unit_form does
  2. an open round exists for this unit        → else refuse, redirect to the
                                                 questionnaire with an explanation
                                                                    FR-DR-014
Then, for the round's disputed set only:
  - the viewing role's own answer, labelled as theirs
  - the peer's answer, labelled as theirs      FR-DR-013
  - the existing joint answer, if one is already committed
  - the tolerance in force, the current rate, the compared count,
    and that this is the unit's only automatic round
                                               FR-DR-016
Indicators not in the disputed set:
  - shown as settled, not editable             FR-DR-012
  - the peer's answer for them is NOT returned FR-DR-017
```

Precondition 2 is refusal for *any* requester in *any* role, not a permission check. There is no unit-plus-role combination for which the workspace returns peer answers when no round is open.

**SC-003 is a shape assertion, not a count**: the response contains the disputed indicators, and its size is a function of the disagreement, never of the questionnaire's length. A 111-indicator unit with three disputes renders three.

---

## 3. What the joint-answer POST does

```
1. round open for this unit?                      → else refuse    FR-DR-014
2. question_id in this round's disputed set?      → else reject    FR-DR-023
3. justification present and non-empty?           → else reject,
   naming the field                                                FR-DR-021
4. insert (round_id, question_id) — unique        FR-DR-020, 022
       IntegrityError → the peer committed first. Show their
       answer as agreed; do not overwrite.
5. every disputed indicator now answered?
       → close the round per detection-and-rounds.md §4            FR-DR-026
6. redirect back to the workspace
```

Step 4's failure is a normal outcome, not an error. Both assessors working the same indicator simultaneously is expected in a two-person reconciliation, and the losing writer must see the committed answer rather than a stack trace or a silent overwrite.

Step 5 means a round can complete without both assessors acting (A4): if one assessor answers every disputed indicator, the peer opens the workspace to find everything settled and the round already closed.

---

## 4. The blindness boundary

The rule, stated as a property of routes rather than of requesters (FR-DR-015):

> Outside an open reconciliation round, **no route reads across roles at all.**

| Surface | Cross-role read? |
|---|---|
| `unit_form` (questionnaire) | no — queries `latest_human_submission(..., role)` scoped to the caller's role only ([assessor.py:75](../../../src/portal/assessor.py#L75)) |
| `GET /reconcile` | **yes, and only here** — restricted to the open round's disputed set |
| `POST .../joint` | writes only; returns no peer answer beyond the disputed indicator being settled |
| admin project detail | reads the *rate*, never either side's answers |
| `GET /human-answers` | no — role-scoped, asserted by [test_api_human_blindness.py](../../../tests/unit/test_api_human_blindness.py) |
| new `GET .../discrepancy` | no — rate, counts, state, and disputed **ids**; never answers |

That last row is the one most easily got wrong. FR-DR-071 asks for the unit's discrepancy state programmatically, and returning the disputed answers alongside the disputed identifiers would be the natural convenience. It would also be a cross-role read on an unauthenticated endpoint — a blindness hole opened by an endpoint nobody would think to check.

**The test that pins this** is an extension of `test_api_human_blindness.py`'s existing technique: assert on the raw response text that the peer's distinguishing notes and actor id do not appear. Applied to every route in the table above except `/reconcile`, that is SC-011 mechanised.

---

## 5. What this contract does not promise

Role and `actor_id` arrive as request parameters and are not authenticated ([assessor.py:57-58](../../../src/portal/assessor.py#L57)). Every rule above is therefore about **what a route is capable of returning**, never about verifying who asked (FR-DR-018).

Concretely: a person who can reach the portal can request the workspace as either role. What they cannot do — because no route implements it — is obtain the peer's answers for an indicator outside an open round's disputed set, in any role, by any request. That is the guarantee, and it is the whole guarantee.

This is recorded in the spec's Known Limitations rather than paper over it. Genuine enforcement needs an authentication and assessor-assignment model, which is a separate feature. Nothing in this contract should be described as access control.

---

## 6. Template obligations

The workspace template inherits three gates that already fail loudly ([research.md](../research.md) R11):

| Gate | Requirement |
|---|---|
| Zero emoji | use the existing SVG sprite (`#icon-alert-triangle`, `#icon-check`), never characters |
| WCAG 2.2 contrast | reuse existing `badge--*` tokens; five states are available among them without adding colours |
| Semantic landmarks | extend `base.html`, which supplies the skip link, `role="banner"`, `id="main-content"`, and `role="contentinfo"` |

**The route-list trap**: [`test_all_portal_routes_render_successfully`](../../../tests/unit/test_ui_quality_checks.py#L205) asserts HTTP 200 for every enumerated route, and its `seeded_client` fixture seeds one Assessor A submission, no Assessor B, and no round. Adding `/reconcile` to that list without changing the fixture asserts 200 on a route that is required to refuse. Either extend the fixture with a unit that has both roles, both completions, and an open round — which is worth having anyway, since nothing else in the suite constructs one — or assert the refusal as its own case. Decide it deliberately; the failure will present as a routing bug.

The reciprocal layout is per-role, so both roles' renderings must be exercised. A single-role test would pass while the peer-labelling in FR-DR-013 was inverted.
