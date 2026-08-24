"""Completions router (spec 008 FR-PF-008, FR-PF-009, FR-PF-010)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.deps import make_repo_dependency
from api.finalize import publication_readiness
from api.schemas import (
    CompletionCreateRequest,
    CompletionCreateResponse,
    CompletionsStatusResponse,
    IncompleteAssessment,
    InvalidRequest,
    NotFound,
    RoleCompletionStatus,
)
from portal.common import ensure_session
from portal.discrepancy import recompute_portal_discrepancy
from portal.tolerance import effective_tolerance
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessorCompletion,
    AssessorRole,
    new_id,
)


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

        try:
            role_enum = AssessorRole(body.role)
        except ValueError:
            raise InvalidRequest(
                f"Invalid role '{body.role}'. Must be 'A' or 'B'.",
                details={"field": "role", "value": body.role},
            )

        session_id = ensure_session(repo, cycle_id)
        questions = repo.list_questions(cycle_id)
        total_indicators = len(questions)

        outstanding: list[str] = []
        answered_count = 0
        for q in questions:
            sub = repo.latest_human_submission(
                session_id, q.question_id, portal_id, role_enum
            )
            if sub is not None and sub.answer is not None:
                answered_count += 1
            else:
                outstanding.append(q.question_id)

        if outstanding:
            cnt = len(outstanding)
            s = "indicator" if cnt == 1 else "indicators"
            first_q = outstanding[0]
            raise IncompleteAssessment(
                message=f"Cannot declare completion: {cnt} {s} outstanding ({first_q}).",
                details={
                    "role": body.role,
                    "outstanding_question_ids": outstanding,
                    "answered_count": answered_count,
                    "total_indicators": total_indicators,
                },
            )

        comp = AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role=body.role,
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
