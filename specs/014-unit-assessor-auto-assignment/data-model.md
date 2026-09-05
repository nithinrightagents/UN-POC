# Phase 1 Data Model: Unit-Level Assessor Assignment

**Feature Directory**: `specs/014-unit-assessor-auto-assignment`
**Spec**: [spec.md](./spec.md) · **Research**: [research.md](./research.md)
**Created**: 2026-09-05

Four new tables, four new entities, two new enums, two retired fields, one retired status value. `init_db` runs `CREATE TABLE IF NOT EXISTS` on every serve ([schema.py:426](../../src/shared/persistence/schema.py#L426)), so there is no migration tooling to add — but there *is* one data migration, and it runs as a startup sweep (§8).

---

## 1. `assessors` — the ingested roster

Satisfies FR-DB-001, FR-DB-004, FR-DB-007.

```sql
CREATE TABLE IF NOT EXISTS assessors (
    assessor_id TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    data        TEXT NOT NULL,   -- display_name, organisation, languages, notes
    ingested_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_assessors_email ON assessors(email);
```

**Idempotency (FR-DB-004)** is the primary key plus `ON CONFLICT(assessor_id) DO UPDATE SET data = excluded.data` — re-ingesting refreshes, never duplicates. The unique index on `email` enforces the spec's "unique contact email".

```python
@dataclass
class Assessor:
    assessor_id: str            # stable identity -- A1, and what a submission cites
    display_name: str
    email: str
    organisation: str = ""
    languages: list[str] = field(default_factory=list)
    notes: str = ""
```

**`organisation`, `languages`, and `notes` are display-only.** FR-MO-003 requires them visible when an administrator overrides; FR-DB-006 bars them from influencing who is assigned. Enforced by test, not by convention — see [quickstart.md](./quickstart.md) §5.

---

## 2. `unit_assessor_mapping` — the source database's statement

Satisfies FR-DB-002, FR-DB-005, and keyed per R7.

```sql
CREATE TABLE IF NOT EXISTS unit_assessor_mapping (
    unit_type   TEXT NOT NULL,   -- 'country' | 'city'
    unit_code   TEXT NOT NULL,   -- ISO country code, as carried on TargetPortal.country_id
    data        TEXT NOT NULL,   -- assessor_a_id, assessor_b_id (either may be null)
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (unit_type, unit_code)
);
```

```python
@dataclass
class UnitAssessorMappingEntry:
    unit_type: str                      # "country" | "city"
    unit_code: str
    assessor_a_id: str | None = None    # None models the single-role defect, FR-IN-007
    assessor_b_id: str | None = None
```

**No project reference** — D4. The composite primary key is the unit identity, and it is computable from a `TargetPortal` with no lookup: `(portal.unit_type, portal.country_id)`.

**Both role fields are nullable on purpose.** A source database that names only one role is a case the spec requires the platform to detect and report (FR-IN-007), so the entry must be representable rather than rejected at load.

---

## 3. `unit_assessor_assignments` — who works this unit of this project

Satisfies FR-UA-001 through FR-UA-005, FR-UA-011, FR-MO-005. Lifecycle table (mutable), on the `reconciliation_rounds` precedent; the audit trail is §4.

```sql
CREATE TABLE IF NOT EXISTS unit_assessor_assignments (
    assignment_id TEXT PRIMARY KEY,
    cycle_id      TEXT NOT NULL,
    portal_id     TEXT NOT NULL,
    data          TEXT NOT NULL,   -- role_a, role_b (each RoleAssignment | null), ingest_defect
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One assignment record per unit: makes distinctness a single-row invariant (R2)
CREATE UNIQUE INDEX IF NOT EXISTS idx_unit_assignment_one_per_unit
    ON unit_assessor_assignments(cycle_id, portal_id);

CREATE INDEX IF NOT EXISTS idx_unit_assignment_cycle
    ON unit_assessor_assignments(cycle_id);
```

```python
class AssignmentSource(str, Enum):
    MAPPING = "mapping"                # applied verbatim from the ingested mapping -- FR-IN-004
    ADMINISTRATOR = "administrator"    # set by hand in the portal -- FR-MO-001
    MIGRATION = "migration"            # carried down from the retired project pair -- FR-UA-008


class UnstaffedReason(str, Enum):
    NO_MAPPING_ENTRY         = "no_mapping_entry"          # FR-IN-008
    INCOMPLETE_MAPPING_ENTRY = "incomplete_mapping_entry"  # FR-IN-007
    DUPLICATE_ASSESSOR       = "duplicate_assessor"        # FR-IN-005
    UNKNOWN_ASSESSOR         = "unknown_assessor"          # FR-IN-006
    CLEARED_BY_ADMINISTRATOR = "cleared_by_administrator"  # FR-MO-005


@dataclass
class RoleAssignment:
    assessor_id: str
    source: AssignmentSource
    set_at: datetime
    set_by_actor_id: str | None = None   # None when source is MAPPING


@dataclass
class UnitAssessorAssignment:
    assignment_id: str
    cycle_id: str
    portal_id: str
    role_a: RoleAssignment | None = None
    role_b: RoleAssignment | None = None
    ingest_defect: UnstaffedReason | None = None   # why the mapping did not staff this unit
```

Nested dataclasses and enums round-trip through the existing serializer without change — `_coerce_value` handles both ([serialization.py:64-82](../../src/shared/persistence/serialization.py#L64)).

### Invariants

| Invariant | Where enforced | Requirement |
|---|---|---|
| `role_a.assessor_id != role_b.assessor_id` when both are set | one validator, shared by the ingestion and override paths | FR-UA-002 |
| Every referenced `assessor_id` exists in `assessors` | same validator | FR-IN-006 |
| A unit is **staffed** iff `role_a` and `role_b` are both set | derived property `is_staffed` | FR-UA-005 |
| An `ADMINISTRATOR` role assignment is never replaced by application of the mapping | application skips a role whose source is `ADMINISTRATOR` | FR-IN-010, SC-006 |
| One project's unit is unaffected by another's | `cycle_id` is part of the row's identity | FR-UA-011 |

### Absence is meaningful (R9)

No row exists for a unit the mapping does not cover. `no_mapping_entry` is derived from the row's absence, not stored. A row is written only when a role is assigned, or when a mapping entry was **found and refused** — the second is the case `ingest_defect` records.

### Concurrency

Writes are read-modify-write of one row inside [`Repository.begin_immediate()`](../../src/shared/persistence/repositories.py#L978). Two administrators editing the same unit serialise; neither can produce a duplicated or half-applied pairing, because the pair is one row and distinctness is checked before it is written. The app already refuses to run multi-worker ([webapp.py:38-45](../../src/portal/webapp.py#L38)), so this is the whole contention surface.

---

## 4. `assignment_changes` — append-only audit

Satisfies FR-MO-008 and SC-009. Append-only, on the `tolerance_changes` precedent ([schema.py:392](../../src/shared/persistence/schema.py#L392)).

```sql
CREATE TABLE IF NOT EXISTS assignment_changes (
    change_id            TEXT PRIMARY KEY,
    cycle_id             TEXT NOT NULL,
    portal_id            TEXT NOT NULL,
    role                 TEXT NOT NULL,   -- 'A' | 'B'
    previous_assessor_id TEXT,            -- NULL when the role was previously unstaffed
    new_assessor_id      TEXT,            -- NULL when the role was cleared
    source               TEXT NOT NULL,   -- 'mapping' | 'administrator' | 'migration'
    changed_by_actor_id  TEXT,            -- NULL when source = 'mapping'
    changed_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_assignment_changes_unit
    ON assignment_changes(cycle_id, portal_id, changed_at);
```

One row per **role**, not per unit, so "who held each unit role over which period" (SC-009) reads directly off the log ordered by `changed_at`. Never updated, never deleted.

---

## 5. `SurveyCycle` — reduced

```diff
 @dataclass
 class SurveyCycle:
     cycle_id: str
     name: str
     questionnaire_ref: str
     country_set: list[str]
-    status: str = "active"                  # "active" | "locked"
+    status: str = "active"                  # "active" only; "locked" retired -- R4
     project_type: ProjectType = ProjectType.NATIONAL_OSI
     discrepancy_rate_threshold: float | None = None
-    # Set together with status="locked" once an admin assigns both assessors --
-    # see assign_assessors()/unassign_assessors() in portal/admin.py.
-    assessor_a_email: str | None = None
-    assessor_b_email: str | None = None
```

FR-UA-006 retires the project-level pair as the source of assignment truth; D11 retires the wholesale locked/unlocked flag.

**No data rewrite is needed.** `_coerce` assigns only keys present in the dataclass's type hints ([serialization.py:47-49](../../src/shared/persistence/serialization.py#L47)), so an existing `survey_cycles.data` blob carrying `assessor_a_email` deserialises cleanly into the reduced dataclass and silently drops it. The startup migration (§8) reads those values *before* they are dropped — see the ordering note there.

`status` is retained rather than removed: the column and field stay, `"locked"` simply stops being written. Removing the field would touch every `SurveyCycle` construction site for no behavioural gain.

---

## 6. `TargetPortal` — unchanged

The unit gains its assessor pair **by reference**, not by new columns. `unit_type` and `country_id` already present on the row are exactly the mapping key (R7), and nothing in this feature writes to `target_portals`.

What does change is who sets `unit_type`: it is derived from `cycle.project_type` at every creation site rather than taken from a form field (R12, FR-UA-009), so a project cannot hold a mixture of classifications.

---

## 7. `HumanAssessorSubmission`, `AssessorCompletion` — unchanged, deliberately

Neither entity changes, and no existing row is rewritten.

- **Role attribution already lives on the row** (`HumanAssessorSubmission.role`, `AssessorCompletion.role`), so FR-MO-006/007 and FR-UA-008 hold without touching data: reassigning a role changes who may write *next*, not what was written before.
- `assessor_actor_id` values written under the old model (`"demo-assessor-a"`, [seed_lifecycle_demo.py:124](../../src/portal/seed_lifecycle_demo.py#L124)) are historical audit facts in an append-only table. They are **not** reconciled against the roster and **not** rewritten — FR-062 forbids it, and FR-MO-006 forbids reattribution.
- Reconciliation continues to compare the A-role and B-role answers of record regardless of who submitted them (A6), so `portal/discrepancy.py` and `portal/reconciliation.py` are untouched.

Going forward, `assessor_actor_id` carries the roster `assessor_id` (A1) — a change in the *values written*, not in the schema.

---

## 8. Migration of project-level assignments

Satisfies FR-UA-008 and SC-011. Runs as a startup sweep in the app lifespan, beside `sweep_interrupted_jobs` ([webapp.py:50](../../src/portal/webapp.py#L50)).

```
for each cycle in survey_cycles:
    if the cycle already has any unit_assessor_assignments rows: skip     # idempotent
    read assessor_a_email / assessor_b_email from the raw stored JSON
    if either is absent: skip
    for each email: find the roster assessor with that email,
                    else create one (display name from the local part, source-flagged)
    for each portal in the cycle:
        write a UnitAssessorAssignment with both roles, source = MIGRATION
        write two assignment_changes rows (previous NULL -> new)
```

**Ordering note.** The sweep must read `assessor_a_email` / `assessor_b_email` from the **raw `data` JSON**, not from a deserialised `SurveyCycle` — by the time it runs, the dataclass no longer declares those fields and `_coerce` will have dropped them (§5). This is the single subtlety in the migration and the easiest thing to get silently wrong: a version that goes through `get_cycle()` finds `None` for every project and migrates nothing, with no error.

**Zero submissions orphaned** (SC-011) follows from §7: no submission row is read or written.

---

## 9. `delete_cycle` cascade

[`Repository.delete_cycle`](../../src/shared/persistence/repositories.py#L84) deletes project-scoped rows explicitly, table by table. Both new project-scoped tables must be added to it:

```sql
DELETE FROM unit_assessor_assignments WHERE cycle_id = ?;
DELETE FROM assignment_changes        WHERE cycle_id = ?;
```

`assessors` and `unit_assessor_mapping` are **not** project-scoped and must not be touched — they survive the deletion of every project, which is what makes them the ingested source rather than project data.

---

## 10. Seeded source data

Two files under `data/reference/`, alongside `un_member_states.json`, loaded by `src/shared/reference/assessors.py` on the `countries.py` pattern (R1, R10).

**`assessors.json`** — 24 records:

```json
[
  {
    "assessor_id": "asr-001",
    "display_name": "Amara Okonkwo",
    "email": "a.okonkwo@ekap-demo.org",
    "organisation": "Regional E-Government Observatory",
    "languages": ["en", "fr"],
    "notes": "Prior OSI cycles: 2022, 2024"
  }
]
```

**`unit_assessor_mapping.json`** — 40 country identities, 40 city identities, plus four deliberate defects, one per failure mode in [research.md](./research.md) R8:

```json
[
  { "unit_type": "country", "unit_code": "DK", "assessor_a_id": "asr-001", "assessor_b_id": "asr-007" },
  { "unit_type": "city",    "unit_code": "KE", "assessor_a_id": "asr-012", "assessor_b_id": "asr-003" },

  { "unit_type": "country", "unit_code": "IS", "assessor_a_id": "asr-004", "assessor_b_id": "asr-004" },
  { "unit_type": "country", "unit_code": "MT", "assessor_a_id": "asr-009", "assessor_b_id": null      },
  { "unit_type": "country", "unit_code": "LU", "assessor_a_id": "asr-002", "assessor_b_id": "asr-999" },
  { "unit_type": "country", "unit_code": "ZZ", "assessor_a_id": "asr-005", "assessor_b_id": "asr-011" }
]
```

The last four, in order: same person both roles (`duplicate_assessor`), one role named (`incomplete_mapping_entry`), unknown assessor reference (`unknown_assessor`), and an entry for a unit identity no project contains (ignored without error, FR-IN-009). Coverage of 40 in each classification comfortably exceeds SC-001's twelve-unit project in both national and city form.

`data/reference/` is already served statically at `/data` ([webapp.py:77](../../src/portal/webapp.py#L77)). These two files contain fabricated demonstration personnel (A4) and no real contact details, which is why placing them there is acceptable; the real assessor database must not be seeded this way.

---

## Requirement coverage

| Requirement group | Where it lands |
|---|---|
| FR-DB-001…007 | §1, §2, §10 |
| FR-IN-001…011 | §2, §3 (invariants, absence), §10; application logic in [contracts/assessor-source-and-ingestion.md](./contracts/assessor-source-and-ingestion.md) |
| FR-UA-001…011 | §3, §5, §6 |
| FR-MO-001…009 | §3, §4, §7 |
| FR-AC-001…005 | §3 (the assignment is the authority); routes in [contracts/assignment-gated-access.md](./contracts/assignment-gated-access.md) |
| FR-SV-001…003 | §3 (`ingest_defect`, `is_staffed`); rendering in [contracts/unit-assignment-and-override.md](./contracts/unit-assignment-and-override.md) |
