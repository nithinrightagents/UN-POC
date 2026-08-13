"""Unit tests for Phase 9 export and EKAP projection (T105-T109)."""

import json
import sqlite3
import pytest
from shared.state.entities import (
    AnswerType,
    AssessmentSession,
    EvidenceLocus,
    Question,
    SessionMode,
    SessionStatus,
    SurveyCycle,
    TargetPortal,
    UnitState,
)
from export.ekap_projection import project_to_ekap_aosq_interactions
from export.invariants import ExportInvariantError, validate_export_record, validate_export_set
from export.writer import export_cycle_answers
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL


def test_export_invariants_validation():
    # Valid record
    rec = {
        "question": {"question_id": "Q1"},
        "delivered_answer": True,
        "session_id": "sess-1",
        "evidence_refs": [],
    }
    validate_export_record(rec, "production")

    # E1 violation: not delivered_answer
    with pytest.raises(ExportInvariantError, match="E1"):
        validate_export_record({"delivered_answer": False, "session_id": "s1", "evidence_refs": []}, "production")

    # E2 violation: benchmark session
    with pytest.raises(ExportInvariantError, match="E2"):
        validate_export_record(rec, "benchmark")

    # E4 violation: invalid exclusion reason
    with pytest.raises(ExportInvariantError, match="E4"):
        validate_export_set([], [{"reason": "invalid_reason_xyz"}], 1)


def test_export_cycle_answers_and_ekap_projection(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)

    repo = Repository(conn)

    cycle_id = "2026-cycle"
    repo.insert_cycle(SurveyCycle(cycle_id, "2026 Biennial", "ref-1", ["EE"]))
    repo.insert_question(Question("Q1", cycle_id, "Quest 1", AnswerType.BINARY, EvidenceLocus.NATIONAL_PORTAL_ONLY))
    repo.insert_portal(TargetPortal("portal-EE", cycle_id, "EE", "https://eesti.ee"))

    session_id = "sess-prod-1"
    repo.insert_session(AssessmentSession(session_id, cycle_id, SessionMode.PRODUCTION, "cfg-1", status=SessionStatus.COMPLETE))
    repo.upsert_unit(session_id, "Q1", "portal-EE", UnitState.DELIVERED.value, {"consensus_answer": True, "consensus_confidence": 95})

    ndjson_path, excl_path = export_cycle_answers(repo, cycle_id, tmp_path)

    assert ndjson_path.exists()
    assert excl_path.exists()

    lines = ndjson_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert record["cycle_id"] == cycle_id
    assert record["country_id"] == "EE"
    assert record["delivered_answer"] is True

    # Test EKAP projection
    projection = project_to_ekap_aosq_interactions(repo, session_id)
    assert isinstance(projection, list)
