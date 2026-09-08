"""Unit tests for REST API parity, read endpoints, cost ledger, and counts.

Covers T075, T076, FR-DL-080, FR-DL-081, FR-DL-090, FR-DL-092, SC-009.
Quickstart Scenario 9.
"""

from __future__ import annotations

import pytest

from portal.assignment import set_role_assignment
from portal.common import ensure_session
from portal.disagreement_labels import (
    dispatch_labelling_pass,
    labelling_counts,
    run_labelling_pass,
    unit_labelling_state,
)
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    Assessor,
    AssessorRole,
    DisagreementLabel,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
)

pytestmark = pytest.mark.unit


def _setup_cycle_and_portals(repo: Repository, cycle_id: str, portals: list[str]) -> None:
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="API Parity Cycle",
            questionnaire_ref="test-ref",
            country_set=[f"C_{p}" for p in portals],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.0,
        )
    )
    repo.upsert_assessor(Assessor(assessor_id="actor-a", display_name="Assessor A", email="a@test.gov"))
    repo.upsert_assessor(Assessor(assessor_id="actor-b", display_name="Assessor B", email="b@test.gov"))

    for p_id in portals:
        repo.insert_portal(
            TargetPortal(
                portal_id=p_id,
                cycle_id=cycle_id,
                country_id=f"C_{p_id}",
                unit_type="country",
                display_name=f"Country {p_id}",
            )
        )
        set_role_assignment(repo, cycle_id, p_id, AssessorRole.A, "actor-a", "admin")
        set_role_assignment(repo, cycle_id, p_id, AssessorRole.B, "actor-b", "admin")

    repo.insert_question(
        Question(
            question_id="q1",
            cycle_id=cycle_id,
            text="Question 1 text",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id="IND-01",
        )
    )


@pytest.mark.asyncio
async def test_scenario_9_portal_and_api_parity(
    client, conn, settings, auth, disputed_unit, fake_label_provider
):
    """T075: Scenario 9.

    Drive one unit through the portal and another through the REST API.
    Assert identical pass and label rows differing only in dispatched_by (FR-DL-080).
    """
    repo = Repository(conn)
    cycle_id = "parity-cycle"
    _setup_cycle_and_portals(repo, cycle_id, ["unit-portal", "unit-api"])
    session_id = ensure_session(repo, cycle_id)
    conn.commit()

    # Unit 1: Portal unit
    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-portal",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Portal notes", False, "https://gov.example/1", "Different notes"),
        },
        declare_both=False,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    # Complete via portal completion endpoint
    resp_p_a = client.post(
        f"/assessor/{cycle_id}/unit-portal/complete?role=A",
        data={"actor_id": "actor-a"},
        follow_redirects=True,
    )
    assert resp_p_a.status_code == 200
    resp_p_b = client.post(
        f"/assessor/{cycle_id}/unit-portal/complete?role=B",
        data={"actor_id": "actor-b"},
        follow_redirects=True,
    )
    assert resp_p_b.status_code == 200

    # Unit 2: API unit
    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-api",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Portal notes", False, "https://gov.example/1", "Different notes"),
        },
        declare_both=False,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    conn.commit()

    # Complete via REST API endpoint
    resp_api_a = client.post(
        f"/api/v1/cycles/{cycle_id}/units/unit-api/completions",
        headers=auth,
        json={"role": "A", "actor_id": "actor-a"},
    )
    assert resp_api_a.status_code in (200, 201)
    resp_api_b = client.post(
        f"/api/v1/cycles/{cycle_id}/units/unit-api/completions",
        headers=auth,
        json={"role": "B", "actor_id": "actor-b"},
    )
    assert resp_api_b.status_code in (200, 201)

    # Compare the two pass rows
    pass_portal = repo.get_labelling_pass(session_id, "unit-portal")
    pass_api = repo.get_labelling_pass(session_id, "unit-api")
    assert pass_portal is not None
    assert pass_api is not None

    # Identical except for pass_id, portal_id, and dispatched_by
    assert pass_portal.dispatched_by == "portal"
    assert pass_api.dispatched_by == "api"
    assert pass_portal.disputed_question_ids == pass_api.disputed_question_ids == ["q1"]
    assert pass_portal.compared_count == pass_api.compared_count == 1

    # Run labelling pass for both with same fake provider
    provider = fake_label_provider(
        canned_response={
            "label": "different_judgement",
            "reason": "Both evaluated same source but reached different conclusions.",
            "position_1_notes_contradict_answer": False,
            "position_2_notes_contradict_answer": False,
        }
    )

    class Runtime:
        def __init__(self):
            self.provider = provider

    rt = Runtime()
    await run_labelling_pass(settings.database_path, settings, rt, pass_portal.pass_id)
    await run_labelling_pass(settings.database_path, settings, rt, pass_api.pass_id)

    labels_portal = repo.list_labels_for_unit(session_id, "unit-portal")
    labels_api = repo.list_labels_for_unit(session_id, "unit-api")
    assert len(labels_portal) == 1
    assert len(labels_api) == 1

    lp = labels_portal[0]
    la = labels_api[0]
    assert lp.label == la.label == DisagreementLabel.DIFFERENT_JUDGEMENT
    assert lp.stated_reason == la.stated_reason
    assert lp.input_digest == la.input_digest
    assert lp.established_by == la.established_by == "classifier"


@pytest.mark.asyncio
async def test_api_read_endpoints_and_schema_field_safety(
    client, conn, settings, auth, disputed_unit, fake_label_provider
):
    """T072, T073: Read-only REST API endpoints return projection.

    The labels response model carries no field capable of holding an assessor's answer or notes (T072).
    """
    repo = Repository(conn)
    cycle_id = "read-cycle"
    _setup_cycle_and_portals(repo, cycle_id, ["unit-read"])
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-read",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Assessor secret notes A", False, "https://gov.example/1", "Assessor secret notes B"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    p = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-read",
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="api",
        provider_available=True,
    )
    assert p is not None

    class Runtime:
        def __init__(self):
            self.provider = fake_label_provider()

    await run_labelling_pass(settings.database_path, settings, Runtime(), p.pass_id)

    # 1. GET /cycles/{cycle_id}/units/{portal_id}/labels
    resp_labels = client.get(
        f"/api/v1/cycles/{cycle_id}/units/unit-read/labels",
        headers=auth,
    )
    assert resp_labels.status_code == 200
    labels_data = resp_labels.json()
    assert len(labels_data) == 1
    item = labels_data[0]
    assert item["question_id"] == "q1"
    assert item["state"] == "established"
    assert item["label"] == "different_judgement"
    assert item["badge"] == "Judged differently"
    assert "provenance" in item
    assert item["provenance"]["established_by"] == "classifier"

    # CRITICAL FIELD SAFETY CHECK (T072):
    # Ensure neither assessor's answer nor assessor notes appear anywhere in the response JSON!
    resp_text = resp_labels.text
    assert "Assessor secret notes A" not in resp_text
    assert "Assessor secret notes B" not in resp_text
    for key in item.keys():
        assert key not in ("answer", "notes", "justification", "answer_a", "answer_b", "notes_a", "notes_b")

    # 2. GET /cycles/{cycle_id}/indicator-ambiguity
    resp_amb = client.get(
        f"/api/v1/cycles/{cycle_id}/indicator-ambiguity",
        headers=auth,
    )
    assert resp_amb.status_code == 200
    amb_data = resp_amb.json()
    assert len(amb_data) == 1
    assert amb_data[0]["indicator_key"] == "IND-01"
    assert amb_data[0]["judged_differently"] == 1

    # 3. GET /labelling/counts
    resp_counts = client.get(
        f"/api/v1/labelling/counts?cycle_id={cycle_id}",
        headers=auth,
    )
    assert resp_counts.status_code == 200
    counts_data = resp_counts.json()
    assert counts_data["established_by_classifier"] == 1
    assert counts_data["awaiting"] == 0
    assert counts_data["exhausted"] == 0


@pytest.mark.asyncio
async def test_cost_ledger_and_count_dynamics(
    conn, settings, disputed_unit, fake_label_provider, raising_provider
):
    """T076: cost_ledger_entries gains rows with stage='disagreement_labelling' and agent_index IS NULL.

    Deterministic labels add NO ledger rows (SC-009).
    labelling_counts reports rising awaiting under down provider and rising exhausted after 3 runs (FR-DL-092).
    """
    repo = Repository(conn)
    cycle_id = "cost-cycle"
    _setup_cycle_and_portals(repo, cycle_id, ["unit-cost-clf", "unit-cost-det"])
    session_id = ensure_session(repo, cycle_id)

    # Unit 1: classifier label
    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-cost-clf",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes", False, "https://gov.example/1", "Notes"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    pass_clf = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-cost-clf",
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="api",
        provider_available=True,
    )

    # Count cost ledger entries before
    c_before = repo.conn.execute("SELECT COUNT(*) FROM cost_ledger_entries").fetchone()[0]

    class RuntimeClassifier:
        def __init__(self):
            self.provider = fake_label_provider()

    await run_labelling_pass(settings.database_path, settings, RuntimeClassifier(), pass_clf.pass_id)

    rows = repo.conn.execute(
        "SELECT stage, agent_index, data FROM cost_ledger_entries WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    assert len(rows) > c_before
    new_entry = rows[-1]
    assert new_entry[0] == "disagreement_labelling"
    assert new_entry[1] is None  # agent_index IS NULL (FR-DL-090)

    # Unit 2: deterministic label (one has no URL -> ONE_FOUND_NOTHING)
    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-cost-det",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes", False, None, "Notes"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    pass_det = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="unit-cost-det",
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="api",
        provider_available=True,
    )
    c_before_det = repo.conn.execute("SELECT COUNT(*) FROM cost_ledger_entries").fetchone()[0]
    await run_labelling_pass(settings.database_path, settings, RuntimeClassifier(), pass_det.pass_id)
    c_after_det = repo.conn.execute("SELECT COUNT(*) FROM cost_ledger_entries").fetchone()[0]
    # Deterministic label adds NO ledger rows (SC-009)
    assert c_after_det == c_before_det

    # Part 3: Count dynamics under down provider (awaiting rising -> exhausted rising)
    _setup_cycle_and_portals(repo, "fail-cycle", ["unit-fail"])
    session_fail = ensure_session(repo, "fail-cycle")
    disputed_unit(
        session_id=session_fail,
        cycle_id="fail-cycle",
        portal_id="unit-fail",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes", False, "https://gov.example/1", "Notes"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    pass_fail = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_fail,
        cycle_id="fail-cycle",
        portal_id="unit-fail",
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="api",
        provider_available=True,
    )

    # Initial state: awaiting = 1
    cnts0 = labelling_counts(repo, cycle_id="fail-cycle")
    assert cnts0.awaiting == 1
    assert cnts0.exhausted == 0

    class FailingRuntime:
        def __init__(self):
            self.provider = raising_provider("503 Provider Outage")

    rt_fail = FailingRuntime()

    # Attempt 1: still awaiting = 1
    await run_labelling_pass(settings.database_path, settings, rt_fail, pass_fail.pass_id)
    cnts1 = labelling_counts(repo, cycle_id="fail-cycle")
    assert cnts1.awaiting == 1
    assert cnts1.exhausted == 0

    # Attempt 2: still awaiting = 1
    await run_labelling_pass(settings.database_path, settings, rt_fail, pass_fail.pass_id)
    cnts2 = labelling_counts(repo, cycle_id="fail-cycle")
    assert cnts2.awaiting == 1
    assert cnts2.exhausted == 0

    # Attempt 3: becomes exhausted = 1, awaiting = 0 (FR-DL-092)
    await run_labelling_pass(settings.database_path, settings, rt_fail, pass_fail.pass_id)
    cnts3 = labelling_counts(repo, cycle_id="fail-cycle")
    assert cnts3.awaiting == 0
    assert cnts3.exhausted == 1
