"""Comprehensive unit and integration tests for all headless FastAPI capabilities."""

import pytest
from fastapi.testclient import TestClient

from portal.common import ensure_session
from shared.persistence.repositories import Repository
from shared.state.entities import (
    EscalationQueueItem,
    EscalationReason,
    PublicationRecord,
    new_id,
)

pytestmark = pytest.mark.unit


def test_reference_endpoints(client: TestClient, auth: dict[str, str]):
    # 1. Question sets registry
    res = client.get("/api/v1/reference/question-sets", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert "question_sets" in data
    assert len(data["question_sets"]) > 0
    set_ids = [s["set_id"] for s in data["question_sets"]]
    assert "un_osi_2024_master" in set_ids or "un_losi_2024_master" in set_ids

    # 2. Countries reference
    res = client.get("/api/v1/reference/countries", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert "countries" in data
    assert len(data["countries"]) >= 193
    country_codes = [c["code"] for c in data["countries"]]
    assert "DK" in country_codes
    assert "US" in country_codes


def test_cycle_template_bootstrapping_and_bulk_units(client: TestClient, auth: dict[str, str]):
    # Create a cycle bootstrapped with UN question set and selected countries
    res = client.post(
        "/api/v1/cycles",
        json={
            "cycle_id": "losi-uk-2025-test",
            "name": "LOSI UK 2025 Test",
            "project_type": "losi_city",
            "question_set_id": "un_losi_2024_master",
            "country_ids": ["DK", "US"],
        },
        headers=auth,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["cycle_id"] == "losi-uk-2025-test"
    assert "DK" in data["country_set"]
    assert "US" in data["country_set"]

    # Verify questions were loaded from template
    q_res = client.get("/api/v1/cycles/losi-uk-2025-test/questions", headers=auth)
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert len(q_data["questions"]) > 0

    # Verify units were created
    u_res = client.get("/api/v1/cycles/losi-uk-2025-test/units", headers=auth)
    assert u_res.status_code == 200
    u_data = u_res.json()
    assert len(u_data["units"]) == 2
    portal_id = u_data["units"][0]["portal_id"]

    # Get single unit
    single_u = client.get(f"/api/v1/cycles/losi-uk-2025-test/units/{portal_id}", headers=auth)
    assert single_u.status_code == 200
    assert single_u.json()["portal_id"] == portal_id

    # Bulk add more units
    bulk_res = client.post(
        "/api/v1/cycles/losi-uk-2025-test/units/bulk",
        json={
            "units": [
                {
                    "country_id": "FR",
                    "display_name": "Paris, France",
                    "url": "https://www.paris.fr",
                    "unit_type": "city",
                },
                {
                    "country_id": "DE",
                    "display_name": "Berlin, Germany",
                    "url": "https://www.berlin.de",
                    "unit_type": "city",
                },
            ]
        },
        headers=auth,
    )
    assert bulk_res.status_code == 201
    assert bulk_res.json()["created_count"] == 2


def test_question_crud_and_patch(client: TestClient, auth: dict[str, str]):
    cycle_id = "test-crud-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "CRUD Test Cycle"},
        headers=auth,
    )

    # 1. Add custom question
    q_res = client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={
            "indicator_id": "CUSTOM.01",
            "title": "Custom Test Indicator",
            "what": "What criteria",
            "why": "Why criteria",
            "how": "How to score",
            "module": "Test Module",
            "evidence_locus": "national_portal_only",
        },
        headers=auth,
    )
    assert q_res.status_code == 201
    q_data = q_res.json()
    qid = q_data["question_id"]
    assert qid == f"{cycle_id}:CUSTOM.01"

    # 2. Get single question
    get_res = client.get(f"/api/v1/cycles/{cycle_id}/questions/{qid}", headers=auth)
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Custom Test Indicator"

    # 3. Edit custom question
    patch_res = client.patch(
        f"/api/v1/cycles/{cycle_id}/questions/{qid}",
        json={
            "title": "Revised Custom Test Indicator",
            "what": "Revised What criteria",
            "editor_actor_id": "admin-tester",
        },
        headers=auth,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Revised Custom Test Indicator"
    assert patch_res.json()["what"] == "Revised What criteria"


def test_tolerance_update_and_reconciliation_closure(client: TestClient, auth: dict[str, str], db_path: str):
    cycle_id = "tolerance-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Tolerance Test Cycle", "discrepancy_rate_threshold": 0.05},
        headers=auth,
    )

    # Update tolerance to 15%
    tol_res = client.post(
        f"/api/v1/cycles/{cycle_id}/tolerance",
        json={"tolerance": 15.0, "actor_id": "senior-lead"},
        headers=auth,
    )
    assert tol_res.status_code == 200
    tol_data = tol_res.json()
    assert tol_data["new_tolerance"] == 0.15
    assert tol_data["previous_tolerance"] == 0.05
    assert tol_data["changed_by"] == "senior-lead"


def test_msq_text_ingestion(client: TestClient, auth: dict[str, str]):
    cycle_id = "msq-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "MSQ Test Cycle"},
        headers=auth,
    )
    unit_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "DK", "display_name": "Denmark", "url": "https://borger.dk"},
        headers=auth,
    )
    portal_id = unit_res.json()["portal_id"]

    # Ingest text MSQ
    msq_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/msq",
        data={"text_content": "Official portal: https://borger.dk. Open data: https://data.gov.dk", "page_count": 5},
        headers=auth,
    )
    assert msq_res.status_code == 201
    msq_data = msq_res.json()
    assert msq_data["country_id"] == "DK"
    assert msq_data["page_count"] == 5

    # Query MSQ status
    detail_res = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/msq", headers=auth)
    assert detail_res.status_code == 200
    assert detail_res.json()["has_msq"] is True


def test_batch_assessment_and_status(client: TestClient, auth: dict[str, str]):
    cycle_id = "batch-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Batch Test Cycle"},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "Q1", "title": "Portal Check", "what": "Check", "why": "Check", "how": "Check"},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "US", "display_name": "USA", "url": "https://usa.gov"},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "FR", "display_name": "France", "url": "https://service-public.fr"},
        headers=auth,
    )

    # Batch trigger
    batch_res = client.post(
        f"/api/v1/cycles/{cycle_id}/assessments/batch",
        json={"actor_id": "batch-caller"},
        headers=auth,
    )
    assert batch_res.status_code == 202
    batch_data = batch_res.json()
    assert batch_data["total_jobs"] == 2

    # Query overall cycle assessments status
    status_res = client.get(f"/api/v1/cycles/{cycle_id}/assessments/status", headers=auth)
    assert status_res.status_code == 200
    assert len(status_res.json()) == 2


def test_reconciliation_workspace_and_joint_answering(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)
    cycle_id = "recon-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Recon Test Cycle", "discrepancy_rate_threshold": 0.05},
        headers=auth,
    )
    q_res = client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "Q1", "title": "Check", "what": "Check", "why": "Check", "how": "Check"},
        headers=auth,
    )
    qid = q_res.json()["question_id"]

    u_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "DK", "display_name": "Denmark", "url": "https://borger.dk"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]

    ensure_session(repo, cycle_id)

    # Role A answers True, Role B answers False
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid, "role": "A", "actor_id": "assessor-a", "answer": True, "evidence_url": "https://borger.dk/a"},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/human-answers",
        json={"question_id": qid, "role": "B", "actor_id": "assessor-b", "answer": False, "evidence_url": "https://borger.dk/b"},
        headers=auth,
    )

    # Both declare completion
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/completions",
        json={"role": "A", "actor_id": "assessor-a"},
        headers=auth,
    )
    client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/completions",
        json={"role": "B", "actor_id": "assessor-b"},
        headers=auth,
    )

    # Check discrepancy state
    disc_res = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/discrepancy", headers=auth)
    assert disc_res.status_code == 200
    disc_data = disc_res.json()
    assert disc_data["state"] == "reconciliation_open"
    assert qid in disc_data["disputed_question_ids"]

    # Check reconciliation workspace
    ws_res = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/reconciliation?role=A", headers=auth)
    assert ws_res.status_code == 200
    ws_data = ws_res.json()
    assert len(ws_data["disputed_rows"]) == 1
    assert ws_data["disputed_rows"][0]["peer_answer"] is False

    # Commit joint answer
    joint_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/reconciliation/{qid}/joint",
        json={"role": "A", "actor_id": "assessor-a", "answer": True, "justification": "Agreed after joint review of Danish portal legislation."},
        headers=auth,
    )
    assert joint_res.status_code == 201
    assert joint_res.json()["answer"] is True
    assert joint_res.json()["round_closed"] is True


def test_escalation_queue_and_disposition(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)
    cycle_id = "esc-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Esc Test Cycle"},
        headers=auth,
    )
    session_id = ensure_session(repo, cycle_id)
    u_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "US", "display_name": "USA", "url": "https://usa.gov"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]

    # Insert an escalation queue item
    item_id = new_id("esc")
    repo.insert_escalation(
        EscalationQueueItem(
            item_id=item_id,
            session_id=session_id,
            portal_id=portal_id,
            question_id="Q1",
            reason=EscalationReason.UNRESOLVED_DISAGREEMENT,
            context={"note": "Assessor models disagreed"},
        )
    )

    # List escalations
    list_res = client.get(f"/api/v1/cycles/{cycle_id}/escalations", headers=auth)
    assert list_res.status_code == 200
    assert len(list_res.json()["escalations"]) >= 1

    # Dispose escalation
    disp_res = client.post(
        f"/api/v1/cycles/{cycle_id}/escalations/{item_id}/dispose",
        json={"resolution": "overridden_by_senior", "notes": "Confirmed affirmative based on national legislation.", "actor_id": "senior-lead"},
        headers=auth,
    )
    assert disp_res.status_code == 200
    assert disp_res.json()["resolution"] == "overridden_by_senior"


def test_ai_review_actions(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)
    cycle_id = "review-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Review Test Cycle"},
        headers=auth,
    )
    q_res = client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "Q1", "title": "Online Tax Filing", "what": "Tax", "why": "Tax", "how": "Tax"},
        headers=auth,
    )
    qid = q_res.json()["question_id"]
    u_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "FR", "display_name": "France", "url": "https://impots.gouv.fr"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]
    ensure_session(repo, cycle_id)

    # Get review status
    st_res = client.get(f"/api/v1/cycles/{cycle_id}/units/{portal_id}/review-status", headers=auth)
    assert st_res.status_code == 200

    # Approve decision
    app_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/questions/{qid}/review/approve",
        json={"actor_id": "reviewer-1"},
        headers=auth,
    )
    assert app_res.status_code == 200
    assert app_res.json()["action"] == "approve"

    # Edit decision
    edit_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/questions/{qid}/review/edit",
        json={"actor_id": "reviewer-1", "edited_answer": True},
        headers=auth,
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["action"] == "edit"

    # Reject decision
    rej_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units/{portal_id}/questions/{qid}/review/reject",
        json={"actor_id": "reviewer-1", "override_answer": False, "rejection_reason": "Broken evidence link"},
        headers=auth,
    )
    assert rej_res.status_code == 200
    assert rej_res.json()["action"] == "reject_override"


def test_public_reporting_knowledge_base(client: TestClient, auth: dict[str, str], conn):
    repo = Repository(conn)
    cycle_id = "pub-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Public Knowledge Base Test Cycle", "project_type": "national_osi"},
        headers=auth,
    )
    q_res = client.post(
        f"/api/v1/cycles/{cycle_id}/questions",
        json={"indicator_id": "Q1", "title": "E-Service", "what": "E-Service", "why": "E-Service", "how": "E-Service"},
        headers=auth,
    )
    qid = q_res.json()["question_id"]
    u_res = client.post(
        f"/api/v1/cycles/{cycle_id}/units",
        json={"country_id": "DK", "display_name": "Denmark", "url": "https://borger.dk"},
        headers=auth,
    )
    portal_id = u_res.json()["portal_id"]

    # Directly insert publication record for testing public reporting JSON endpoints
    repo.insert_publication(
        PublicationRecord(
            publication_id=new_id("pub"),
            cycle_id=cycle_id,
            portal_id=portal_id,
            published_by_actor_id="senior-reviewer",
            score=1.0,
            score_breakdown={qid: True},
            contested_question_ids=[],
        )
    )

    # 1. List public cycles
    cycles_res = client.get("/api/v1/public/cycles", headers=auth)
    assert cycles_res.status_code == 200
    cycle_ids = [c["cycle_id"] for c in cycles_res.json()["cycles"]]
    assert cycle_id in cycle_ids

    # 2. Get cycle rankings table
    rank_res = client.get(f"/api/v1/public/cycles/{cycle_id}/rankings", headers=auth)
    assert rank_res.status_code == 200
    rank_data = rank_res.json()
    assert len(rank_data["rankings"]) == 1
    assert rank_data["rankings"][0]["country_id"] == "DK"
    assert rank_data["rankings"][0]["score"] == 1.0

    # 3. Get public unit profile
    prof_res = client.get(f"/api/v1/public/cycles/{cycle_id}/units/{portal_id}", headers=auth)
    assert prof_res.status_code == 200
    prof_data = prof_res.json()
    assert prof_data["score"] == 1.0
    assert len(prof_data["breakdown"]) == 1
    assert prof_data["breakdown"][0]["answer"] is True


def test_export_and_telemetry_and_verify(client: TestClient, auth: dict[str, str], tmp_path):
    cycle_id = "telemetry-test-cycle"
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": cycle_id, "name": "Telemetry Test Cycle"},
        headers=auth,
    )

    # Export triggering
    out_dir = str(tmp_path / "exports")
    exp_res = client.post(
        f"/api/v1/cycles/{cycle_id}/export",
        json={"output_directory": out_dir, "include_exclusions": True},
        headers=auth,
    )
    assert exp_res.status_code == 200
    assert exp_res.json()["cycle_id"] == cycle_id

    # Retrieve answers and exclusions NDJSON streams
    ans_res = client.get(f"/api/v1/cycles/{cycle_id}/export/answers", headers=auth)
    assert ans_res.status_code == 200

    exc_res = client.get(f"/api/v1/cycles/{cycle_id}/export/exclusions", headers=auth)
    assert exc_res.status_code == 200

    # Telemetry endpoints
    sum_res = client.get(f"/api/v1/cycles/{cycle_id}/telemetry/summary", headers=auth)
    assert sum_res.status_code == 200
    assert "unit_states" in sum_res.json()["summary"]

    time_res = client.get(f"/api/v1/cycles/{cycle_id}/telemetry/timings", headers=auth)
    assert time_res.status_code == 200

    cost_res = client.get(f"/api/v1/cycles/{cycle_id}/telemetry/cost", headers=auth)
    assert cost_res.status_code == 200

    # Audit summary
    audit_res = client.get(f"/api/v1/cycles/{cycle_id}/audit/summary", headers=auth)
    assert audit_res.status_code == 200

    # Verification run
    ver_res = client.post(
        f"/api/v1/cycles/{cycle_id}/verify",
        json={"checks": ["independence", "evidence", "resume", "telemetry", "credentials"]},
        headers=auth,
    )
    assert ver_res.status_code == 200
    assert "clean" in ver_res.json()

    # System config & health
    cfg_res = client.get("/api/v1/system/config", headers=auth)
    assert cfg_res.status_code == 200
    assert "parameters" in cfg_res.json()

    hlth_res = client.get("/api/v1/system/health", headers=auth)
    assert hlth_res.status_code == 200
    assert hlth_res.json()["status"] == "ok"
