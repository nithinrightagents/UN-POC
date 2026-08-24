"""AI review actions and review queue REST API router (FR-043, FR-044–FR-047)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends

from api.deps import make_repo_dependency
from api.schemas import (
    InvalidRequest,
    NotFound,
    ReviewActionRequest,
    ReviewActionResponse,
    ReviewQuestionResponse,
    ReviewStatusResponse,
)
from portal.common import ensure_session
from review import actions
from review.query import build_question_review
from review.unlock import portal_review_status
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def _serialize_view(view: Any) -> dict[str, Any]:
    d = asdict(view)
    if view.evidence and view.evidence.captured_at:
        d["evidence"]["captured_at"] = (
            view.evidence.captured_at.isoformat()
            if hasattr(view.evidence.captured_at, "isoformat")
            else str(view.evidence.captured_at)
        )
        if view.evidence.verified_at:
            d["evidence"]["verified_at"] = (
                view.evidence.verified_at.isoformat()
                if hasattr(view.evidence.verified_at, "isoformat")
                else str(view.evidence.verified_at)
            )
    return d


def build_review_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["review"])
    get_repo = make_repo_dependency(database_path)

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/review-status",
        response_model=ReviewStatusResponse,
    )
    def get_review_status(
        cycle_id: str,
        portal_id: str,
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

        session_id = ensure_session(repo, cycle_id)
        questions = repo.list_questions(cycle_id)
        qids = [q.question_id for q in questions]
        status_obj = portal_review_status(repo, session_id, portal_id, qids)

        return ReviewStatusResponse(
            session_id=session_id,
            portal_id=portal_id,
            cycle_id=cycle_id,
            status=asdict(status_obj),
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/questions/{question_id}/review",
        response_model=ReviewQuestionResponse,
    )
    def get_question_review_view(
        cycle_id: str,
        portal_id: str,
        question_id: str,
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

        session_id = ensure_session(repo, cycle_id)
        view = build_question_review(
            repo,
            session_id,
            question_id,
            portal_id,
            settings.confidence_acceptance_threshold,
        )
        if not view:
            raise NotFound(
                f"Question '{question_id}' review view not found.",
                details={"question_id": question_id, "portal_id": portal_id},
            )

        return ReviewQuestionResponse(
            session_id=session_id,
            portal_id=portal_id,
            question_id=question_id,
            view=_serialize_view(view),
        )

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/questions/{question_id}/review/approve",
        response_model=ReviewActionResponse,
    )
    def approve_review_decision(
        cycle_id: str,
        portal_id: str,
        question_id: str,
        body: ReviewActionRequest,
        repo: Repository = Depends(get_repo),
    ):
        session_id = ensure_session(repo, cycle_id)
        view = build_question_review(
            repo,
            session_id,
            question_id,
            portal_id,
            settings.confidence_acceptance_threshold,
        )
        if not view:
            raise NotFound(
                f"Question '{question_id}' review view not found.",
                details={"question_id": question_id, "portal_id": portal_id},
            )

        decision = actions.approve(
            repo,
            session_id,
            question_id,
            portal_id,
            view.system_proposed_answer,
            body.actor_id,
        )
        return ReviewActionResponse(
            decision_id=decision.decision_id, action="approve"
        )

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/questions/{question_id}/review/edit",
        response_model=ReviewActionResponse,
    )
    def edit_review_decision(
        cycle_id: str,
        portal_id: str,
        question_id: str,
        body: ReviewActionRequest,
        repo: Repository = Depends(get_repo),
    ):
        session_id = ensure_session(repo, cycle_id)
        view = build_question_review(
            repo,
            session_id,
            question_id,
            portal_id,
            settings.confidence_acceptance_threshold,
        )
        if not view:
            raise NotFound(
                f"Question '{question_id}' review view not found.",
                details={"question_id": question_id, "portal_id": portal_id},
            )

        if body.edited_answer is None:
            raise InvalidRequest(
                "Field 'edited_answer' is required for edit action."
            )

        decision = actions.edit(
            repo,
            session_id,
            question_id,
            portal_id,
            view.system_proposed_answer,
            body.edited_answer,
            body.actor_id,
        )
        return ReviewActionResponse(
            decision_id=decision.decision_id, action="edit"
        )

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/questions/{question_id}/review/reject",
        response_model=ReviewActionResponse,
    )
    def reject_review_decision(
        cycle_id: str,
        portal_id: str,
        question_id: str,
        body: ReviewActionRequest,
        repo: Repository = Depends(get_repo),
    ):
        session_id = ensure_session(repo, cycle_id)
        view = build_question_review(
            repo,
            session_id,
            question_id,
            portal_id,
            settings.confidence_acceptance_threshold,
        )
        if not view:
            raise NotFound(
                f"Question '{question_id}' review view not found.",
                details={"question_id": question_id, "portal_id": portal_id},
            )

        if body.override_answer is None:
            raise InvalidRequest(
                "Field 'override_answer' is required for reject action."
            )

        if not body.rejection_reason or not body.rejection_reason.strip():
            raise InvalidRequest(
                "Field 'rejection_reason' is mandatory when rejecting/overriding an answer."
            )

        try:
            decision = actions.reject_and_override(
                repo,
                session_id,
                question_id,
                portal_id,
                view.system_proposed_answer,
                body.override_answer,
                body.rejection_reason,
                body.actor_id,
            )
        except actions.MissingRejectionReasonError as exc:
            raise InvalidRequest(str(exc))

        return ReviewActionResponse(
            decision_id=decision.decision_id, action="reject_override"
        )

    return router
