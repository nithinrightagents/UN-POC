"""Publication and public reporting knowledge base router (spec 005, 007 US4 & public JSON APIs)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.deps import make_repo_dependency
from api.finalize import final_answer_detail, publication_readiness
from api.schemas import (
    AssessmentIncomplete,
    NotFound,
    PublicationBreakdownItem,
    PublicationCreateRequest,
    PublicationResponse,
    PublicationStatusResponse,
    PublicCycleItem,
    PublicCycleListResponse,
    PublicProfileBreakdownItem,
    PublicProfileResponse,
    PublicRankingItem,
    PublicRankingsResponse,
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

    # --- Unit Publication Actions ---

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
        contested_ids: list[str] = []
        for q in questions:
            final, source = final_answer_detail(repo, session_id, q.question_id, portal_id)
            if final is not None:
                breakdown_dict[q.question_id] = bool(final)
            if source == "contested_a_wins":
                contested_ids.append(q.question_id)

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
            contested_question_ids=contested_ids,
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

    # --- Public Knowledge Base JSON Endpoints ---

    @router.get("/public/cycles", response_model=PublicCycleListResponse)
    def list_public_cycles(repo: Repository = Depends(get_repo)):
        published_cycle_ids = repo.list_all_published_cycles()
        cycle_items: list[PublicCycleItem] = []
        for cid in published_cycle_ids:
            c = repo.get_cycle(cid)
            if c:
                pub_portals = repo.list_published_portals(cid)
                cycle_items.append(
                    PublicCycleItem(
                        cycle_id=c.cycle_id,
                        name=c.name,
                        project_type=c.project_type.value
                        if hasattr(c.project_type, "value")
                        else str(c.project_type),
                        published_units_count=len(pub_portals),
                    )
                )

        return PublicCycleListResponse(cycles=cycle_items)

    @router.get(
        "/public/cycles/{cycle_id}/rankings",
        response_model=PublicRankingsResponse,
    )
    def get_public_rankings(
        cycle_id: str,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        records = repo.list_published_portals(cycle_id)
        rankings = []
        for rec in sorted(records, key=lambda x: x.score, reverse=True):
            portal = repo.get_portal(rec.portal_id)
            if portal:
                pub_at_str = (
                    rec.published_at.isoformat()
                    if hasattr(rec.published_at, "isoformat")
                    else str(rec.published_at)
                )
                rankings.append(
                    PublicRankingItem(
                        portal_id=portal.portal_id,
                        country_id=portal.country_id,
                        display_name=portal.display_name,
                        unit_type=portal.unit_type,
                        score=rec.score,
                        published_at=pub_at_str,
                    )
                )

        return PublicRankingsResponse(
            cycle_id=cycle.cycle_id,
            cycle_name=cycle.name,
            project_type=cycle.project_type.value
            if hasattr(cycle.project_type, "value")
            else str(cycle.project_type),
            rankings=rankings,
        )

    @router.get(
        "/public/cycles/{cycle_id}/units/{portal_id}",
        response_model=PublicProfileResponse,
    )
    def get_public_unit_profile(
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

        record = repo.latest_publication(cycle_id, portal_id)
        if record is None:
            raise NotFound(
                f"No published record found for unit '{portal_id}'.",
                details={"portal_id": portal_id},
            )

        questions = repo.list_questions(cycle_id)
        questions_by_id = {q.question_id: q for q in questions}

        breakdown = []
        for qid, answer in record.score_breakdown.items():
            q = questions_by_id.get(qid)
            breakdown.append(
                PublicProfileBreakdownItem(
                    question_id=qid,
                    indicator_id=q.indicator_id if q else qid,
                    title=q.title or q.text if q else None,
                    module=q.question_class if q else None,
                    answer=bool(answer),
                )
            )

        pub_at_str = (
            record.published_at.isoformat()
            if hasattr(record.published_at, "isoformat")
            else str(record.published_at)
        )

        return PublicProfileResponse(
            cycle_id=cycle.cycle_id,
            portal_id=portal.portal_id,
            country_id=portal.country_id,
            display_name=portal.display_name,
            unit_type=portal.unit_type,
            score=record.score,
            published_at=pub_at_str,
            published_by=record.published_by_actor_id,
            breakdown=breakdown,
        )

    return router
