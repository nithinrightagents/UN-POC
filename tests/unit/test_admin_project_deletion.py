"""Unit tests for admin project removal and optional portal URLs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portal.common import ensure_session
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    AssessorRole,
    EvidenceLocus,
    HumanAssessorSubmission,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


def test_repo_delete_cycle_removes_all_associated_data(conn):
    repo = Repository(conn)
    cycle_id = "test-delete-cycle"

    # Insert cycle
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Project to Delete",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
        )
    )

    # Insert session
    session_id = ensure_session(repo, cycle_id)

    # Insert portal
    portal_id = new_id("portal")
    portal = TargetPortal(
        portal_id=portal_id,
        cycle_id=cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    repo.insert_portal(portal)

    # Insert question
    q_id = new_id("q")
    repo.insert_question(
        Question(
            question_id=q_id,
            cycle_id=cycle_id,
            text="Test indicator",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
    )

    # Insert submission
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=q_id,
            portal_id=portal_id,
            role=AssessorRole.A,
            assessor_actor_id="assessor-1",
            answer=True,
            evidence_url="https://example.com/evidence",
            notes="Verified",
        )
    )

    assert repo.get_cycle(cycle_id) is not None
    assert len(repo.list_portals(cycle_id)) == 1
    assert len(repo.list_questions(cycle_id)) == 1
    assert len(repo.list_human_submissions(session_id, portal_id, role=AssessorRole.A)) == 1

    # Perform delete
    repo.delete_cycle(cycle_id)

    assert repo.get_cycle(cycle_id) is None
    assert not any(c.cycle_id == cycle_id for c in repo.list_cycles())
    assert len(repo.list_portals(cycle_id)) == 0
    assert len(repo.list_questions(cycle_id)) == 0
    assert len(repo.list_human_submissions(session_id, portal_id, role=AssessorRole.A)) == 0


def test_admin_delete_project_endpoint_redirects_and_deletes(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-portal-delete"

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Delete Via Admin",
            questionnaire_ref="ref",
            country_set=["US"],
            project_type=ProjectType.NATIONAL_OSI,
        )
    )

    # Verify project appears on /admin with Manage Workspace but no remove button on list table
    resp_admin = client.get("/admin")
    assert resp_admin.status_code == 200
    assert cycle_id in resp_admin.text
    assert f"/admin/projects/{cycle_id}/delete" not in resp_admin.text
    assert "Manage Workspace" in resp_admin.text

    # Verify project detail page contains the remove/delete action
    resp_detail = client.get(f"/admin/projects/{cycle_id}")
    assert resp_detail.status_code == 200
    assert f"/admin/projects/{cycle_id}/delete" in resp_detail.text

    # Post to delete endpoint
    resp_delete = client.post(f"/admin/projects/{cycle_id}/delete", follow_redirects=False)
    assert resp_delete.status_code == 303
    assert resp_delete.headers["location"] == "/admin"

    # Verify project is gone
    resp_admin_after = client.get("/admin")
    assert resp_admin_after.status_code == 200
    assert cycle_id not in resp_admin_after.text
    assert repo.get_cycle(cycle_id) is None


def test_admin_add_unit_with_optional_url(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-optional-url-cycle"

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Optional URL Cycle",
            questionnaire_ref="ref",
            country_set=[],
            project_type=ProjectType.NATIONAL_OSI,
        )
    )

    # Add unit with empty url
    resp_add = client.post(
        f"/admin/projects/{cycle_id}/units",
        data={
            "country_id": "SE",
            "display_name": "Sweden",
            "url": "",
            "unit_type": "country",
        },
        follow_redirects=False,
    )
    assert resp_add.status_code == 303
    assert resp_add.headers["location"] == f"/admin/projects/{cycle_id}"

    portals = repo.list_portals(cycle_id)
    assert len(portals) == 1
    assert portals[0].country_id == "SE"
    assert portals[0].resolved_url is None


def test_admin_project_detail_html_omits_no_url_notice(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-no-banner-cycle"

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="No Banner Cycle",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
        )
    )

    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle_id,
        country_id="DK",
        resolved_url=None,
        unit_type="country",
        display_name="Denmark",
    )
    repo.insert_portal(portal)

    resp = client.get(f"/admin/projects/{cycle_id}")
    assert resp.status_code == 200
    assert "No URL configured" not in resp.text
    assert "link resolution searches live per question" not in resp.text
    assert f"/admin/projects/{cycle_id}/delete" in resp.text
    assert "Delete Survey Project" in resp.text


def test_api_delete_cycle_endpoint(client: TestClient, conn, auth: dict[str, str]):
    repo = Repository(conn)
    cycle_id = "test-api-del-cycle"

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="API Del Cycle",
            questionnaire_ref="ref",
            country_set=["NO"],
            project_type=ProjectType.NATIONAL_OSI,
        )
    )

    # Delete via API
    resp = client.delete(f"/api/v1/cycles/{cycle_id}", headers=auth)
    assert resp.status_code == 204
    assert repo.get_cycle(cycle_id) is None

    # Deleting again should return 404
    resp_again = client.delete(f"/api/v1/cycles/{cycle_id}", headers=auth)
    assert resp_again.status_code == 404
