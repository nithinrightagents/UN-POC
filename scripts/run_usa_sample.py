"""Run the assessment pipeline for the 25-question USA sample."""

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import httpx
from core.llm_factory import ModelProvider
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from orchestration.scheduler import run_batch
from portal.common import ensure_session
from shared.config.settings import load_settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db
from shared.ratelimit.token_bucket import RateLimiter
from shared.tools.browser import BrowserSession

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

CYCLE_ID = "usa-sample-2026"
DB_PATH = str(pathlib.Path(__file__).resolve().parents[1] / "data" / "usa_sample.db")


async def main():
    settings = load_settings()
    settings.database_path = DB_PATH
    init_db(settings.database_path)

    conn = connect(settings.database_path)
    repo = Repository(conn)

    session_id = ensure_session(repo, CYCLE_ID)
    print(f"Using session {session_id} on {DB_PATH}")

    questions = repo.list_questions(CYCLE_ID)
    portals = [p for p in repo.list_portals(CYCLE_ID) if p.country_id == "US"]

    print(f"Loaded {len(questions)} questions and {len(portals)} portal(s).")
    if not questions or not portals:
        print("ERROR: Questions or portal not found!")
        return

    limiter = RateLimiter(rate_per_sec=settings.rate_limit_per_domain_rps)
    provider = ModelProvider(
        settings.google_cloud_project,
        settings.google_cloud_location,
        settings.google_genai_use_vertexai,
        settings.google_api_key,
    )
    browser = BrowserSession(settings.user_agent, limiter)
    await browser.start()

    start_t = time.time()
    try:
        async with httpx.AsyncClient(timeout=15.0) as http_client:
            summary = await run_batch(
                repo=repo,
                settings=settings,
                session_id=session_id,
                provider=provider,
                browser=browser,
                http_client=http_client,
                fetch_log=FetchLog(conn, session_id),
                stage_log=StageEventLog(conn, session_id),
                cost_ledger=CostLedger(conn, session_id),
                questions=questions,
                portals=portals,
                adjudicate_results=True,
            )
        elapsed = time.time() - start_t
        print(f"\nCompleted in {elapsed:.1f}s")
        print(
            f"Results: delivered={summary.delivered}, "
            f"no_suggestion={summary.no_suggestion}, "
            f"unassessable={summary.unassessable}, "
            f"escalated={summary.escalated}, "
            f"in_progress={summary.in_progress} "
            f"of {len(summary.outcomes)} units"
        )
    finally:
        await browser.stop()
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
