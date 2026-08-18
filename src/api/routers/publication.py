"""Publication and published results router (spec 007 US4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.deps import make_repo_dependency
from api.finalize import final_answer, publication_readiness
from api.schemas import (
    AssessmentIncomplete,
    NotFound,
    PublicationBreakdownItem,
    PublicationCreateRequest,
    PublicationResponse,
    PublicationStatusResponse,
)
from portal.common import ensure_session
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import PublicationRecord, new_id


def build_publication_router(
    database_path: str, settings: Settings
) -> APIRouter:
    router = APIRouter(tags=["publication"])
    get_repo = make_repo_dependency(database_path)

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/publication",
        response_model=PublicationResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def publish_unit(
        cycle_id: str,
        portal_id: str,
        body: PublicationCreateRequest = PublicationCreateRequest(),
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
        if not readiness.ready:
            roles_details = {
                r_k: {"declared": r_v.declared, "complete": r_v.complete}
                for r_k, r_v in readiness.roles.items()
            }
            raise AssessmentIncomplete(
                message=readiness.blocking_reason or "Assessment incomplete.",
                details={"roles": roles_details},
            )

        questions = repo.list_questions(cycle_id)

        breakdown_dict: dict[str, bool] = {}
        for q in questions:
            final = final_answer(repo, session_id, q.question_id, portal_id)
            if final is not None:
                breakdown_dict[q.question_id] = bool(final)

        affirmative = sum(1 for v in breakdown_dict.values() if v)
        score = (affirmative / len(breakdown_dict)) if breakdown_dict else 0.0

        pub_id = new_id("pub")
        pub = PublicationRecord(
            publication_id=pub_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            published_by_actor_id=body.actor_id,
            score=score,
            score_breakdown=breakdown_dict,
        )
        repo.insert_publication(pub)

        q_by_id = {q.question_id: q for q in questions}
        breakdown_items = [
            PublicationBreakdownItem(
                question_id=qid,
                indicator_id=q_by_id[qid].indicator_id
                if qid in q_by_id
                else qid,
                final_answer=ans,
            )
            for qid, ans in breakdown_dict.items()
        ]

        return PublicationResponse(
            publication_id=pub.publication_id,
            score=pub.score,
            published_by=pub.published_by_actor_id,
            published_at=pub.published_at.isoformat()
            if hasattr(pub.published_at, "isoformat")
            else str(pub.published_at),
            breakdown=breakdown_items,
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/publication",
        response_model=PublicationStatusResponse,
    )
    def get_publication(
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

        pub = repo.latest_publication(cycle_id, portal_id)
        if pub is None:
            return PublicationStatusResponse(
                published=False,
                score=None,
                published_by=None,
                published_at=None,
                publication_id=None,
                breakdown=[],
            )

        questions = repo.list_questions(cycle_id)
        q_by_id = {q.question_id: q for q in questions}
        breakdown_dict = (
            pub.score_breakdown if isinstance(pub.score_breakdown, dict) else {}
        )
        breakdown_items = [
            PublicationBreakdownItem(
                question_id=qid,
                indicator_id=q_by_id[qid].indicator_id
                if qid in q_by_id
                else qid,
                final_answer=bool(ans),
            )
            for qid, ans in breakdown_dict.items()
        ]

        return PublicationStatusResponse(
            published=True,
            score=pub.score,
            published_by=pub.published_by_actor_id,
            published_at=pub.published_at.isoformat()
            if hasattr(pub.published_at, "isoformat")
            else str(pub.published_at),
            publication_id=pub.publication_id,
            breakdown=breakdown_items,
        )

    return router
