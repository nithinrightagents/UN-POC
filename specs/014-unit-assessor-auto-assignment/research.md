# Phase 0 Research: Unit-Level Assessor Assignment

**Feature Directory**: `specs/014-unit-assessor-auto-assignment`
**Spec**: [spec.md](./spec.md)
**Created**: 2026-09-05

The spec carries **zero `[NEEDS CLARIFICATION]` markers** — the `/speckit-clarify` session settled ten questions on 2026-09-05, and the model is fixed: an external database names the pair per unit, the portal ingests and applies it verbatim, an administrator corrects afterwards. What remains unresolved is entirely implementation-level, and that is what R1–R12 settle.

One item was deliberately deferred out of `/speckit-clarify` into this phase, and it is R4: **`_blocked_if_locked` guards fifteen admin routes off the project-level lock that D11 retires.** What guards project edits afterwards was correctly judged an implementation decision, not a spec defect.

---

## Structural map (graphify)

`graphify query` on the persistence and assessor-workspace paths surfaced the load-bearing nodes this feature touches. They are listed here so the Technical Context in [plan.md](./plan.md) does not have to re-derive them:

| Node | Location | Why it matters here |
|---|---|---|
| `Repository` | [repositories.py:49](../../src/shared/persistence/repositories.py#L49) | Sole persistence surface; every new table needs methods here |
| `to_json` / `from_json` | [serialization.py:27](../../src/shared/persistence/serialization.py#L27), [:35](../../src/shared/persistence/serialization.py#L35) | Entities are stored as a JSON `data` column; `_coerce` handles nested dataclasses, enums, and lists |
| `init_db()` | [schema.py:426](../../src/shared/persistence/schema.py#L426) | Runs `CREATE TABLE IF NOT EXISTS` on every serve — no migration tooling exists |
| `SurveyCycle` | [entities.py:205](../../src/shared/state/entities.py#L205) | Holds the two fields being retired |
| `TargetPortal` | [entities.py:283](../../src/shared/state/entities.py#L283) | The unit; carries `unit_type` and `country_id`, which together form the mapping key |
| `HumanAssessorSubmission` | [entities.py:539](../../src/shared/state/entities.py#L539) | Carries `role` and `assessor_actor_id`; must not be rewritten |
| `ensure_session()` | [common.py:24](../../src/portal/common.py#L24) | One session per cycle, `f"{cycle_id}-workflow-session"` |
| `_build_unit_rows` | [admin.py:81](../../src/portal/admin.py#L81) | The existing per-unit aggregator the staffing display extends |

---

## R1 — Where the assessor source data lives

**Decision.** Two seeded JSON files under `data/reference/` — `assessors.json` and `unit_assessor_mapping.json` — loaded by a new `src/shared/reference/assessors.py` that mirrors [`countries.py`](../../src/shared/reference/countries.py) exactly (frozen dataclasses, `@lru_cache(maxsize=1)`, `_REPO_ROOT / "data" / "reference" / ...`). A separate **ingestion step** copies them into two SQLite tables at startup. Assignment reads only the tables, never the JSON.

**Rationale.** The spec asks for two things that pull in opposite directions. FR-DB-001/003/004 want persisted, pre-populated, idempotent records — that is the seeded-reference-data pattern the spec names as dependency D-5. FR-DB-005 and SC-013 want the demonstration data replaceable by the real database *without changing how assignment consumes it*, and FR-IN-001 makes ingestion an explicit setup-time load rather than a read-through.

Splitting loader from tables gives exactly one seam. Swapping the programme's real database in means replacing what `shared/reference/assessors.py` reads. Ingestion, application, override, and access control all sit downstream of the tables and do not move — which is precisely what SC-013 asserts.

**Alternatives considered.**

- *JSON only, read through `lru_cache` at every use, like `countries.py`.* Rejected: FR-DB-001 says "persisted assessor records" and FR-IN-001 makes ingestion a real step with a real time of occurrence. More concretely, an assignment must reference an assessor that existed **at the time of assignment**; if the roster is only ever a file on disk, editing the file silently rewrites history that `assignment_changes` claims to record.
- *A protocol/ABC with a seed implementation and a placeholder real implementation.* Rejected as speculative generality. One module with two loader functions is the seam; an interface for a single implementation is machinery with no second caller.

---

## R2 — Shape of the assignment record

**Decision.** **One row per unit holding both roles**, in a lifecycle table `unit_assessor_assignments` with `UNIQUE(cycle_id, portal_id)`, plus a **separate append-only** `assignment_changes` log.

**Rationale.** This is the `tolerance_changes` pattern from spec 012 — a mutable current value alongside an append-only record of every edit — and it is already the accepted way to satisfy the repository's append-only rule ([repositories.py:1-6](../../src/shared/persistence/repositories.py#L1)) without pretending a settable value is immutable. `reconciliation_rounds` set the same precedent for a declared lifecycle table.

The choice of *one row per unit* rather than one row per (unit, role) is what makes the two invariants enforceable:

- **FR-UA-002 (distinctness)** becomes a single-row invariant checked in one constructor. Across two rows it is not expressible as any index, and a read-then-write check would let two concurrent administrators each set a different role to the same person.
- **FR-UA-005 (workable only when both roles are filled)** is read without a join or a second lookup.
- The concurrency edge case — *"two administrators changing the same unit concurrently … a unit never ends up with a duplicated or half-applied pairing"* — reduces to a read-modify-write of one row under [`Repository.begin_immediate()`](../../src/shared/persistence/repositories.py#L978), which already exists for exactly this purpose. The app additionally refuses to run multi-worker ([webapp.py:38-45](../../src/portal/webapp.py#L38)), so this is genuinely the only contention window.

**Alternatives considered.**

- *Purely append-only log; current assignment = latest row per (unit, role).* Rejected on three counts: clearing a role (FR-MO-005) needs tombstone rows; every project view becomes 2N ordered scans on top of the per-unit work `_build_unit_rows` already does; and the distinctness check across two independently-latest rows has no atomic form.
- *Columns on `target_portals`.* Rejected: `TargetPortal` is written by resolution and publication paths that have no business touching staffing, and `update_portal_resolution` would clobber assignments written concurrently.

---

## R3 — When the mapping is applied

**Decision.** At unit creation, through a single new domain function `create_units(r, cycle_id, portals)` in `src/portal/assignment.py` that inserts the portals and then applies the mapping. All six existing unit-creation sites call it instead of `Repository.insert_portal(s)` directly.

The six sites: [`admin.py` `create_project`](../../src/portal/admin.py#L225), [`add_units`](../../src/portal/admin.py#L617), [`bulk_add_units`](../../src/portal/admin.py#L656), [`api/routers/cycles.py:127`](../../src/api/routers/cycles.py#L127), [`seed.py`](../../src/portal/seed.py), [`seed_lifecycle_demo.py`](../../src/portal/seed_lifecycle_demo.py).

**Rationale.** FR-IN-003 requires application "at the point a unit comes into existence", and units come into existence at six places. Funnelling them through one function leaves `insert_portals` as a bare persistence primitive used only by `create_units` and by tests that deliberately want an unstaffed unit — so a future creation site that skips staffing is visible as a direct repository call, not invisible as a missing line.

**Alternatives considered.**

- *Apply inside `Repository.insert_portals`.* Rejected: the repository is a thin persistence wrapper by design and by docstring; embedding assignment policy there would make every test that inserts a portal implicitly write assignment and audit rows.
- *Apply lazily on read (project detail, assessor picker).* Rejected outright — it violates the **display writes nothing** gate that spec 012 established (FR-DR-007, SC-010). A GET must not create audit rows.
- *A one-line call after each of the six `insert_portals` calls.* Rejected as the weaker form of the same thing: identical cost, no structural protection against the seventh site.

**Cost note.** `create_project` tags all 193 UN member states in one go ([admin.py:236](../../src/portal/admin.py#L236)). Application loads the mapping once into a dict and writes rows only for units that have something to record (see R9), so a fresh project writes on the order of tens of rows, not 193.

---

## R4 — What replaces the project-level lock *(the deferred item)*

**Decision.** Keep the guard, replace its trigger. `_blocked_if_locked` becomes `_blocked_if_work_started`, and the condition changes from `cycle.status == "locked"` to *"any human submission or completion declaration exists in this project's session"*. `SurveyCycle.status` stops being flipped to `"locked"` by assignment, and the `"locked"` value is retired along with the project-level pair.

**Rationale.** Read the guard's own docstring ([admin.py:56-64](../../src/portal/admin.py#L56)): units and questions freeze *"otherwise a mid-assessment unit/question change would silently skew `recompute_portal_discrepancy()` and `AssessorCompletion.indicator_count_at_declaration`, which both assume a fixed question set per unit."*

That reason is about **assessment having started**, not about assessors having been named. Naming the pair was only ever a proxy for it — a proxy this feature removes, since units are now staffed automatically at creation and a project is staffed piecemeal rather than all at once. Substituting the real condition for the proxy preserves the invariant exactly while cutting its dependence on the retired field, and it is strictly more accurate: today a project locks the instant an administrator types two emails, even though nobody has answered anything.

The guard's **first parameter changes** — today it takes the already-fetched `SurveyCycle | None` ([admin.py:56](../../src/portal/admin.py#L56)) and reads a field; the new trigger is a query, so it takes the `Repository` instead. Return type, redirect target, and `?lock_error=1` are unchanged, so each of the fifteen `if (resp := ...) is not None:` lines changes in the name it calls and its first argument, and the eleven sites that currently pass `r.get_cycle(cycle_id)` drop that now-redundant fetch. `session_id_for_cycle` is already a pure helper in [`portal/common.py`](../../src/portal/common.py#L17) — no session is created by the check.

**Cost.** One `SELECT 1 ... LIMIT 1` per guarded route, on a table already indexed by `session_id`. A new repository method `has_any_human_activity(session_id)` covers both submissions and completions.

**Alternatives considered.**

- *Drop the guard entirely.* Rejected — it would reintroduce precisely the skew the docstring names, and D11 retires the *project-wide staffing flag*, not the freeze.
- *Freeze per unit rather than per project.* Rejected as scope creep the user explicitly excluded ("Nothing else"). The question set is project-scoped, so a question edit affects every unit; a per-unit freeze cannot express that.

---

## R5 — Deriving role and identity from the assignment

**Decision.** The assessor workspace URL carries **`actor_id` only**. Role is looked up from the unit's assignment. `role` is removed from every portal route signature and every form; the API keeps `role` in its request bodies but **validates it against the assignment and rejects a contradiction** rather than honouring it.

**Rationale.** FR-AC-002 is unambiguous: role must be derived from the assignment, never from the request. Today it is the opposite — [`assessor.py:59-60`](../../src/portal/assessor.py#L59) takes `role: AssessorRole` as a query parameter and `actor_id: str = "assessor-1"` as a defaulted one, and the submit and complete routes take both as form fields ([:126-127](../../src/portal/assessor.py#L126), [:206-207](../../src/portal/assessor.py#L206)).

There is a sharper defect underneath, visible only by reading the picker template alongside the route: [`assessor_picker.html`](../../src/portal/templates/assessor_picker.html) links to `?role=A` and `?role=B` **with no `actor_id` at all**. Both roles therefore fall through to the default, and every submission made through the portal's own navigation is attributed to `assessor-1` — for A and B alike. Unit-level assignment cannot be built on top of that, because there is no identity to check an assignment against.

Consequently the picker changes shape: instead of "Open as A / Open as B" per unit, it asks who you are and then lists the units you are assigned to, in the role you hold on each. That falls directly out of the assignment table and is what makes User Story 2 scenario 4 (same person, A on one unit, B on another) demonstrable.

**Rejecting the request `role` on the API rather than ignoring it** keeps the wire shape stable for existing clients while making the rule unbypassable, and it surfaces a client bug instead of silently correcting it. Removing the field would be a breaking change to `api/routers/human.py` and `completions.py` for no gain in enforcement.

**Limit, stated plainly.** This is an **assignment** check, not an identity proof. Nothing authenticates `actor_id`, so anyone who knows an assessor's identifier can present it. Assumption A3 already grants exactly this, and spec 012 recorded the same limitation. FR-AC-001/003 are satisfied to the level the platform's demonstration-grade identity permits, and no further.

---

## R6 — Migrating projects staffed under the retired model

**Decision.** A startup sweep `migrate_project_level_assignments(conn)` in the app lifespan, immediately alongside the existing `sweep_interrupted_jobs(conn)` ([webapp.py:50](../../src/portal/webapp.py#L50)). Idempotent: it skips any cycle that already has unit assignments. For each legacy cycle it resolves `assessor_a_email` / `assessor_b_email` against the roster by email, creating a roster record from the email if none matches, then writes one assignment per unit with source `migration`.

**Rationale.** There is no migration tooling in this project — `init_db` is `CREATE TABLE IF NOT EXISTS` and nothing else ([schema.py:426](../../src/shared/persistence/schema.py#L426)) — but there is an established precedent for a startup sweep that repairs state and logs a count, and this is the same shape.

Two facts make the migration much smaller than it first looks:

1. **No submission is touched.** FR-UA-008 requires preserving "the role attribution of all existing submissions", and role attribution lives in `HumanAssessorSubmission.role`, which this feature never changes. The historical `assessor_actor_id` strings (`"demo-assessor-a"` and friends, [seed_lifecycle_demo.py:124](../../src/portal/seed_lifecycle_demo.py#L124)) are audit rows in an append-only table and stay exactly as written. They do not need to reconcile with the roster, and rewriting them would violate FR-062.
2. **Dropping the two `SurveyCycle` fields is safe against already-stored JSON.** `_coerce` only assigns keys that appear in the dataclass's type hints ([serialization.py:47-49](../../src/shared/persistence/serialization.py#L47)), so an old `survey_cycles.data` blob carrying `assessor_a_email` deserialises cleanly into the reduced dataclass, ignoring it. No data rewrite is required to retire the fields.

**Alternatives considered.** *Migrate on first read of each cycle.* Rejected — same "display writes nothing" objection as R3, and it would leave the migration's completion unobservable.

---

## R7 — The mapping key

**Decision.** `(unit_type, unit_code)` where `unit_type` is `"country"` or `"city"` and `unit_code` is the ISO country code already carried on `TargetPortal.country_id`.

**Rationale.** D4 and A2 key the mapping on "country or city code plus national/city classification". The platform derives exactly one city per country — `most_populous_city` from [`un_member_states.json`](../../data/reference/un_member_states.json), applied at [cycles.py:127-132](../../src/api/routers/cycles.py#L127) and [admin.py:259-266](../../src/portal/admin.py#L259) — so a city unit is uniquely identified by its country code plus the `"city"` classification. No new code vocabulary is needed, and the key is computable from a `TargetPortal` with no lookup.

**Constraint this creates, recorded honestly.** If the programme later assesses more than one city per country, this key stops being unique and a real city code (and a city reference table) becomes necessary. That is a change to the reference data and the key, not to assignment, override, or access control. It is carried into [plan.md](./plan.md) Risks.

---

## R8 — Validation and the closed set of unstaffed reasons

**Decision.** One shared validation function used by both the ingestion path and the override path, and a closed enum of reasons stored on the assignment row:

| Reason | Raised when | Requirement |
|---|---|---|
| `no_mapping_entry` | the mapping does not cover the unit's identity | FR-IN-008 |
| `incomplete_mapping_entry` | the entry names only one of the two roles | FR-IN-007 |
| `duplicate_assessor` | the entry names the same person for both roles | FR-IN-005, FR-UA-002 |
| `unknown_assessor` | the entry references an id not on the roster | FR-IN-006 |
| `cleared_by_administrator` | an administrator cleared a role | FR-MO-005 |

**Rationale.** FR-SV-001 and FR-IN-011 both require the *reason* to be displayable per unit, and recomputing it at render time would mean re-reading the mapping on every project view — work the display-writes-nothing rule makes awkward and the per-unit aggregator does not need. Storing it makes the reason a fact about what happened at application time, which is what the administrator actually needs to see.

Routing ingestion and override through **one** validator is what makes FR-UA-002's "whether ingested or manual" true by construction rather than by two parallel checks that can drift.

---

## R9 — Absence is the default unstaffed state

**Decision.** An assignment row is written only when there is something to record: a staffed role, or a mapping entry that was *found and refused*. A unit the mapping simply does not cover gets no row, and `no_mapping_entry` is derived from the row's absence.

**Rationale.** `create_project` creates 193 units. Writing a row per unit to say "nothing is known about this unit" would triple the write cost of project creation and fill the audit log with non-events. The distinction that matters to an administrator is between *the source database had nothing to say* and *the source database said something invalid* — and only the second is an event worth recording.

FR-IN-009 ("a mapping entry whose unit identity matches no unit in any project MUST be ignored without error") falls out for free: application iterates units and looks up entries, never the reverse, so an unmatched entry is never visited.

---

## R10 — Seeded demonstration data

**Decision.** `assessors.json` carries 24 assessor records. `unit_assessor_mapping.json` carries entries for 40 country identities and 40 city identities, plus **four deliberate defect entries**, one per ingestion failure mode in R8.

**Rationale.** SC-001 requires a twelve-unit project to be fully staffed on creation, and SC-010 requires a newly initialised platform to staff and complete a multi-unit project with no manual entry — so coverage must comfortably exceed twelve in both classifications. User Story 4 and FR-IN-005 through FR-IN-008 are only demonstrable from seed data if the seed *contains* the defects, which A4 anticipates ("realistic in shape and sufficient to exercise every path, including the gap and conflict cases").

Descriptive fields (organisation, languages, notes) are present because FR-MO-003 requires an administrator to see them when overriding. FR-DB-006 bars them from influencing assignment — enforced by a test asserting that application reads only the mapping, which is also the test for SC-004.

---

## R11 — Portal / REST parity

**Decision.** Every rule lands in `src/portal/assignment.py`, and both surfaces call it. The API's unit-creation path ([cycles.py:127](../../src/api/routers/cycles.py#L127)) uses the same `create_units`; `human.py` and `completions.py` derive role through the same `resolve_actor_role`.

**Rationale.** Spec 012's Constitution Check established this as a gate: *"neither surface may bypass a rule"*. FR-AC-002 and FR-UA-002 are exactly the kind of rule that grows a second, divergent implementation if each surface enforces it locally.

---

## R12 — Enforcing "a project is national or city, never both" (FR-UA-009)

**Decision.** Derive `unit_type` from `cycle.project_type` at every creation site and remove `unit_type` as an input. The two admin unit forms drop the field, and the template's hidden `unit_type` inputs ([admin_project_detail.html:731, 734, 798, 801](../../src/portal/templates/admin_project_detail.html)) are deleted.

**Rationale.** This is the one constraint in the spec that today's code does **not** enforce: [`admin.py:661`](../../src/portal/admin.py#L661) reads `unit_type` from the form with a `"country"` default, independently of the project's type, so an administrator can already mix classifications in one project. The API path already does it correctly ([cycles.py:127-132](../../src/api/routers/cycles.py#L127)) — this makes the portal match, which is R11's parity gate applied to a rule the portal is currently the weaker half of.

Deriving rather than validating is the stronger form: a mixed project becomes unrepresentable instead of merely rejected. Existing tests that post `unit_type` continue to pass, because FastAPI ignores unexpected form fields.

---

## Resolved / outstanding

**Resolved**: R1–R12, covering every implementation unknown including the one item `/speckit-clarify` deferred (R4).

**Outstanding, and deliberately so**: nothing in this feature authenticates an assessor (R5). It is recorded in the spec as A3 and as Known Limitation, in this document as R5's closing paragraph, and in [plan.md](./plan.md) as a Risk. It is not resolvable within this feature's scope and should not be silently absorbed into it.
