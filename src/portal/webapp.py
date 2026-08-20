"""The app (spec 005): mounts the admin, assessor, and public surfaces
alongside 001's original AI-review app (unmodified, mounted at /review)
behind one landing page -- there is no separate standalone review app
anymore, it's a component of this one. Same FastAPI + Jinja2 + SQLite stack
as 001 -- no new framework introduced."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import logging
import os
import sqlite3
from api.app import build_api_router, install_api_error_handlers
from api.jobs import sweep_interrupted_jobs
from api.runtime import AIRuntime
from portal.admin import build_admin_router
from portal.assessor import build_assessor_router
from portal.common import repo_factory
from portal.public import build_public_router
from review.web.app import build_app as build_review_app
from shared.config.settings import Settings
from shared.persistence.schema import init_db

logger = logging.getLogger(__name__)
_TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_app(database_path: str, settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Guard single-process requirement
        for var in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
            val = os.environ.get(var)
            if val and int(val) > 1:
                raise RuntimeError(
                    f"EKAP server does not support multi-worker processes ({var}={val}) "
                    "because assessment job state sweep requires a single process. Run with 1 worker."
                )

        init_db(database_path)
        conn = sqlite3.connect(database_path)
        try:
            swept_count = sweep_interrupted_jobs(conn)
            logger.info("swept %d interrupted assessment job(s)", swept_count)
        finally:
            conn.close()

        runtime = AIRuntime(settings)
        await runtime.start()
        app.state.ai_runtime = runtime
        try:
            yield
        finally:
            await runtime.stop()

    app = FastAPI(title="EKAP — UN E-Government Assessment Platform", lifespan=lifespan)
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    repo = repo_factory(database_path)

    install_api_error_handlers(app)
    app.include_router(build_api_router(database_path, settings), prefix="/api/v1")
    app.include_router(build_admin_router(database_path, settings, templates))
    app.include_router(build_assessor_router(database_path, settings, templates))
    app.include_router(build_public_router(database_path, templates))
    app.mount("/review", build_review_app(database_path, settings))

    # Serves evidence snapshots captured under ./data/captures/... (capture_ref
    # values are stored as './data/captures/{session_id}/{id}.png'-style paths).
    data_dir = Path(database_path).parent if Path(database_path).parent != Path("") else Path("./data")
    (data_dir / "captures").mkdir(parents=True, exist_ok=True)
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="captures")

    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request):
        r = repo()
        cycles = r.list_cycles()
        return templates.TemplateResponse(request, "landing.html", {"cycles": cycles})

    return app


def create_app() -> FastAPI:
    from shared.config.settings import load_settings
    settings = load_settings()
    return build_app(settings.database_path, settings)
