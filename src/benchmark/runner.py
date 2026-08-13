"""Benchmark pipeline runner (FR-093, FR-094, FR-095).

Drives the exact same production pipeline against a benchmark set with session mode BENCHMARK.
Ground-truth answers remain isolated in BenchmarkStore and are never passed into run_batch.
"""

from __future__ import annotations

import pathlib
from typing import Sequence

import httpx

from core.llm_factory import ModelProvider
from benchmark.measures import compute_benchmark_measures
from benchmark.store import BenchmarkStore
from shared.config.settings import Settings
from shared.state.entities import (
    AssessmentSession,
    BenchmarkRunResult,
    ConfigurationSnapshot,
    Question,
    SessionMode,
    SessionStatus,
    TargetPortal,
    new_id,
)
from orchestration.scheduler import run_batch
from shared.persistence.repositories import Repository
from shared.tools.browser import BrowserSession
from shared.ratelimit.token_bucket import get_shared_limiter
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog


async def run_benchmark_session(
    repo: Repository,
    settings: Settings,
    benchmark_set_id: str,
    questions: Sequence[Question],
    portals: Sequence[TargetPortal],
    provider: ModelProvider | None = None,
) -> tuple[str, BenchmarkRunResult]:
    """Run an assessment session in benchmark mode (FR-093). Returns (session_id, result)."""
    snapshot = ConfigurationSnapshot(snapshot_id=new_id("cfg"), session_id="", values=settings.as_dict())
    session = AssessmentSession(
        session_id=new_id("bm-sess"),
        cycle_id=None,  # Not tied to a production cycle (FR-095)
        mode=SessionMode.BENCHMARK,
        config_snapshot_id=snapshot.snapshot_id,
        status=SessionStatus.RUNNING,
    )
    snapshot.session_id = session.session_id
    repo.insert_config_snapshot(snapshot)
    repo.insert_session(session)
    session_id = session.session_id

    limiter = get_shared_limiter(settings.rate_limit_per_domain_rps)
    if provider is None:
        provider = ModelProvider(
            settings.google_cloud_project,
            settings.google_cloud_location,
            settings.google_genai_use_vertexai,
        )

    browser = BrowserSession(settings.user_agent, limiter)
    await browser.start()
    capture_dir = f"./data/captures/{session_id}"
    pathlib.Path(capture_dir).mkdir(parents=True, exist_ok=True)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            await run_batch(
                repo=repo,
                settings=settings,
                session_id=session_id,
                provider=provider,
                browser=browser,
                http_client=http_client,
                fetch_log=FetchLog(repo.conn, session_id),
                stage_log=StageEventLog(repo.conn, session_id),
                cost_ledger=CostLedger(repo.conn, session_id),
                capture_dir=capture_dir,
                questions=questions,
                portals=portals,
                adjudicate_results=True,
            )
    finally:
        await browser.stop()

    store = BenchmarkStore(repo.conn)
    result = compute_benchmark_measures(repo, session_id, benchmark_set_id, store, settings)
    return session_id, result
