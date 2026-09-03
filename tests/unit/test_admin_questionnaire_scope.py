"""Unit tests for scoped questionnaire selection and custom set persistence.

Covers two behaviors:
1. The admin "create project" picker only ever offers the questionnaire
   matching the chosen Assessment Scope (national_osi vs losi_city) --
   never the other type's questionnaire, and never the raw module
   fragments the master templates are extracted from.
2. Adding a custom indicator to a project persists that project's full
   indicator set as a new, named, reusable question set -- discoverable
   via the registry and scoped to the project's own type -- rather than
   only renaming the in-memory questionnaire_ref label.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from shared.persistence.repositories import Repository
from shared.questionnaires.registry import list_question_sets, load_question_set
from shared.state.entities import ProjectType, SurveyCycle

pytestmark = pytest.mark.unit

_CUSTOM_DIR = pathlib.Path(__file__).resolve().parents[2] / "data" / "questionnaires" / "custom"


def _cleanup_custom_set(cycle_id: str) -> None:
    path = _CUSTOM_DIR / f"custom_{cycle_id}.json"
    path.unlink(missing_ok=True)


def test_master_templates_are_scoped_to_their_project_type():
    national_sets = {s.set_id for s in list_question_sets(scope="national_osi")}
    local_sets = {s.set_id for s in list_question_sets(scope="losi_city")}

    assert "un_osi_2024_master" in national_sets
    assert "un_losi_2024_master" not in national_sets

    assert "un_losi_2024_master" in local_sets
    assert "un_osi_2024_master" not in local_sets

    # Module fragments (the source material the masters were extracted
    # from) have no project_type tag and must not leak into either scope.
    assert not any(s.startswith("module_2_") for s in national_sets)
    assert not any(s.startswith("module_2_") for s in local_sets)


def test_admin_projects_page_only_shows_scoped_options_per_type(client: TestClient):
    resp = client.get("/admin")
    assert resp.status_code == 200
    html = resp.text

    assert 'data-scope="national_osi"' in html
    assert 'data-scope="losi_city"' in html
    # Unscoped module fragments must not render as selectable options at all.
    assert "Institutional Framework</option>" not in html


def test_add_question_saves_reusable_scoped_custom_set(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-custom-questionnaire-cycle"

    try:
        repo.insert_cycle(
            SurveyCycle(
                cycle_id=cycle_id,
                name="Custom Set Source Project",
                questionnaire_ref="UN OSI 2024 Master",
                country_set=["US"],
                project_type=ProjectType.NATIONAL_OSI,
            )
        )

        resp = client.post(
            f"/admin/projects/{cycle_id}/questions",
            data={
                "question_id": "CUST-001",
                "title": "Custom Indicator",
                "what": "Does the thing",
                "why": "Because it matters",
                "how": "Check the portal",
                "module": "Custom Dimension",
                "evidence_locus": "national_portal_only",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        cycle = repo.get_cycle(cycle_id)
        assert cycle is not None
        assert "Custom Indicator Set" in cycle.questionnaire_ref
        assert cycle.name in cycle.questionnaire_ref

        # The saved set must show up in the registry, scoped to this
        # project's own type (national_osi), so a *future* national
        # project can select it from the create-project picker.
        expected_set_id = f"custom_{cycle_id}"
        national_scoped = {s.set_id: s for s in list_question_sets(scope="national_osi")}
        assert expected_set_id in national_scoped
        assert expected_set_id not in {s.set_id for s in list_question_sets(scope="losi_city")}

        saved_info = national_scoped[expected_set_id]
        assert saved_info.question_count == 1  # only the one custom indicator was inserted

        # And it must be loadable for a brand new cycle without ID collisions.
        reloaded = load_question_set(expected_set_id, "some-future-cycle")
        assert len(reloaded) == 1
        assert len(reloaded) == len({q.question_id for q in reloaded})
    finally:
        _cleanup_custom_set(cycle_id)
