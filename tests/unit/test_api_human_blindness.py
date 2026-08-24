"""Human assessor submissions, blindness preservation, and final answer integration tests (spec 007 US3)."""

import pytest
from fastapi.testclient import TestClient

from api.finalize import final_answer
from portal.common import ensure_session
from shared.persistence.repositories import Repository

pytestmark = pytest.mark.unit


def test_human_submissions_role_scoped_and_blind(client: TestClient, auth: dict[str, str]):
    # 1. Setup cycle, 2 questions, 1 unit
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "blind-cycle", "name": "Blindness Test Cycle"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/blind-cycle/questions",
        json={"indicator_id": "B.1", "title": "Question B1", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/blind-cycle/questions",
        json={"indicator_id": "B.2", "title": "Question B2", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        "/api/v1/cycles/blind-cycle/units",
        json={"country_id": "ISL", "display_name": "Iceland", "url": "https://island.is"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]

    # 2. Submit answer for B.1 as Role A
    sub_a = client.post(
        f"/api/v1/cycles/blind-cycle/units/{portal_id}/human-answers",
        json={
            "question_id": "blind-cycle:B.1",
            "role": "A",
            "actor_id": "assessor-alice",
            "answer": True,
            "notes": "Found feature on main page",
        },
        headers=auth,
    )
    assert sub_a.status_code == 201
    data_a = sub_a.json()
    assert data_a["role"] == "A"
    assert data_a["answer"] is True

    # 3. Submit answer for B.1 as Role B with different answer
    sub_b = client.post(
        f"/api/v1/cycles/blind-cycle/units/{portal_id}/human-answers",
        json={
            "question_id": "blind-cycle:B.1",
            "role": "B",
            "actor_id": "assessor-bob",
            "answer": False,
            "notes": "Could not locate evidence",
        },
        headers=auth,
    )
    assert sub_b.status_code == 201
    data_b = sub_b.json()
    assert data_b["role"] == "B"
    assert data_b["answer"] is False

    # 4. Read Role A answers: must show only Role A, B.1 answered True, B.2 not answered
    res_a = client.get(
        f"/api/v1/cycles/blind-cycle/units/{portal_id}/human-answers?role=A",
        headers=auth,
    )
    assert res_a.status_code == 200
    list_a = res_a.json()
    assert list_a["role"] == "A"
    ans_a_map = {item["indicator_id"]: item for item in list_a["answers"]}
    assert ans_a_map["B.1"]["answered"] is True
    assert ans_a_map["B.1"]["answer"] is True
    assert ans_a_map["B.1"]["actor_id"] == "assessor-alice"
    assert ans_a_map["B.1"]["notes"] == "Found feature on main page"
    assert ans_a_map["B.2"]["answered"] is False
    assert ans_a_map["B.2"]["answer"] is None

    # Blindness assertion: no mention of Bob or Role B
    raw_text_a = res_a.text
    assert "assessor-bob" not in raw_text_a
    assert "Could not locate evidence" not in raw_text_a

    # 5. Read Role B answers: must show only Role B, B.1 answered False, B.2 not answered
    res_b = client.get(
        f"/api/v1/cycles/blind-cycle/units/{portal_id}/human-answers?role=B",
        headers=auth,
    )
    assert res_b.status_code == 200
    list_b = res_b.json()
    assert list_b["role"] == "B"
    ans_b_map = {item["indicator_id"]: item for item in list_b["answers"]}
    assert ans_b_map["B.1"]["answered"] is True
    assert ans_b_map["B.1"]["answer"] is False
    assert ans_b_map["B.1"]["actor_id"] == "assessor-bob"
    assert ans_b_map["B.1"]["notes"] == "Could not locate evidence"
    assert ans_b_map["B.2"]["answered"] is False

    # Blindness assertion: no mention of Alice or Role A
    raw_text_b = res_b.text
    assert "assessor-alice" not in raw_text_b
    assert "Found feature on main page" not in raw_text_b


def test_submission_validation_and_errors(client: TestClient, auth: dict[str, str]):
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "val-cycle", "name": "Validation Cycle"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/val-cycle/questions",
        json={"indicator_id": "V.1", "title": "Title", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        "/api/v1/cycles/val-cycle/units",
        json={"country_id": "EST", "display_name": "Estonia", "url": "https://e-estonia.com"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]

    # 1. Missing role query parameter on GET -> 422
    get_no_role = client.get(
        f"/api/v1/cycles/val-cycle/units/{portal_id}/human-answers",
        headers=auth,
    )
    assert get_no_role.status_code == 422

    # 2. Invalid role on GET -> 422
    get_bad_role = client.get(
        f"/api/v1/cycles/val-cycle/units/{portal_id}/human-answers?role=INVALID",
        headers=auth,
    )
    assert get_bad_role.status_code == 422

    # 3. Invalid role on POST -> 422
    post_bad_role = client.post(
        f"/api/v1/cycles/val-cycle/units/{portal_id}/human-answers",
        json={
            "question_id": "val-cycle:V.1",
            "role": "C",
            "actor_id": "assessor-c",
            "answer": True,
        },
        headers=auth,
    )
    assert post_bad_role.status_code == 422

    # 4. Non-existent question on POST -> 404
    post_bad_q = client.post(
        f"/api/v1/cycles/val-cycle/units/{portal_id}/human-answers",
        json={
            "question_id": "val-cycle:V.999",
            "role": "A",
            "actor_id": "assessor-a",
            "answer": True,
        },
        headers=auth,
    )
    assert post_bad_q.status_code == 404

    # 5. Non-existent unit on POST -> 404
    post_bad_unit = client.post(
        "/api/v1/cycles/val-cycle/units/portal-nonexistent/human-answers",
        json={
            "question_id": "val-cycle:V.1",
            "role": "A",
            "actor_id": "assessor-a",
            "answer": True,
        },
        headers=auth,
    )
    assert post_bad_unit.status_code == 404

    # 6. Non-existent cycle on POST -> 404
    post_bad_cycle = client.post(
        f"/api/v1/cycles/cycle-nonexistent/units/{portal_id}/human-answers",
        json={
            "question_id": "val-cycle:V.1",
            "role": "A",
            "actor_id": "assessor-a",
            "answer": True,
        },
        headers=auth,
    )
    assert post_bad_cycle.status_code == 404


def test_human_submissions_feed_into_final_answer(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "feed-cycle", "name": "Feed Cycle"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/feed-cycle/questions",
        json={"indicator_id": "F.1", "title": "Title", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        "/api/v1/cycles/feed-cycle/units",
        json={"country_id": "LVA", "display_name": "Latvia", "url": "https://latvija.lv"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    qid = "feed-cycle:F.1"
    session_id = ensure_session(repo, "feed-cycle")

    # Initially no human submission, AI run, or unit delivered -> returns None
    assert final_answer(repo, session_id, qid, portal_id) is None

    # 1. Submit role A = True
    client.post(
        f"/api/v1/cycles/feed-cycle/units/{portal_id}/human-answers",
        json={"question_id": qid, "role": "A", "actor_id": "a1", "answer": True},
        headers=auth,
    )
    # Lone human submission A = True -> final_answer becomes True
    assert final_answer(repo, session_id, qid, portal_id) is True

    # 2. Submit role B = False (Disagreement pending arbitration)
    client.post(
        f"/api/v1/cycles/feed-cycle/units/{portal_id}/human-answers",
        json={"question_id": qid, "role": "B", "actor_id": "b1", "answer": False},
        headers=auth,
    )
    # Disagreement pending arbitration returns role A answer as placeholder
    assert final_answer(repo, session_id, qid, portal_id) is True

    # 3. Role A submits revised answer = False (Agreement on False!)
    client.post(
        f"/api/v1/cycles/feed-cycle/units/{portal_id}/human-answers",
        json={"question_id": qid, "role": "A", "actor_id": "a1", "answer": False},
        headers=auth,
    )
    # A & B agree on False -> final_answer returns False
    assert final_answer(repo, session_id, qid, portal_id) is False


def test_prefill_endpoint_blind_to_human_roles(client: TestClient, auth: dict[str, str], conn):
    """GET /prefills carries AI prefill data and contains no role or human assessor submission data."""
    repo = Repository(conn)
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "blind-pf-cycle", "name": "Blind Prefill Cycle"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/blind-pf-cycle/questions",
        json={"indicator_id": "BP.1", "title": "Question BP1", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        "/api/v1/cycles/blind-pf-cycle/units",
        json={"country_id": "SWE", "display_name": "Sweden", "url": "https://sweden.se"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    session_id = ensure_session(repo, "blind-pf-cycle")

    # Assessor A and B submit answers
    client.post(
        f"/api/v1/cycles/blind-pf-cycle/units/{portal_id}/human-answers",
        json={"question_id": "blind-pf-cycle:BP.1", "role": "A", "actor_id": "assessor-secret-a", "answer": True},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/blind-pf-cycle/units/{portal_id}/human-answers",
        json={"question_id": "blind-pf-cycle:BP.1", "role": "B", "actor_id": "assessor-secret-b", "answer": False},
        headers=auth,
    )

    # Call GET /prefills
    res = client.get(
        f"/api/v1/cycles/blind-pf-cycle/units/{portal_id}/prefills",
        headers=auth,
    )
    assert res.status_code == 200
    body_text = res.text
    assert "assessor-secret-a" not in body_text
    assert "assessor-secret-b" not in body_text
    data = res.json()
    assert "role" not in data
    for item in data["prefills"]:
        assert "role" not in item


def test_cross_route_blindness_preservation_sc011(client: TestClient, auth: dict[str, str], conn):
    """Mechanises SC-011 across all routes in contracts/reconciliation-workspace.md §4."""
    repo = Repository(conn)
    cycle_id = "blind-sc11-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Blindness SC11 Cycle", "discrepancy_rate_threshold": 0.05},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "SC.1", "title": "Question SC1", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "SC.2", "title": "Question SC2", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "NOR", "display_name": "Norway", "url": "https://norge.no"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    qid1 = f"{cycle_id}:SC.1"
    qid2 = f"{cycle_id}:SC.2"

    alice_actor = "alice-unique-actor-99"
    bob_actor = "bob-unique-actor-77"
    alice_note = "Alice secret note about portal layout 42"
    bob_note = "Bob secret note about missing certificate 88"

    # Alice submits Q1=True, Q2=True
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid1, "role": "A", "actor_id": alice_actor, "answer": True, "notes": alice_note},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid2, "role": "A", "actor_id": alice_actor, "answer": True, "notes": alice_note},
        headers=auth,
    )

    # Bob submits Q1=False (dispute), Q2=True (consensus)
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid1, "role": "B", "actor_id": bob_actor, "answer": False, "notes": bob_note},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid2, "role": "B", "actor_id": bob_actor, "answer": True, "notes": bob_note},
        headers=auth,
    )

    # 1. Check GET /assessor questionnaire in Role A
    res_assessor_a = client.get(f"/assessor/{cycle_id}/{portal_id}?role=A")
    assert res_assessor_a.status_code == 200
    assert bob_actor not in res_assessor_a.text
    assert bob_note not in res_assessor_a.text

    # Check GET /assessor questionnaire in Role B
    res_assessor_b = client.get(f"/assessor/{cycle_id}/{portal_id}?role=B")
    assert res_assessor_b.status_code == 200
    assert alice_actor not in res_assessor_b.text
    assert alice_note not in res_assessor_b.text

    # 2. Check GET /human-answers?role=A and ?role=B
    res_api_a = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers?role=A", headers=auth)
    assert res_api_a.status_code == 200
    assert bob_actor not in res_api_a.text
    assert bob_note not in res_api_a.text

    res_api_b = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers?role=B", headers=auth)
    assert res_api_b.status_code == 200
    assert alice_actor not in res_api_b.text
    assert alice_note not in res_api_b.text

    # 3. Check GET /discrepancy endpoint
    res_disc = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/discrepancy", headers=auth)
    assert res_disc.status_code == 200
    assert alice_actor not in res_disc.text
    assert bob_actor not in res_disc.text
    assert alice_note not in res_disc.text
    assert bob_note not in res_disc.text
    assert "true" not in res_disc.text.lower() or "automatic_round_used" in res_disc.text

    # 4. Check admin project detail page
    res_admin = client.get(f"/admin/projects/{cycle_id}")
    assert res_admin.status_code == 200
    assert alice_note not in res_admin.text
    assert bob_note not in res_admin.text


