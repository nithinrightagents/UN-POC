"""Seed script for a 25-question random sample on USA (United States).

Usage:
    python scripts/seed_usa_sample.py
"""

from __future__ import annotations

import json
import pathlib
import random
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from shared.config.settings import load_settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import init_db
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

CYCLE_ID = "usa-sample-2026"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_INDICATORS_PATH = _REPO_ROOT / "data" / "questionnaires" / "templates" / "un_osi_2024_master.json"
_SEED = 42
_SAMPLE_SIZE = 25

_DB_PATH = str(_REPO_ROOT / "data" / "usa_sample.db")


def main() -> None:
    settings = load_settings()
    settings.database_path = _DB_PATH
    init_db(settings.database_path)
    
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    repo = Repository(conn)

    data = json.loads(_INDICATORS_PATH.read_text(encoding="utf-8"))
    all_questions = data["questions"]
    rng = random.Random(_SEED)
    sample = rng.sample(all_questions, _SAMPLE_SIZE)

    cycle = SurveyCycle(
        cycle_id=CYCLE_ID,
        name="United States 25-Question Relaxed Sample (2026)",
        questionnaire_ref=str(_INDICATORS_PATH),
        country_set=["US"],
        project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)

    question_ids: list[str] = []
    for q in sample:
        question_id = f"{CYCLE_ID}:{q['question_id']}"
        question = Question(
            question_id=question_id,
            cycle_id=CYCLE_ID,
            text=q["text"],
            answer_type=AnswerType(q["answer_type"]),
            evidence_locus=EvidenceLocus(q["evidence_locus"]),
            indicator_id=q.get("indicator_id"),
            question_class=q.get("module"),
            title=q.get("title"),
            what=q.get("what"),
            why=q.get("why"),
            how=q.get("how"),
            benchmark_case=q.get("benchmark_case"),
            reference_links=q.get("reference_links", []),
        )
        repo.insert_question(question)
        question_ids.append(question_id)

    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=CYCLE_ID,
        country_id="US",
        display_name="United States",
        resolved_url="https://www.usa.gov",
    )
    repo.insert_portal(portal)

    print(f"Seeded Cycle: {CYCLE_ID}")
    print(f"Seeded Portal: US ({portal.portal_id})")
    print(f"Seeded {len(question_ids)} questions into {_DB_PATH}")


if __name__ == "__main__":
    main()
