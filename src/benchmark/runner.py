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
from shared.ratelimit.token_bucket import RateLimiter
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
    resolve_only: bool = False,
) -> tuple[str, BenchmarkRunResult | None]:
    """Run an assessment session in benchmark mode (FR-093). Returns (session_id, result)."""
    snapshot_vals = settings.as_dict() if hasattr(settings, "as_dict") else dict(settings)
    snapshot = ConfigurationSnapshot(snapshot_id=new_id("cfg"), session_id="", values=snapshot_vals)
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

    limiter = RateLimiter(rate_per_sec=settings.rate_limit_per_domain_rps)
    if provider is None:
        provider = ModelProvider(
            settings.google_cloud_project,
            settings.google_cloud_location,
            settings.google_genai_use_vertexai,
            settings.google_api_key,
        )

    browser = BrowserSession(settings.user_agent, limiter)
    await browser.start()

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
                questions=questions,
                portals=portals,
                adjudicate_results=not resolve_only,
                resolve_only=resolve_only,
            )
        repo.update_session_status(session_id, SessionStatus.COMPLETE)
    except Exception:
        repo.update_session_status(session_id, SessionStatus.INTERRUPTED)
        raise
    finally:
        await browser.stop()

    if resolve_only:
        return session_id, None

    store = BenchmarkStore(repo.conn)
    result = compute_benchmark_measures(repo, session_id, benchmark_set_id, store, settings)
    return session_id, result
