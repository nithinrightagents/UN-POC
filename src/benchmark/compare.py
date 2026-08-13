"""Benchmark comparison across runs (FR-099, SC-022).

Compares two benchmark runs, reporting measure deltas and configuration snapshot differences.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shared.state.entities import BenchmarkRunResult
from shared.persistence.benchmark_repo import BenchmarkRepository
from shared.persistence.repositories import Repository


@dataclass
class BenchmarkComparisonReport:
    session_a: str
    session_b: str
    overall_accuracy_a: float
    overall_accuracy_b: float
    overall_accuracy_delta: float
    discrepancy_flag_rate_a: float
    discrepancy_flag_rate_b: float
    discrepancy_flag_rate_delta: float
    class_accuracy_deltas: dict[str, float]
    config_differences: dict[str, tuple[Any, Any]]


def compare_benchmark_runs(
    repo: Repository,
    session_id_a: str,
    session_id_b: str,
) -> BenchmarkComparisonReport:
    """Compare two benchmark runs and report measure deltas and configuration differences (FR-099, SC-022)."""
    bm_repo = BenchmarkRepository(repo.conn)
    result_a = bm_repo.get_run_result(session_id_a)
    result_b = bm_repo.get_run_result(session_id_b)

    if not result_a or not result_b:
        raise ValueError(f"Run results not found for sessions {session_id_a!r} and/or {session_id_b!r}")

    # Config snapshots
    snap_a = repo.get_config_snapshot(result_a.config_snapshot_id) if hasattr(repo, "get_config_snapshot") else None
    snap_b = repo.get_config_snapshot(result_b.config_snapshot_id) if hasattr(repo, "get_config_snapshot") else None

    vals_a = snap_a.values if snap_a else {}
    vals_b = snap_b.values if snap_b else {}

    all_keys = set(vals_a.keys()) | set(vals_b.keys())
    config_diffs = {}
    for k in all_keys:
        va = vals_a.get(k)
        vb = vals_b.get(k)
        if va != vb:
            config_diffs[k] = (va, vb)

    # Class deltas
    classes = set(result_a.accuracy_by_class.keys()) | set(result_b.accuracy_by_class.keys())
    class_deltas = {}
    for c in classes:
        ca = result_a.accuracy_by_class.get(c, 0.0)
        cb = result_b.accuracy_by_class.get(c, 0.0)
        class_deltas[c] = cb - ca

    return BenchmarkComparisonReport(
        session_a=session_id_a,
        session_b=session_id_b,
        overall_accuracy_a=result_a.overall_accuracy,
        overall_accuracy_b=result_b.overall_accuracy,
        overall_accuracy_delta=result_b.overall_accuracy - result_a.overall_accuracy,
        discrepancy_flag_rate_a=result_a.discrepancy_flag_rate,
        discrepancy_flag_rate_b=result_b.discrepancy_flag_rate,
        discrepancy_flag_rate_delta=result_b.discrepancy_flag_rate - result_a.discrepancy_flag_rate,
        class_accuracy_deltas=class_deltas,
        config_differences=config_diffs,
    )
