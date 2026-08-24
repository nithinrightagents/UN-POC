"""Telemetry reporting and audit reconstruction REST API router (FR-061, FR-112–FR-116)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import make_repo_dependency
from api.schemas import (
    AuditSummaryResponse,
    CostReportResponse,
    FetchesReportResponse,
    NotFound,
    QuestionAuditResponse,
    TelemetrySummaryResponse,
    TimingsReportResponse,
)
from core.telemetry.reports import (
    get_cost_report,
    get_fetches_report,
    get_telemetry_summary,
    get_timings_report,
)
from portal.common import ensure_session
from review.audit import reconstruct_question_history, reconstruct_session_summary
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def build_telemetry_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["telemetry"])
    get_repo = make_repo_dependency(database_path)

    @router.get(
        "/cycles/{cycle_id}/telemetry/summary",
        response_model=TelemetrySummaryResponse,
    )
    def get_session_telemetry_summary(
        cycle_id: str,
        session_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        sess_id = session_id or ensure_session(repo, cycle_id)
        res = get_telemetry_summary(repo.conn, sess_id)
        return TelemetrySummaryResponse(session_id=sess_id, summary=res)

    @router.get(
        "/cycles/{cycle_id}/telemetry/timings",
        response_model=TimingsReportResponse,
    )
    def get_session_timings(
        cycle_id: str,
        session_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        sess_id = session_id or ensure_session(repo, cycle_id)
        res = get_timings_report(repo.conn, sess_id)
        return TimingsReportResponse(session_id=sess_id, timings=res)

    @router.get(
        "/cycles/{cycle_id}/telemetry/fetches",
        response_model=FetchesReportResponse,
    )
    def get_session_fetches(
        cycle_id: str,
        session_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        sess_id = session_id or ensure_session(repo, cycle_id)
        res = get_fetches_report(repo.conn, sess_id)
        return FetchesReportResponse(session_id=sess_id, fetches=res)

    @router.get(
        "/cycles/{cycle_id}/telemetry/cost",
        response_model=CostReportResponse,
    )
    def get_session_cost(
        cycle_id: str,
        session_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        sess_id = session_id or ensure_session(repo, cycle_id)
        res = get_cost_report(repo.conn, sess_id)
        return CostReportResponse(session_id=sess_id, cost=res)

    @router.get(
        "/cycles/{cycle_id}/audit/summary",
        response_model=AuditSummaryResponse,
    )
    def get_audit_summary(
        cycle_id: str,
        session_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        sess_id = session_id or ensure_session(repo, cycle_id)
        summary = reconstruct_session_summary(repo, sess_id)
        return AuditSummaryResponse(session_id=sess_id, summary=summary)

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/questions/{question_id}/audit",
        response_model=QuestionAuditResponse,
    )
    def get_question_audit(
        cycle_id: str,
        portal_id: str,
        question_id: str,
        session_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        portal = repo.get_portal(portal_id)
        if portal is None or portal.cycle_id != cycle_id:
            raise NotFound(
                f"Unit '{portal_id}' not found in cycle '{cycle_id}'.",
                details={"portal_id": portal_id, "cycle_id": cycle_id},
            )

        sess_id = session_id or ensure_session(repo, cycle_id)
        history = reconstruct_question_history(
            repo, sess_id, question_id, portal_id
        )
        return QuestionAuditResponse(
            session_id=sess_id,
            question_id=question_id,
            portal_id=portal_id,
            history=history,
        )

    return router
