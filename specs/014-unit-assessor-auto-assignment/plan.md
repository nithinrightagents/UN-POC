# Implementation Plan: Unit-Level Assessor Assignment

**Feature Directory**: `specs/014-unit-assessor-auto-assignment`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-09-05
**Status**: Phase 1 complete — design artifacts generated
**Branch**: `phase-1`

## Summary

A survey project today has exactly one pair of human assessors, typed in by hand, and that pair works every unit in it. This feature makes the pair a property of the **unit**, taken from an external assessor database that already records who covers what, with administrator override on top.

The persistence and portal scaffolding for per-unit work is entirely in place. `TargetPortal` is already the granularity for portal URL, MSQ upload, submissions, completion, discrepancy, reconciliation, and publication; `_build_unit_rows` ([admin.py:81](../../src/portal/admin.py#L81)) already aggregates per unit; role-scoped blind reads already work ([assessor.py:82](../../src/portal/assessor.py#L82)). Nothing in the assessment machinery needs to learn about units — it already thinks in them.

**Four things change, and one of them is much larger than it looks from the spec.**

1. **Four new tables and one new domain module.** An ingested roster, an ingested unit→pair mapping, a per-unit assignment, and an append-only change log. Verbatim application, validation, override, and access resolution all live in one new `src/portal/assignment.py`.
2. **Two admin routes are deleted and one is added.** `assign-assessors` / `unassign-assessors` ([admin.py:692](../../src/portal/admin.py#L692), [:709](../../src/portal/admin.py#L709)) go; a per-unit override route replaces them, alongside a read-only roster view.
3. **The project-level lock is re-homed.** `_blocked_if_locked` guards fifteen admin routes off `status == "locked"`, which only ever becomes true when an administrator names the project pair — the exact mechanism D11 retires. This was the item `/speckit-clarify` deferred, and [research.md](./research.md) R4 settles it: keep the guard, change its trigger from *"assessors have been named"* to *"assessment has actually begun"*, which is what the guard's own docstring says it is protecting.
4. **Access control moves from the request to the assignment**, and this is the large one.

**Primary technical challenge: there is no assessor identity to attach an assignment to.** [`assessor.py:59-60`](../../src/portal/assessor.py#L59) takes `role: AssessorRole` as a query parameter and `actor_id: str = "assessor-1"` as a *defaulted* one. Read the picker template alongside it and the consequence is concrete: [`assessor_picker.html`](../../src/portal/templates/assessor_picker.html) links to `?role=A` and `?role=B` with **no `actor_id` at all**, so both roles fall through to the default and every submission made through the portal's own navigation is attributed to `assessor-1` — for A and for B alike. FR-AC-001 ("only if they are that unit's assigned assessor") has nothing to check against until that is fixed, so the fix is not a refinement of access control, it is its precondition. It reaches seven portal routes, two API routers, two templates, both seed scripts, and every test that opens a unit.

Secondary, and easy to miss: **the migration must read raw JSON, not a `SurveyCycle`.** Retiring `assessor_a_email` / `assessor_b_email` from the dataclass is safe against stored data because `_coerce` only assigns keys present in the type hints ([serialization.py:47-49](../../src/shared/persistence/serialization.py#L47)) — but that same mechanism means a migration going through `get_cycle()` reads `None` for every legacy project and migrates nothing, silently, with no error. [data-model.md](./data-model.md) §8 and [quickstart.md](./quickstart.md) Scenario 7 both call this out because a test built from a constructed `SurveyCycle` would pass against the broken version.

## Technical Context

| Dimension | Decision | Source |
|---|---|---|
| **Language / runtime** | Python 3.11+, unchanged | `pyproject.toml` |
| **New dependencies** | **None.** FastAPI + Jinja2 + SQLite, as already present | `pyproject.toml` |
| **New modules** | `src/portal/assignment.py` (ingestion, verbatim application, validation, override, `resolve_actor_role`, `staffing_summary`), `src/shared/reference/assessors.py` (source loader) | [research.md](./research.md) R1, R3 |
| **New data files** | `data/reference/assessors.json`, `data/reference/unit_assessor_mapping.json` | [data-model.md](./data-model.md) §10 |
| **Modified — portal** | `portal/admin.py` (−2 routes, +2 routes, `_build_unit_rows` +2 keys, guard re-homed at 16 sites, `unit_type` derived), `portal/assessor.py` (role parameter removed from 5 routes, picker rewritten), `portal/webapp.py` (+2 lifespan steps), `portal/seed.py`, `portal/seed_lifecycle_demo.py` | [contracts/](./contracts/) |
| **Modified — API** | `api/routers/human.py`, `api/routers/completions.py` (validate-and-reject `role`), `api/routers/cycles.py` (unit creation through `create_units`) | [contracts/assignment-gated-access.md](./contracts/assignment-gated-access.md) §5 |
| **Modified — shared** | `shared/persistence/{schema,repositories}.py` (+4 tables, +4 indexes, +~9 methods, `delete_cycle` cascade), `shared/state/entities.py` (+4 entities, +2 enums, −2 fields) | [data-model.md](./data-model.md) |
| **New templates** | `admin_assessors.html` (read-only roster) | [contracts/unit-assignment-and-override.md](./contracts/unit-assignment-and-override.md) §2 |
| **Modified templates** | `admin_project_detail.html` (assign card → staffing card, +2 unit columns, +override control, −hidden `unit_type`), `assessor_picker.html` (role buttons → assigned-units list), `assessor_unit.html` (role no longer a form field) | [contracts/](./contracts/) |
| **Unchanged (deliberately)** | `portal/discrepancy.py`, `portal/reconciliation.py`, `portal/tolerance.py`, `agents/**`, `orchestration/**`, `export/**`, `benchmark/**`, `shared/state/unit_state.py` | see Project Structure |
| **New configuration** | **None.** No `Settings` parameter, no threshold, no toggle | — |
| **Persistence** | Four new tables. `init_db` runs `CREATE TABLE IF NOT EXISTS` on every serve ([schema.py:426](../../src/shared/persistence/schema.py#L426)), so no migration tooling — but one **data** migration runs as a startup sweep beside `sweep_interrupted_jobs` ([webapp.py:50](../../src/portal/webapp.py#L50)) | [data-model.md](./data-model.md) §8 |
| **Auth** | Nothing new, and nothing claimed. `actor_id` remains an unauthenticated request value; this feature checks *assignment*, not identity | spec A3, [research.md](./research.md) R5 |
| **Testing** | `pytest` against temp-file SQLite. **No model calls anywhere in this feature** — the human A/B path has no AI in it, so the whole suite is offline and free | [quickstart.md](./quickstart.md) |
| **Target scale** | 193 units per project at creation. Application does two index reads per `create_units` call, not two per unit; `_build_unit_rows` gains two dict lookups per unit and zero queries | [research.md](./research.md) R3, [contracts/unit-assignment-and-override.md](./contracts/unit-assignment-and-override.md) §3 |

**No unresolved NEEDS CLARIFICATION.** The `/speckit-clarify` session (2026-09-05) settled ten spec-level questions; Phase 0 resolved the implementation unknowns as R1–R12.

### The clarify Deferred item

One, and Phase 0 closes it: **`_blocked_if_locked` guards fifteen admin routes off the project-level lock that D11 retires.** The clarify pass correctly declined to answer it, because the choice is about how the codebase protects an invariant, not about what the feature is.

[research.md](./research.md) R4 resolves it by reading the guard's own docstring ([admin.py:56-64](../../src/portal/admin.py#L56)): units and questions freeze because a mid-assessment change *"would silently skew `recompute_portal_discrepancy()` and `AssessorCompletion.indicator_count_at_declaration`, which both assume a fixed question set per unit."* That reason is about assessment having started. Naming the pair was a proxy for it — one this feature removes. Substituting the real condition preserves the invariant exactly, and is strictly more accurate than what exists today, where a project locks the moment two emails are typed even though nobody has answered anything.

### What the spec's own history got wrong, and why it matters here

The spec reached its current form through four iterations, two of which encoded models this plan must **not** re-import. They are recorded in [checklists/requirements.md](./checklists/requirements.md) and worth restating, because both are natural things for an implementer to reintroduce:

| Discarded model | Why it must not come back |
|---|---|
| **A selection algorithm** — language matching, regional matching, capacity caps, load balancing | The portal makes no choice at all. FR-IN-004 and SC-004 are assertions that *nothing* selects. The roster's `languages` field survives only for FR-MO-003's override display, and [contracts/assessor-source-and-ingestion.md](./contracts/assessor-source-and-ingestion.md) §6 carries a test that assignment cannot read it |
| **Projects holding a mixture of country and city units** | Reasoned from what `admin.py:661` permits rather than from the survey model. FR-UA-009 forbids it — and this is the one spec constraint the code does **not** enforce today, which R12 fixes by deriving `unit_type` from `project_type` rather than accepting it as a form field |

A third correction shapes the scope directly: roster CRUD, a staffing dashboard, and an approval gate on ingested assignments were all cut on the user's explicit instruction ("Nothing else"). They are in the spec's Out of Scope section as decisions. `GET /admin/assessors` is a **read-only** list for FR-DB-007 and must not grow an edit control.

## Constitution Check

**No constitution file exists** at `.specify/memory/constitution.md`, as with specs 001, 003, 004, 007, 008, 012, and 013. Following those plans' precedent, the design is gated against the spec's own non-negotiables and this codebase's tested invariants.

| Gate | Requirement | How the design satisfies it | Status |
|---|---|---|---|
| **Blind A/B integrity** (spec 005; FR-AC-004) | Blindness is a query shape, not a UI toggle | No role-scoped read changes. `latest_human_submission(..., role=...)` is untouched, and the one cross-role route stays gated on an open reconciliation round. This feature changes *who holds a role*, never *what a role can see* — `tests/independence/` must pass **unedited**, and that is the stated regression signal | PASS |
| **Display writes nothing** (spec 012 FR-DR-007) | A GET must not create audit rows | Application happens at unit creation, never on read ([research.md](./research.md) R3). `staffing_summary` is derived from stored rows. The lazy-apply-on-view alternative was rejected on exactly this gate | PASS |
| **Append-only audit** (spec 001 FR-062) | No UPDATE/DELETE against audit tables | `assignment_changes` is append-only, on the `tolerance_changes` precedent. `unit_assessor_assignments` is a *lifecycle* table on the `reconciliation_rounds` precedent and is declared as such, not smuggled in. **No existing submission is read or written by any part of this feature**, migration included | PASS — with the classification stated, see Risks |
| **No silent under-staffing** (FR-IN-005…008, D8) | Never leave a unit looking ready with nobody responsible | Every failure mode leaves the unit **wholly** unstaffed with a stated reason, never half-assigned. The closed `UnstaffedReason` enum makes "unstaffed for no recorded reason" unrepresentable | PASS |
| **The platform substitutes nobody** (FR-IN-004, SC-004) | Assignment is transcription, not decision | One function applies the mapping, and it reads exactly two fields of the entry. Descriptive roster fields are unreachable from it, enforced by test | PASS |
| **Administrator intent is never overwritten** (FR-IN-010, SC-006) | An override survives everything the platform does | Application skips any role whose `source` is `ADMINISTRATOR`. Ingestion is a setup-time load with no recurring sync, so there is no second writer to contest it | PASS |
| **Exactly-one pairing under concurrency** (edge case) | A unit never ends up duplicated or half-applied | Both roles live in **one row**, so distinctness is a single-row invariant and a write is a read-modify-write under the existing [`begin_immediate()`](../../src/shared/persistence/repositories.py#L978). The app already refuses multi-worker ([webapp.py:38-45](../../src/portal/webapp.py#L38)) | PASS |
| **Parity between portal and REST** (spec 007/008/012) | Neither surface may bypass a rule | Every rule lands in `src/portal/assignment.py`: distinctness in one validator used by both the ingest and override paths, role derivation in one `resolve_actor_role` used by both surfaces, unit creation in one `create_units` used by all six sites. The surfaces differ only in which routes call them | PASS |
| **AI and human paths stay separate** (spec 008 clarification 5; spec 013) | The human A/B path must not be wired to the AI path | No file under `agents/`, `orchestration/`, or the prefill path is touched. Spec 013 removed AI prefill from the portal; this feature adds none back, including no assignment recommendation | PASS |
| **Configuration externalized** (spec 001 FR-072–075) | No operational constant hidden in code | Nothing configurable is introduced. Assessor data lives in `data/reference/`, alongside `un_member_states.json`, behind one loader module that is the replacement seam | PASS |

**Post-design re-evaluation**: see [Post-Design Constitution Re-check](#post-design-constitution-re-check).

## Project Structure

```
data/reference/
    un_member_states.json               unchanged
    assessors.json                      NEW -- 24 demonstration assessors
    unit_assessor_mapping.json          NEW -- 40 country + 40 city + 4 defect entries

src/shared/reference/
    countries.py                        unchanged -- the pattern assessors.py follows
    assessors.py                        NEW -- the replacement seam (R1)

src/shared/state/
    entities.py                         MOD -- +Assessor, +UnitAssessorMappingEntry,
                                               +RoleAssignment, +UnitAssessorAssignment,
                                               +AssignmentChange, +AssignmentSource,
                                               +UnstaffedReason;
                                               -SurveyCycle.assessor_a_email/_b_email

src/shared/persistence/
    schema.py                           MOD -- +4 tables, +4 indexes
    repositories.py                     MOD -- +~9 methods, delete_cycle cascade
    serialization.py                    unchanged -- nested dataclasses already coerce

src/portal/
    assignment.py                       NEW -- ingest, apply, validate, override,
                                               resolve_actor_role, staffing_summary
    admin.py                            MOD -- -2 routes, +2 routes, guard re-homed,
                                               unit_type derived, unit rows extended
    assessor.py                         MOD -- role derived on 5 routes, picker rewritten
    webapp.py                           MOD -- +ingest, +migration in the lifespan
    seed.py                             MOD -- units through create_units
    seed_lifecycle_demo.py              MOD -- submit as the assigned assessors
    discrepancy.py                      unchanged
    reconciliation.py                   unchanged
    tolerance.py                        unchanged
    templates/
        admin_assessors.html            NEW
        admin_project_detail.html       MOD
        assessor_picker.html            MOD
        assessor_unit.html              MOD

src/api/routers/
    human.py                            MOD -- role validated against the assignment
    completions.py                      MOD -- same
    cycles.py                           MOD -- units through create_units

tests/
    unit/test_assessor_source.py        NEW
    unit/test_unit_assignment.py        NEW
    unit/test_assessor_access.py        NEW
    unit/test_assessor_assignment.py    REWRITTEN -- all four current tests assert
                                                    the retired project-level model
    integration/test_assignment_migration.py  NEW
    independence/                       unchanged -- MUST stay green unedited
    contract/test_assessor_input.py     unchanged
```

Untouched by design: `agents/**`, `orchestration/**`, `export/**`, `benchmark/**`, `review/**`, `shared/state/unit_state.py`.

## Phase 0 — Research

Complete. [research.md](./research.md) records R1–R12 with decision, rationale, and rejected alternatives:

| | Question | Decision |
|---|---|---|
| R1 | Where the source data lives | Seeded JSON behind one loader module, ingested into two tables; the loader is the replacement seam |
| R2 | Shape of the assignment record | One row per unit holding both roles + a separate append-only change log |
| R3 | When the mapping is applied | At unit creation, through one `create_units` used by all six creation sites |
| **R4** | **What replaces the project lock** *(the deferred item)* | **Keep the guard, change its trigger to "assessment has begun"** |
| R5 | Deriving role and identity | `actor_id` only in the request; role from the assignment; API validates and rejects a contradiction |
| R6 | Migrating legacy projects | Startup sweep beside `sweep_interrupted_jobs`, reading the raw stored JSON |
| R7 | The mapping key | `(unit_type, country_id)` — computable from a `TargetPortal` with no lookup |
| R8 | Validation and reasons | One shared validator; a closed `UnstaffedReason` enum stored on the row |
| R9 | Uncovered units | No row at all; `no_mapping_entry` derived from absence |
| R10 | Seeded data | 24 assessors, 80 valid mapping entries, 4 deliberate defects |
| R11 | Portal / REST parity | Every rule in `assignment.py`, called by both surfaces |
| R12 | Enforcing single-type projects | Derive `unit_type` from `project_type`; drop the form field |

## Phase 1 — Design & Contracts

Complete.

- **[data-model.md](./data-model.md)** — four tables with full DDL, four entities and two enums, the invariants and where each is enforced, the concurrency argument, `SurveyCycle`'s reduction, why `HumanAssessorSubmission` is deliberately untouched, the migration procedure and its ordering trap, the `delete_cycle` cascade, and the seed data shape.
- **[contracts/assessor-source-and-ingestion.md](./contracts/assessor-source-and-ingestion.md)** — the loader, the idempotent startup ingest, `create_units`, the verbatim rule and its four refusals, `staffing_summary`, repository additions, eleven contract tests. Covers FR-DB-\*, FR-IN-\*.
- **[contracts/unit-assignment-and-override.md](./contracts/unit-assignment-and-override.md)** — routes removed and added, the override endpoint and its refusals, `_build_unit_rows`' two new keys, the re-homed guard, `unit_type` derivation, template changes, thirteen contract tests. Covers FR-UA-\*, FR-MO-\*, FR-SV-\*.
- **[contracts/assignment-gated-access.md](./contracts/assignment-gated-access.md)** — what is wrong today and why it is the precondition rather than a refinement, `resolve_actor_role`, the seven portal routes, the rewritten picker, API validate-and-reject, the fallout list, eleven contract tests. Covers FR-AC-\*, FR-UA-007.
- **[quickstart.md](./quickstart.md)** — nine offline validation scenarios mapped to user stories and success criteria, plus a manual walkthrough.

## Risks

| Risk | Assessment |
|---|---|
| **The identity change is wider than the spec suggests.** Removing `role` from the request touches 7 portal routes, 2 API routers, 2 templates, 2 seed scripts, and every test that opens a unit | Real, and the largest single source of churn. Mitigated by doing it as one change with one shared resolver rather than route by route, and by `tests/independence/` as the boundary alarm. The alternative — keeping `role` in the request and merely cross-checking it — was rejected because FR-AC-002 says role must be *derived*, and a cross-check leaves the old path alive for anything that forgets to call it |
| **`unit_assessor_assignments` is a mutable table in an append-only repository** | Declared, not hidden. It follows `reconciliation_rounds` (lifecycle) with `assignment_changes` (append-only) carrying the history, which is exactly the `tolerance_changes` pattern spec 012 established and had accepted. Reviewers should check the classification, not assume it |
| **The migration can fail silently.** Reading through `get_cycle()` returns `None` for both legacy emails once the fields are dropped, migrating nothing without error | Called out three times — [data-model.md](./data-model.md) §8, [quickstart.md](./quickstart.md) Scenario 7, and this plan's Summary — because the obvious test (build a `SurveyCycle`, migrate, assert) passes against the broken version. The test must start from a stored legacy blob |
| **The mapping key assumes one city per country** | True today: the platform derives exactly one city per country from `most_populous_city`. If the programme later assesses several cities per country, `(unit_type, country_id)` stops being unique and a real city code plus a city reference table becomes necessary. That is a change to the reference data and the key — assignment, override, and access control are unaffected. Recorded in [research.md](./research.md) R7 |
| **Nothing authenticates `actor_id`** | Unchanged from today and out of scope by A3, but the stakes rise: access control now *depends* on identity where before it depended on nothing. Anyone who knows an assessor's identifier can present it. The assessor picker must say so plainly rather than implying a login. This is a limitation to disclose, not a defect to hide |
| **`create_project` staffs 193 units in one request** | Two index reads per call, not per unit, and rows written only for units with something to record ([research.md](./research.md) R9) — so a fresh project writes on the order of tens of rows. Worth measuring once against the existing creation time rather than assuming |
| **The re-homed guard changes when projects freeze** | Deliberately, and in the loosening direction: a staffed-but-idle project stays editable where today it locks. That is the correct behaviour per the guard's own docstring, but it is a behaviour change an operator will notice, and the rewritten `test_assessor_assignment.py` should assert it explicitly rather than let it appear as a test that quietly stopped failing |

## Notes

**Branch.** Work continues on `phase-1`, the branch this repository is currently on. No `before_specify` hook ran (there is no `.specify/extensions.yml`), so no feature branch was created; the spec directory name and the branch name are independent by design.

**Spec Kit setup.** This project has no `.specify/scripts/`, no `.specify/memory/constitution.md`, and no `.specify/extensions.yml`. The setup script could not be run, the Constitution Check has no constitution to load (handled as above, on the precedent of seven prior specs in this repository), and both the `before_plan` and `after_plan` hooks are skipped. The feature directory resolves from `.specify/feature.json`.

**graphify.** `graphify query` supplied the structural map in [research.md](./research.md) rather than sequential source reading. Per `CLAUDE.md`, `graphify update .` must run after the implementation lands.

**Not yet done.** `/speckit-tasks` has not run. This command ends after Phase 1 design, as specified.

## Post-Design Constitution Re-check

Re-evaluated against the artifacts above rather than against the intent.

| Gate | Post-design finding |
|---|---|
| Blind A/B integrity | **PASS, strengthened.** No role-scoped query changes shape. The feature in fact *closes* a hole: today both roles submit as `actor_id="assessor-1"` through the portal's own picker, so A's and B's submissions are attributed to the same actor. `tests/independence/` passing unedited is the stated gate |
| Display writes nothing | **PASS.** Every write is on a POST or at unit creation. `staffing_summary` and `_build_unit_rows`' two new keys are pure reads |
| Append-only audit | **PASS, with the lifecycle table declared.** No submission or completion row is read or written anywhere in the feature, migration included — which is also what makes SC-011 ("zero submissions orphaned") true by construction rather than by test |
| No silent under-staffing | **PASS.** [contracts/assessor-source-and-ingestion.md](./contracts/assessor-source-and-ingestion.md) §3 makes each refusal leave the unit wholly unstaffed, and [quickstart.md](./quickstart.md) Scenario 3 asserts "none, not one" per case — the natural bug being to assign A and then fail on B |
| The platform substitutes nobody | **PASS.** `apply_mapping_entry` reads two fields of the entry and nothing else; a test shuffles the descriptive fields and asserts identical output |
| Administrator intent never overwritten | **PASS.** Skipping `ADMINISTRATOR`-sourced roles is an invariant in [data-model.md](./data-model.md) §3 with a test in both the ingestion and override contracts |
| Exactly-one pairing under concurrency | **PASS.** One row, one `begin_immediate()` transaction, single-process app |
| Portal / REST parity | **PASS.** Three shared entry points — `create_units`, the validator, `resolve_actor_role` — and no rule implemented twice. The API keeps its `role` field but cannot honour it |
| AI / human separation | **PASS.** No file under `agents/`, `orchestration/`, or the prefill path appears anywhere in the Project Structure |
| Configuration externalized | **PASS.** No new configuration exists to externalize |

**No gate violations, and no complexity requiring justification.** The one design choice worth a reviewer's attention is the mutable `unit_assessor_assignments` table, which is declared as a lifecycle table on an existing precedent rather than presented as append-only.
