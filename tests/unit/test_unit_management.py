"""Unit tests for unit-level project initialization and removal.

Covers two behaviors:
1. Both National (country) and LOSI (city) projects now default to
   tagging every UN member state at creation time -- LOSI contributing
   each country's most-populous city -- rather than requiring the admin
   to hand-pick countries for LOSI up front.
2. Manage Workspace now supports removing a single unit, via
   Repository.delete_portal() and the /admin/projects/{cycle_id}/units/
   {portal_id}/remove route, cleaning up the portal (and pruning the
   cycle's country_set when no other unit still targets that country)
   without touching any other unit or the project's questions.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portal.common import ensure_session
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


def test_losi_project_creation_defaults_to_all_countries(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-losi-default-all"

    resp = client.post(
        "/admin/projects",
        data={
            "cycle_id": cycle_id,
            "name": "LOSI Default All Cities",
            "question_set_id": "un_losi_2024_master",
            "project_type": "losi_city",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    cycle = repo.get_cycle(cycle_id)
    assert cycle is not None
    assert cycle.project_type is ProjectType.LOSI_CITY

    all_countries = list_countries()
    portals = repo.list_portals(cycle_id)
    assert len(portals) == len(all_countries)
    assert set(cycle.country_set) == {c.code for c in all_countries}
    assert all(p.unit_type == "city" for p in portals)
    assert all("," in p.display_name for p in portals)  # "City, Country"


def test_national_project_creation_still_defaults_to_all_countries(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-national-default-all"

    resp = client.post(
        "/admin/projects",
        data={
            "cycle_id": cycle_id,
            "name": "National Default All",
            "question_set_id": "un_osi_2024_master",
            "project_type": "national_osi",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    portals = repo.list_portals(cycle_id)
    assert len(portals) == len(list_countries())
    assert all(p.unit_type == "country" for p in portals)


def test_repo_delete_portal_removes_only_that_units_data(conn):
    repo = Repository(conn)
    cycle_id = "test-delete-portal"

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Portal Delete Cycle",
            questionnaire_ref="ref",
            country_set=["DK", "SE"],
            project_type=ProjectType.LOSI_CITY,
        )
    )
    ensure_session(repo, cycle_id)

    portal_dk = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="DK",
        resolved_url=None, unit_type="city", display_name="Copenhagen, Denmark",
    )
    portal_se = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="SE",
        resolved_url=None, unit_type="city", display_name="Stockholm, Sweden",
    )
    repo.insert_portals([portal_dk, portal_se])

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

    repo.delete_portal(cycle_id, portal_dk.portal_id)

    remaining = repo.list_portals(cycle_id)
    assert len(remaining) == 1
    assert remaining[0].portal_id == portal_se.portal_id
    # The other unit's cycle-level state must be untouched.
    assert len(repo.list_questions(cycle_id)) == 1
    assert repo.get_cycle(cycle_id) is not None


def test_repo_delete_portal_is_noop_for_unknown_or_foreign_portal(conn):
    repo = Repository(conn)
    cycle_id = "test-delete-portal-noop"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id, name="Noop Cycle", questionnaire_ref="ref",
            country_set=["US"], project_type=ProjectType.NATIONAL_OSI,
        )
    )
    portal = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="US",
        resolved_url=None, unit_type="country", display_name="United States",
    )
    repo.insert_portal(portal)

    # Unknown portal id: no error, nothing removed.
    repo.delete_portal(cycle_id, "portal-does-not-exist")
    assert len(repo.list_portals(cycle_id)) == 1

    # Portal exists but under a different cycle_id: no-op.
    repo.delete_portal("some-other-cycle", portal.portal_id)
    assert len(repo.list_portals(cycle_id)) == 1


def test_admin_remove_unit_endpoint_prunes_country_set_when_last_unit(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-remove-unit-endpoint"

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id, name="Remove Unit Cycle", questionnaire_ref="ref",
            country_set=["DK"], project_type=ProjectType.NATIONAL_OSI,
        )
    )
    portal = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="DK",
        resolved_url=None, unit_type="country", display_name="Denmark",
    )
    repo.insert_portal(portal)

    resp_detail = client.get(f"/admin/projects/{cycle_id}")
    assert resp_detail.status_code == 200
    assert f"/admin/projects/{cycle_id}/units/{portal.portal_id}/remove" in resp_detail.text

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/{portal.portal_id}/remove",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}"

    assert repo.list_portals(cycle_id) == []
    cycle = repo.get_cycle(cycle_id)
    assert cycle is not None
    assert "DK" not in cycle.country_set


def test_admin_remove_unit_leaves_other_countries_units_and_country_set_intact(
    client: TestClient, conn
):
    # target_portals enforces UNIQUE(cycle_id, country_id), so a country can
    # never have two units in the same cycle -- the realistic case to guard
    # is that removing one country's unit doesn't disturb a different
    # country's unit or its country_set entry.
    repo = Repository(conn)
    cycle_id = "test-remove-unit-other-country-intact"

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id, name="Two Country Cycle", questionnaire_ref="ref",
            country_set=["DK", "SE"], project_type=ProjectType.LOSI_CITY,
        )
    )
    portal_dk = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="DK",
        resolved_url=None, unit_type="city", display_name="Copenhagen, Denmark",
    )
    portal_se = TargetPortal(
        portal_id=new_id("portal"), cycle_id=cycle_id, country_id="SE",
        resolved_url=None, unit_type="city", display_name="Stockholm, Sweden",
    )
    repo.insert_portals([portal_dk, portal_se])

    resp = client.post(
        f"/admin/projects/{cycle_id}/units/{portal_dk.portal_id}/remove",
        follow_redirects=False,
    )
    assert resp.status_code == 303

    remaining = repo.list_portals(cycle_id)
    assert len(remaining) == 1
    assert remaining[0].portal_id == portal_se.portal_id
    cycle = repo.get_cycle(cycle_id)
    assert "DK" not in cycle.country_set
    assert "SE" in cycle.country_set
