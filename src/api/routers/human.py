"""Human assessor submissions and role-scoped reads router (spec 007 US3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from api.deps import make_repo_dependency
from api.schemas import (
    HumanAnswerItem,
    HumanAnswersResponse,
    HumanSubmissionRequest,
    HumanSubmissionResponse,
    InvalidRequest,
    NotFound,
)
from portal.common import ensure_session
from portal.discrepancy import recompute_portal_discrepancy
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import AssessorRole, HumanAssessorSubmission, new_id


def build_human_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["human-answers"])
    get_repo = make_repo_dependency(database_path)

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/human-answers",
        response_model=HumanSubmissionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def submit_human_answer(
        cycle_id: str,
        portal_id: str,
        body: HumanSubmissionRequest,
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

        question = repo.get_question(body.question_id)
        if question is None or question.cycle_id != cycle_id:
            raise NotFound(
                f"Question '{body.question_id}' not found in cycle '{cycle_id}'.",
                details={"question_id": body.question_id, "cycle_id": cycle_id},
            )

        try:
            role = AssessorRole(body.role)
        except ValueError:
            raise InvalidRequest(
                f"Invalid role '{body.role}'. Must be 'A' or 'B'.",
                details={"field": "role", "value": body.role},
            )

        session_id = ensure_session(repo, cycle_id)

        # Check AI suggestion linkage from prefill
        prefill = repo.latest_prefill(session_id, body.question_id, portal_id)
        ai_suggested_answer = prefill.answer if (prefill and prefill.suggested) else None
        ai_suggestion_accepted = (
            bool(prefill.answer) == body.answer if (prefill and prefill.suggested) else None
        )

        sub_id = new_id("hsub")
        submission = HumanAssessorSubmission(
            submission_id=sub_id,
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=body.question_id,
            portal_id=portal_id,
            role=role,
            assessor_actor_id=body.actor_id,
            answer=body.answer,
            evidence_url=body.evidence_url or None,
            notes=body.notes or None,
            ai_suggested_answer=ai_suggested_answer,
            ai_suggestion_accepted=ai_suggestion_accepted,
        )
        repo.insert_human_submission(submission)

        questions = repo.list_questions(cycle_id)
        recompute_portal_discrepancy(
            repo,
            session_id,
            portal_id,
            [q.question_id for q in questions],
            settings.human_discrepancy_rate_threshold,
        )

        return HumanSubmissionResponse(
            submission_id=submission.submission_id,
            role=submission.role.value,
            answer=bool(submission.answer),
            submitted_at=submission.submitted_at.isoformat()
            if hasattr(submission.submitted_at, "isoformat")
            else str(submission.submitted_at),
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/human-answers",
        response_model=HumanAnswersResponse,
    )
    def get_human_answers(
        cycle_id: str,
        portal_id: str,
        role: str = Query(..., description="Assessor role 'A' or 'B'"),
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
            assessor_role = AssessorRole(role)
        except ValueError:
            raise InvalidRequest(
                f"Invalid role '{role}'. Must be 'A' or 'B'.",
                details={"field": "role", "value": role},
            )

        session_id = ensure_session(repo, cycle_id)
        questions = repo.list_questions(cycle_id)

        answers: list[HumanAnswerItem] = []
        for q in questions:
            latest = repo.latest_human_submission(
                session_id, q.question_id, portal_id, assessor_role
            )
            if latest:
                answers.append(
                    HumanAnswerItem(
                        question_id=q.question_id,
                        indicator_id=q.indicator_id,
                        answered=True,
                        answer=bool(latest.answer),
                        evidence_url=latest.evidence_url,
                        notes=latest.notes,
                        actor_id=latest.assessor_actor_id,
                        submitted_at=latest.submitted_at.isoformat()
                        if hasattr(latest.submitted_at, "isoformat")
                        else str(latest.submitted_at),
                    )
                )
            else:
                answers.append(
                    HumanAnswerItem(
                        question_id=q.question_id,
                        indicator_id=q.indicator_id,
                        answered=False,
                        answer=None,
                        evidence_url=None,
                        notes=None,
                        actor_id=None,
                        submitted_at=None,
                    )
                )

        return HumanAnswersResponse(role=assessor_role.value, answers=answers)

    return router
