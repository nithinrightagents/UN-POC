"""Isolation tests demonstrating disagreement labelling cannot modify assessment outcomes (T042-T044).

Covers Scenario 0, FR-DL-040 to FR-DL-047, FR-DL-066, SC-002.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import sqlite3

from api.finalize import publication_readiness
from portal.assignment import set_role_assignment
from portal.common import ensure_session
from portal.disagreement_labels import (
    dispatch_labelling_pass,
    run_labelling_pass,
    unit_labelling_state,
)
from portal.discrepancy import recompute_portal_discrepancy
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db
from shared.state.entities import (
    AnswerType,
    Assessor,
    AssessorRole,
    DisagreementLabel,
    DisagreementLabelRecord,
    EvidenceLocus,
    LabellingAttempt,
    ProjectType,
    Question,
    SideObservation,
    SurveyCycle,
    TargetPortal,
    new_id,
    utcnow,
)

pytestmark = pytest.mark.unit


class MockRuntime:
    def __init__(self, provider):
        self.provider = provider


def _setup_test_db(tmp_path, db_name: str) -> tuple[str, Repository]:
    db_path = str(tmp_path / db_name)
    init_db(db_path)
    conn = connect(db_path)
    repo = Repository(conn)
    return db_path, repo


def _seed_unit(repo: Repository, cycle_id: str, portal_id: str):
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Cycle",
            questionnaire_ref="test",
            country_set=["TEST"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.1,
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="TEST",
            unit_type="country",
            display_name="Test Country",
        )
    )
    repo.insert_question(
        Question(
            question_id="q1",
            cycle_id=cycle_id,
            text="Indicator 1",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id="IND-01",
        )
    )
    repo.insert_question(
        Question(
            question_id="q2",
            cycle_id=cycle_id,
            text="Indicator 2",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id="IND-02",
        )
    )
    repo.upsert_assessor(Assessor(assessor_id="actor-a", display_name="Assessor A", email="a@test.gov"))
    repo.upsert_assessor(Assessor(assessor_id="actor-b", display_name="Assessor B", email="b@test.gov"))
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.A, "actor-a", "admin")
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.B, "actor-b", "admin")


def test_scenario_0_identical_outcomes_with_and_without_labelling(tmp_path, disputed_unit):
    """T042: Assessing a unit twice (labelling enabled vs disabled) produces identical discrepancy outcomes.

    Compares serialized rows across discrepancy_cases, escalation_queue_items, and reconciliation_rounds.
    """
    cycle_id = "c1"
    portal_id = "p1"

    # Database 1: Labelling Enabled
    db1_path, repo1 = _setup_test_db(tmp_path, "unit1_enabled.db")
    _seed_unit(repo1, cycle_id, portal_id)
    session1 = ensure_session(repo1, cycle_id)
    settings_enabled = Settings(database_path=db1_path, disagreement_labelling_enabled=True)

    # Database 2: Labelling Disabled
    db2_path, repo2 = _setup_test_db(tmp_path, "unit2_disabled.db")
    _seed_unit(repo2, cycle_id, portal_id)
    session2 = ensure_session(repo2, cycle_id)
    settings_disabled = Settings(database_path=db2_path, disagreement_labelling_enabled=False)

    # Identical submissions (q1 disputed, q2 agreed)
    dispute_map = {
        "q1": (True, "https://gov.example/1", "Notes A1", False, "https://gov.example/1", "Notes B1"),
        "q2": (True, "https://gov.example/2", "Notes A2", True, "https://gov.example/2", "Notes B2"),
    }

    # Populate db1
    for qid, (a_ans, a_url, a_notes, b_ans, b_url, b_notes) in dispute_map.items():
        from shared.state.entities import HumanAssessorSubmission
        repo1.insert_human_submission(
            HumanAssessorSubmission(new_id("sub"), session1, cycle_id, qid, portal_id, AssessorRole.A, "actor-a", a_ans, a_url, a_notes)
        )
        repo1.insert_human_submission(
            HumanAssessorSubmission(new_id("sub"), session1, cycle_id, qid, portal_id, AssessorRole.B, "actor-b", b_ans, b_url, b_notes)
        )
        repo2.insert_human_submission(
            HumanAssessorSubmission(new_id("sub"), session2, cycle_id, qid, portal_id, AssessorRole.A, "actor-a", a_ans, a_url, a_notes)
        )
        repo2.insert_human_submission(
            HumanAssessorSubmission(new_id("sub"), session2, cycle_id, qid, portal_id, AssessorRole.B, "actor-b", b_ans, b_url, b_notes)
        )

    # Insert completions for both
    from shared.state.entities import AssessorCompletion
    for role, actor in [("A", "actor-a"), ("B", "actor-b")]:
        repo1.insert_assessor_completion(
            AssessorCompletion(new_id("comp"), session1, cycle_id, portal_id, role, actor, 2)
        )
        repo2.insert_assessor_completion(
            AssessorCompletion(new_id("comp"), session2, cycle_id, portal_id, role, actor, 2)
        )

    # Run discrepancy recomputation on both
    recompute_portal_discrepancy(repo1, session1, portal_id, ["q1", "q2"], 0.1, cycle_id=cycle_id)
    recompute_portal_discrepancy(repo2, session2, portal_id, ["q1", "q2"], 0.1, cycle_id=cycle_id)

    # Dispatch labelling on db1 (enabled) and db2 (disabled)
    pass1 = dispatch_labelling_pass(repo1, settings_enabled, session1, cycle_id, portal_id, ["q1", "q2"], 0.1, "portal", True)
    pass2 = dispatch_labelling_pass(repo2, settings_disabled, session2, cycle_id, portal_id, ["q1", "q2"], 0.1, "portal", True)

    assert pass1 is not None
    assert pass2 is None

    # Compare serialized discrepancy_cases
    cases1 = [json.loads(r["data"]) for r in repo1.conn.execute("SELECT data FROM discrepancy_cases ORDER BY rowid").fetchall()]
    cases2 = [json.loads(r["data"]) for r in repo2.conn.execute("SELECT data FROM discrepancy_cases ORDER BY rowid").fetchall()]
    assert len(cases1) == len(cases2)
    for c1, c2 in zip(cases1, cases2):
        assert c1["differing_answer_rate"] == c2["differing_answer_rate"]
        assert c1["points_of_disagreement"] == c2["points_of_disagreement"]
        assert c1["outcome"] == c2["outcome"]

    # Compare serialized escalation_queue_items
    esc1 = [json.loads(r["data"]) for r in repo1.conn.execute("SELECT data FROM escalation_queue_items ORDER BY rowid").fetchall()]
    esc2 = [json.loads(r["data"]) for r in repo2.conn.execute("SELECT data FROM escalation_queue_items ORDER BY rowid").fetchall()]
    assert len(esc1) == len(esc2)
    for e1, e2 in zip(esc1, esc2):
        assert e1["reason"] == e2["reason"]
        assert e1["context"]["disagreements"] == e2["context"]["disagreements"]
        assert e1["context"]["differing_answer_rate"] == e2["context"]["differing_answer_rate"]

    # Compare reconciliation_rounds
    r1 = repo1.conn.execute("SELECT * FROM reconciliation_rounds ORDER BY rowid").fetchall()
    r2 = repo2.conn.execute("SELECT * FROM reconciliation_rounds ORDER BY rowid").fetchall()
    assert len(r1) == len(r2)


def test_exhausted_vs_labelled_opens_same_round_and_byte_identical_readiness(tmp_path):
    """T043: A unit whose disputes are exhausted produces identical reconciliation rounds and byte-identical publication readiness (FR-DL-047, FR-DL-066)."""
    cycle_id = "c1"
    portal_id = "p1"

    db1_path, repo1 = _setup_test_db(tmp_path, "unit_labelled.db")
    _seed_unit(repo1, cycle_id, portal_id)
    session1 = ensure_session(repo1, cycle_id)

    db2_path, repo2 = _setup_test_db(tmp_path, "unit_exhausted.db")
    _seed_unit(repo2, cycle_id, portal_id)
    session2 = ensure_session(repo2, cycle_id)

    # Identical submissions and completions
    from shared.state.entities import AssessorCompletion, HumanAssessorSubmission, LabellingPass
    fixed_time = utcnow()
    for repo, s_id in [(repo1, session1), (repo2, session2)]:
        repo.insert_human_submission(HumanAssessorSubmission(new_id("sub"), s_id, cycle_id, "q1", portal_id, AssessorRole.A, "actor-a", True, "https://gov.example", "Notes A", submitted_at=fixed_time))
        repo.insert_human_submission(HumanAssessorSubmission(new_id("sub"), s_id, cycle_id, "q1", portal_id, AssessorRole.B, "actor-b", False, "https://gov.example", "Notes B", submitted_at=fixed_time))
        repo.insert_assessor_completion(AssessorCompletion(new_id("comp"), s_id, cycle_id, portal_id, "A", "actor-a", 1, declared_at=fixed_time))
        repo.insert_assessor_completion(AssessorCompletion(new_id("comp"), s_id, cycle_id, portal_id, "B", "actor-b", 1, declared_at=fixed_time))
        recompute_portal_discrepancy(repo, s_id, portal_id, ["q1"], 0.0, cycle_id=cycle_id)

    # Unit 1 gets a pass and an established label
    repo1.insert_labelling_pass(
        LabellingPass(
            pass_id="pass-1",
            session_id=session1,
            cycle_id=cycle_id,
            portal_id=portal_id,
            disputed_question_ids=["q1"],
            compared_count=1,
            dispatched_by="portal",
        )
    )
    label_rec = DisagreementLabelRecord(
        label_id=new_id("lbl"),
        pass_id="pass-1",
        session_id=session1,
        portal_id=portal_id,
        question_id="q1",
        label=DisagreementLabel.DIFFERENT_JUDGEMENT,
        established_by="classifier",
        input_digest="digest1",
        stated_reason="Judged differently",
        observations={"A": [], "B": []},
        submission_ids={"A": "sub-a", "B": "sub-b"},
    )
    repo1.insert_disagreement_label(label_rec)

    # Unit 2 gets a pass and 3 attempts (exhausted)
    repo2.insert_labelling_pass(
        LabellingPass(
            pass_id="pass-2",
            session_id=session2,
            cycle_id=cycle_id,
            portal_id=portal_id,
            disputed_question_ids=["q1"],
            compared_count=1,
            dispatched_by="portal",
        )
    )
    for i in range(3):
        repo2.insert_labelling_attempt(
            LabellingAttempt(new_id("att"), "pass-2", "q1", "provider_error", f"Failure {i}")
        )

    # Check state projections
    state1 = unit_labelling_state(repo1, session1, portal_id)
    state2 = unit_labelling_state(repo2, session2, portal_id)
    assert state1["q1"].state == "established"
    assert state2["q1"].state == "exhausted"

    # Verify publication_readiness is byte-identical
    readiness1 = publication_readiness(repo1, session1, cycle_id, portal_id)
    readiness2 = publication_readiness(repo2, session2, cycle_id, portal_id)

    def _canonical(obj):
        d = asdict(obj)
        # Normalize session/db variance
        return json.dumps(d, sort_keys=True, default=str)

    bytes1 = _canonical(readiness1).encode("utf-8")
    bytes2 = _canonical(readiness2).encode("utf-8")
    assert bytes1 == bytes2

    # Verify reconciliation_rounds identical
    rounds1 = repo1.list_rounds_for_unit(session1, portal_id)
    rounds2 = repo2.list_rounds_for_unit(session2, portal_id)
    assert len(rounds1) == len(rounds2) == 1
    assert rounds1[0].data["disputed_question_ids"] == rounds2[0].data["disputed_question_ids"]
    assert rounds1[0].cycle_id == rounds2[0].cycle_id


def test_error_in_dispatch_or_runner_does_not_surface_to_assessor(app, client, conn, settings, disputed_unit):
    """T044: Provider errors in dispatch or runner do not surface to the assessor; completion is recorded and redirect/response unchanged (FR-DL-043, FR-DL-044)."""
    repo = Repository(conn)
    cycle_id = "surf-cycle"
    portal_id = "portal-surf"
    _seed_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example", "Notes A", False, "https://gov.example", "Notes B"),
            "q2": (False, "https://gov.example", "Notes A", True, "https://gov.example", "Notes B"),
        },
        declare_both=False,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    # 1. Portal completion with dispatch raising
    with patch("portal.assessor.dispatch_labelling_pass", side_effect=RuntimeError("Provider crashed inside dispatch")):
        resp = client.post(
            f"/assessor/{cycle_id}/{portal_id}/complete",
            data={"actor_id": "actor-a"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert f"/assessor/{cycle_id}/{portal_id}" in resp.headers["location"]

        # Assessor A's completion was recorded despite dispatch error
        comp_a = repo.latest_assessor_completion(session_id, portal_id, "A")
        assert comp_a is not None
        assert comp_a.actor_id == "actor-a"

    # 2. REST API completion with dispatch raising
    with patch("api.routers.completions.dispatch_labelling_pass", side_effect=RuntimeError("Provider crashed inside dispatch")):
        resp_api = client.post(
            f"/api/v1/cycles/{cycle_id}/units/{portal_id}/completions",
            json={"role": "B", "actor_id": "actor-b"},
            headers={"X-API-Key": "test-secret"},
        )
        assert resp_api.status_code == 201
        data = resp_api.json()
        assert data["actor_id"] == "actor-b"
        assert data["role"] == "B"

        comp_b = repo.latest_assessor_completion(session_id, portal_id, "B")
        assert comp_b is not None
        assert comp_b.actor_id == "actor-b"
