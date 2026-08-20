"""Same 25-question RANDOM sample (seed=42) of the RELAXED Denmark
questionnaire as seed_denmark_relaxed_sample.py, seeded into a SEPARATE db
file (2026-08-20: phase 1 navigation + phase 2 stale-stub fixes) so this
rerun doesn't collide with the review-portal server already holding
data/denmark_relaxed_sample.db open.

Usage:
    python scripts/seed_denmark_relaxed_sample_v2.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import random
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

CYCLE_ID = "denmark-relaxed-sample-v2-2026"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_INDICATORS_PATH = _REPO_ROOT / "data" / "questionnaires" / "templates" / "un_osi_2024_relaxed.json"
_DENMARK_MSQ_PATH = _REPO_ROOT / "understanding docs" / "Denmark - MS MSQ 2024.pdf"
_SEED = 42
_SAMPLE_SIZE = 25

_DB_PATH = str(_REPO_ROOT / "data" / "denmark_relaxed_sample_v2.db")


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
    rng = random.Random(_SEED)
    sample = rng.sample(all_questions, _SAMPLE_SIZE)

    cycle = SurveyCycle(
        cycle_id=CYCLE_ID,
        name="Denmark 25-Question Relaxed Sample v2 (2026-08-20: one-hop navigation + stale-stub detection)",
        questionnaire_ref=str(_INDICATORS_PATH),
        country_set=["DK"],
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
        country_id="DK",
    )
    repo.insert_portal(portal)

    if _DENMARK_MSQ_PATH.exists():
        doc = ingest_msq_pdf(str(_DENMARK_MSQ_PATH), CYCLE_ID, "DK", _DENMARK_MSQ_PATH.name)
        repo.insert_msq_document(doc)
        sample_questions = [repo.get_question(qid) for qid in question_ids]
        provider = ModelProvider(
            settings.google_cloud_project,
            settings.google_cloud_location,
            settings.google_genai_use_vertexai,
            settings.google_api_key,
        )
        candidates = asyncio.run(
            match_msq_links(doc, [q for q in sample_questions if q], provider, settings.validator_model)
        )
        for candidate in candidates:
            repo.insert_msq_link_candidate(candidate)
        print(f"Ingested Denmark MSQ ({len(doc.sections)} sections, {len(doc.extracted_urls)} URLs).")
        print(f"Matched {len(candidates)} MSQ link candidate(s) to sampled questions.")
    else:
        print(f"WARNING: Denmark MSQ PDF not found at {_DENMARK_MSQ_PATH}; link resolution will fall through to search.")

    print(f"Cycle: {CYCLE_ID}")
    print(f"Portal: DK ({portal.portal_id})")
    print(f"Questions ({len(question_ids)}):")
    for qid, q in zip(question_ids, sample):
        print(f"  {qid}  [{q.get('indicator_id')}]  {q['title']}")
    print()
    print("Run with:")
    print(
        f'  AIQ_DATABASE_PATH={_DB_PATH} aiq run --cycle {CYCLE_ID} --portal DK '
        f'--questions "{",".join(question_ids)}"'
    )


if __name__ == "__main__":
    main()
