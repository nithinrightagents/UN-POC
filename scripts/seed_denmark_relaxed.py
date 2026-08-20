"""One-off seed: fresh Denmark full-questionnaire cycle using the RELAXED
questionnaire (data/questionnaires/templates/un_osi_2024_relaxed.json --
diagram requirement on IF-010 softened to accept an equivalent text/list
representation), under the 2026-08-20 baseline model/config
(gemini-3.5-flash-lite assessor, gemini-3.7-flash validator, single
assessor agent) plus the link-retry fix (link_likely_wrong signal, up to 3
search candidates tried on a bad MSQ link).

A new cycle_id/db (not denmark-v2-2026 / denmark_v2.db) is used
deliberately, to give a clean read of this specific combination rather
than mixing in prior partial runs.

Usage:
    python scripts/seed_denmark_relaxed.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from core.llm_factory import ModelProvider
from portal.msq import ingest_msq_pdf, match_msq_links
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

CYCLE_ID = "denmark-relaxed-2026"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_INDICATORS_PATH = _REPO_ROOT / "data" / "questionnaires" / "templates" / "un_osi_2024_relaxed.json"
_DENMARK_MSQ_PATH = _REPO_ROOT / "understanding docs" / "Denmark - MS MSQ 2024.pdf"

_DB_PATH = str(_REPO_ROOT / "data" / "denmark_relaxed.db")


def main() -> None:
    settings = load_settings()
    settings.database_path = _DB_PATH
    init_db(settings.database_path)
    import sqlite3
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    repo = Repository(conn)

    data = json.loads(_INDICATORS_PATH.read_text(encoding="utf-8"))
    all_questions = data["questions"]

    cycle = SurveyCycle(
        cycle_id=CYCLE_ID,
        name="Denmark Full OSI Questionnaire, Relaxed (2026-08-20: 3.5-flash-lite assessor / 3.7-flash validator, no diagram requirement, link-retry fix)",
        questionnaire_ref=str(_INDICATORS_PATH),
        country_set=["DK"],
        project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)

    question_ids: list[str] = []
    for q in all_questions:
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
        country_id="DK",
    )
    repo.insert_portal(portal)

    if _DENMARK_MSQ_PATH.exists():
        doc = ingest_msq_pdf(str(_DENMARK_MSQ_PATH), CYCLE_ID, "DK", _DENMARK_MSQ_PATH.name)
        repo.insert_msq_document(doc)
        all_repo_questions = [repo.get_question(qid) for qid in question_ids]
        provider = ModelProvider(
            settings.google_cloud_project,
            settings.google_cloud_location,
            settings.google_genai_use_vertexai,
            settings.google_api_key,
        )
        candidates = asyncio.run(
            match_msq_links(doc, [q for q in all_repo_questions if q], provider, settings.validator_model)
        )
        for candidate in candidates:
            repo.insert_msq_link_candidate(candidate)
        print(f"Ingested Denmark MSQ ({len(doc.sections)} sections, {len(doc.extracted_urls)} URLs).")
        print(f"Matched {len(candidates)} MSQ link candidate(s) to {len(question_ids)} questions.")
    else:
        print(f"WARNING: Denmark MSQ PDF not found at {_DENMARK_MSQ_PATH}; link resolution will fall through to search.")

    print(f"Cycle: {CYCLE_ID}")
    print(f"Portal: DK ({portal.portal_id})")
    print(f"Questions: {len(question_ids)}")
    print()
    print("Run with:")
    print(f'  AIQ_DATABASE_PATH={_DB_PATH} aiq run --cycle {CYCLE_ID} --portal DK')


if __name__ == "__main__":
    main()
