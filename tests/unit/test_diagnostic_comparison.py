import json
import sqlite3

from benchmark.compare import compare_diagnostic_runs
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL


def test_diagnostic_comparison_detects_individual_indicator_divergence():
    # T040: Two runs with identical totals but different indicators failing must surface the change
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    session_a = "sess-diag-a"
    session_b = "sess-diag-b"

    # In Run A: Q1 passes (match), Q2 fails (miss) -> 1 match, 1 miss
    data_a = {
        "result_id": "res-a",
        "session_id": session_a,
        "benchmark_set_id": "test-bm",
        "config_snapshot_id": "cfg-1",
        "status": "complete",
        "resolve_only": False,
        "authoritative_matches": 1,
        "authoritative_misses": 1,
        "verdicts": [
            {
                "question_id": "Q1",
                "indicator_id": "#001",
                "link_verdict": "match",
                "attributed_stage": "search",
                "resolved_url": "https://usa.gov/health",
            },
            {
                "question_id": "Q2",
                "indicator_id": "#002",
                "link_verdict": "miss",
                "attributed_stage": "search",
                "resolved_url": "https://usa.gov/wrong",
            },
        ],
    }

    # In Run B: Q1 fails (miss), Q2 passes (match) -> 1 match, 1 miss (TOTALS ARE IDENTICAL: 1 match, 1 miss)
    data_b = {
        "result_id": "res-b",
        "session_id": session_b,
        "benchmark_set_id": "test-bm",
        "config_snapshot_id": "cfg-2",
        "status": "complete",
        "resolve_only": False,
        "authoritative_matches": 1,
        "authoritative_misses": 1,
        "verdicts": [
            {
                "question_id": "Q1",
                "indicator_id": "#001",
                "link_verdict": "miss",
                "attributed_stage": "search",
                "resolved_url": "https://usa.gov/wrong",
            },
            {
                "question_id": "Q2",
                "indicator_id": "#002",
                "link_verdict": "match",
                "attributed_stage": "search",
                "resolved_url": "https://usa.gov/education",
            },
        ],
    }

    conn.execute(
        "INSERT INTO benchmark_run_results (result_id, session_id, data) VALUES (?, ?, ?)",
        ("res-a", session_a, json.dumps(data_a)),
    )
    conn.execute(
        "INSERT INTO benchmark_run_results (result_id, session_id, data) VALUES (?, ?, ?)",
        ("res-b", session_b, json.dumps(data_b)),
    )
    conn.commit()

    report = compare_diagnostic_runs(repo, session_a, session_b)

    # Must detect Q1 as regression and Q2 as improvement
    assert report.has_regression is True
    assert len(report.regressions) == 1
    assert report.regressions[0].question_id == "Q1"
    assert report.regressions[0].verdict_before == "match"
    assert report.regressions[0].verdict_after == "miss"

    assert len(report.improvements) == 1
    assert report.improvements[0].question_id == "Q2"
    assert report.improvements[0].verdict_before == "miss"
    assert report.improvements[0].verdict_after == "match"
