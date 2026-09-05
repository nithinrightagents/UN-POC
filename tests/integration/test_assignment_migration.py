"""Integration tests for startup migration of legacy project-level assignments (Scenario 7)."""

from __future__ import annotations

import json

import pytest

from portal.assignment import ingest_assessor_source, migrate_project_level_assignments
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db
from shared.state.entities import (
    AssessorRole,
    HumanAssessorSubmission,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def conn(tmp_path):
    path = str(tmp_path / "test_migration.db")
    init_db(path)
    c = connect(path)
    try:
        yield c
    finally:
        c.close()


def test_migration_migrates_legacy_assignments_and_preserves_submissions(conn):
    repo = Repository(conn)
    ingest_assessor_source(repo)

    cycle_id = "legacy-cycle-1"
    raw_cycle = {
        "cycle_id": cycle_id,
        "name": "Legacy Project",
        "questionnaire_ref": "ref-1",
        "country_set": ["DK", "SE"],
        "status": "locked",
        "project_type": "national_osi",
        "assessor_a_email": "a.okonkwo@ekap-demo.org",  # Existing in assessors.json (asr-001)
        "assessor_b_email": "unmatched.assessor@external.org",  # Unmatched email
    }
    conn.execute(
        "INSERT INTO survey_cycles (cycle_id, data) VALUES (?, ?)",
        (cycle_id, json.dumps(raw_cycle)),
    )

    portal_dk = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="DK",
        resolved_url=None, unit_type="country", display_name="Denmark",
    )
    portal_se = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="SE",
        resolved_url=None, unit_type="country", display_name="Sweden",
    )
    repo.insert_portal(portal_dk)
    repo.insert_portal(portal_se)

    # Insert a human submission before migration
    sub_before = HumanAssessorSubmission(
        submission_id=new_id("sub"),
        session_id=f"session-{cycle_id}",
        cycle_id=cycle_id,
        question_id="q-1",
        portal_id=portal_dk.portal_id,
        role=AssessorRole.A,
        assessor_actor_id="legacy-actor",
        answer=True,
    )
    repo.insert_human_submission(sub_before)

    # Count of submissions before migration
    rows_before = conn.execute("SELECT * FROM human_assessor_submissions").fetchall()

    # Run migration
    count = migrate_project_level_assignments(conn)
    assert count == 1

    # Assert submissions are row-for-row identical (SC-011)
    rows_after = conn.execute("SELECT * FROM human_assessor_submissions").fetchall()
    assert len(rows_after) == len(rows_before)
    assert [dict(r) for r in rows_after] == [dict(r) for r in rows_before]

    # Check that unmatched email created a roster record
    unmatched_assessor = conn.execute(
        "SELECT * FROM assessors WHERE email = ?", ("unmatched.assessor@external.org",)
    ).fetchone()
    assert unmatched_assessor is not None
    b_id = unmatched_assessor["assessor_id"]

    # Check that both units got both roles with source = MIGRATION
    dk_assignment = repo.get_unit_assignment(cycle_id, portal_dk.portal_id)
    assert dk_assignment is not None
    assert dk_assignment.is_staffed
    assert dk_assignment.role_a.assessor_id == "asr-001"
    assert dk_assignment.role_a.source == "migration"
    assert dk_assignment.role_b.assessor_id == b_id
    assert dk_assignment.role_b.source == "migration"

    se_assignment = repo.get_unit_assignment(cycle_id, portal_se.portal_id)
    assert se_assignment is not None
    assert se_assignment.is_staffed
    assert se_assignment.role_a.assessor_id == "asr-001"
    assert se_assignment.role_b.assessor_id == b_id

    # Check assignment_changes audit log
    changes = repo.list_assignment_changes(cycle_id, portal_dk.portal_id)
    assert len(changes) == 2
    assert changes[0].source == "migration"
    assert changes[1].source == "migration"

    # Second migration run migrates nothing further (idempotent)
    count2 = migrate_project_level_assignments(conn)
    assert count2 == 0
