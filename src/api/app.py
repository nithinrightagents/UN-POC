"""REST API router construction and error handler registration (spec 007)."""

from __future__ import annotations

from typing import Any, Callable
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.deps import make_require_api_key
from api.routers.assessments import build_assessments_router
from api.routers.completions import build_completions_router
from api.routers.cycles import build_cycles_router
from api.routers.human import build_human_router
from api.routers.prefills import build_prefills_router
from api.routers.publication import build_publication_router
from api.schemas import ApiError, CapacityReached
from shared.config.settings import Settings


def build_api_router(
    database_path: str,
    settings: Settings,
    runtime_getter: Callable[[], Any] | None = None,
) -> APIRouter:
    """Builds the main /api/v1 router with X-API-Key security dependency and sub-routers."""
    router = APIRouter(
        dependencies=[Depends(make_require_api_key(settings))],
    )

    router.include_router(build_cycles_router(database_path, settings))
    router.include_router(build_assessments_router(database_path, settings))
    router.include_router(build_human_router(database_path, settings))
    router.include_router(build_publication_router(database_path, settings))
    router.include_router(build_prefills_router(database_path, settings))
    router.include_router(build_completions_router(database_path, settings))

    return router


def install_api_error_handlers(app: FastAPI) -> None:
    """Registers exception handlers on the FastAPI app to ensure single-shape error envelope."""

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        headers = {}
        if isinstance(exc, CapacityReached) or exc.code == "capacity_reached":
            retry_after = getattr(exc, "retry_after_seconds", 30)
            headers["Retry-After"] = str(retry_after)

        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
            headers=headers if headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Invalid request.",
                    "details": {"errors": exc.errors()},
                }
            },
        )
