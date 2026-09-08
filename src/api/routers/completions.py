"""Completions router (spec 008 FR-PF-008, FR-PF-009, FR-PF-010)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status

from api.deps import make_repo_dependency
from api.finalize import publication_readiness
from api.schemas import (
    CompletionCreateRequest,
    CompletionCreateResponse,
    CompletionsStatusResponse,
    Conflict,
    Forbidden,
    IncompleteAssessment,
    NotFound,
    RoleCompletionStatus,
)
from portal.assignment import resolve_actor_role
from portal.common import ensure_session
from portal.disagreement_labels import dispatch_labelling_pass, run_labelling_pass
from portal.discrepancy import recompute_portal_discrepancy
from portal.tolerance import effective_tolerance
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessorCompletion,
    new_id,
)

logger = logging.getLogger(__name__)


def build_completions_router(
    database_path: str, settings: Settings
) -> APIRouter:
    router = APIRouter(tags=["completions"])
    get_repo = make_repo_dependency(database_path)

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/completions",
        response_model=CompletionCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def declare_completion(
        request: Request,
        background: BackgroundTasks,
        cycle_id: str,
        portal_id: str,
        body: CompletionCreateRequest,
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

        assigned_role = resolve_actor_role(repo, cycle_id, portal_id, body.actor_id)
        if assigned_role is None:
            raise Forbidden(
                "You are not assigned to this unit.",
                details={"actor_id": body.actor_id, "portal_id": portal_id},
            )

        if body.role != assigned_role.value:
            raise Conflict(
                f"Requested role '{body.role}' contradicts assigned role '{assigned_role.value}'.",
                details={"assigned_role": assigned_role.value, "requested_role": body.role},
            )

        # Idempotency check: if this actor already completed for this unit, return it
        existing = repo.latest_assessor_completion(
            session_id=ensure_session(repo, cycle_id),
            portal_id=portal_id,
            role=assigned_role.value,
        )
        if existing and existing.actor_id == body.actor_id:
            return CompletionCreateResponse(
                completion_id=existing.completion_id,
                role=existing.role,
                actor_id=existing.actor_id,
                declared_at=existing.declared_at.isoformat()
                if hasattr(existing.declared_at, "isoformat")
                else str(existing.declared_at),
                indicator_count=existing.indicator_count_at_declaration,
            )

        questions = repo.list_questions(cycle_id)
        session_id = ensure_session(repo, cycle_id)
        total_indicators = len(questions)

        # Check all indicators are answered
        unanswered: list[str] = []
        for q in questions:
            sub = repo.latest_human_submission(
                session_id, q.question_id, portal_id, assigned_role
            )
            if sub is None or sub.answer is None:
                unanswered.append(q.question_id)

        if unanswered:
            raise IncompleteAssessment(
                f"Cannot declare completion: {len(unanswered)} indicators unanswered.",
                details={"unanswered_question_ids": unanswered},
            )

        comp = AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role=assigned_role.value,
            actor_id=body.actor_id,
            indicator_count_at_declaration=total_indicators,
        )
        repo.insert_assessor_completion(comp)

        recompute_portal_discrepancy(
            repo,
            session_id,
            portal_id,
            [q.question_id for q in questions],
            effective_tolerance(repo, cycle_id, settings),
            cycle_id=cycle_id,
        )

        try:
            runtime = getattr(request.app.state, "ai_runtime", None)
            labelling_pass = dispatch_labelling_pass(
                repo=repo,
                settings=settings,
                session_id=session_id,
                cycle_id=cycle_id,
                portal_id=portal_id,
                question_ids=[q.question_id for q in questions],
                threshold=effective_tolerance(repo, cycle_id, settings),
                dispatched_by="api",
                provider_available=runtime is not None,
            )
            if labelling_pass is not None:
                background.add_task(
                    run_labelling_pass,
                    database_path,
                    settings,
                    runtime,
                    labelling_pass.pass_id,
                )
        except Exception:
            logger.exception("Failed to dispatch disagreement labelling pass for unit %s", portal_id)

        return CompletionCreateResponse(
            completion_id=comp.completion_id,
            role=comp.role,
            actor_id=comp.actor_id,
            declared_at=comp.declared_at.isoformat()
            if hasattr(comp.declared_at, "isoformat")
            else str(comp.declared_at),
            indicator_count=comp.indicator_count_at_declaration,
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/completions",
        response_model=CompletionsStatusResponse,
    )
    def get_completions(
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
        readiness = publication_readiness(repo, session_id, cycle_id, portal_id)

        roles_status = {
            r_k: RoleCompletionStatus(
                declared=r_v.declared,
                actor_id=r_v.actor_id,
                declared_at=r_v.declared_at,
                answered_count=r_v.answered_count,
                total_indicators=r_v.total_indicators,
                outstanding_question_ids=r_v.outstanding_question_ids,
                complete=r_v.complete,
            )
            for r_k, r_v in readiness.roles.items()
        }

        return CompletionsStatusResponse(
            ready_to_publish=readiness.ready,
            roles=roles_status,
            blocking_reason=readiness.blocking_reason,
        )

    return router
