"""Unit tests for Phase 9 export and EKAP projection (T105-T109)."""

import json
import sqlite3

import pytest

from export.ekap_projection import project_to_ekap_aosq_interactions
from export.invariants import (
    VALID_EXCLUSION_REASONS,
    ExportInvariantError,
    validate_export_record,
    validate_export_set,
)
from export.writer import export_cycle_answers
from review import actions
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    AnswerType,
    AssessmentSession,
    EscalationReason,
    EvidenceLocus,
    Question,
    SessionMode,
    SessionStatus,
    SurveyCycle,
    TargetPortal,
    UnitState,
)


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


def test_valid_exclusion_reasons_matches_escalation_reason_enum():
    # research.md R5 -- the exclusion-reason set is derived from the same
    # EscalationReason enumeration reason_tags.py is keyed on, plus the one
    # non-blocking code ("awaiting_human_review") that isn't an EscalationReason.
    assert VALID_EXCLUSION_REASONS == {r.value for r in EscalationReason} | {"awaiting_human_review"}


def _seed_export_fixture(tmp_path):
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
    return repo, cycle_id, session_id


def test_blocked_unit_with_decision_reaches_export(tmp_path):
    repo, cycle_id, session_id = _seed_export_fixture(tmp_path)
    repo.upsert_unit(
        session_id, "Q1", "portal-EE", UnitState.ESCALATED.value,
        {"escalation_reason": EscalationReason.UNRESOLVED_DISAGREEMENT.value},
    )
    actions.edit(repo, session_id, "Q1", "portal-EE", None, True, "reviewer-a")

    ndjson_path, excl_path = export_cycle_answers(repo, cycle_id, tmp_path)

    lines = ndjson_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["delivered_answer"] is True
    assert record["provenance"] == "human_edited"

    exclusion_report = json.loads(excl_path.read_text(encoding="utf-8"))
    assert exclusion_report["excluded"] == []


def test_blocked_unit_without_decision_stays_excluded(tmp_path):
    repo, cycle_id, session_id = _seed_export_fixture(tmp_path)
    repo.upsert_unit(
        session_id, "Q1", "portal-EE", UnitState.ESCALATED.value,
        {"escalation_reason": EscalationReason.UNRESOLVED_DISAGREEMENT.value},
    )

    ndjson_path, excl_path = export_cycle_answers(repo, cycle_id, tmp_path)

    lines = ndjson_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 0

    exclusion_report = json.loads(excl_path.read_text(encoding="utf-8"))
    assert len(exclusion_report["excluded"]) == 1
    item = exclusion_report["excluded"][0]
    assert item["reason"] == EscalationReason.UNRESOLVED_DISAGREEMENT.value
    assert item["reason_tag"]
    assert item["reason_tag"].startswith("Left blank: ")


def test_language_not_supported_exports_cleanly(tmp_path):
    repo, cycle_id, session_id = _seed_export_fixture(tmp_path)
    repo.upsert_unit(
        session_id, "Q1", "portal-EE", UnitState.ESCALATED.value,
        {
            "escalation_reason": EscalationReason.LANGUAGE_NOT_SUPPORTED.value,
            "detected_language": "fr",
        },
    )

    ndjson_path, excl_path = export_cycle_answers(repo, cycle_id, tmp_path)

    exclusion_report = json.loads(excl_path.read_text(encoding="utf-8"))
    assert len(exclusion_report["excluded"]) == 1
    assert exclusion_report["excluded"][0]["reason"] == "language_not_supported"
