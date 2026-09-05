"""Domain service for unit-level assessor assignment and ingestion.

This module is the single home for:
- Ingestion of external assessor roster and unit mapping
- Verbatim application of mapping at unit creation
- Validation of assessor pairs
- Administrator overrides and clear actions
- Assessor role resolution and access control
- Staffing summary generation

The portal selects nobody (FR-IN-004, SC-004). Assignments are transcribed verbatim
from the ingested mapping or set explicitly by administrators.

Persistence model:
- `unit_assessor_assignments` is a lifecycle table on the `reconciliation_rounds` precedent.
- `assignment_changes` is an append-only audit trail on the `tolerance_changes` precedent.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from shared.persistence.repositories import Repository
from shared.state.entities import (
    Assessor,
    AssessorRole,
    AssignmentChange,
    AssignmentSource,
    RoleAssignment,
    TargetPortal,
    UnitAssessorAssignment,
    UnitAssessorMappingEntry,
    UnstaffedReason,
    new_id,
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestSummary:
    assessors_written: int
    mapping_entries_written: int


@dataclass(frozen=True)
class StaffingSummary:
    total_units: int
    staffed_units: int
    unstaffed: dict[str, UnstaffedReason]  # portal_id -> reason


def ingest_assessor_source(
    r: Repository,
    assessors_path: Path | None = None,
    mapping_path: Path | None = None,
) -> IngestSummary:
    """Setup-time idempotent ingestion of reference assessors and unit mappings.

    Writes to assessors and unit_assessor_mapping tables only. Never writes
    assignments. Assessors are written before mapping so references can be checked.
    """
    from shared.reference.assessors import list_source_assessors, list_source_mapping

    source_assessors = list_source_assessors(assessors_path)
    for a in source_assessors:
        r.upsert_assessor(
            Assessor(
                assessor_id=a.assessor_id,
                display_name=a.display_name,
                email=a.email,
                organisation=a.organisation,
                languages=list(a.languages),
                notes=a.notes,
            )
        )

    source_mapping = list_source_mapping(mapping_path)
    for m in source_mapping:
        r.upsert_mapping_entry(
            UnitAssessorMappingEntry(
                unit_type=m.unit_type,
                unit_code=m.unit_code,
                assessor_a_id=m.assessor_a_id,
                assessor_b_id=m.assessor_b_id,
            )
        )

    summary = IngestSummary(
        assessors_written=len(source_assessors),
        mapping_entries_written=len(source_mapping),
    )
    _log.info(
        "Ingested assessor source: %d assessors, %d mapping entries",
        summary.assessors_written,
        summary.mapping_entries_written,
    )
    return summary


def validate_pair(
    assessor_a_id: str | None,
    assessor_b_id: str | None,
    roster: dict[str, Assessor] | set[str] | list[str],
) -> UnstaffedReason | None:
    """The single validator shared by mapping application and administrator override (FR-UA-002)."""
    if not assessor_a_id or not assessor_b_id:
        return UnstaffedReason.INCOMPLETE_MAPPING_ENTRY
    if assessor_a_id == assessor_b_id:
        return UnstaffedReason.DUPLICATE_ASSESSOR
    if assessor_a_id not in roster or assessor_b_id not in roster:
        return UnstaffedReason.UNKNOWN_ASSESSOR
    return None


def migrate_project_level_assignments(conn: sqlite3.Connection) -> int:
    """Migrate legacy project-level assignments from survey_cycles.data JSON to unit_assessor_assignments.

    Reads raw data JSON from survey_cycles directly so it is independent of SurveyCycle
    dataclass fields (FR-UA-008, SC-011). Resolves each email against the assessors table
    or creates a new record. Writes UnitAssessorAssignment with source = MIGRATION and
    records two AssignmentChange rows per unit. Skips cycles that already have any unit
    assignments (idempotent).
    """
    import json
    import uuid

    r = Repository(conn)
    cursor = conn.cursor()

    cycles_rows = cursor.execute("SELECT cycle_id, data FROM survey_cycles").fetchall()
    migrated_count = 0

    for c_row in cycles_rows:
        cycle_id = c_row["cycle_id"]
        # If the cycle already has any unit assignments, skip (idempotent)
        has_assignments = cursor.execute(
            "SELECT 1 FROM unit_assessor_assignments WHERE cycle_id = ? LIMIT 1",
            (cycle_id,),
        ).fetchone()
        if has_assignments:
            continue

        data_raw = c_row["data"]
        data = json.loads(data_raw) if isinstance(data_raw, str) else (data_raw or {})
        email_a = data.get("assessor_a_email")
        email_b = data.get("assessor_b_email")
        if not email_a or not email_b:
            continue

        # Resolve or create assessor records for each email
        assessor_ids = []
        for email in (str(email_a).strip(), str(email_b).strip()):
            assessor_row = cursor.execute(
                "SELECT assessor_id FROM assessors WHERE email = ?",
                (email,),
            ).fetchone()
            if assessor_row:
                assessor_ids.append(assessor_row["assessor_id"])
            else:
                new_id_val = f"asr-migrated-{uuid.uuid4().hex[:8]}"
                display_name = email.split("@")[0].replace(".", " ").title()
                r.upsert_assessor(
                    Assessor(
                        assessor_id=new_id_val,
                        display_name=display_name,
                        email=email,
                        notes="Migrated from legacy project-level assignment",
                    )
                )
                assessor_ids.append(new_id_val)

        a_id, b_id = assessor_ids[0], assessor_ids[1]

        # Fetch portals for this cycle
        portal_rows = cursor.execute(
            "SELECT portal_id FROM target_portals WHERE cycle_id = ?",
            (cycle_id,),
        ).fetchall()

        now = datetime.now(UTC)
        for p_row in portal_rows:
            portal_id = p_row["portal_id"]
            assignment = UnitAssessorAssignment(
                assignment_id=new_id("asmt"),
                cycle_id=cycle_id,
                portal_id=portal_id,
                role_a=RoleAssignment(assessor_id=a_id, source=AssignmentSource.MIGRATION, set_at=now),
                role_b=RoleAssignment(assessor_id=b_id, source=AssignmentSource.MIGRATION, set_at=now),
            )
            r.upsert_unit_assignment(assignment)
            r.insert_assignment_change(
                AssignmentChange(
                    change_id=new_id("chg"),
                    cycle_id=cycle_id,
                    portal_id=portal_id,
                    role="A",
                    previous_assessor_id=None,
                    new_assessor_id=a_id,
                    source="migration",
                    changed_by_actor_id=None,
                    changed_at=now,
                )
            )
            r.insert_assignment_change(
                AssignmentChange(
                    change_id=new_id("chg"),
                    cycle_id=cycle_id,
                    portal_id=portal_id,
                    role="B",
                    previous_assessor_id=None,
                    new_assessor_id=b_id,
                    source="migration",
                    changed_by_actor_id=None,
                    changed_at=now,
                )
            )

        migrated_count += 1

    conn.commit()
    if migrated_count > 0:
        _log.info("Migrated project-level assignments for %d cycle(s)", migrated_count)
    return migrated_count


def apply_mapping_entry(
    r: Repository,
    cycle_id: str,
    portal: TargetPortal,
    entry: UnitAssessorMappingEntry,
    roster: dict[str, Assessor],
) -> UnitAssessorAssignment:
    """Applies a mapping entry verbatim to a unit of a cycle (FR-IN-004, SC-004).

    Reads exactly entry.assessor_a_id and entry.assessor_b_id.
    Never overwrites an ADMINISTRATOR assignment (FR-IN-010, SC-006).
    """
    existing = r.get_unit_assignment(cycle_id, portal.portal_id)
    if existing:
        a_admin = existing.role_a and existing.role_a.source == AssignmentSource.ADMINISTRATOR
        b_admin = existing.role_b and existing.role_b.source == AssignmentSource.ADMINISTRATOR
        if a_admin and b_admin:
            return existing

    reason = validate_pair(entry.assessor_a_id, entry.assessor_b_id, roster)
    now = datetime.now(UTC)

    if reason is not None:
        # On defect: staff neither role (leave both None) and record ingest_defect
        assignment = UnitAssessorAssignment(
            assignment_id=existing.assignment_id if existing else new_id("asmt"),
            cycle_id=cycle_id,
            portal_id=portal.portal_id,
            role_a=(
                existing.role_a
                if (existing and existing.role_a and existing.role_a.source == AssignmentSource.ADMINISTRATOR)
                else None
            ),
            role_b=(
                existing.role_b
                if (existing and existing.role_b and existing.role_b.source == AssignmentSource.ADMINISTRATOR)
                else None
            ),
            ingest_defect=reason,
        )
        r.upsert_unit_assignment(assignment)
        return assignment

    role_a = (
        existing.role_a
        if (existing and existing.role_a and existing.role_a.source == AssignmentSource.ADMINISTRATOR)
        else RoleAssignment(
            assessor_id=entry.assessor_a_id,
            source=AssignmentSource.MAPPING,
            set_at=now,
        )
    )
    role_b = (
        existing.role_b
        if (existing and existing.role_b and existing.role_b.source == AssignmentSource.ADMINISTRATOR)
        else RoleAssignment(
            assessor_id=entry.assessor_b_id,
            source=AssignmentSource.MAPPING,
            set_at=now,
        )
    )

    assignment = UnitAssessorAssignment(
        assignment_id=existing.assignment_id if existing else new_id("asmt"),
        cycle_id=cycle_id,
        portal_id=portal.portal_id,
        role_a=role_a,
        role_b=role_b,
        ingest_defect=None,
    )
    r.upsert_unit_assignment(assignment)

    if not existing or not existing.role_a or existing.role_a.source != AssignmentSource.ADMINISTRATOR:
        r.insert_assignment_change(
            AssignmentChange(
                change_id=new_id("chg"),
                cycle_id=cycle_id,
                portal_id=portal.portal_id,
                role="A",
                previous_assessor_id=existing.role_a.assessor_id if (existing and existing.role_a) else None,
                new_assessor_id=entry.assessor_a_id,
                source="mapping",
                changed_by_actor_id=None,
                changed_at=now,
            )
        )
    if not existing or not existing.role_b or existing.role_b.source != AssignmentSource.ADMINISTRATOR:
        r.insert_assignment_change(
            AssignmentChange(
                change_id=new_id("chg"),
                cycle_id=cycle_id,
                portal_id=portal.portal_id,
                role="B",
                previous_assessor_id=existing.role_b.assessor_id if (existing and existing.role_b) else None,
                new_assessor_id=entry.assessor_b_id,
                source="mapping",
                changed_by_actor_id=None,
                changed_at=now,
            )
        )
    return assignment


def create_units(
    r: Repository, cycle_id: str, portals: list[TargetPortal]
) -> list[UnitAssessorAssignment]:
    """Inserts portals and applies unit-assessor mapping verbatim (FR-IN-003, SC-001).

    Reads mapping index and roster index once per call (2 lookups regardless of unit count).
    """
    if not portals:
        return []

    r.insert_portals(portals)
    mapping = r.load_mapping_index()
    roster = r.load_assessor_index()

    assignments: list[UnitAssessorAssignment] = []
    for portal in portals:
        entry = mapping.get((portal.unit_type, portal.country_id))
        if entry is None:
            # Absence is meaningful (R9, FR-IN-008): no assignment row created
            continue
        asmt = apply_mapping_entry(r, cycle_id, portal, entry, roster)
        assignments.append(asmt)

    return assignments


def staffing_summary(r: Repository, cycle_id: str) -> StaffingSummary:
    """Derived summary of project staffing (FR-IN-011, FR-SV-002). Never stored."""
    portals = r.list_portals(cycle_id)
    assignments = r.list_unit_assignments(cycle_id)

    total_units = len(portals)
    staffed_units = 0
    unstaffed: dict[str, UnstaffedReason] = {}

    for portal in portals:
        asmt = assignments.get(portal.portal_id)
        if asmt is None:
            unstaffed[portal.portal_id] = UnstaffedReason.NO_MAPPING_ENTRY
        elif asmt.is_staffed:
            staffed_units += 1
        else:
            unstaffed[portal.portal_id] = asmt.ingest_defect or UnstaffedReason.NO_MAPPING_ENTRY

    return StaffingSummary(
        total_units=total_units,
        staffed_units=staffed_units,
        unstaffed=unstaffed,
    )


def set_role_assignment(
    r: Repository,
    cycle_id: str,
    portal_id: str,
    role: str | AssessorRole,
    assessor_id: str,
    actor_id: str,
) -> UnitAssessorAssignment:
    """Administrator override for a single role on a single unit (FR-MO-001).

    Validates against the roster and ensures the assessor does not duplicate the
    other role on this unit (FR-MO-004, FR-UA-002).
    Writes an append-only assignment_changes row (FR-MO-008, SC-009).
    """
    role_str = "A" if str(role).upper().endswith("A") else "B"

    with r.begin_immediate():
        roster = r.load_assessor_index()
        if assessor_id not in roster:
            raise ValueError("unknown")

        existing = r.get_unit_assignment(cycle_id, portal_id)
        other_id = (
            (existing.role_b.assessor_id if existing and existing.role_b else None)
            if role_str == "A"
            else (existing.role_a.assessor_id if existing and existing.role_a else None)
        )
        if other_id == assessor_id:
            raise ValueError("duplicate")

        if other_id is not None:
            pair_a = assessor_id if role_str == "A" else other_id
            pair_b = other_id if role_str == "A" else assessor_id
            err = validate_pair(pair_a, pair_b, roster)
            if err == UnstaffedReason.DUPLICATE_ASSESSOR:
                raise ValueError("duplicate")
            elif err == UnstaffedReason.UNKNOWN_ASSESSOR:
                raise ValueError("unknown")

        now = datetime.now(UTC)
        prev_id = (
            (existing.role_a.assessor_id if role_str == "A" else existing.role_b.assessor_id)
            if (existing and (existing.role_a if role_str == "A" else existing.role_b))
            else None
        )
        new_role_asmt = RoleAssignment(
            assessor_id=assessor_id,
            source=AssignmentSource.ADMINISTRATOR,
            set_at=now,
            set_by_actor_id=actor_id,
        )
        role_a = new_role_asmt if role_str == "A" else (existing.role_a if existing else None)
        role_b = new_role_asmt if role_str == "B" else (existing.role_b if existing else None)
        defect = None if (role_a is not None and role_b is not None) else (existing.ingest_defect if existing else None)

        assignment = UnitAssessorAssignment(
            assignment_id=existing.assignment_id if existing else new_id("asmt"),
            cycle_id=cycle_id,
            portal_id=portal_id,
            role_a=role_a,
            role_b=role_b,
            ingest_defect=defect,
        )
        r.upsert_unit_assignment(assignment)
        r.insert_assignment_change(
            AssignmentChange(
                change_id=new_id("chg"),
                cycle_id=cycle_id,
                portal_id=portal_id,
                role=role_str,
                previous_assessor_id=prev_id,
                new_assessor_id=assessor_id,
                source="administrator",
                changed_by_actor_id=actor_id,
                changed_at=now,
            )
        )
        return assignment


def clear_role_assignment(
    r: Repository,
    cycle_id: str,
    portal_id: str,
    role: str | AssessorRole,
    actor_id: str,
) -> UnitAssessorAssignment:
    """Administrator clears an assigned role, returning unit to unstaffed (FR-MO-005)."""
    role_str = "A" if str(role).upper().endswith("A") else "B"

    with r.begin_immediate():
        existing = r.get_unit_assignment(cycle_id, portal_id)
        prev_id = (
            (existing.role_a.assessor_id if role_str == "A" else existing.role_b.assessor_id)
            if (existing and (existing.role_a if role_str == "A" else existing.role_b))
            else None
        )
        now = datetime.now(UTC)
        role_a = None if role_str == "A" else (existing.role_a if existing else None)
        role_b = None if role_str == "B" else (existing.role_b if existing else None)

        assignment = UnitAssessorAssignment(
            assignment_id=existing.assignment_id if existing else new_id("asmt"),
            cycle_id=cycle_id,
            portal_id=portal_id,
            role_a=role_a,
            role_b=role_b,
            ingest_defect=UnstaffedReason.CLEARED_BY_ADMINISTRATOR,
        )
        r.upsert_unit_assignment(assignment)
        r.insert_assignment_change(
            AssignmentChange(
                change_id=new_id("chg"),
                cycle_id=cycle_id,
                portal_id=portal_id,
                role=role_str,
                previous_assessor_id=prev_id,
                new_assessor_id=None,
                source="administrator",
                changed_by_actor_id=actor_id,
                changed_at=now,
            )
        )
        return assignment


def resolve_actor_role(
    r: Repository,
    cycle_id: str,
    portal_id: str,
    actor_id: str | None,
) -> AssessorRole | None:
    """Resolves an actor_id to their assigned role for this specific unit (FR-AC-001, FR-AC-002).

    Returns:
    - AssessorRole.A if the actor is assigned as Role A and the unit is fully staffed.
    - AssessorRole.B if the actor is assigned as Role B and the unit is fully staffed.
    - None if the actor is not assigned, the unit is unstaffed or partially staffed (FR-UA-005).

    There is NO project-wide fallback (FR-UA-007, SC-012).
    """
    if not actor_id:
        return None

    assignment = r.get_unit_assignment(cycle_id, portal_id)
    if assignment is None or not assignment.is_staffed:
        return None

    if assignment.role_a and assignment.role_a.assessor_id == actor_id:
        return AssessorRole.A
    if assignment.role_b and assignment.role_b.assessor_id == actor_id:
        return AssessorRole.B

    return None



