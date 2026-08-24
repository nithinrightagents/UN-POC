"""Unit tests for per-project tolerance configuration (US7, Scenario 9)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from portal.common import ensure_session
from portal.discrepancy import compute_portal_discrepancy, recompute_portal_discrepancy
from portal.tolerance import effective_tolerance
from shared.config.settings import Settings
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


def test_unset_project_inherits_default_tolerance(conn, settings: Settings):
    repo = Repository(conn)
    cycle_id = "c-unset"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Unset Cycle",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=None,
        )
    )
    assert effective_tolerance(repo, cycle_id, settings) == 0.05


def test_two_projects_at_different_tolerances_judge_independently(conn, settings: Settings):
    repo = Repository(conn)
    # Project X: 5%
    repo.insert_cycle(
        SurveyCycle(
            cycle_id="c-x",
            name="Cycle X",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.05,
        )
    )
    # Project Y: 15%
    repo.insert_cycle(
        SurveyCycle(
            cycle_id="c-y",
            name="Cycle Y",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.15,
        )
    )

    assert effective_tolerance(repo, "c-x", settings) == 0.05
    assert effective_tolerance(repo, "c-y", settings) == 0.15


def test_tolerance_update_route_validation_and_audit(client: TestClient, conn, settings: Settings):
    repo = Repository(conn)
    cycle_id = "c-tol-audit"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Cycle Audit",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=None,
        )
    )

    # 1. Invalid values rejected with previous value standing (FR-DR-064)
    resp_neg = client.post(
        f"/admin/projects/{cycle_id}/tolerance",
        data={"tolerance": "-5", "actor_id": "reviewer-sam"},
        follow_redirects=False,
    )
    assert resp_neg.status_code == 303
    assert "tolerance_error=invalid_range" in resp_neg.headers["location"]
    assert effective_tolerance(repo, cycle_id, settings) == 0.05

    resp_101 = client.post(
        f"/admin/projects/{cycle_id}/tolerance",
        data={"tolerance": "101", "actor_id": "reviewer-sam"},
        follow_redirects=False,
    )
    assert resp_101.status_code == 303
    assert "tolerance_error=invalid_range" in resp_101.headers["location"]
    assert effective_tolerance(repo, cycle_id, settings) == 0.05

    # 2. First change from inheriting project records previous_value=None (FR-DR-066)
    resp_valid = client.post(
        f"/admin/projects/{cycle_id}/tolerance",
        data={"tolerance": "8.0", "actor_id": "senior-reviewer-anna"},
        follow_redirects=False,
    )
    assert resp_valid.status_code == 303
    assert effective_tolerance(repo, cycle_id, settings) == 0.08

    changes = repo.list_tolerance_changes(cycle_id)
    assert len(changes) == 1
    assert changes[0].previous_value is None
    assert changes[0].new_value == 0.08
    assert changes[0].changed_by_actor_id == "senior-reviewer-anna"

    # 3. 0% tolerance flags any disagreement and is not coerced to None (FR-DR-065)
    resp_zero = client.post(
        f"/admin/projects/{cycle_id}/tolerance",
        data={"tolerance": "0", "actor_id": "senior-reviewer-anna"},
        follow_redirects=False,
    )
    assert resp_zero.status_code == 303
    assert effective_tolerance(repo, cycle_id, settings) == 0.0
    cycle = repo.get_cycle(cycle_id)
    assert cycle.discrepancy_rate_threshold == 0.0

    changes2 = repo.list_tolerance_changes(cycle_id)
    assert len(changes2) == 2
    assert changes2[1].previous_value == 0.08
    assert changes2[1].new_value == 0.0


def test_tolerance_change_closes_open_round_as_not_required(client: TestClient, conn, settings: Settings):
    from portal.reconciliation import open_automatic_round
    repo = Repository(conn)
    cycle_id = "c-not-req"
    portal_id = "p-not-req"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Cycle Not Req",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.05,
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="DK",
            unit_type="country",
            display_name="Denmark",
        )
    )
    session_id = ensure_session(repo, cycle_id)

    # 10 questions, 1 disagreement = 10% rate > 5% tolerance
    questions = []
    for i in range(10):
        q = Question(
            question_id=f"{cycle_id}:Q{i}",
            cycle_id=cycle_id,
            text=f"Q{i}",
            indicator_id=f"Q{i}",
            question_class="Core",
            title=f"Q{i}",
            what="W",
            why="Y",
            how={},
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
        repo.insert_question(q)
        questions.append(q)

        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"), session_id=session_id, cycle_id=cycle_id,
                question_id=q.question_id, portal_id=portal_id, role=AssessorRole.A,
                assessor_actor_id="actor-a", answer=True,
            )
        )
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"), session_id=session_id, cycle_id=cycle_id,
                question_id=q.question_id, portal_id=portal_id, role=AssessorRole.B,
                assessor_actor_id="actor-b", answer=(False if i == 0 else True),
            )
        )

    # Open automatic round 1 (dispute rate 10% > 5%)
    r1 = open_automatic_round(
        repo,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=[questions[0].question_id],
        rate=0.10,
        tolerance=0.05,
    )
    assert r1 is not None

    # Reviewer increases project tolerance to 15% (15% >= 10%)
    resp = client.post(
        f"/admin/projects/{cycle_id}/tolerance",
        data={"tolerance": "15", "actor_id": "reviewer-sam"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Round is closed as 'not_required' (FR-DR-037)
    closed = repo.list_rounds_for_unit(session_id, portal_id)[0]
    assert closed.state == "not_required"
    assert repo.open_round_for_unit(session_id, portal_id) is None


def test_changing_project_x_does_not_change_project_y(client: TestClient, conn, settings: Settings):
    repo = Repository(conn)
    repo.insert_cycle(
        SurveyCycle(
            cycle_id="proj-x",
            name="Project X",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.05,
        )
    )
    repo.insert_cycle(
        SurveyCycle(
            cycle_id="proj-y",
            name="Project Y",
            questionnaire_ref="ref",
            country_set=["SE"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.05,
        )
    )

    # Change X to 20%
    resp = client.post(
        "/admin/projects/proj-x/tolerance",
        data={"tolerance": "20", "actor_id": "reviewer"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert effective_tolerance(repo, "proj-x", settings) == 0.20
    # Y is strictly unchanged (SC-009)
    assert effective_tolerance(repo, "proj-y", settings) == 0.05


def test_discrepancy_case_retains_historical_tolerance(client: TestClient, conn, settings: Settings):
    repo = Repository(conn)
    cycle_id = "c-hist-tol"
    portal_id = "p-hist-tol"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Cycle Hist",
            questionnaire_ref="ref",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.05,
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="DK",
            unit_type="country",
            display_name="Denmark",
        )
    )
    session_id = ensure_session(repo, cycle_id)
    q = Question(
        question_id=f"{cycle_id}:Q1",
        cycle_id=cycle_id,
        text="Q1",
        indicator_id="Q1",
        question_class="Core",
        title="Q1",
        what="W",
        why="Y",
        how={},
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q)
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"), session_id=session_id, cycle_id=cycle_id,
            question_id=q.question_id, portal_id=portal_id, role=AssessorRole.A,
            assessor_actor_id="actor-a", answer=True,
        )
    )
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"), session_id=session_id, cycle_id=cycle_id,
            question_id=q.question_id, portal_id=portal_id, role=AssessorRole.B,
            assessor_actor_id="actor-b", answer=False,
        )
    )

    case1 = recompute_portal_discrepancy(repo, session_id, portal_id, [q.question_id], threshold=0.05, cycle_id=cycle_id)
    assert case1.thresholds_in_force == {"differing_answer_rate_threshold": 0.05}

    # Now change project tolerance to 15%
    client.post(
        f"/admin/projects/{cycle_id}/tolerance",
        data={"tolerance": "15", "actor_id": "reviewer"},
        follow_redirects=False,
    )

    # Historical case recorded under 0.05 still reports 0.05 (FR-DR-063)
    cases = repo.list_discrepancy_cases(session_id)
    old_case = [c for c in cases if c.case_id == case1.case_id][0]
    assert old_case.thresholds_in_force == {"differing_answer_rate_threshold": 0.05}


