"""Tests for assessor completion declaration and readiness (spec 008 US1, Scenario 5)."""

import sqlite3
import pytest
from fastapi.testclient import TestClient

from api.app import build_api_router, install_api_error_handlers
from api.finalize import publication_readiness
from portal.common import ensure_session
from fastapi import FastAPI
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    AnswerType,
    AssessorCompletion,
    AssessorRole,
    EvidenceLocus,
    HumanAssessorSubmission,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


def _setup_repo():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle = SurveyCycle(
        cycle_id="c-2024",
        name="Test Cycle 2024",
        questionnaire_ref="Test Ref 2024",
        country_set=["DK"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id="p-dk",
        cycle_id="c-2024",
        country_id="DK",
        resolved_url="https://borger.dk",
    )
    repo.insert_portal(portal)

    q1 = Question(
        question_id="c-2024:1.1.1",
        cycle_id="c-2024",
        indicator_id="1.1.1",
        text="Indicator 1",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    q2 = Question(
        question_id="c-2024:1.1.2",
        cycle_id="c-2024",
        indicator_id="1.1.2",
        text="Indicator 2",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q1)
    repo.insert_question(q2)

    return repo, "s-1", "c-2024", "p-dk", [q1, q2]


def test_refusal_names_outstanding_indicators(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)
    cycle_id = "c-2024"
    portal_id = "p-dk"

    cycle = SurveyCycle(
        cycle_id=cycle_id,
        name="Test Cycle 2024",
        questionnaire_ref="Test Ref 2024",
        country_set=["DK"],
    )
    repo.insert_cycle(cycle)

    portal = TargetPortal(
        portal_id=portal_id,
        cycle_id=cycle_id,
        country_id="DK",
        resolved_url="https://borger.dk",
    )
    repo.insert_portal(portal)

    q1 = Question(
        question_id=f"{cycle_id}:1.1.1",
        cycle_id=cycle_id,
        indicator_id="1.1.1",
        text="Indicator 1",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    q2 = Question(
        question_id=f"{cycle_id}:1.1.2",
        cycle_id=cycle_id,
        indicator_id="1.1.2",
        text="Indicator 2",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q1)
    repo.insert_question(q2)

    session_id = ensure_session(repo, cycle_id)

    # Assessor A only submits answer for q1
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("hsub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=q1.question_id,
            portal_id=portal_id,
            role=AssessorRole.A,
            assessor_actor_id="actor-a",
            answer=True,
        )
    )

    resp = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/completions",
        json={"role": "A", "actor_id": "actor-a"},
        headers=auth,
    )
    assert resp.status_code == 409
    data = resp.json()
    assert data["error"]["code"] == "incomplete_assessment"
    assert "outstanding" in data["error"]["message"]
    assert q2.question_id in data["error"]["details"]["outstanding_question_ids"]


def test_all_answered_but_undeclared_is_not_publishable():
    repo, session_id, cycle_id, portal_id, questions = _setup_repo()

    # Both A and B answer all questions, but neither declares completion
    for role in (AssessorRole.A, AssessorRole.B):
        for q in questions:
            repo.insert_human_submission(
                HumanAssessorSubmission(
                    submission_id=new_id("hsub"),
                    session_id=session_id,
                    cycle_id=cycle_id,
                    question_id=q.question_id,
                    portal_id=portal_id,
                    role=role,
                    assessor_actor_id=f"actor-{role.value.lower()}",
                    answer=True,
                )
            )

    readiness = publication_readiness(repo, session_id, cycle_id, portal_id)
    assert readiness.ready is False
    assert "not declared" in readiness.blocking_reason.lower()


def test_declaring_records_role_actor_timestamp():
    repo, session_id, cycle_id, portal_id, questions = _setup_repo()

    for q in questions:
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=q.question_id,
                portal_id=portal_id,
                role=AssessorRole.A,
                assessor_actor_id="actor-a",
                answer=True,
            )
        )

    comp = AssessorCompletion(
        completion_id=new_id("comp"),
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        role="A",
        actor_id="actor-a",
        indicator_count_at_declaration=len(questions),
    )
    repo.insert_assessor_completion(comp)

    latest = repo.latest_assessor_completion(session_id, portal_id, "A")
    assert latest is not None
    assert latest.role == "A"
    assert latest.actor_id == "actor-a"
    assert latest.indicator_count_at_declaration == 2
    assert latest.declared_at is not None


def test_revising_after_declaring_keeps_unit_complete():
    repo, session_id, cycle_id, portal_id, questions = _setup_repo()

    for q in questions:
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=q.question_id,
                portal_id=portal_id,
                role=AssessorRole.A,
                assessor_actor_id="actor-a",
                answer=True,
            )
        )

    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="A",
            actor_id="actor-a",
            indicator_count_at_declaration=len(questions),
        )
    )

    # Assessor revises q1
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("hsub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=questions[0].question_id,
            portal_id=portal_id,
            role=AssessorRole.A,
            assessor_actor_id="actor-a",
            answer=False,
        )
    )

    readiness = publication_readiness(repo, session_id, cycle_id, portal_id)
    assert readiness.roles["A"].complete is True


def test_adding_indicator_after_declaring_reverts_completion():
    repo, session_id, cycle_id, portal_id, questions = _setup_repo()

    for q in questions:
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=q.question_id,
                portal_id=portal_id,
                role=AssessorRole.A,
                assessor_actor_id="actor-a",
                answer=True,
            )
        )

    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="A",
            actor_id="actor-a",
            indicator_count_at_declaration=len(questions),
        )
    )

    # Add a new indicator q3
    q3 = Question(
        question_id="c-2024:1.1.3",
        cycle_id=cycle_id,
        indicator_id="1.1.3",
        text="Indicator 3",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q3)

    readiness = publication_readiness(repo, session_id, cycle_id, portal_id)
    assert readiness.roles["A"].complete is False
    assert "c-2024:1.1.3" in readiness.roles["A"].outstanding_question_ids


def test_redeclaration_appends_second_row_without_mutating_first():
    repo, session_id, cycle_id, portal_id, questions = _setup_repo()

    for q in questions:
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=q.question_id,
                portal_id=portal_id,
                role=AssessorRole.A,
                assessor_actor_id="actor-a",
                answer=True,
            )
        )

    comp1 = AssessorCompletion(
        completion_id="comp-1",
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        role="A",
        actor_id="actor-a",
        indicator_count_at_declaration=2,
    )
    repo.insert_assessor_completion(comp1)

    # Add q3 and answer it
    q3 = Question(
        question_id="c-2024:1.1.3",
        cycle_id=cycle_id,
        indicator_id="1.1.3",
        text="Indicator 3",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    repo.insert_question(q3)

    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("hsub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=q3.question_id,
            portal_id=portal_id,
            role=AssessorRole.A,
            assessor_actor_id="actor-a",
            answer=True,
        )
    )

    comp2 = AssessorCompletion(
        completion_id="comp-2",
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        role="A",
        actor_id="actor-a",
        indicator_count_at_declaration=3,
    )
    repo.insert_assessor_completion(comp2)

    latest = repo.latest_assessor_completion(session_id, portal_id, "A")
    assert latest.completion_id == "comp-2"
    assert latest.indicator_count_at_declaration == 3

    # Check that comp-1 is still in database with indicator_count 2
    cursor = repo.conn.cursor()
    cursor.execute("SELECT * FROM assessor_completions WHERE completion_id = 'comp-1'")
    row = cursor.fetchone()
    assert row is not None
    assert row["indicator_count_at_declaration"] == 2
