import json
import sqlite3
import pytest
from click.testing import CliRunner

from benchmark.compare import compare_diagnostic_runs, IndicatorDelta
from cli import main
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL


@pytest.fixture
def test_repo(tmp_path):
    db_file = tmp_path / "test_reg.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDDL := DDL)
    repo = Repository(conn)
    return repo, str(db_file)


def test_regression_gate_detects_drop_in_authoritative_matches(test_repo, tmp_path):
    repo, db_path = test_repo

    # Session A (Baseline): 10 authoritative matches
    run_a = {
        "result_id": "diag-a",
        "session_id": "sess-a",
        "authoritative_matches": 10,
        "verdicts": [
            {
                "question_id": "Q1",
                "indicator_id": "#001",
                "link_verdict": "match",
                "attributed_stage": "search",
                "resolved_url": "https://gov.uk/service1",
            },
            {
                "question_id": "Q2",
                "indicator_id": "#002",
                "link_verdict": "match",
                "attributed_stage": "search",
                "resolved_url": "https://gov.uk/service2",
            },
        ],
    }

    # Session B: 9 authoritative matches (Q2 regressed to miss)
    run_b = {
        "result_id": "diag-b",
        "session_id": "sess-b",
        "authoritative_matches": 9,
        "verdicts": [
            {
                "question_id": "Q1",
                "indicator_id": "#001",
                "link_verdict": "match",
                "attributed_stage": "search",
                "resolved_url": "https://gov.uk/service1",
            },
            {
                "question_id": "Q2",
                "indicator_id": "#002",
                "link_verdict": "miss",
                "attributed_stage": "search",
                "resolved_url": None,
            },
        ],
    }

    # Store both in database
    repo.conn.execute(
        "INSERT INTO benchmark_run_results (result_id, session_id, data) VALUES (?, ?, ?)",
        ("diag-a", "sess-a", json.dumps(run_a)),
    )
    repo.conn.execute(
        "INSERT INTO benchmark_run_results (result_id, session_id, data) VALUES (?, ?, ?)",
        ("diag-b", "sess-b", json.dumps(run_b)),
    )
    repo.conn.commit()

    report = compare_diagnostic_runs(repo, "sess-a", "sess-b")
    assert report.has_regression is True
    assert report.authoritative_matches_delta == -1
    assert len(report.regressions) == 1
    assert report.regressions[0].question_id == "Q2"


def test_regression_gate_accepts_json_files(test_repo, tmp_path):
    repo, db_path = test_repo

    file_a = tmp_path / "baseline.json"
    file_b = tmp_path / "current.json"

    file_a.write_text(json.dumps({
        "session_id": "base",
        "authoritative_matches": 5,
        "verdicts": [
            {"question_id": "Q1", "indicator_id": "#001", "link_verdict": "miss"}
        ],
    }), encoding="utf-8")

    file_b.write_text(json.dumps({
        "session_id": "curr",
        "authoritative_matches": 6,
        "verdicts": [
            {"question_id": "Q1", "indicator_id": "#001", "link_verdict": "match"}
        ],
    }), encoding="utf-8")

    report = compare_diagnostic_runs(repo, str(file_a), str(file_b))
    assert report.has_regression is False
    assert report.authoritative_matches_delta == 1
    assert len(report.improvements) == 1


def test_cli_diagnose_compare_fail_on_regression(test_repo, tmp_path, monkeypatch):
    repo, db_path = test_repo
    monkeypatch.setenv("DATABASE_PATH", db_path)
    file_a = tmp_path / "base.json"
    file_b = tmp_path / "regressed.json"

    file_a.write_text(json.dumps({
        "session_id": "base",
        "authoritative_matches": 10,
        "verdicts": [{"question_id": "Q1", "indicator_id": "#001", "link_verdict": "match"}],
    }), encoding="utf-8")

    file_b.write_text(json.dumps({
        "session_id": "regressed",
        "authoritative_matches": 9,
        "verdicts": [{"question_id": "Q1", "indicator_id": "#001", "link_verdict": "miss"}],
    }), encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        main,
        ["diagnose", "compare", str(file_a), str(file_b), "--fail-on-regression"],
    )
    assert res.exit_code == 1
    assert "Regression detected" in res.output
