"""Cycles, questions, and units router (spec 007 US1 & headless extensions)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status

from api.deps import make_repo_dependency
from api.identity import compose_question_id
from api.schemas import (
    Conflict,
    CycleCreateRequest,
    CycleDetailResponse,
    CycleListResponse,
    CycleResponse,
    InvalidRequest,
    NotFound,
    QuestionCreateRequest,
    QuestionEditRequest,
    QuestionListResponse,
    QuestionResponse,
    ToleranceUpdateRequest,
    ToleranceUpdateResponse,
    UnitBulkCreateRequest,
    UnitBulkCreateResponse,
    UnitCreateRequest,
    UnitListResponse,
    UnitResponse,
)
from portal.common import ensure_session
from portal.discrepancy import _compare, recompute_portal_discrepancy
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.questionnaires.registry import list_question_sets, load_question_set
from shared.reference.countries import list_countries
from shared.state.entities import (
    AnswerType,
    EscalationReason,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    ToleranceChange,
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

        try:
            ptype = ProjectType(body.project_type)
        except ValueError:
            raise InvalidRequest(
                f"Invalid project_type '{body.project_type}'.",
                details={"project_type": body.project_type},
            )

        questionnaire_ref = body.questionnaire_ref
        if body.question_set_id:
            qsets = list_question_sets()
            qset = next((s for s in qsets if s.set_id == body.question_set_id), None)
            if qset:
                questionnaire_ref = qset.label

        all_countries = list_countries()
        target_countries = []
        if body.country_ids:
            selected = set(body.country_ids)
            target_countries = [c for c in all_countries if c.code in selected]
        elif body.question_set_id and ptype is ProjectType.NATIONAL_OSI:
            target_countries = all_countries

        country_set = [c.code for c in target_countries]

        cycle = SurveyCycle(
            cycle_id=body.cycle_id,
            name=body.name,
            questionnaire_ref=questionnaire_ref,
            country_set=country_set,
            project_type=ptype,
            discrepancy_rate_threshold=body.discrepancy_rate_threshold,
        )
        repo.insert_cycle(cycle)
        ensure_session(repo, body.cycle_id)

        # Pre-populate questions if question_set_id supplied
        if body.question_set_id:
            loaded_qs = load_question_set(body.question_set_id, body.cycle_id)
            for q in loaded_qs:
                repo.insert_question(q)

        # Pre-populate units if target countries resolved
        for c in target_countries:
            if ptype is ProjectType.NATIONAL_OSI:
                display_name = c.name
                unit_type = "country"
            else:
                display_name = f"{c.most_populous_city}, {c.name}"
                unit_type = "city"
            repo.insert_portal(
                TargetPortal(
                    portal_id=new_id("portal"),
                    cycle_id=body.cycle_id,
                    country_id=c.code,
                    resolved_url=None,
                    unit_type=unit_type,
                    display_name=display_name,
                )
            )

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
            discrepancy_rate_threshold=stored.discrepancy_rate_threshold,
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
                    discrepancy_rate_threshold=c.discrepancy_rate_threshold,
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
            discrepancy_rate_threshold=cycle.discrepancy_rate_threshold,
        )

    @router.post(
        "/cycles/{cycle_id}/tolerance",
        response_model=ToleranceUpdateResponse,
    )
    def update_project_tolerance(
        cycle_id: str,
        body: ToleranceUpdateRequest,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        new_ratio = body.tolerance / 100.0
        prev_ratio = cycle.discrepancy_rate_threshold
        cycle.discrepancy_rate_threshold = new_ratio
        repo.insert_cycle(cycle)

        now = datetime.now(UTC)
        repo.insert_tolerance_change(
            ToleranceChange(
                change_id=new_id("tol"),
                cycle_id=cycle_id,
                previous_value=prev_ratio,
                new_value=new_ratio,
                changed_by_actor_id=body.actor_id.strip() or "senior-reviewer",
                changed_at=now,
            )
        )

        session_id = ensure_session(repo, cycle_id)
        questions = repo.list_questions(cycle_id)
        q_ids = [q.question_id for q in questions]
        units = repo.list_portals(cycle_id)

        closed_count = 0
        for u in units:
            open_rnd = repo.open_round_for_unit(session_id, u.portal_id)
            if open_rnd is not None:
                cmp_res = _compare(repo, session_id, u.portal_id, q_ids, new_ratio)
                if cmp_res is not None:
                    rate = cmp_res[2]
                    if rate <= new_ratio:
                        repo.close_round(open_rnd.round_id, "not_required", now)
                        closed_count += 1
                        for item in repo.list_escalations(session_id, unresolved_only=True):
                            if item.portal_id == u.portal_id and item.reason == EscalationReason.PORTAL_DISCREPANCY:
                                if item.context.get("round_id") == open_rnd.round_id or not item.context.get("round_id"):
                                    repo.record_disposition(
                                        item.item_id,
                                        {
                                            "resolution": "tolerance_adjusted_within_threshold",
                                            "resolved_by_actor_id": body.actor_id,
                                            "notes": f"Tolerance changed to {body.tolerance}%; round no longer required.",
                                        },
                                    )
                        recompute_portal_discrepancy(repo, session_id, u.portal_id, q_ids, new_ratio, cycle_id=cycle_id)

        return ToleranceUpdateResponse(
            cycle_id=cycle_id,
            previous_tolerance=prev_ratio,
            new_tolerance=new_ratio,
            changed_by=body.actor_id,
            changed_at=now.isoformat(),
            closed_rounds_count=closed_count,
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
                    indicator_id=q.indicator_id or q.question_id,
                    title=q.title or q.text,
                    what=q.what or q.text,
                    why=q.why or "",
                    how=q.how if isinstance(q.how, dict) else {},
                    module=q.question_class or "Standard",
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

    @router.get(
        "/cycles/{cycle_id}/questions/{question_id}",
        response_model=QuestionResponse,
    )
    def get_question(
        cycle_id: str, question_id: str, repo: Repository = Depends(get_repo)
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        q = repo.get_question(question_id)
        if q is None or q.cycle_id != cycle_id:
            raise NotFound(
                f"Question '{question_id}' not found in cycle '{cycle_id}'.",
                details={"question_id": question_id, "cycle_id": cycle_id},
            )

        return QuestionResponse(
            question_id=q.question_id,
            indicator_id=q.indicator_id or q.question_id,
            title=q.title or q.text,
            what=q.what or q.text,
            why=q.why or "",
            how=q.how if isinstance(q.how, dict) else {},
            module=q.question_class or "Standard",
            evidence_locus=q.evidence_locus.value
            if hasattr(q.evidence_locus, "value")
            else str(q.evidence_locus),
            benchmark_case=q.benchmark_case,
            answer_type=q.answer_type.value
            if hasattr(q.answer_type, "value")
            else str(q.answer_type),
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

    @router.patch(
        "/cycles/{cycle_id}/questions/{question_id}",
        response_model=QuestionResponse,
    )
    def edit_question(
        cycle_id: str,
        question_id: str,
        body: QuestionEditRequest,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        existing = repo.get_question(question_id)
        if existing is None or existing.cycle_id != cycle_id:
            raise NotFound(
                f"Question '{question_id}' not found in cycle '{cycle_id}'.",
                details={"question_id": question_id, "cycle_id": cycle_id},
            )

        new_title = body.title if body.title is not None else existing.title
        new_what = body.what if body.what is not None else existing.what
        new_why = body.why if body.why is not None else existing.why
        new_text = body.text if body.text is not None else (f"{new_title} — {new_what}" if new_title else existing.text)

        new_how = existing.how
        if body.how is not None:
            if isinstance(existing.how, dict):
                new_how = {**existing.how, "scoring_guidance": body.how}
            else:
                new_how = {"scoring_guidance": body.how}

        updated = replace(
            existing,
            text=new_text,
            title=new_title,
            what=new_what,
            why=new_why,
            how=new_how,
        )

        try:
            repo.update_question(updated, revised_by=body.editor_actor_id)
        except ValueError as exc:
            raise InvalidRequest(str(exc))

        stored = repo.get_question(question_id) or updated
        return QuestionResponse(
            question_id=stored.question_id,
            indicator_id=stored.indicator_id or stored.question_id,
            title=stored.title or stored.text,
            what=stored.what or stored.text,
            why=stored.why or "",
            how=stored.how if isinstance(stored.how, dict) else {},
            module=stored.question_class or "Standard",
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

    @router.get("/cycles/{cycle_id}/units/{portal_id}", response_model=UnitResponse)
    def get_unit(
        cycle_id: str, portal_id: str, repo: Repository = Depends(get_repo)
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        u = repo.get_portal(portal_id)
        if u is None or u.cycle_id != cycle_id:
            raise NotFound(
                f"Unit '{portal_id}' not found in cycle '{cycle_id}'.",
                details={"portal_id": portal_id, "cycle_id": cycle_id},
            )

        msq = repo.find_msq_document(cycle_id, u.country_id)
        latest_job = repo.latest_assessment_job(cycle_id, u.portal_id)
        pub = repo.latest_publication(cycle_id, u.portal_id)

        return UnitResponse(
            portal_id=u.portal_id,
            country_id=u.country_id,
            display_name=u.display_name,
            unit_type=u.unit_type,
            resolved_url=u.resolved_url,
            has_msq=msq is not None,
            latest_job_state=latest_job.state if latest_job else None,
            published=pub is not None,
        )

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

    @router.post(
        "/cycles/{cycle_id}/units/bulk",
        response_model=UnitBulkCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def bulk_create_units(
        cycle_id: str,
        body: UnitBulkCreateRequest,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        created_units: list[UnitResponse] = []
        for req in body.units:
            existing = repo.get_portal_by_country(cycle_id, req.country_id)
            if existing is not None:
                continue

            portal_id = new_id("portal")
            portal = TargetPortal(
                portal_id=portal_id,
                cycle_id=cycle_id,
                country_id=req.country_id,
                resolved_url=req.url,
                unit_type=req.unit_type,
                display_name=req.display_name,
            )
            repo.insert_portal(portal)
            if req.country_id not in cycle.country_set:
                cycle.country_set.append(req.country_id)

            created_units.append(
                UnitResponse(
                    portal_id=portal_id,
                    country_id=req.country_id,
                    display_name=req.display_name,
                    unit_type=req.unit_type,
                    resolved_url=req.url,
                    has_msq=False,
                    latest_job_state=None,
                    published=False,
                )
            )

        repo.insert_cycle(cycle)
        return UnitBulkCreateResponse(
            created_count=len(created_units), units=created_units
        )

    return router
