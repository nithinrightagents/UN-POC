"""FastAPI dependencies for the REST API (spec 007)."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Any

from fastapi import Header, Request

from api.schemas import NotConfigured, Unauthorized
from portal.common import repo_factory
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def make_require_api_key(settings: Settings) -> Callable[[str | None], str]:
    """Dependency that enforces X-API-Key header against settings.api_key."""

    def require_api_key(
        x_api_key: str | None = Header(None, alias="X-API-Key"),
    ) -> str:
        if not settings.api_key:
            raise NotConfigured(
                "Programmatic API access is not configured on this server."
            )
        if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
            raise Unauthorized("Invalid or missing API key.")
        return x_api_key

    return require_api_key


def make_repo_dependency(database_path: str) -> Callable[[], Repository]:
    """Dependency that returns a fresh Repository instance."""
    factory = repo_factory(database_path)

    def get_repo() -> Repository:
        return factory()

    return get_repo


def get_ai_runtime(request: Request) -> Any:
    """Dependency that retrieves the shared AIRuntime from app state."""
    return getattr(request.app.state, "ai_runtime", None)
