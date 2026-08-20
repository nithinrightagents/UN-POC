"""Assessment jobs, lifecycle, restart sweep, and concurrency tests (spec 007 US2)."""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from api.jobs import AssessmentJob, sweep_interrupted_jobs
from portal.common import ensure_session
from portal.webapp import build_app
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db
from shared.state.entities import Question, SurveyCycle, TargetPortal, UnitState, AnswerType, EvidenceLocus

pytestmark = pytest.mark.unit


def test_lifespan_starts_shared_runtime(tmp_path):
    db_file = str(tmp_path / "lifespan_test.db")
    settings = Settings(
        api_key="test-secret",
        google_cloud_project="test-proj",
        google_cloud_location="us-central1",
        database_path=db_file,
    )
    app = build_app(db_file, settings)
    with patch("playwright.async_api.async_playwright") as mock_playwright:
        with TestClient(app):
            assert hasattr(app.state, "ai_runtime")
            runtime = app.state.ai_runtime
            assert runtime is not None
            assert runtime.provider is not None
            assert runtime.limiter is not None
            assert runtime.http_client is not None
            assert not runtime._browser_started
            mock_playwright.assert_not_called()


def test_interrupted_job_reports_failed_with_terminal_cause_after_sweep(tmp_path):
    db_file = str(tmp_path / "sweep_test.db")
    init_db(db_file)
    conn = connect(db_file)
    repo = Repository(conn)

    # 1. Setup cycle, 5 questions, 1 unit
    cycle = SurveyCycle(cycle_id="c-sweep", name="Sweep Cycle", questionnaire_ref="Ref", country_set=["DNK"])
    repo.insert_cycle(cycle)
    for i in range(1, 6):
        repo.insert_question(
            Question(
                question_id=f"c-sweep:q{i}",
                cycle_id="c-sweep",
                text=f"Q{i}",
                answer_type=AnswerType.BINARY,
                evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
                indicator_id=f"q{i}",
            )
        )
    portal = TargetPortal(portal_id="portal-sweep", cycle_id="c-sweep", country_id="DNK", resolved_url="https://borger.dk")
    repo.insert_portal(portal)

    session_id = ensure_session(repo, "c-sweep")

    # 2. Seed running job and 2 completed units
    job = AssessmentJob(
        job_id="job-sweep-1",
        session_id=session_id,
        cycle_id="c-sweep",
        portal_id="portal-sweep",
        state="running",
        questions_total=5,
        failure_cause=None,
        triggered_by="api",
        data={"actor_id": "test"},
    )
    repo.insert_assessment_job(job)
    repo.upsert_unit(session_id, "c-sweep:q1", "portal-sweep", UnitState.DELIVERED.value, {})
    repo.upsert_unit(session_id, "c-sweep:q2", "portal-sweep", UnitState.ESCALATED.value, {})
    conn.commit()
    conn.close()

    # 3. Simulate startup lifespan with app
    settings = Settings(
        api_key="test-secret",
        database_path=db_file,
    )
    app = build_app(db_file, settings)

    with patch("api.jobs.run_assessment_job", new_callable=AsyncMock):
        with TestClient(app) as client:
            auth = {"X-API-Key": "test-secret"}
            res = client.get("/api/v1/cycles/c-sweep/units/portal-sweep/assessment", headers=auth)
            assert res.status_code == 200
            data = res.json()
            assert data["state"] == "failed"
            assert data["failure_cause"] == "service_stopped_mid_run"
            assert data["questions_total"] == 5
            assert data["questions_completed"] == 2
            assert data["job_id"] == "job-sweep-1"

            # 4. Assert unit can be re-triggered now that it's failed
            trig_res = client.post("/api/v1/cycles/c-sweep/units/portal-sweep/assessment", headers=auth)
            assert trig_res.status_code == 202
            assert trig_res.json()["state"] == "running"
            assert trig_res.json()["already_running"] is False
            assert trig_res.json()["job_id"] != "job-sweep-1"


def test_never_triggered_unit_reports_zero_progress_and_cycle_total(client: TestClient, auth: dict[str, str]):
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "never-cycle", "name": "Never Triggered Cycle"},
        headers=auth,
    )
    for i in range(1, 4):
        client.post(
            "/api/v1/cycles/never-cycle/questions",
            json={"indicator_id": f"N.{i}", "title": f"Title {i}", "what": "W", "why": "Y", "how": "H"},
            headers=auth,
        )
    unit_res = client.post(
        "/api/v1/cycles/never-cycle/units",
        json={"country_id": "NOR", "display_name": "Norway", "url": "https://norge.no"},
        headers=auth,
    )
    portal_id = unit_res.json()["portal_id"]

    res = client.get(f"/api/v1/cycles/never-cycle/units/{portal_id}/assessment", headers=auth)
    assert res.status_code == 200
    data = res.json()
    assert data["state"] == "never_triggered"
    assert data["questions_total"] == 3
    assert data["questions_completed"] == 0
    assert data["job_id"] is None
    assert data["failure_cause"] is None
    assert data["triggered_by"] is None
    assert data["outcomes"] is None


def test_idempotent_retrigger_at_capacity_succeeds_without_starting_new_task(
    client: TestClient, auth: dict[str, str], settings: Settings
):
    # max_concurrent_assessment_runs = 2 in fixture
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "idemp-cycle", "name": "Idempotent Cycle"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/idemp-cycle/questions",
        json={"indicator_id": "I.1", "title": "Title", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u1 = client.post(
        "/api/v1/cycles/idemp-cycle/units",
        json={"country_id": "U1", "display_name": "Unit 1", "url": "https://u1.gov"},
        headers=auth,
    ).json()["portal_id"]
    u2 = client.post(
        "/api/v1/cycles/idemp-cycle/units",
        json={"country_id": "U2", "display_name": "Unit 2", "url": "https://u2.gov"},
        headers=auth,
    ).json()["portal_id"]

    # Trigger both to reach capacity (2/2)
    t1 = client.post(f"/api/v1/cycles/idemp-cycle/units/{u1}/assessment", headers=auth)
    assert t1.status_code == 202
    job_id_1 = t1.json()["job_id"]
    assert t1.json()["already_running"] is False

    t2 = client.post(f"/api/v1/cycles/idemp-cycle/units/{u2}/assessment", headers=auth)
    assert t2.status_code == 202
    assert t2.json()["already_running"] is False

    # Idempotent re-trigger for u1 at capacity returns 202 with already_running=True (not 429)
    re_t1 = client.post(f"/api/v1/cycles/idemp-cycle/units/{u1}/assessment", headers=auth)
    assert re_t1.status_code == 202
    assert re_t1.json()["already_running"] is True
    assert re_t1.json()["job_id"] == job_id_1


def test_concurrency_cap_rejects_with_429_and_retry_after(
    client: TestClient, auth: dict[str, str], conn
):
    repo = Repository(conn)
    client.post(
        "/api/v1/cycles",
        json={"cycle_id": "cap-cycle", "name": "Capacity Cycle"},
        headers=auth,
    )
    client.post(
        "/api/v1/cycles/cap-cycle/questions",
        json={"indicator_id": "C.1", "title": "Title", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    u1 = client.post(
        "/api/v1/cycles/cap-cycle/units",
        json={"country_id": "C1", "display_name": "Unit 1", "url": "https://c1.gov"},
        headers=auth,
    ).json()["portal_id"]
    u2 = client.post(
        "/api/v1/cycles/cap-cycle/units",
        json={"country_id": "C2", "display_name": "Unit 2", "url": "https://c2.gov"},
        headers=auth,
    ).json()["portal_id"]
    u3 = client.post(
        "/api/v1/cycles/cap-cycle/units",
        json={"country_id": "C3", "display_name": "Unit 3", "url": "https://c3.gov"},
        headers=auth,
    ).json()["portal_id"]

    # Trigger u1 and u2 (filling capacity 2/2)
    client.post(f"/api/v1/cycles/cap-cycle/units/{u1}/assessment", headers=auth)
    client.post(f"/api/v1/cycles/cap-cycle/units/{u2}/assessment", headers=auth)

    # Trigger u3 (should be rejected with 429)
    res_u3 = client.post(f"/api/v1/cycles/cap-cycle/units/{u3}/assessment", headers=auth)
    assert res_u3.status_code == 429
    assert res_u3.headers.get("retry-after") == "30"
    data = res_u3.json()
    assert data["error"]["code"] == "capacity_reached"

    # Verify no job row was created for u3
    assert repo.latest_assessment_job("cap-cycle", u3) is None


def test_trigger_preconditions_order_and_rejections(
    client: TestClient, auth: dict[str, str], conn
):
    repo = Repository(conn)

    # 1. Non-existent cycle -> 404
    r1 = client.post("/api/v1/cycles/missing-cycle/units/portal-1/assessment", headers=auth)
    assert r1.status_code == 404
    assert r1.json()["error"]["code"] == "not_found"

    # Setup cycle 1
    client.post("/api/v1/cycles", json={"cycle_id": "pre-c1", "name": "Cycle 1"}, headers=auth)

    # 2. Non-existent unit in existing cycle -> 404
    r2 = client.post("/api/v1/cycles/pre-c1/units/portal-missing/assessment", headers=auth)
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "not_found"

    # Setup cycle 2 and unit in cycle 2
    client.post("/api/v1/cycles", json={"cycle_id": "pre-c2", "name": "Cycle 2"}, headers=auth)
    u_c2 = client.post(
        "/api/v1/cycles/pre-c2/units",
        json={"country_id": "C2U", "display_name": "Unit C2", "url": "https://c2.gov"},
        headers=auth,
    ).json()["portal_id"]

    # 3. Unit belongs to cycle 2, but requested under cycle 1 -> 404
    r3 = client.post(f"/api/v1/cycles/pre-c1/units/{u_c2}/assessment", headers=auth)
    assert r3.status_code == 404
    assert r3.json()["error"]["code"] == "not_found"

    # 4. A unit with no resolved URL is NOT rejected for that reason -- it
    # falls through to the next precondition (cycle_has_no_questions), since
    # resolved_url is a leftover manual-entry field never read by the actual
    # link-resolution chain (bulk-tagged NOSI/LOSI units are created with no
    # resolved_url at all and must remain assessable).
    portal_nourl = TargetPortal(
        portal_id="portal-nourl",
        cycle_id="pre-c1",
        country_id="NOURL",
        resolved_url="",
        display_name="No URL",
    )
    repo.insert_portal(portal_nourl)
    r4 = client.post("/api/v1/cycles/pre-c1/units/portal-nourl/assessment", headers=auth)
    assert r4.status_code == 409
    assert r4.json()["error"]["code"] == "precondition_failed"
    assert r4.json()["error"]["details"]["reason"] == "cycle_has_no_questions"

    # 5. Once the cycle has a question, the same no-URL unit can start an
    # assessment -- proving the missing URL alone no longer blocks it.
    client.post(
        "/api/v1/cycles/pre-c1/questions",
        json={"indicator_id": "P.1", "title": "Title", "what": "W", "why": "Y", "how": "H"},
        headers=auth,
    )
    r5 = client.post("/api/v1/cycles/pre-c1/units/portal-nourl/assessment", headers=auth)
    assert r5.status_code == 202
    assert r5.json()["already_running"] is False
