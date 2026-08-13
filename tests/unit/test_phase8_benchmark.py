"""Unit tests for Phase 8 benchmark evaluation (T097-T104)."""

import sqlite3
from benchmark.compare import compare_benchmark_runs
from benchmark.measures import compute_benchmark_measures
from benchmark.store import BenchmarkStore
from benchmark.verify import verify_benchmark_isolation
from shared.config.settings import Settings
from shared.state.entities import (
    AdjudicationResult,
    AssessmentSession,
    BenchmarkRunResult,
    BenchmarkSet,
    ConfigurationSnapshot,
    GroundTruthAnswer,
    SessionMode,
    SessionStatus,
    TargetPortal,
    new_id,
)
from shared.persistence.benchmark_repo import BenchmarkRepository
from shared.persistence.repositories import Repository
from shared.persistence.schema import init_db


def test_benchmark_store_and_measures():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from shared.persistence.schema import DDL
    conn.executescript(DDL)

    repo = Repository(conn)
    bm_repo = BenchmarkRepository(conn)
    store = BenchmarkStore(conn)

    # 1. Save benchmark set
    b_set = BenchmarkSet("set-1", "Test Benchmark Set")
    labels = [
        GroundTruthAnswer(new_id("gt"), "set-1", "Q1", "EE", True, "survey", "assessor", "class-A"),
        GroundTruthAnswer(new_id("gt"), "set-1", "Q2", "EE", False, "survey", "assessor", "class-B"),
    ]
    store.save_set(b_set, labels)

    assert store.get_set("set-1") is not None
    assert len(store.list_ground_truth("set-1")) == 2

    # 2. Create session and target portal
    session_id = "sess-bm-1"
    snap = ConfigurationSnapshot("cfg-1", session_id, {"assessor_agent_count": 2})
    repo.insert_config_snapshot(snap)
    repo.insert_session(AssessmentSession(session_id, None, SessionMode.BENCHMARK, "cfg-1", status=SessionStatus.COMPLETE))
    repo.insert_portal(TargetPortal("portal-EE", "cycle-1", "EE", "https://eesti.ee"))

    # 3. Insert adjudication results (consensus answers)
    repo.insert_adjudication_result(
        AdjudicationResult(new_id("adj"), session_id, "Q1", "portal-EE", 1, ["r1", "r2"], False, None, 5, True, 85, False)
    )
    repo.insert_adjudication_result(
        AdjudicationResult(new_id("adj"), session_id, "Q2", "portal-EE", 1, ["r3", "r4"], False, None, 5, False, 90, False)
    )

    settings = Settings.defaults()
    result = compute_benchmark_measures(repo, session_id, "set-1", store, settings)

    assert result.overall_accuracy == 1.0
    assert result.accuracy_by_class.get("class-A") == 1.0
    assert result.accuracy_by_class.get("class-B") == 1.0
    assert result.discrepancy_flag_rate == 0.0
    # SC-003 floor check: 0.0 discrepancy rate <= 0.05 floor -> non_independence_failed == True
    assert result.portal_measures.get("non_independence_failed") is True


def test_benchmark_compare_and_isolation():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from shared.persistence.schema import DDL
    conn.executescript(DDL)

    repo = Repository(conn)
    bm_repo = BenchmarkRepository(conn)

    # Insert two run results
    res_a = BenchmarkRunResult("res-a", "sess-a", "cfg-a", 0.80, {"A": 0.80}, {"86-100": 0.80}, 0.10, {}, {})
    res_b = BenchmarkRunResult("res-b", "sess-b", "cfg-b", 0.90, {"A": 0.90}, {"86-100": 0.90}, 0.15, {}, {})

    repo.insert_config_snapshot(ConfigurationSnapshot("cfg-a", "sess-a", {"model": "gemini-1.5-flash"}))
    repo.insert_config_snapshot(ConfigurationSnapshot("cfg-b", "sess-b", {"model": "gemini-2.0-flash"}))

    bm_repo.insert_run_result(res_a)
    bm_repo.insert_run_result(res_b)

    report = compare_benchmark_runs(repo, "sess-a", "sess-b")
    import pytest
    assert report.overall_accuracy_delta == pytest.approx(0.10)
    assert report.discrepancy_flag_rate_delta == pytest.approx(0.05)
    assert "model" in report.config_differences

    isolation = verify_benchmark_isolation(repo, "sess-a")
    assert isolation.clean is True
