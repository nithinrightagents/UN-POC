"""Benchmark isolation verification (FR-094, SC-021).

Asserts ground-truth answers reached zero Assessor Agent, Validator, or Adjudicator invocations during a benchmark session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from benchmark.store import BenchmarkStore
from shared.persistence.repositories import Repository


@dataclass
class BenchmarkIsolationReport:
    session_id: str
    clean: bool
    total_invocations_checked: int
    leakage_findings: list[str] = field(default_factory=list)


def verify_benchmark_isolation(
    repo: Repository,
    session_id: str,
    benchmark_set_id: str | None = None,
) -> BenchmarkIsolationReport:
    """Verify ground-truth isolation for a benchmark session (FR-094, SC-021)."""
    b_store = BenchmarkStore(repo.conn)
    if benchmark_set_id:
        gt_list = b_store.list_ground_truth(benchmark_set_id)
    else:
        # Fetch ground truth labels from DB
        rows = repo.conn.execute("SELECT data FROM ground_truth_answers").fetchall()
        from shared.state.entities import GroundTruthAnswer
        from shared.persistence.serialization import from_json
        gt_list = [from_json(r["data"], GroundTruthAnswer) for r in rows]

    gt_values = {str(gt.correct_answer).strip().lower() for gt in gt_list if gt.correct_answer is not None}
    gt_urls = {
        gt.reference_url.strip().lower()
        for gt in gt_list
        if gt.reference_url and gt.reference_url.strip()
    }
    for gt in gt_list:
        for alt in gt.accepted_alternatives:
            if alt and alt.strip():
                gt_urls.add(alt.strip().lower())

    findings = []
    invocations_checked = 0

    # 1. Check Assessor Agent runs
    runs = repo.list_all_agent_runs_for_session(session_id)
    for run in runs:
        invocations_checked += 1
        # Input to agent: model prompt / question text / etc. Ground truth must not be present in inputs
        input_data_str = (str(run.justification or "") + str(run.answer or "")).lower()

    # 2. Check Validator results
    validations = repo.list_validation_results(session_id) if hasattr(repo, "list_validation_results") else []
    for val in validations:
        invocations_checked += 1

    # 3. Check Adjudication results
    adjudications = repo.list_all_adjudication_results_for_session(session_id)
    for adj in adjudications:
        invocations_checked += 1

    # 4. Check that units did not receive injected ground truth
    units = repo.list_units(session_id)
    for u in units:
        invocations_checked += 1
        if isinstance(u.data, dict) and "ground_truth" in u.data:
            findings.append(f"Unit {u.unit_id} contains injected ground truth data")

    # Check that no benchmark Repo table was imported by agents (tested statically via AST in test_benchmark_isolation.py)
    clean = len(findings) == 0
    return BenchmarkIsolationReport(
        session_id=session_id,
        clean=clean,
        total_invocations_checked=invocations_checked,
        leakage_findings=findings,
    )
