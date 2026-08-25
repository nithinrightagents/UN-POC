"""System configuration, health, and status REST API router."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request

from api.deps import get_ai_runtime, make_repo_dependency
from api.schemas import SystemConfigResponse, SystemHealthResponse
from shared.config.settings import Settings
from shared.config.validation import ConfigurationError, validate_settings
from shared.persistence.repositories import Repository


def build_system_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["system"])
    get_repo = make_repo_dependency(database_path)

    @router.get("/system/config", response_model=SystemConfigResponse)
    def get_system_config():
        defaults = Settings.defaults().as_dict()
        effective = settings.as_dict()

        param_dict = {}
        for key in sorted(effective):
            eff = effective[key]
            default = defaults.get(key)
            source = "default" if eff == default else "configured"
            param_dict[key] = {
                "effective": eff,
                "default": default,
                "source": source,
            }

        valid = True
        error_msg = None
        try:
            validate_settings(settings)
        except ConfigurationError as exc:
            valid = False
            error_msg = str(exc)

        return SystemConfigResponse(
            valid=valid,
            error=error_msg,
            parameters=param_dict,
        )

    @router.get("/system/health", response_model=SystemHealthResponse)
    def get_system_health(
        request: Request,
        repo: Repository = Depends(get_repo),
        runtime=Depends(get_ai_runtime),
    ):
        now = datetime.now(UTC)
        return SystemHealthResponse(
            status="ok",
            database_path=database_path,
            ai_runtime_active=runtime is not None,
            timestamp=now.isoformat(),
        )

    return router
