"""Unit tests for viewing and deleting questionnaires in the admin portal."""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from shared.persistence.repositories import Repository
from shared.questionnaires.registry import (
    get_questionnaire_detail,
    list_question_sets,
    save_custom_question_set,
)
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
)

pytestmark = pytest.mark.unit

_CUSTOM_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "questionnaires" / "custom"


def _make_test_cycle_with_custom_set(repo: Repository, cycle_id: str):
    cycle = SurveyCycle(
        cycle_id=cycle_id,
        name="Test Delete Custom Questionnaire Cycle",
        questionnaire_ref="UN OSI 2024 Master",
        country_set=["US"],
        project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)
    q = Question(
        question_id=f"{cycle_id}:CUST-DEL-01",
        cycle_id=cycle_id,
        text="Custom Deletion Test Indicator",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        indicator_id="CUST-DEL-01",
        title="Custom Deletion Test Indicator",
        what="Checks something custom",
        why="Necessary for testing deletion",
        how={"criteria_for_yes": "Found", "criteria_for_no": "Not found"},
        is_custom=True,
    )
    repo.insert_question(q)
    saved_info = save_custom_question_set(cycle, [q], label="Temporary Custom Test Questionnaire")
    return cycle, saved_info


def test_registry_metadata_and_detail():
    sets = list_question_sets()
    assert len(sets) > 0

    master = next((s for s in sets if s.set_id == "un_osi_2024_master"), None)
    assert master is not None
    assert master.kind == "template"
    assert master.is_master_template is True
    assert master.is_custom is False
    assert master.question_count > 0

    detail = get_questionnaire_detail("un_osi_2024_master")
    assert detail is not None
    assert detail["set_id"] == "un_osi_2024_master"
    assert detail["total_questions"] > 0
    assert len(detail["questions"]) == detail["total_questions"]
    assert "modules_count" in detail
    assert "evidence_loci_count" in detail
    assert detail["is_deletable"] is False

    unknown = get_questionnaire_detail("nonexistent-set-id")
    assert unknown is None


def test_admin_questionnaires_list_page(client: TestClient):
    resp = client.get("/admin/questionnaires")
    assert resp.status_code == 200
    html = resp.text

    assert "Questionnaires &amp; Indicator Sets" in html or "Questionnaires & Indicator Sets" in html
    assert "un_osi_2024_master" in html
    assert "un_losi_2024_master" in html
    assert "View Indicators" in html
    assert "Master Templates" in html


def test_admin_questionnaire_detail_page(client: TestClient):
    resp = client.get("/admin/questionnaires/un_osi_2024_master")
    assert resp.status_code == 200
    html = resp.text

    assert "Online Service Index" in html or "OSI" in html
    assert "Dimensions &amp; Modules Overview" in html or "Dimensions & Modules Overview" in html
    assert "Indicators" in html

    # Unknown questionnaire should return 404
    resp_404 = client.get("/admin/questionnaires/unknown_not_exist_slug")
    assert resp_404.status_code == 404


def test_delete_custom_questionnaire_flow(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-delete-flow-cycle"

    cycle, saved_info = _make_test_cycle_with_custom_set(repo, cycle_id)
    custom_set_id = saved_info.set_id

    try:
        # 1. Custom set should be in registry and list page
        assert custom_set_id in {s.set_id for s in list_question_sets()}
        resp_list = client.get("/admin/questionnaires")
        assert custom_set_id in resp_list.text

        # 2. Detail page should load and have delete button
        resp_detail = client.get(f"/admin/questionnaires/{custom_set_id}")
        assert resp_detail.status_code == 200
        assert "Delete Questionnaire" in resp_detail.text

        # 3. Post delete endpoint
        resp_delete = client.post(
            f"/admin/questionnaires/{custom_set_id}/delete",
            follow_redirects=False,
        )
        assert resp_delete.status_code == 303
        assert "/admin/questionnaires" in resp_delete.headers["location"]
        assert "deleted=1" in resp_delete.headers["location"]

        # 4. Registry no longer contains it
        assert custom_set_id not in {s.set_id for s in list_question_sets()}
        assert get_questionnaire_detail(custom_set_id) is None

        # 5. File does not exist
        assert not (_CUSTOM_DIR / f"{custom_set_id}.json").exists()

    finally:
        # Cleanup just in case
        (_CUSTOM_DIR / f"{custom_set_id}.json").unlink(missing_ok=True)


def test_delete_system_template_is_protected(client: TestClient):
    resp = client.post(
        "/admin/questionnaires/un_osi_2024_master/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]

    # System template must still exist and be intact
    assert "un_osi_2024_master" in {s.set_id for s in list_question_sets()}
    assert get_questionnaire_detail("un_osi_2024_master") is not None


def test_delete_nonexistent_questionnaire_redirects_with_error(client: TestClient):
    resp = client.post(
        "/admin/questionnaires/totally-bogus-set/delete",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
