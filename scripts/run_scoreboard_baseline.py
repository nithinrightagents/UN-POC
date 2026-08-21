"""T010: Run the scoreboard against the existing baseline session.

Passes question_filter to include only the 25 sample IDs that are in both
the cycle and the reference fixture, avoiding errors for the 6 original-seeded
entries not in the 25Q sample.
"""
import asyncio, sys, pathlib, json, sqlite3
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from benchmark.diagnostics import run_diagnostic
from benchmark.report import render_diagnostic_report
from shared.config.settings import load_settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db
from portal.common import ensure_session

DB_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "data" / "usa_sample.db")
FIXTURE_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "data" / "benchmark" / "reference_links_us.json")
CYCLE_ID = "usa-sample-2026"


def _sample_question_ids() -> list[str]:
    """Return bare question IDs from the 25Q sample (e.g. 'CP-030')."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT data FROM questions WHERE cycle_id = 'usa-sample-2026'")
    ids = []
    for (d,) in cur.fetchall():
        qid = json.loads(d).get("question_id", "")
        if ":" in qid:
            qid = qid.split(":", 1)[1]
        if qid:
            ids.append(qid)
    conn.close()
    return sorted(set(ids))


def _fixture_question_ids() -> set:
    data = json.loads(pathlib.Path(FIXTURE_PATH).read_text(encoding="utf-8"))
    return {e["question_id"] for e in data.get("entries", [])}


async def main():
    settings = load_settings()
    settings.database_path = DB_PATH
    init_db(settings.database_path)
    conn = connect(settings.database_path)
    repo = Repository(conn)
    session_id = ensure_session(repo, CYCLE_ID)
    print(f"Session: {session_id}")

    sample_ids = _sample_question_ids()
    fixture_ids = _fixture_question_ids()
    # Only score questions that exist in both the sample and the fixture
    question_filter = [qid for qid in sample_ids if qid in fixture_ids]
    print(f"Scoring {len(question_filter)} questions covered by the reference fixture")

    result = await run_diagnostic(
        repo=repo,
        settings=settings,
        benchmark_set_id="bm-reference-links-us",
        cycle_id=CYCLE_ID,
        reference_fixture_path=FIXTURE_PATH,
        question_filter=question_filter,
        resolve_only=True,
    )
    conn.close()

    correct = sum(1 for v in result.verdicts if v.answer_verdict == "match")
    total = len(result.verdicts)
    print(f"\n{'='*60}")
    print(f"  SCOREBOARD BASELINE: {correct} of {total} scoreable correct")
    print(f"  (Pipeline: 22 delivered, 3 no_suggestion, of 25 total)")
    print(f"{'='*60}\n")
    print(render_diagnostic_report(result))

asyncio.run(main())
