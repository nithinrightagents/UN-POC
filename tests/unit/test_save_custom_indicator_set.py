"""Unit tests for explicitly saving a project's current indicator set as a
named, reusable custom questionnaire.

Before this feature, save_custom_question_set() only ever ran as a side
effect of add_question() -- so an admin who only retired, reactivated, or
edited indicators (without adding a brand-new custom one) had no way to
persist that resulting set for reuse in future projects. This covers:

1. POST /admin/projects/{cycle_id}/questions/save-custom-set persists the
   current live (non-retired) indicators as a custom set, even when no new
   custom question was ever added.
2. The saved set is discoverable via list_question_sets(scope=...) for
   future project creation of the same project type.
3. Saving again overwrites the same set rather than accumulating stale
   duplicates.
4. An optional label lets the admin name the saved set; omitting it falls
   back to the auto-generated label.
5. The Manage Workspace page renders the save-custom-set control and the
   success banner after a save.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.persistence.repositories import Repository
from shared.questionnaires.registry import list_question_sets
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
)

pytestmark = pytest.mark.unit


def _make_cycle_with_questions(repo: Repository, cycle_id: str, n: int = 3):
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id, name="Save Custom Set Cycle", questionnaire_ref="ref",
            country_set=[], project_type=ProjectType.NATIONAL_OSI,
        )
    )
    q_ids = []
    for i in range(n):
        q = Question(
            question_id=f"{cycle_id}:q{i}",
            cycle_id=cycle_id,
            text=f"Indicator {i}",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
        repo.insert_question(q)
        q_ids.append(q.question_id)
    return q_ids


def test_save_custom_set_after_retire_only_persists_live_indicators(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-save-custom-after-retire"
    q_ids = _make_cycle_with_questions(repo, cycle_id, n=3)

    repo.set_question_status(q_ids[0], "retired", revised_by="senior-reviewer")

    resp = client.post(
        f"/admin/projects/{cycle_id}/questions/save-custom-set",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}?custom_set_saved=1"

    cycle = repo.get_cycle(cycle_id)
    assert cycle.questionnaire_ref != "ref"

    sets = list_question_sets(scope="national_osi")
    saved = next(s for s in sets if s.set_id == f"custom_{cycle_id}")
    assert saved.question_count == 2  # retired indicator excluded
    assert saved.label == cycle.questionnaire_ref


def test_save_custom_set_accepts_custom_label(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-save-custom-label"
    _make_cycle_with_questions(repo, cycle_id, n=2)

    resp = client.post(
        f"/admin/projects/{cycle_id}/questions/save-custom-set",
        data={"label": "Hardened National Set 2026"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    cycle = repo.get_cycle(cycle_id)
    assert cycle.questionnaire_ref == "Hardened National Set 2026"

    sets = list_question_sets(scope="national_osi")
    saved = next(s for s in sets if s.set_id == f"custom_{cycle_id}")
    assert saved.label == "Hardened National Set 2026"


def test_save_custom_set_twice_overwrites_rather_than_duplicates(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-save-custom-overwrite"
    q_ids = _make_cycle_with_questions(repo, cycle_id, n=3)

    client.post(f"/admin/projects/{cycle_id}/questions/save-custom-set", data={}, follow_redirects=False)
    before = [s for s in list_question_sets() if s.set_id == f"custom_{cycle_id}"]
    assert len(before) == 1
    assert before[0].question_count == 3

    repo.set_question_status(q_ids[0], "retired", revised_by="senior-reviewer")
    client.post(f"/admin/projects/{cycle_id}/questions/save-custom-set", data={}, follow_redirects=False)

    after = [s for s in list_question_sets() if s.set_id == f"custom_{cycle_id}"]
    assert len(after) == 1  # still exactly one file -- overwritten, not duplicated
    assert after[0].question_count == 2


def test_save_custom_set_unknown_cycle_redirects_to_admin(client: TestClient, conn):
    resp = client.post(
        "/admin/projects/does-not-exist/questions/save-custom-set",
        data={},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"


def test_project_detail_renders_save_custom_set_control_and_success_banner(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-save-custom-ui"
    _make_cycle_with_questions(repo, cycle_id, n=1)

    resp = client.get(f"/admin/projects/{cycle_id}")
    assert resp.status_code == 200
    assert f'/admin/projects/{cycle_id}/questions/save-custom-set' in resp.text

    resp_saved = client.get(f"/admin/projects/{cycle_id}?custom_set_saved=1")
    assert resp_saved.status_code == 200
    assert "Custom Indicator Set Saved" in resp_saved.text
