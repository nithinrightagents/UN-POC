"""Unit tests for bulk add/remove of monitored units and bulk retire/reactivate
of indicators in Manage Workspace.

Covers:
1. POST /admin/projects/{cycle_id}/units/bulk-add -- tag many countries as
   target units in one request (country or city unit_type for all of them).
2. POST /admin/projects/{cycle_id}/units/bulk-remove -- remove many units in
   one request, reusing the same per-unit cleanup as the single-unit route.
3. POST /admin/projects/{cycle_id}/questions/bulk-retire and bulk-reactivate
   -- flip lifecycle status for many indicators in one request.
4. The Manage Workspace page renders the bulk-selection UI (checkboxes,
   bulk-add country grid) and excludes already-monitored countries from the
   bulk-add grid.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.persistence.repositories import Repository
from shared.reference.countries import list_countries
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


def _make_cycle(repo: Repository, cycle_id: str, project_type: ProjectType, country_set=None):
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id, name="Bulk Ops Cycle", questionnaire_ref="ref",
            country_set=country_set or [], project_type=project_type,
        )
    )


def test_bulk_add_units_tags_selected_countries_as_country_units(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-add-country"
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI)

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-add",
        data={"country_codes": ["DK", "SE"], "unit_type": "country"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    portals = repo.list_portals(cycle_id)
    assert {p.country_id for p in portals} == {"DK", "SE"}
    assert all(p.unit_type == "country" for p in portals)
    dk = next(p for p in portals if p.country_id == "DK")
    assert dk.display_name == "Denmark"

    cycle = repo.get_cycle(cycle_id)
    assert set(cycle.country_set) == {"DK", "SE"}


def test_bulk_add_units_tags_selected_countries_as_city_units(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-add-city"
    _make_cycle(repo, cycle_id, ProjectType.LOSI_CITY)

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-add",
        data={"country_codes": ["DK"], "unit_type": "city"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    portals = repo.list_portals(cycle_id)
    assert len(portals) == 1
    assert portals[0].unit_type == "city"
    assert "," in portals[0].display_name  # "City, Country"


def test_bulk_add_units_is_noop_when_no_countries_selected(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-add-empty"
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI)

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-add",
        data={"unit_type": "country"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert repo.list_portals(cycle_id) == []


def test_bulk_add_units_ignores_unknown_country_codes(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-add-unknown"
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI)

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-add",
        data={"country_codes": ["DK", "ZZZZ"], "unit_type": "country"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    portals = repo.list_portals(cycle_id)
    assert len(portals) == 1
    assert portals[0].country_id == "DK"


def test_bulk_remove_units_removes_only_selected_portals(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-remove"
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI, country_set=["DK", "SE", "US"])

    portals = [
        TargetPortal(
            portal_id=new_id("portal"), cycle_id=cycle_id, country_id=code,
            resolved_url=None, unit_type="country", display_name=code,
        )
        for code in ("DK", "SE", "US")
    ]
    repo.insert_portals(portals)
    to_remove = [p.portal_id for p in portals if p.country_id in ("DK", "SE")]

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-remove",
        data={"portal_ids": to_remove},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    remaining = repo.list_portals(cycle_id)
    assert len(remaining) == 1
    assert remaining[0].country_id == "US"

    cycle = repo.get_cycle(cycle_id)
    assert set(cycle.country_set) == {"US"}


def test_bulk_remove_units_is_noop_when_no_portals_selected(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-remove-empty"
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI, country_set=["DK"])
    repo.insert_portal(
        TargetPortal(
            portal_id=new_id("portal"), cycle_id=cycle_id, country_id="DK",
            resolved_url=None, unit_type="country", display_name="Denmark",
        )
    )

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/bulk-remove",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert len(repo.list_portals(cycle_id)) == 1


def test_bulk_retire_and_reactivate_questions(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-questions"
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI)

    q_ids = []
    for i in range(3):
        q = Question(
            question_id=new_id("q"),
            cycle_id=cycle_id,
            text=f"Indicator {i}",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
        repo.insert_question(q)
        q_ids.append(q.question_id)

    to_retire = q_ids[:2]
    resp = client.post(
        f"/admin/projects/{cycle_id}/questions/bulk-retire",
        data={"question_ids": to_retire, "actor_id": "senior-reviewer"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    questions_by_id = {q.question_id: q for q in repo.list_questions(cycle_id, include_retired=True)}
    assert questions_by_id[to_retire[0]].status == "retired"
    assert questions_by_id[to_retire[1]].status == "retired"
    assert questions_by_id[q_ids[2]].status != "retired"

    resp = client.post(
        f"/admin/projects/{cycle_id}/questions/bulk-reactivate",
        data={"question_ids": to_retire, "actor_id": "senior-reviewer"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    questions_by_id = {q.question_id: q for q in repo.list_questions(cycle_id, include_retired=True)}
    assert questions_by_id[to_retire[0]].status == "active"
    assert questions_by_id[to_retire[1]].status == "active"


def test_project_detail_renders_bulk_selection_ui(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-ui-render"
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI, country_set=["DK"])
    repo.insert_portal(
        TargetPortal(
            portal_id=new_id("portal"), cycle_id=cycle_id, country_id="DK",
            resolved_url=None, unit_type="country", display_name="Denmark",
        )
    )
    repo.insert_question(
        Question(
            question_id=new_id("q"), cycle_id=cycle_id, text="Indicator",
            answer_type=AnswerType.BINARY, evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
    )

    resp = client.get(f"/admin/projects/{cycle_id}")
    assert resp.status_code == 200
    body = resp.text
    assert 'class="question-select"' in body
    assert 'id="questionsSelectAll"' in body
    assert 'class="unit-select"' in body
    assert 'id="unitsSelectAll"' in body
    assert f'/admin/projects/{cycle_id}/units/bulk-add' in body
    assert f'/admin/projects/{cycle_id}/units/bulk-remove' in body
    assert f'/admin/projects/{cycle_id}/questions/bulk-retire' in body
    assert f'/admin/projects/{cycle_id}/questions/bulk-reactivate' in body
    # Sweden not yet monitored -- should appear as a bulk-add option.
    assert 'value="SE"' in body
    # Denmark already monitored -- must be excluded from the bulk-add grid.
    assert 'value="DK"' not in body


def test_project_detail_bulk_add_grid_empty_when_all_countries_monitored(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-bulk-ui-all-monitored"
    all_codes = [c.code for c in list_countries()]
    _make_cycle(repo, cycle_id, ProjectType.NATIONAL_OSI, country_set=all_codes)
    repo.insert_portals([
        TargetPortal(
            portal_id=new_id("portal"), cycle_id=cycle_id, country_id=c.code,
            resolved_url=None, unit_type="country", display_name=c.name,
        )
        for c in list_countries()
    ])

    resp = client.get(f"/admin/projects/{cycle_id}")
    assert resp.status_code == 200
    assert "Every country is already monitored in this project." in resp.text
