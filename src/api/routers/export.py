"""Export router for NDJSON delivered answers and exclusion report (FR-101–FR-106)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Response

from api.deps import make_repo_dependency
from api.schemas import ExportResponse, ExportTriggerRequest, NotFound
from export.writer import export_cycle_answers
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def build_export_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["export"])
    get_repo = make_repo_dependency(database_path)

    @router.post("/cycles/{cycle_id}/export", response_model=ExportResponse)
    def trigger_cycle_export(
        cycle_id: str,
        body: ExportTriggerRequest = ExportTriggerRequest(),
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        out_dir = Path(body.output_dir)
        ndjson_path, excl_path = export_cycle_answers(
            repo, cycle_id, out_dir, body.actor_id
        )

        now = datetime.now(UTC)
        return ExportResponse(
            cycle_id=cycle_id,
            ndjson_path=str(ndjson_path),
            exclusion_report_path=str(excl_path),
            exported_at=now.isoformat(),
        )

    @router.get("/cycles/{cycle_id}/export/answers")
    def get_exported_answers(
        cycle_id: str,
        output_dir: str = "./data/exports",
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        # Look for existing export or generate fresh one
        ndjson_path, _ = export_cycle_answers(repo, cycle_id, Path(output_dir))
        if not ndjson_path.exists():
            raise NotFound(f"Export file not found at {ndjson_path}")

        content = ndjson_path.read_text(encoding="utf-8")
        return Response(content=content, media_type="application/x-ndjson")

    @router.get("/cycles/{cycle_id}/export/exclusions")
    def get_exported_exclusions(
        cycle_id: str,
        output_dir: str = "./data/exports",
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        _, excl_path = export_cycle_answers(repo, cycle_id, Path(output_dir))
        if not excl_path.exists():
            raise NotFound(f"Exclusion report not found at {excl_path}")

        content = excl_path.read_text(encoding="utf-8")
        return Response(content=content, media_type="application/json")

    return router
