"""Unit tests for Assessor Portal navigation, auto-advance, and live saving."""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from portal.common import ensure_session, repo_factory
from portal.webapp import build_app
from shared.config.settings import Settings
from shared.persistence.schema import init_db
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
)


@pytest.fixture
def seeded_portal_app(tmp_path: pathlib.Path):
    db_path = str(tmp_path / "test_assessor.db")
    init_db(db_path)
    settings = Settings(database_path=db_path)
    repo = repo_factory(db_path)()

    cycle = SurveyCycle(
        cycle_id="test-cycle-2026",
        name="Test Survey Cycle 2026",
        project_type=ProjectType.NATIONAL_OSI,
        questionnaire_ref="UN MSQ 2026 Indicator Set",
        country_set=["US"],
    )
    repo.insert_cycle(cycle)
    session_id = ensure_session(repo, cycle.cycle_id)

    portal = TargetPortal(
        portal_id="portal-us-01",
        cycle_id=cycle.cycle_id,
        country_id="US",
        unit_type="country",
        display_name="United States Portal",
        resolved_url="https://www.usa.gov",
    )
    repo.insert_portal(portal)

    for i in range(1, 4):
        q = Question(
            question_id=f"Q-00{i}",
            cycle_id=cycle.cycle_id,
            text=f"Question {i} evaluation prompt",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id=f"Q{i:02d}",
        )
        repo.insert_question(q)

    app = build_app(db_path, settings)
    return TestClient(app), session_id, cycle.cycle_id, portal.portal_id


def test_assessor_ajax_submission_returns_json(seeded_portal_app):
    """Submitting with Accept: application/json returns JSON with next_unsubmitted_id."""
    client, session_id, cycle_id, portal_id = seeded_portal_app

    # Submit Q-001
    res = client.post(
        f"/assessor/{cycle_id}/{portal_id}/question/Q-001/submit",
        data={
            "role": "A",
            "actor_id": "assessor-1",
            "answer": "true",
            "evidence_url": "https://www.usa.gov/services",
            "notes": "Verified online.",
        },
        headers={"Accept": "application/json"},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["saved_question_id"] == "Q-001"
    assert data["answer"] is True
    assert data["evidence_url"] == "https://www.usa.gov/services"
    assert data["answered_count"] == 1
    assert data["total_questions"] == 3
    assert data["next_unsubmitted_id"] == "Q-002"
    assert data["can_complete"] is False
    assert "Q-001" not in data["outstanding_question_ids"]
    assert "Q-002" in data["outstanding_question_ids"]


def test_assessor_form_submission_redirects_to_anchor(seeded_portal_app):
    """Submitting without JSON header returns 303 redirect with #q_{next_unsubmitted} anchor."""
    client, session_id, cycle_id, portal_id = seeded_portal_app

    # Submit Q-001 via standard form POST
    res = client.post(
        f"/assessor/{cycle_id}/{portal_id}/question/Q-001/submit",
        data={
            "role": "A",
            "actor_id": "assessor-1",
            "answer": "false",
            "evidence_url": "",
            "notes": "Absent.",
        },
        follow_redirects=False,
    )

    assert res.status_code == 303
    location = res.headers["location"]
    assert location == f"/assessor/{cycle_id}/{portal_id}?role=A&actor_id=assessor-1#q_Q-002"


def test_assessor_submission_all_completed_targets_progress_panel(seeded_portal_app):
    """When all questions are answered, submission indicates completion and targets progress panel."""
    client, session_id, cycle_id, portal_id = seeded_portal_app

    # Submit Q-001, Q-002, Q-003
    for i in range(1, 4):
        res = client.post(
            f"/assessor/{cycle_id}/{portal_id}/question/Q-00{i}/submit",
            data={
                "role": "A",
                "actor_id": "assessor-1",
                "answer": "true",
                "evidence_url": "https://www.usa.gov",
                "notes": "Done",
            },
            headers={"Accept": "application/json"},
        )
        assert res.status_code == 200

    data = res.json()
    assert data["answered_count"] == 3
    assert data["total_questions"] == 3
    assert data["can_complete"] is True
    assert data["next_unsubmitted_id"] is None
    assert len(data["outstanding_question_ids"]) == 0
