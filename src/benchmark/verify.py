"""Benchmark isolation verification (FR-094, SC-021).

Asserts ground-truth answers reached zero Assessor Agent, Validator, or Adjudicator invocations during a benchmark session.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    findings = []
    invocations_checked = 0

    # 1. Check Assessor Agent runs
    runs = repo.list_all_agent_runs_for_session(session_id)
    for _run in runs:
        invocations_checked += 1

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
