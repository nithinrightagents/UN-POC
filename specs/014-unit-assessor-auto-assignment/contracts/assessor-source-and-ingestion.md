# Contract: Assessor Source Data and Ingestion

**Feature**: [spec.md](../spec.md) · **Design**: [data-model.md](../data-model.md) · **Research**: [research.md](../research.md) R1, R3, R8, R9, R10

Covers **FR-DB-001…007** and **FR-IN-001…011**. Two new modules, one startup step, one domain function that every unit-creation site calls.

---

## 1. Source loader — `src/shared/reference/assessors.py`

Mirrors [`countries.py`](../../../src/shared/reference/countries.py): module-level `_REPO_ROOT`, `@lru_cache(maxsize=1)`, frozen dataclasses, no I/O beyond two JSON reads.

```python
_ASSESSORS_PATH = _REPO_ROOT / "data" / "reference" / "assessors.json"
_MAPPING_PATH   = _REPO_ROOT / "data" / "reference" / "unit_assessor_mapping.json"

@lru_cache(maxsize=1)
def list_source_assessors() -> list[AssessorRef]: ...

@lru_cache(maxsize=1)
def list_source_mapping() -> list[UnitMappingRef]: ...
```

**This module is the entire replacement seam** (FR-DB-005, SC-013). When the programme supplies the real assessor database, these two functions read from it instead. Nothing downstream changes, and that invariance is what SC-013 asserts.

**A malformed source file must fail loudly at startup, not silently produce an empty roster.** A missing required key, an unknown `unit_type`, or a duplicate `(unit_type, unit_code)` raises at load. An empty roster that ingests cleanly would leave every unit unstaffed with `no_mapping_entry` — indistinguishable from a source database that genuinely covers nothing.

---

## 2. Ingestion — `ingest_assessor_source(r: Repository) -> IngestSummary`

Lives in `src/portal/assignment.py`. Called once from the app lifespan in [`webapp.py`](../../../src/portal/webapp.py#L50), immediately after `init_db` and before `sweep_interrupted_jobs`.

| Rule | Behaviour | Requirement |
|---|---|---|
| Setup-time load, not a sync | Runs at startup only. No scheduler, no background task, no polling. | FR-IN-001, D5 |
| Idempotent | `ON CONFLICT(assessor_id) DO UPDATE` and `ON CONFLICT(unit_type, unit_code) DO UPDATE`. Re-running refreshes; it never duplicates. | FR-DB-004 |
| Roster before mapping | Assessors are written first, so the `unknown_assessor` check at application time reads a complete roster. | FR-IN-006 |
| Ingestion never writes assignments | It populates `assessors` and `unit_assessor_mapping` only. Assignment happens at unit creation (§3). | FR-IN-003 |

`IngestSummary` returns `(assessors_written, mapping_entries_written)` and is logged in the same style as `sweep_interrupted_jobs`' count.

**Ordering within the lifespan is load-bearing.** `ingest_assessor_source` must run *before* `migrate_project_level_assignments` ([data-model.md](../data-model.md) §8), because migration resolves legacy emails against the roster.

---

## 3. Application at unit creation — `create_units(r, cycle_id, portals) -> list[UnitAssessorAssignment]`

The single path by which a unit comes into existence. Replaces direct `Repository.insert_portal(s)` calls at all six sites (R3).

```
create_units(r, cycle_id, portals):
    r.insert_portals(portals)
    mapping = r.load_mapping_index()          # one read, {(unit_type, unit_code): entry}
    roster  = r.load_assessor_index()         # one read, {assessor_id: Assessor}
    for portal in portals:
        entry = mapping.get((portal.unit_type, portal.country_id))
        if entry is None:
            continue                          # no row -- absence means no_mapping_entry (R9)
        apply_mapping_entry(r, cycle_id, portal, entry, roster)
```

Two index reads per call regardless of how many units are created — `create_project` tags 193 units in one call ([admin.py:236](../../../src/portal/admin.py#L236)) and must not issue 386 lookups.

### `apply_mapping_entry` — the verbatim rule and its four refusals

```
a, b = entry.assessor_a_id, entry.assessor_b_id

if a is None or b is None:      record INCOMPLETE_MAPPING_ENTRY, staff neither   # FR-IN-007
if a == b:                      record DUPLICATE_ASSESSOR,       staff neither   # FR-IN-005
if a not in roster or
   b not in roster:             record UNKNOWN_ASSESSOR,         staff neither   # FR-IN-006

otherwise: assign both roles with source = MAPPING, ingest_defect = None
```

| Rule | Requirement |
|---|---|
| The assessors written are exactly the ids the entry names — no substitution, ranking, matching, or fallback of any kind | **FR-IN-004**, SC-004 |
| A refusal leaves the unit **wholly** unstaffed, never half-assigned | FR-IN-005, FR-IN-006, FR-IN-007, D8 |
| A role whose current `source` is `ADMINISTRATOR` is skipped, never overwritten | **FR-IN-010**, SC-006 |
| An entry whose `(unit_type, unit_code)` matches no unit is never visited — iteration is over units, not entries | FR-IN-009 |
| Assessor `organisation`, `languages`, and `notes` are not read by this function at all | **FR-DB-006** |

Each role actually assigned writes one `assignment_changes` row with `source = 'mapping'` and `changed_by_actor_id = NULL`.

### Behaviour is identical for country and city units

The only difference between a national project's unit and a city project's unit is the `unit_type` half of the mapping key. Nothing branches on it (FR-UA-010).

---

## 4. Staffing report — `staffing_summary(r, cycle_id) -> StaffingSummary`

Backs FR-IN-011 and FR-SV-002.

```python
@dataclass
class StaffingSummary:
    total_units: int
    staffed_units: int
    unstaffed: dict[str, UnstaffedReason]   # portal_id -> reason
```

Derived, never stored: one read of the project's assignment rows, joined in memory against its portals. A unit with no row is reported `no_mapping_entry` (R9); a unit with a row and a missing role is reported by that row's `ingest_defect`, or `CLEARED_BY_ADMINISTRATOR` if an administrator emptied it.

---

## 5. Repository additions

```python
def upsert_assessor(self, assessor: Assessor) -> None
def get_assessor(self, assessor_id: str) -> Assessor | None
def list_assessors(self) -> list[Assessor]
def load_assessor_index(self) -> dict[str, Assessor]

def upsert_mapping_entry(self, entry: UnitAssessorMappingEntry) -> None
def load_mapping_index(self) -> dict[tuple[str, str], UnitAssessorMappingEntry]
```

`assessors` and `unit_assessor_mapping` are **not** project-scoped and are deliberately absent from `delete_cycle`'s cascade ([data-model.md](../data-model.md) §9).

---

## 6. Contract tests

| Test | Asserts | Requirement |
|---|---|---|
| `test_ingest_is_idempotent` | ingesting twice yields the same row counts | FR-DB-004 |
| `test_create_units_applies_mapping_verbatim` | assigned ids equal the mapping's ids for every covered unit | FR-IN-004, SC-004 |
| `test_uncovered_unit_gets_no_assignment_row` | absence, and `staffing_summary` reports `no_mapping_entry` | FR-IN-008, R9 |
| `test_duplicate_entry_leaves_unit_wholly_unstaffed` | neither role assigned; `ingest_defect = DUPLICATE_ASSESSOR` | FR-IN-005 |
| `test_single_role_entry_leaves_unit_unstaffed` | `INCOMPLETE_MAPPING_ENTRY` | FR-IN-007 |
| `test_unknown_assessor_entry_leaves_unit_unstaffed` | `UNKNOWN_ASSESSOR` | FR-IN-006 |
| `test_orphan_mapping_entry_is_ignored` | no error, no row, no log noise | FR-IN-009 |
| `test_mapping_never_overwrites_administrator_assignment` | override, re-apply, assert unchanged | FR-IN-010, SC-006 |
| `test_assignment_ignores_assessor_descriptive_fields` | shuffle `languages`/`organisation` in the roster, re-apply, assert identical assignments | **FR-DB-006** |
| `test_seed_staffs_a_twelve_unit_project_with_no_input` | end-to-end from a fresh database | SC-001, SC-010 |
| `test_swapping_source_data_changes_only_who` | substitute a different `assessors.json`/mapping; assert the same units are staffed/unstaffed for the same reasons, with different people | **SC-013** |
