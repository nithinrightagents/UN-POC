"""Cycles, questions, and units router (spec 007 US1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.deps import make_repo_dependency
from api.identity import compose_question_id
from api.schemas import (
    Conflict,
    CycleCreateRequest,
    CycleDetailResponse,
    CycleListResponse,
    CycleResponse,
    NotFound,
    QuestionCreateRequest,
    QuestionListResponse,
    QuestionResponse,
    UnitCreateRequest,
    UnitListResponse,
    UnitResponse,
)
from portal.common import ensure_session
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)


def _cycle_created_at(repo: Repository, cycle_id: str) -> str:
    try:
        r = repo.conn.execute(
            "SELECT created_at FROM survey_cycles WHERE cycle_id = ? ORDER BY created_at DESC LIMIT 1",
            (cycle_id,),
        ).fetchone()
        return r["created_at"] if r else ""
    except Exception:
        return ""


def build_cycles_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["cycles"])
    get_repo = make_repo_dependency(database_path)

    # --- Cycles ---

    @router.post(
        "/cycles",
        response_model=CycleResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_cycle(
        body: CycleCreateRequest, repo: Repository = Depends(get_repo)
    ):
        existing = repo.get_cycle(body.cycle_id)
        if existing is not None:
            raise Conflict(
                f"Cycle '{body.cycle_id}' already exists.",
                details={"cycle_id": body.cycle_id},
            )

        cycle = SurveyCycle(
            cycle_id=body.cycle_id,
            name=body.name,
            questionnaire_ref=body.questionnaire_ref,
            country_set=[],
            project_type=ProjectType(body.project_type),
        )
        repo.insert_cycle(cycle)
        ensure_session(repo, body.cycle_id)
        stored = repo.get_cycle(body.cycle_id) or cycle
        created_at = _cycle_created_at(repo, stored.cycle_id)

        return CycleResponse(
            cycle_id=stored.cycle_id,
            name=stored.name,
            questionnaire_ref=stored.questionnaire_ref,
            project_type=stored.project_type.value
            if hasattr(stored.project_type, "value")
            else str(stored.project_type),
            country_set=stored.country_set,
            created_at=created_at,
        )

    @router.get("/cycles", response_model=CycleListResponse)
    def list_cycles(repo: Repository = Depends(get_repo)):
        cycles = repo.list_cycles()
        return CycleListResponse(
            cycles=[
                CycleResponse(
                    cycle_id=c.cycle_id,
                    name=c.name,
                    questionnaire_ref=c.questionnaire_ref,
                    project_type=c.project_type.value
                    if hasattr(c.project_type, "value")
                    else str(c.project_type),
                    country_set=c.country_set,
                    created_at=_cycle_created_at(repo, c.cycle_id),
                )
                for c in cycles
            ]
        )

    @router.get("/cycles/{cycle_id}", response_model=CycleDetailResponse)
    def get_cycle(cycle_id: str, repo: Repository = Depends(get_repo)):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        questions = repo.list_questions(cycle_id)
        units = repo.list_portals(cycle_id)

        return CycleDetailResponse(
            cycle_id=cycle.cycle_id,
            name=cycle.name,
            questionnaire_ref=cycle.questionnaire_ref,
            project_type=cycle.project_type.value
            if hasattr(cycle.project_type, "value")
            else str(cycle.project_type),
            country_set=cycle.country_set,
            created_at=_cycle_created_at(repo, cycle.cycle_id),
            question_count=len(questions),
            unit_count=len(units),
        )

    # --- Questions ---

    @router.get(
        "/cycles/{cycle_id}/questions", response_model=QuestionListResponse
    )
    def list_questions(cycle_id: str, repo: Repository = Depends(get_repo)):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        questions = repo.list_questions(cycle_id)
        return QuestionListResponse(
            questions=[
                QuestionResponse(
                    question_id=q.question_id,
                    indicator_id=q.indicator_id,
                    title=q.title,
                    what=q.what,
                    why=q.why,
                    how=q.how if isinstance(q.how, dict) else {},
                    module=q.question_class,
                    evidence_locus=q.evidence_locus.value
                    if hasattr(q.evidence_locus, "value")
                    else str(q.evidence_locus),
                    benchmark_case=q.benchmark_case,
                    answer_type=q.answer_type.value
                    if hasattr(q.answer_type, "value")
                    else str(q.answer_type),
                )
                for q in questions
            ]
        )

    @router.post(
        "/cycles/{cycle_id}/questions",
        response_model=QuestionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_question(
        cycle_id: str,
        body: QuestionCreateRequest,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        qid = compose_question_id(cycle_id, body.indicator_id)
        existing_q = repo.get_question(qid)
        if existing_q is not None:
            raise Conflict(
                f"Indicator '{body.indicator_id}' already exists in cycle '{cycle_id}'.",
                details={"indicator_id": body.indicator_id, "question_id": qid},
            )

        text = f"{body.title} — {body.what}"
        how_data = {
            "evidence_locus": body.evidence_locus,
            "scoring_guidance": body.how,
            "criteria_for_yes": "Evidence found on the designated government portal satisfying the What specification.",
            "criteria_for_no": "No evidence found or feature unreachable within reasonable navigation.",
        }

        q = Question(
            question_id=qid,
            cycle_id=cycle_id,
            text=text,
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus(body.evidence_locus),
            is_custom=True,
            indicator_id=body.indicator_id,
            question_class=body.module,
            title=body.title,
            what=body.what,
            why=body.why,
            how=how_data,
            benchmark_case=body.benchmark_case or None,
        )
        repo.insert_question(q)

        # Rewrite questionnaire_ref to match portal parity
        existing_questions = repo.list_questions(cycle_id)
        total_count = len(existing_questions)
        cycle.questionnaire_ref = (
            f"{cycle.name} Custom Questionnaire Set ({total_count} indicators)"
        )
        repo.insert_cycle(cycle)

        stored = repo.get_question(qid) or q
        return QuestionResponse(
            question_id=stored.question_id,
            indicator_id=stored.indicator_id,
            title=stored.title,
            what=stored.what,
            why=stored.why,
            how=stored.how if isinstance(stored.how, dict) else {},
            module=stored.question_class,
            evidence_locus=stored.evidence_locus.value
            if hasattr(stored.evidence_locus, "value")
            else str(stored.evidence_locus),
            benchmark_case=stored.benchmark_case,
            answer_type=stored.answer_type.value
            if hasattr(stored.answer_type, "value")
            else str(stored.answer_type),
        )

    # --- Units ---

    @router.get("/cycles/{cycle_id}/units", response_model=UnitListResponse)
    def list_units(cycle_id: str, repo: Repository = Depends(get_repo)):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        units = repo.list_portals(cycle_id)
        unit_responses = []
        for u in units:
            msq = repo.find_msq_document(cycle_id, u.country_id)
            latest_job = repo.latest_assessment_job(cycle_id, u.portal_id)
            pub = repo.latest_publication(cycle_id, u.portal_id)
            unit_responses.append(
                UnitResponse(
                    portal_id=u.portal_id,
                    country_id=u.country_id,
                    display_name=u.display_name,
                    unit_type=u.unit_type,
                    resolved_url=u.resolved_url,
                    has_msq=msq is not None,
                    latest_job_state=latest_job.state if latest_job else None,
                    published=pub is not None,
                )
            )

        return UnitListResponse(units=unit_responses)

    @router.post(
        "/cycles/{cycle_id}/units",
        response_model=UnitResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_unit(
        cycle_id: str,
        body: UnitCreateRequest,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        existing_portal = repo.get_portal_by_country(cycle_id, body.country_id)
        if existing_portal is not None:
            raise Conflict(
                f"Unit for country/city '{body.country_id}' already exists in cycle '{cycle_id}'.",
                details={
                    "country_id": body.country_id,
                    "portal_id": existing_portal.portal_id,
                },
            )

        portal_id = new_id("portal")
        portal = TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id=body.country_id,
            resolved_url=body.url,
            unit_type=body.unit_type,
            display_name=body.display_name,
        )
        repo.insert_portal(portal)

        if body.country_id not in cycle.country_set:
            cycle.country_set.append(body.country_id)
            repo.insert_cycle(cycle)

        return UnitResponse(
            portal_id=portal_id,
            country_id=body.country_id,
            display_name=body.display_name,
            unit_type=body.unit_type,
            resolved_url=body.url,
            has_msq=False,
            latest_job_state=None,
            published=False,
        )

    return router
