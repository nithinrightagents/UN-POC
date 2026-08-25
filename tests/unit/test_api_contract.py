"""Contract and lifecycle tests for JSON REST API (spec 007 US1)."""

import pytest
from fastapi.testclient import TestClient

from portal.common import ensure_session
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AdjudicationResult,
    AssessorAgentRun,
    EscalationReason,
    UnitState,
    ValidationResult,
    VerificationOutcome,
    new_id,
)

pytestmark = pytest.mark.unit


def test_full_lifecycle_returns_json_and_chains_identifiers(client: TestClient, auth: dict[str, str]):
    # 1. Create cycle
    cycle_res = client.post(
        "/api/v1/cycles",
        json={
            "cycle_id": "osi-2026",
            "name": "UN E-Government Survey 2026",
            "questionnaire_ref": "UN MSQ 2026 Indicator Set",
            "project_type": "national_osi",
        },
        headers=auth,
    )
    assert cycle_res.status_code == 201
    assert cycle_res.headers["content-type"].startswith("application/json")
    cycle_data = cycle_res.json()
    cycle_id = cycle_data["cycle_id"]
    assert cycle_id == "osi-2026"

    # 2. Create question
    q_res = client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={
            "indicator_id": "2.1.1",
            "title": "National Portal Exists",
            "what": "Is there a functioning central portal?",
            "why": "Centralized access is foundational.",
            "how": "Verify the portal URL responds with 200.",
            "module": "Institutional Framework",
            "evidence_locus": "national_portal_only",
        },
        headers=auth,
    )
    assert q_res.status_code == 201
    assert q_res.headers["content-type"].startswith("application/json")
    q_data = q_res.json()
    assert q_data["indicator_id"] == "2.1.1"
    assert q_data["question_id"] == "osi-2026:2.1.1"

    # 3. Create unit
    unit_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={
            "country_id": "DNK",
            "display_name": "Denmark",
            "url": "https://www.borger.dk",
            "unit_type": "country",
        },
        headers=auth,
    )
    assert unit_res.status_code == 201
    assert unit_res.headers["content-type"].startswith("application/json")
    unit_data = unit_res.json()
    portal_id = unit_data["portal_id"]
    assert portal_id.startswith("portal-")

    # 4. Trigger assessment
    trig_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/assessment",
        json={"actor_id": "test-client"},
        headers=auth,
    )
    assert trig_res.status_code == 202
    assert trig_res.headers["content-type"].startswith("application/json")
    trig_data = trig_res.json()
    assert trig_data["state"] == "running"
    assert trig_data["already_running"] is False
    assert trig_data["questions_total"] == 1
    job_id = trig_data["job_id"]
    assert job_id.startswith("job-")

    # 5. Poll status
    status_res = client.get(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/assessment",
        headers=auth,
    )
    assert status_res.status_code == 200
    assert status_res.headers["content-type"].startswith("application/json")
    status_data = status_res.json()
    assert status_data["state"] == "running"
    assert status_data["job_id"] == job_id
    assert status_data["questions_total"] == 1

    # 6. Read results
    results_res = client.get(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/results",
        headers=auth,
    )
    assert results_res.status_code == 200
    assert results_res.headers["content-type"].startswith("application/json")
    results_data = results_res.json()
    assert results_data["complete"] is False
    assert len(results_data["results"]) == 1
    assert results_data["results"][0]["question_id"] == "osi-2026:2.1.1"
    assert results_data["results"][0]["indicator_id"] == "2.1.1"


def test_duplicate_creates_are_conflicts(client: TestClient, auth: dict[str, str]):
    # Create cycle
    res = client.post(
        "/api/v1/cycles",
        json={"cycle_id": "dup-cycle", "name": "Initial Name"},
        headers=auth,
    )
    assert res.status_code == 201

    # Duplicate cycle create
    dup_cycle = client.post(
        "/api/v1/cycles",
        json={"cycle_id": "dup-cycle", "name": "Modified Name"},
        headers=auth,
    )
    assert dup_cycle.status_code == 409
    assert dup_cycle.json()["error"]["code"] == "conflict"
    # Ensure not modified
    cycle_get = client.get("/api/v1/cycles/dup-cycle", headers=auth)
    assert cycle_get.json()["name"] == "Initial Name"

    # Add question
    res_q = client.post(
        "/api/v1/cycles/dup-cycle/questions",
        json={
            "indicator_id": "IND-1",
            "title": "Indicator 1",
            "what": "What 1",
            "why": "Why 1",
            "how": "How 1",
        },
        headers=auth,
    )
    assert res_q.status_code == 201

    # Duplicate question create
    dup_q = client.post(
        "/api/v1/cycles/dup-cycle/questions",
        json={
            "indicator_id": "IND-1",
            "title": "Indicator 1 Modified",
            "what": "What 1",
            "why": "Why 1",
            "how": "How 1",
        },
        headers=auth,
    )
    assert dup_q.status_code == 409
    assert dup_q.json()["error"]["code"] == "conflict"

    # Add unit
    res_u = client.post(
        "/api/v1/cycles/dup-cycle/units",
        json={
            "country_id": "USA",
            "display_name": "United States",
            "url": "https://www.usa.gov",
        },
        headers=auth,
    )
    assert res_u.status_code == 201

    # Duplicate unit create (same country, different URL)
    dup_u = client.post(
        "/api/v1/cycles/dup-cycle/units",
        json={
            "country_id": "USA",
            "display_name": "United States",
            "url": "https://www.whitehouse.gov",
        },
        headers=auth,
    )
    assert dup_u.status_code == 409
    assert dup_u.json()["error"]["code"] == "conflict"

    # Verify original URL is unchanged
    units_res = client.get("/api/v1/cycles/dup-cycle/units", headers=auth)
    assert units_res.json()["units"][0]["resolved_url"] == "https://www.usa.gov"


def test_results_partial_and_blocked(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)

    # 1. Create cycle and 3 questions
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "part-cycle", "name": "Partial Results Cycle"},
        headers=auth,
    )
    for ind in ["1.1", "1.2", "1.3"]:
        client.post(
            "/api/v1/cycles/part-cycle/questions",
            json={
                "indicator_id": ind,
                "title": f"Indicator {ind}",
                "what": f"What {ind}",
                "why": "Why",
                "how": "How",
            },
            headers=auth,
        )

    # 2. Create unit
    u_res = client.post(
        "/api/v1/cycles/part-cycle/units",
        json={
            "country_id": "SWE",
            "display_name": "Sweden",
            "url": "https://www.sweden.se",
        },
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]

    # 3. Trigger assessment
    client.post(
        f"/api/v1/cycles/part-cycle/units/{portal_id}/assessment",
        headers=auth,
    )

    # 4. Seed terminal state for question 1 (DELIVERED), question 2 (ESCALATED), question 3 (unreached/pending)
    session_id = ensure_session(repo, "part-cycle")
    q1_id = "part-cycle:1.1"
    q2_id = "part-cycle:1.2"

    # DELIVERED unit for q1
    repo.upsert_unit(
        session_id,
        q1_id,
        portal_id,
        UnitState.DELIVERED.value,
        {"consensus_answer": True, "consensus_confidence": 90, "justification": "Verified on portal."},
    )
    run1 = AssessorAgentRun(
        run_id=new_id("run"),
        session_id=session_id,
        question_id=q1_id,
        portal_id=portal_id,
        agent_index=0,
        round_number=1,
        answer=True,
        confidence=90,
        justification="Verified on portal.",
    )
    repo.insert_agent_run(run1)
    val1 = ValidationResult(
        validation_id=new_id("val"),
        run_id=run1.run_id,
        session_id=session_id,
        quality_score=0.9,
        gaps=[],
        passed=True,
        retry_number=0,
        verification_outcome=VerificationOutcome.CONFIRMED,
        verification_attempts=1,
    )
    repo.insert_validation_result(val1)
    adj1 = AdjudicationResult(
        adjudication_id=new_id("adj"),
        session_id=session_id,
        question_id=q1_id,
        portal_id=portal_id,
        round_number=1,
        input_run_ids=[run1.run_id],
        discrepancy_flagged=False,
        flag_reason=None,
        max_pairwise_confidence_delta=0,
        consensus_answer=True,
        consensus_confidence=90,
        below_acceptance_threshold=False,
    )
    repo.insert_adjudication_result(adj1)

    # ESCALATED unit for q2 with reason tag
    repo.upsert_unit(
        session_id,
        q2_id,
        portal_id,
        UnitState.ESCALATED.value,
        {"escalation_reason": EscalationReason.UNRESOLVED_DISAGREEMENT.value},
    )

    # Read results over API
    res = client.get(f"/api/v1/cycles/part-cycle/units/{portal_id}/results", headers=auth)
    assert res.status_code == 200
    data = res.json()

    assert data["complete"] is False
    assert data["questions_total"] == 3
    assert data["questions_completed"] == 2

    results_by_q = {r["indicator_id"]: r for r in data["results"]}

    # q1 (DELIVERED)
    r1 = results_by_q["1.1"]
    assert r1["assessed"] is True
    assert r1["answer"] is True
    assert r1["confidence"] == 90
    assert r1["blocked"] is False
    assert r1["blank_reason"] is None

    # q2 (ESCALATED)
    r2 = results_by_q["1.2"]
    assert r2["assessed"] is True
    assert r2["answer"] is None
    assert r2["blocked"] is True
    assert r2["blank_reason"] == "Left blank: Unresolved AI disagreement after retry limit"

    # q3 (Unreached)
    r3 = results_by_q["1.3"]
    assert r3["assessed"] is False
    assert r3["answer"] is None
    assert r3["blocked"] is False
    assert r3["blank_reason"] is None


def test_portal_and_api_share_one_dataset(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)

    # Create cycle, question, unit via API
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "shared-cycle", "name": "Shared Dataset Cycle"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/shared-cycle/questions",
        json={
            "indicator_id": "S.1",
            "title": "Shared Q",
            "what": "What",
            "why": "Why",
            "how": "How",
        },
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/shared-cycle/units",
        json={
            "country_id": "FIN",
            "display_name": "Finland",
            "url": "https://www.suomi.fi",
        },
        headers=auth,
    )

    # Assert repo lists them
    cycles = repo.list_cycles()
    assert any(c.cycle_id == "shared-cycle" for c in cycles)
    questions = repo.list_questions("shared-cycle")
    assert any(q.indicator_id == "S.1" for q in questions)
    portals = repo.list_portals("shared-cycle")
    assert any(p.country_id == "FIN" for p in portals)

    # Assert visible on portal admin UI
    admin_res = client.get("/admin")
    assert admin_res.status_code == 200
    assert "Shared Dataset Cycle" in admin_res.text

    # Create cycle via portal form
    portal_create = client.post(
        "/admin/projects",
        data={
            "cycle_id": "portal-cycle",
            "name": "Portal Created Cycle",
            "question_set_id": "un_osi_2024_master",
            "project_type": "national_osi",
        },
        follow_redirects=False,
    )
    assert portal_create.status_code == 303

    # Assert visible in API
    api_cycles = client.get("/api/v1/cycles", headers=auth).json()["cycles"]
    assert any(c["cycle_id"] == "portal-cycle" for c in api_cycles)


def test_api_discrepancy_endpoint_parity_and_no_answers_exposed(client: TestClient, auth: dict[str, str], conn, settings):
    from portal.reconciliation import unit_reconciliation_state
    repo = Repository(conn)
    cycle_id = "disc-api-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Discrepancy API Cycle", "discrepancy_rate_threshold": 0.05},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "D.1", "title": "Question D1", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "EST", "display_name": "Estonia", "url": "https://eesti.ee"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    session_id = ensure_session(repo, cycle_id)

    # 1. Awaiting second assessment -> state="awaiting_second_assessment", differing_answer_rate=None
    res1 = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/discrepancy", headers=auth)
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["state"] == "awaiting_second_assessment"
    assert data1["differing_answer_rate"] is None
    assert data1["rounds_consumed"] == 0
    assert data1["automatic_round_used"] is False
    assert data1["open_round_id"] is None
    assert "answer" not in data1
    assert "answers" not in data1

    # Verify parity with unit_reconciliation_state
    state_obj = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, repo.list_questions(cycle_id), settings)
    assert data1["state"] == state_obj.state

    # 2. Both assessors submit consensus answers + complete -> state="full_consensus", differing_answer_rate=0.0
    qid = f"{cycle_id}:D.1"
    for role in ("A", "B"):
        client.post(
            f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
            json={"question_id": qid, "role": role, "actor_id": f"actor-{role.lower()}", "answer": True},
            headers=auth,
        )
        client.post(
            f"/api/v1/cycles/{cycle_id}/units/{portal_id}/completions",
            json={"role": role, "actor_id": f"actor-{role.lower()}"},
            headers=auth,
        )

    res2 = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/discrepancy", headers=auth)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["state"] == "full_consensus"
    assert data2["differing_answer_rate"] == 0.0
    assert data2["compared_count"] == 1
    assert data2["disputed_question_ids"] == []


def test_api_end_to_end_discrepancy_and_round_opening(client: TestClient, auth: dict[str, str], conn):
    """Drive a unit end to end through REST API only and verify round opening (T070, FR-DR-070)."""
    cycle_id = "rest-e2e-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "REST E2E Cycle", "discrepancy_rate_threshold": 0.05},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "E.1", "title": "Question E1", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "LVA", "display_name": "Latvia", "url": "https://latvija.lv"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    qid = f"{cycle_id}:E.1"

    # Assessor A submits True, Assessor B submits False
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid, "role": "A", "actor_id": "actor-a", "answer": True},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/completions",
        json={"role": "A", "actor_id": "actor-a"},
        headers=auth,
    )

    # Unit is not yet complete for both -> state is above_tolerance_in_progress, no open round yet
    res_mid = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/discrepancy", headers=auth).json()
    assert res_mid["state"] == "awaiting_second_assessment"

    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid, "role": "B", "actor_id": "actor-b", "answer": False},
        headers=auth,
    )
    # The moment Assessor B completes, the round must open automatically (FR-DR-009, FR-DR-070)
    comp_b = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/completions",
        json={"role": "B", "actor_id": "actor-b"},
        headers=auth,
    )
    assert comp_b.status_code == 201

    res_post = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/discrepancy", headers=auth).json()
    assert res_post["state"] == "reconciliation_open"
    assert res_post["rounds_consumed"] == 1
    assert res_post["automatic_round_used"] is True
    assert res_post["open_round_id"] is not None
    assert res_post["disputed_question_ids"] == [qid]
    assert res_post["differing_answer_rate"] == 1.0

