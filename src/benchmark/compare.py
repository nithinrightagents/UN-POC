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


@dataclass
class IndicatorDelta:
    question_id: str
    indicator_id: str
    verdict_before: str
    verdict_after: str
    stage_before: str | None
    stage_after: str | None
    resolved_url_before: str | None
    resolved_url_after: str | None
    is_regression: bool
    is_improvement: bool


@dataclass
class DiagnosticComparisonReport:
    session_id_a: str
    session_id_b: str
    regressions: list[IndicatorDelta]
    improvements: list[IndicatorDelta]
    unchanged: list[IndicatorDelta]
    has_regression: bool
    summary: str


def compare_diagnostic_runs(
    repo: Repository,
    session_id_a: str,
    session_id_b: str,
) -> DiagnosticComparisonReport:
    """Compare two diagnostic runs and report per-indicator regressions and improvements (FR-LD-033)."""
    import json

    row_a = repo.conn.execute(
        "SELECT data FROM benchmark_run_results WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
        (session_id_a,),
    ).fetchone()
    row_b = repo.conn.execute(
        "SELECT data FROM benchmark_run_results WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
        (session_id_b,),
    ).fetchone()

    if not row_a or not row_b:
        raise ValueError(
            f"Diagnostic run results not found for sessions {session_id_a!r} and/or {session_id_b!r}"
        )

    data_a = json.loads(row_a["data"])
    data_b = json.loads(row_b["data"])

    verdicts_a = {v["question_id"]: v for v in data_a.get("verdicts", [])}
    verdicts_b = {v["question_id"]: v for v in data_b.get("verdicts", [])}

    all_qids = sorted(set(verdicts_a.keys()) | set(verdicts_b.keys()))

    regressions: list[IndicatorDelta] = []
    improvements: list[IndicatorDelta] = []
    unchanged: list[IndicatorDelta] = []

    for qid in all_qids:
        va = verdicts_a.get(qid, {})
        vb = verdicts_b.get(qid, {})

        ind_id = vb.get("indicator_id") or va.get("indicator_id") or qid
        v_before = va.get("link_verdict", "absent")
        v_after = vb.get("link_verdict", "absent")
        s_before = va.get("attributed_stage")
        s_after = vb.get("attributed_stage")
        u_before = va.get("resolved_url")
        u_after = vb.get("resolved_url")

        is_regr = False
        is_impr = False

        if v_before == "match" and v_after != "match":
            is_regr = True
        elif v_before != "match" and v_after == "match":
            is_impr = True
        elif v_before != v_after or s_before != s_after or u_before != u_after:
            # Different failure or change
            pass

        delta = IndicatorDelta(
            question_id=qid,
            indicator_id=ind_id,
            verdict_before=v_before,
            verdict_after=v_after,
            stage_before=s_before,
            stage_after=s_after,
            resolved_url_before=u_before,
            resolved_url_after=u_after,
            is_regression=is_regr,
            is_improvement=is_impr,
        )

        if is_regr:
            regressions.append(delta)
        elif is_impr:
            improvements.append(delta)
        else:
            unchanged.append(delta)

    has_reg = len(regressions) > 0
    lines = [
        f"DIAGNOSTIC RUN COMPARISON: {session_id_a} -> {session_id_b}",
        f"Regressions: {len(regressions)} | Improvements: {len(improvements)} | Unchanged/Stable: {len(unchanged)}",
    ]
    if regressions:
        lines.append("\nREGRESSIONS DETECTED:")
        for r in regressions:
            lines.append(
                f"  • {r.indicator_id} ({r.question_id}): {r.verdict_before} -> {r.verdict_after} "
                f"[{r.stage_before or 'none'} -> {r.stage_after or 'none'}]"
            )
    if improvements:
        lines.append("\nIMPROVEMENTS:")
        for im in improvements:
            lines.append(
                f"  • {im.indicator_id} ({im.question_id}): {im.verdict_before} -> {im.verdict_after}"
            )

    summary_txt = "\n".join(lines)

    return DiagnosticComparisonReport(
        session_id_a=session_id_a,
        session_id_b=session_id_b,
        regressions=regressions,
        improvements=improvements,
        unchanged=unchanged,
        has_regression=has_reg,
        summary=summary_txt,
    )
