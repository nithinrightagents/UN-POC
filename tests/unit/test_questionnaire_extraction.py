"""Tests for enriched questionnaire extraction, What/Why/How schemas, and questionnaire set branching."""

import json
import pathlib
import sqlite3

from shared.persistence.repositories import Repository
from shared.persistence.serialization import from_json, to_json
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_master_template_and_modules_exist():
    master_path = REPO_ROOT / "data" / "questionnaires" / "templates" / "un_osi_2024_master.json"
    assert master_path.exists(), "Master template JSON must exist"

    raw_text = master_path.read_text(encoding="utf-8")
    for lig in ["\ufb00", "\ufb01", "\ufb02", "\ufb03", "\ufb04"]:
        assert lig not in raw_text, f"Master template contains raw ligature: {repr(lig)}"

    master = json.loads(raw_text)
    assert master["total_questions"] == 102
    assert len(master["questions"]) == 102

    # Verify every question has what, why, how, and valid enum values
    for q in master["questions"]:
        assert "question_id" in q and len(q["question_id"]) > 0
        assert "title" in q and len(q["title"]) > 0
        assert "text" in q and len(q["text"]) > 0
        assert "what" in q and len(q["what"]) > 0
        assert "why" in q and len(q["why"]) > 0
        assert "how" in q and isinstance(q["how"], dict)
        assert "evidence_locus" in q
        assert EvidenceLocus(q["evidence_locus"])  # must be valid enum
        assert AnswerType(q["answer_type"]) == AnswerType.BINARY

    modules_dir = REPO_ROOT / "data" / "questionnaires" / "modules"
    module_files = list(modules_dir.glob("module_*.json"))
    assert len(module_files) == 6, f"Expected 6 module files, found {len(module_files)}"

    # Check LOSI template exists
    losi_path = REPO_ROOT / "data" / "questionnaires" / "templates" / "un_losi_2024_master.json"
    assert losi_path.exists(), "LOSI master template JSON must exist"
    losi = json.loads(losi_path.read_text(encoding="utf-8"))
    assert losi["total_questions"] == 95


def test_question_entity_rich_fields_roundtrip():
    q = Question(
        question_id="cycle1:CUST-001",
        cycle_id="cycle1",
        text="Custom Indicator — Details",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        is_custom=True,
        title="Custom Indicator",
        what="Online tool to check environmental compliance.",
        why="Ensures sustainable governance and transparency.",
        how={
            "evidence_locus": "national_portal_only",
            "scoring_guidance": "1. Search for compliance portal. 2. Verify form.",
        },
        benchmark_case="Check out Denmark's environmental reporting tool",
        reference_links=["https://mst.dk"],
    )

    serialized = to_json(q)
    deserialized = from_json(serialized, Question)

    assert deserialized.question_id == "cycle1:CUST-001"
    assert deserialized.title == "Custom Indicator"
    assert deserialized.what == "Online tool to check environmental compliance."
    assert deserialized.why == "Ensures sustainable governance and transparency."
    assert deserialized.benchmark_case == "Check out Denmark's environmental reporting tool"
    assert deserialized.reference_links == ["https://mst.dk"]
    assert isinstance(deserialized.how, dict)
    assert deserialized.how["evidence_locus"] == "national_portal_only"


def test_question_insertion_and_cycle_branching(tmp_path):
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    # Initialize minimal schema matching schema.py
    conn.execute(
        "CREATE TABLE survey_cycles (cycle_id TEXT PRIMARY KEY, data TEXT, created_at TEXT DEFAULT (datetime('now')))"
    )
    conn.execute(
        "CREATE TABLE questions (question_id TEXT PRIMARY KEY, cycle_id TEXT, is_custom INTEGER, data TEXT, created_at TEXT DEFAULT (datetime('now')))"
    )
    conn.commit()

    repo = Repository(conn)

    # 1. Create a survey cycle using default template
    cycle = SurveyCycle(
        cycle_id="cycle_2026",
        name="UN E-Gov Survey 2026",
        questionnaire_ref="UN OSI 2024 Master Indicator Set",
        country_set=["DK", "US"],
        project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)

    retrieved = repo.get_cycle("cycle_2026")
    assert retrieved.questionnaire_ref == "UN OSI 2024 Master Indicator Set"

    # 2. Insert standard question
    q1 = Question(
        question_id="cycle_2026:IF-010",
        cycle_id="cycle_2026",
        text="Organogram",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        what="Government organogram chart",
        why="Promotes transparency",
        how="Look for organization chart",
    )
    repo.insert_question(q1)

    # 3. Add custom question and simulate branching
    q_custom = Question(
        question_id="cycle_2026:CUST-999",
        cycle_id="cycle_2026",
        text="Custom AI Ethics Checklist",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        is_custom=True,
        what="Published AI ethics framework",
        why="Promotes ethical AI in government",
        how="Check national portal for AI ethics guidance",
    )
    repo.insert_question(q_custom)

    # Update cycle to branch questionnaire set
    all_questions = repo.list_questions("cycle_2026")
    assert len(all_questions) == 2

    cycle.questionnaire_ref = f"{cycle.name} Custom Questionnaire Set ({len(all_questions)} indicators)"
    repo.insert_cycle(cycle)

    updated_cycle = repo.get_cycle("cycle_2026")
    assert "Custom Questionnaire Set" in updated_cycle.questionnaire_ref
    assert "2 indicators" in updated_cycle.questionnaire_ref
