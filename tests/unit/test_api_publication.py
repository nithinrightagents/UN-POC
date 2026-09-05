"""Publication, published results, and portal parity tests (spec 007 US4, spec 008 Scenario 6)."""

from datetime import UTC

import pytest
from fastapi.testclient import TestClient

from api.finalize import final_answer, publication_readiness
from portal.common import ensure_session
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessorCompletion,
    AssessorRole,
    AssignmentSource,
    HumanAssessorSubmission,
    Prefill,
    RoleAssignment,
    UnitAssessorAssignment,
    new_id,
)

pytestmark = pytest.mark.unit


def test_publication_parity_with_portal(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)

    # 1. Create cycle with 3 questions
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "pub-cycle", "name": "Publication Cycle"},
        headers=auth,
    )
    for ind in ["P.1", "P.2", "P.3"]:
        client.post(
            "/api/v1/cycles/pub-cycle/questions",
            json={"indicator_id": ind, "title": f"Question {ind}", "what": "W", "why": "Y", "how": "H"},
            headers=auth,
        )

    # 2. Create two identical units: unit-api and unit-portal
    u_api = client.post(
        "/api/v1/cycles/pub-cycle/units",
        json={"country_id": "API", "display_name": "API Unit", "url": "https://api.gov"},
        headers=auth,
    ).json()["portal_id"]

    u_portal = client.post(
        "/api/v1/cycles/pub-cycle/units",
        json={"country_id": "POR", "display_name": "Portal Unit", "url": "https://portal.gov"},
        headers=auth,
    ).json()["portal_id"]

    session_id = ensure_session(repo, "pub-cycle")

    # Seed answers for both units:
    # Q1: A=True, B=True (Agreeing -> True)
    # Q2: A=False, B=True (Differing without arbitration -> False from A)
    # Q3: A=True, B=True
    for p_id in [u_api, u_portal]:
        for q_id in ["pub-cycle:P.1", "pub-cycle:P.2", "pub-cycle:P.3"]:
            ans_a = True if q_id != "pub-cycle:P.2" else False
            ans_b = True
            repo.insert_human_submission(
                HumanAssessorSubmission(
                    submission_id=new_id("hsub"), session_id=session_id, cycle_id="pub-cycle",
                    question_id=q_id, portal_id=p_id, role=AssessorRole.A,
                    assessor_actor_id="a1", answer=ans_a,
                )
            )
            repo.insert_human_submission(
                HumanAssessorSubmission(
                    submission_id=new_id("hsub"), session_id=session_id, cycle_id="pub-cycle",
                    question_id=q_id, portal_id=p_id, role=AssessorRole.B,
                    assessor_actor_id="b1", answer=ans_b,
                )
            )

        # Complete both roles
        repo.insert_assessor_completion(
            AssessorCompletion(
                completion_id=new_id("comp"), session_id=session_id, cycle_id="pub-cycle",
                portal_id=p_id, role="A", actor_id="a1", indicator_count_at_declaration=3,
            )
        )
        repo.insert_assessor_completion(
            AssessorCompletion(
                completion_id=new_id("comp"), session_id=session_id, cycle_id="pub-cycle",
                portal_id=p_id, role="B", actor_id="b1", indicator_count_at_declaration=3,
            )
        )

    # 3. Publish u_api via API
    api_pub_res = client.post(
        f"/api/v1/cycles/pub-cycle/units/{u_api}/publication",
        json={"actor_id": "senior-reviewer"},
        headers=auth,
    )
    assert api_pub_res.status_code == 201

    # 4. Publish u_portal via Portal
    portal_pub_res = client.post(
        f"/admin/projects/pub-cycle/units/{u_portal}/publish",
        data={"actor_id": "senior-reviewer"},
        follow_redirects=False,
    )
    assert portal_pub_res.status_code == 303

    # 5. Read both publications and assert parity
    api_read = client.get(f"/api/v1/cycles/pub-cycle/units/{u_api}/publication", headers=auth).json()
    portal_read = client.get(f"/api/v1/cycles/pub-cycle/units/{u_portal}/publication", headers=auth).json()

    assert api_read["published"] is True
    assert portal_read["published"] is True
    assert api_read["score"] == portal_read["score"]

    api_breakdown = {item["indicator_id"]: item["final_answer"] for item in api_read["breakdown"]}
    portal_breakdown = {item["indicator_id"]: item["final_answer"] for item in portal_read["breakdown"]}
    assert api_breakdown == portal_breakdown
    assert len(api_breakdown) == 3


def test_fully_prefilled_unit_with_zero_human_answers_publishes_nothing(
    client: TestClient, auth: dict[str, str], conn
):
    repo = Repository(conn)
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "prefill-only-cycle", "name": "Prefill Only Cycle"},
        headers=auth,
    )
    for ind in ["PF.1", "PF.2"]:
        client.post(
            "/api/v1/cycles/prefill-only-cycle/questions",
            json={"indicator_id": ind, "title": f"Question {ind}", "what": "W", "why": "Y", "how": "H"},
            headers=auth,
        )
    u_res = client.post(
        "/api/v1/cycles/prefill-only-cycle/units",
        json={"country_id": "NOR", "display_name": "Norway", "url": "https://norge.no"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    session_id = ensure_session(repo, "prefill-only-cycle")

    # Insert prefills for all questions
    for q_id in ["prefill-only-cycle:PF.1", "prefill-only-cycle:PF.2"]:
        repo.insert_prefill(
            Prefill(
                prefill_id=new_id("pf"),
                run_id="run-1",
                session_id=session_id,
                cycle_id="prefill-only-cycle",
                question_id=q_id,
                portal_id=portal_id,
                suggested=True,
                answer=True,
                confidence=95,
                justification="Automated prefill finding.",
                evidence_url="https://norge.no",
                supplying_source="search",
                agreement_outcome="unanimous",
            )
        )

    # 1. final_answer returns None for every question because zero humans answered
    for q_id in ["prefill-only-cycle:PF.1", "prefill-only-cycle:PF.2"]:
        assert final_answer(repo, session_id, q_id, portal_id) is None

    # 2. publication_readiness is not ready
    readiness = publication_readiness(repo, session_id, "prefill-only-cycle", portal_id)
    assert readiness.ready is False

    # 3. Attempting to publish via API returns 409
    res = client.post(
        f"/api/v1/cycles/prefill-only-cycle/units/{portal_id}/publication",
        json={"actor_id": "senior-reviewer"},
        headers=auth,
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "assessment_incomplete"


def test_never_published_and_republish(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "repub-cycle", "name": "Republish Cycle", "discrepancy_rate_threshold": 1.0},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/repub-cycle/questions",
        json={"indicator_id": "R.1", "title": "Question R1", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        "/api/v1/cycles/repub-cycle/units",
        json={"country_id": "LTU", "display_name": "Lithuania", "url": "https://lietuva.lt"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    repo.upsert_unit_assignment(
        UnitAssessorAssignment(
            assignment_id=new_id("asmt"),
            cycle_id="repub-cycle",
            portal_id=portal_id,
            role_a=RoleAssignment(assessor_id="actor-a", source=AssignmentSource.MAPPING),
            role_b=RoleAssignment(assessor_id="actor-b", source=AssignmentSource.MAPPING),
        )
    )
    qid = "repub-cycle:R.1"
    ensure_session(repo, "repub-cycle")

    # 1. Never published -> 200 with published: false, score: null
    get_unpub = client.get(f"/api/v1/cycles/repub-cycle/units/{portal_id}/publication", headers=auth)
    assert get_unpub.status_code == 200
    data_unpub = get_unpub.json()
    assert data_unpub["published"] is False
    assert data_unpub["score"] is None
    assert data_unpub["breakdown"] == []

    # 2. First submission (False) for A and B + declare completion
    for role_name in ("A", "B"):
        client.post(
            f"/api/v1/cycles/repub-cycle/units/{portal_id}/human-answers",
            json={"question_id": qid, "role": role_name, "actor_id": f"actor-{role_name.lower()}", "answer": False},
            headers=auth,
        )
        client.post(
            f"/api/v1/cycles/repub-cycle/units/{portal_id}/completions",
            json={"role": role_name, "actor_id": f"actor-{role_name.lower()}"},
            headers=auth,
        )

    pub1 = client.post(
        f"/api/v1/cycles/repub-cycle/units/{portal_id}/publication",
        json={"actor_id": "reviewer-1"},
        headers=auth,
    )
    assert pub1.status_code == 201
    pub1_id = pub1.json()["publication_id"]
    assert pub1.json()["score"] == 0.0

    # Read after pub 1
    read1 = client.get(f"/api/v1/cycles/repub-cycle/units/{portal_id}/publication", headers=auth).json()
    assert read1["published"] is True
    assert read1["publication_id"] == pub1_id
    assert read1["score"] == 0.0

    # 3. Revision (True) and republish
    for role_name in ("A", "B"):
        client.post(
            f"/api/v1/cycles/repub-cycle/units/{portal_id}/human-answers",
            json={"question_id": qid, "role": role_name, "actor_id": f"actor-{role_name.lower()}", "answer": True},
            headers=auth,
        )

    pub2 = client.post(
        f"/api/v1/cycles/repub-cycle/units/{portal_id}/publication",
        json={"actor_id": "reviewer-2"},
        headers=auth,
    )
    assert pub2.status_code == 201
    pub2_id = pub2.json()["publication_id"]
    assert pub2_id != pub1_id
    assert pub2.json()["score"] == 1.0

    # Read after pub 2: must return pub 2
    read2 = client.get(f"/api/v1/cycles/repub-cycle/units/{portal_id}/publication", headers=auth).json()
    assert read2["published"] is True
    assert read2["publication_id"] == pub2_id
    assert read2["score"] == 1.0
    assert read2["published_by"] == "reviewer-2"


def test_scenario_6_publish_unresolved_with_contested_indicators_and_identical_score(
    client: TestClient, auth: dict[str, str], conn
):
    repo = Repository(conn)
    cycle_id = "c-sc6"

    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Scenario 6 Cycle", "discrepancy_rate_threshold": 0.05},
        headers=auth,
    )
    for ind in ["Q1", "Q2", "Q3"]:
        client.post(
            "/api/v1/cycles/c-sc6/questions",
            json={"indicator_id": ind, "title": f"Question {ind}", "what": "W", "why": "Y", "how": "H"},
            headers=auth,
        )

    u_res = client.post(
        "/api/v1/cycles/c-sc6/units",
        json={"country_id": "DK", "display_name": "Denmark SC6", "url": "https://dk.gov"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    session_id = ensure_session(repo, cycle_id)

    # Q1: A=True, B=True (Consensus -> True)
    # Q2: A=True, B=False (Unresolved disagreement -> Assessor A wins -> True, marked contested)
    # Q3: A=False, B=False (Consensus -> False)
    answers_a = {"c-sc6:Q1": True, "c-sc6:Q2": True, "c-sc6:Q3": False}
    answers_b = {"c-sc6:Q1": True, "c-sc6:Q2": False, "c-sc6:Q3": False}

    for qid, ans in answers_a.items():
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"), session_id=session_id, cycle_id=cycle_id,
                question_id=qid, portal_id=portal_id, role=AssessorRole.A,
                assessor_actor_id="actor-a", answer=ans,
            )
        )
    for qid, ans in answers_b.items():
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"), session_id=session_id, cycle_id=cycle_id,
                question_id=qid, portal_id=portal_id, role=AssessorRole.B,
                assessor_actor_id="actor-b", answer=ans,
            )
        )

    # Both declare completion
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"), session_id=session_id, cycle_id=cycle_id,
            portal_id=portal_id, role="A", actor_id="actor-a", indicator_count_at_declaration=3,
        )
    )
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"), session_id=session_id, cycle_id=cycle_id,
            portal_id=portal_id, role="B", actor_id="actor-b", indicator_count_at_declaration=3,
        )
    )

    # Unit has 1 dispute out of 3 = 33.3% > 5% tolerance
    # Publish unit directly
    pub_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/publication",
        json={"actor_id": "senior-reviewer-elena"},
        headers=auth,
    )
    assert pub_res.status_code == 201
    pub_data = pub_res.json()

    # The score is arithmetically identical to what today's code produces for the same data (2/3 = 0.6666666666666666)
    expected_score = 2 / 3
    assert pytest.approx(pub_data["score"], 0.0001) == expected_score
    assert pub_data["published_by"] == "senior-reviewer-elena"

    # Database publication record has contested_question_ids recorded
    pub_rec = repo.latest_publication(cycle_id, portal_id)
    assert pub_rec is not None
    assert pub_rec.contested_question_ids == ["c-sc6:Q2"]
    assert pytest.approx(pub_rec.score, 0.0001) == expected_score
    assert pub_rec.published_by_actor_id == "senior-reviewer-elena"


def test_final_answer_prefers_joint_value_over_both_originals(conn):
    from datetime import datetime

    from api.finalize import final_answer_detail
    from shared.state.entities import JointAnswer

    repo = Repository(conn)
    session_id = "s-joint-pref"
    cycle_id = "c-joint-pref"
    portal_id = "p-joint-pref"
    qid = "c-joint-pref:IND-01"

    # Assessor A says False, Assessor B says True
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"), session_id=session_id, cycle_id=cycle_id,
            question_id=qid, portal_id=portal_id, role=AssessorRole.A,
            assessor_actor_id="actor-a", answer=False,
        )
    )
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"), session_id=session_id, cycle_id=cycle_id,
            question_id=qid, portal_id=portal_id, role=AssessorRole.B,
            assessor_actor_id="actor-b", answer=True,
        )
    )

    # Before joint answer: final_answer returns Assessor A's False (contested_a_wins)
    ans_val, source = final_answer_detail(repo, session_id, qid, portal_id)
    assert ans_val is False
    assert source == "contested_a_wins"
    assert final_answer(repo, session_id, qid, portal_id) is False

    # Joint answer committed as True (by Assessor B with Assessor A concurring)
    repo.insert_joint_answer(
        JointAnswer(
            joint_answer_id=new_id("joint"),
            session_id=session_id,
            portal_id=portal_id,
            question_id=qid,
            round_id="rnd-1",
            data={
                "answer": True,
                "justification": "Found official gazette evidence",
                "submitted_by_role": "B",
                "submitted_by_actor_id": "actor-b",
            },
            created_at=datetime.now(UTC),
        )
    )

    # After joint answer: final_answer returns True (joint_answer takes precedence over originals)
    ans_val_after, source_after = final_answer_detail(repo, session_id, qid, portal_id)
    assert ans_val_after is True
    assert source_after == "joint_answer"
    assert final_answer(repo, session_id, qid, portal_id) is True


