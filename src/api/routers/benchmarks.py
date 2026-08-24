"""Benchmarks and link resolution diagnostics REST API router (FR-093, FR-099, spec 009)."""

from __future__ import annotations

from dataclasses import asdict
from fastapi import APIRouter, Depends

from api.deps import make_repo_dependency
from api.schemas import (
    BenchmarkCompareRequest,
    BenchmarkCompareResponse,
    BenchmarkRunRequest,
    BenchmarkRunResponse,
    DiagnosticCompareRequest,
    DiagnosticCompareResponse,
    DiagnosticRunRequest,
    DiagnosticRunResponse,
    NotFound,
)
from benchmark.compare import compare_benchmark_runs, compare_diagnostic_runs
from benchmark.diagnostics import run_diagnostic
from benchmark.report import render_diagnostic_report
from benchmark.runner import run_benchmark_session
from benchmark.store import BenchmarkStore
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def build_benchmarks_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["benchmarks"])
    get_repo = make_repo_dependency(database_path)

    @router.post("/benchmarks/run", response_model=BenchmarkRunResponse)
    async def run_benchmark(
        body: BenchmarkRunRequest,
        repo: Repository = Depends(get_repo),
    ):
        store = BenchmarkStore(repo.conn)
        store.load_from_json(body.dataset_path, body.set_id, "Benchmark Set")

        questions = repo.list_questions() or []
        portals = repo.list_portals() or []

        session_id, result = await run_benchmark_session(
            repo, settings, body.set_id, questions, portals
        )

        return BenchmarkRunResponse(
            session_id=session_id,
            overall_accuracy=result.overall_accuracy,
            discrepancy_flag_rate=result.discrepancy_flag_rate,
            total_evaluated=len(result.evaluations) if hasattr(result, "evaluations") else 0,
        )

    @router.post("/benchmarks/compare", response_model=BenchmarkCompareResponse)
    def compare_benchmarks(
        body: BenchmarkCompareRequest,
        repo: Repository = Depends(get_repo),
    ):
        report = compare_benchmark_runs(repo, body.session_id_a, body.session_id_b)
        return BenchmarkCompareResponse(
            session_id_a=body.session_id_a,
            session_id_b=body.session_id_b,
            comparison=asdict(report),
        )

    @router.post("/diagnostics/run", response_model=DiagnosticRunResponse)
    async def run_diagnostics_suite(
        body: DiagnosticRunRequest,
        repo: Repository = Depends(get_repo),
    ):
        result = await run_diagnostic(
            repo=repo,
            settings=settings,
            benchmark_set_id=body.reference_set_id,
            cycle_id=body.cycle_id,
            reference_fixture_path=body.fixture_path,
            question_filter=body.questions_filter,
            resolve_only=body.resolve_only,
            check_staleness=body.check_staleness,
        )
        report_text = render_diagnostic_report(result)
        return DiagnosticRunResponse(
            session_id=result.session_id,
            summary=report_text,
            diagnostic_result=asdict(result),
        )

    @router.post("/diagnostics/compare", response_model=DiagnosticCompareResponse)
    def compare_diagnostics_suite(
        body: DiagnosticCompareRequest,
        repo: Repository = Depends(get_repo),
    ):
        report = compare_diagnostic_runs(repo, body.session_a, body.session_b)
        return DiagnosticCompareResponse(
            session_a=body.session_a,
            session_b=body.session_b,
            has_regression=report.has_regression,
            summary=report.summary,
        )

    return router
