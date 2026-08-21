"""
T009: score_25q.py

Runs the full pipeline (link resolution + assessment + validation + adjudication)
against the 25-question USA sample via `run_diagnostic(resolve_only=False)`, then
prints:
  - One headline: "N of 25 correct (was M)"
  - Per-stage attribution breakdown from src/benchmark/report.py

Usage:
    python scripts/score_25q.py [--baseline N]

The --baseline flag sets the comparison count M; if omitted the script
reads the count from specs/010-recall-recovery/baseline-before.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from benchmark.diagnostics import DiagnosticRunResult, run_diagnostic
from benchmark.report import render_diagnostic_report
from core.llm_factory import ModelProvider
from shared.config.settings import load_settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

CYCLE_ID = "usa-sample-2026"
DB_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "data" / "usa_sample.db")
FIXTURE_PATH = str(
    pathlib.Path(__file__).resolve().parents[1]
    / "data"
    / "benchmark"
    / "reference_links_us.json"
)
BASELINE_DOC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "specs"
    / "010-recall-recovery"
    / "baseline-before.md"
)
TOTAL = 25


def _read_baseline_count() -> int | None:
    """Try to read the M (baseline correct count) from baseline-before.md."""
    if not BASELINE_DOC.exists():
        return None
    text = BASELINE_DOC.read_text(encoding="utf-8")
    m = re.search(r"(\d+)\s+of\s+25\s+correct", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _sample_question_ids() -> list[str]:
    """Return bare question IDs from the 25Q sample (e.g. 'CP-030')."""
    import sqlite3
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


def _fixture_question_ids() -> set[str]:
    data = json.loads(pathlib.Path(FIXTURE_PATH).read_text(encoding="utf-8"))
    return {e["question_id"] for e in data.get("entries", [])}


async def _run_diagnostics(settings) -> DiagnosticRunResult:
    """Run the full pipeline (assessment + validation + adjudication) against the
    reference fixture and return real answer-correctness verdicts.

    `run_diagnostic` runs its own benchmark session internally (via
    `run_benchmark_session`), so the pipeline must not be run separately first —
    doing so would pay for and execute the assessment twice.
    """
    conn = connect(settings.database_path)
    repo = Repository(conn)

    sample_ids = _sample_question_ids()
    fixture_ids = _fixture_question_ids()
    question_filter = [qid for qid in sample_ids if qid in fixture_ids]

    provider = ModelProvider(
        settings.google_cloud_project,
        settings.google_cloud_location,
        settings.google_genai_use_vertexai,
        settings.google_api_key,
    )

    try:
        result = await run_diagnostic(
            repo=repo,
            settings=settings,
            benchmark_set_id="bm-reference-links-us",
            cycle_id=CYCLE_ID,
            reference_fixture_path=FIXTURE_PATH,
            question_filter=question_filter,
            resolve_only=False,
            provider=provider,
        )
    finally:
        conn.close()
    return result


def _count_correct(result: DiagnosticRunResult) -> int:
    correct = 0
    for v in result.verdicts:
        if v.answer_verdict == "match":
            correct += 1
    return correct


async def main(baseline_override: int | None = None) -> None:
    settings = load_settings()
    settings.database_path = DB_PATH
    init_db(settings.database_path)

    print("==> Effective configuration:")
    print(f"    AIQ_VALIDATION_QUALITY_THRESHOLD   = {settings.validation_quality_threshold}")
    print(f"    AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD = {settings.confidence_acceptance_threshold}")
    print(f"    AIQ_MIN_VALIDATED_POSITIONS        = {settings.min_validated_positions}")
    print(f"    AIQ_ASSESSOR_AGENT_COUNT           = {settings.assessor_agent_count}")
    print()

    print("==> Running pipeline + scoreboard against reference fixture …")
    start = time.time()
    result = await _run_diagnostics(settings)
    elapsed = time.time() - start
    correct = _count_correct(result)
    print(f"    ({elapsed:.1f}s)")

    # Read per-unit supplying sources and terminal states for detailed report
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT question_id, state, data FROM units WHERE session_id = ?", (result.session_id,))
    units_map = {}
    for qid, state, d_str in cur.fetchall():
        d = json.loads(d_str) if d_str else {}
        bare_qid = qid.split(":", 1)[1] if ":" in qid else qid
        units_map[bare_qid] = {"state": state, "data": d}
    conn.close()

    delivered_count = sum(1 for v in result.verdicts if v.pipeline_answer is not None)
    withheld_count = len(result.verdicts) - delivered_count

    # Per-source breakdown
    source_stats: dict[str, dict[str, int]] = {}
    for v in result.verdicts:
        u_info = units_map.get(v.question_id, {})
        u_data = u_info.get("data", {})
        source = u_data.get("supplying_source") or "unknown"
        if source not in source_stats:
            source_stats[source] = {"total": 0, "correct": 0, "delivered": 0}
        source_stats[source]["total"] += 1
        if v.pipeline_answer is not None:
            source_stats[source]["delivered"] += 1
        if v.answer_verdict == "match":
            source_stats[source]["correct"] += 1

    baseline = baseline_override if baseline_override is not None else _read_baseline_count()
    was_str = f" (was {baseline})" if baseline is not None else ""
    print()
    print("=" * 60)
    print(f"  Delivered and correct: {correct} of {len(result.verdicts)} ({correct}/{len(result.verdicts)}){was_str}")
    print(f"  Delivered: {delivered_count} | Withheld: {withheld_count}")
    print("=" * 60)
    print()
    print("Per-Source Correctness Breakdown:")
    for src, stats in sorted(source_stats.items()):
        corr = stats["correct"]
        tot = stats["total"]
        pct = (corr / tot * 100.0) if tot > 0 else 0.0
        print(f"  - {src:16s}: {corr}/{tot} ({pct:.1f}%) [Delivered: {stats['delivered']}]")
    print()

    report = render_diagnostic_report(result)
    print(report)

    return correct


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score the 25-question USA sample")
    parser.add_argument("--baseline", type=int, default=None, help="Override baseline count M")
    args = parser.parse_args()
    asyncio.run(main(args.baseline))
