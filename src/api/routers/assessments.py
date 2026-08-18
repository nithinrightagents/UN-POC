"""Assessment triggers, status polling, and results router (spec 007 US1, US2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from api.deps import get_ai_runtime, make_repo_dependency
from api.jobs import job_status, start_assessment_job
from api.schemas import (
    AIQuestionResult,
    AIResultsEnvelope,
    AssessmentStatusResponse,
    AssessmentTriggerRequest,
    AssessmentTriggerResponse,
    NotFound,
)
from portal.common import ensure_session
from review.query import build_question_review
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import TERMINAL_UNIT_STATES, UnitState


def build_assessments_router(
    database_path: str, settings: Settings
) -> APIRouter:
    router = APIRouter(tags=["assessments"])
    get_repo = make_repo_dependency(database_path)

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/assessment",
        response_model=AssessmentTriggerResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def trigger_assessment(
        cycle_id: str,
        portal_id: str,
        body: AssessmentTriggerRequest = AssessmentTriggerRequest(),
        repo: Repository = Depends(get_repo),
        runtime=Depends(get_ai_runtime),
    ):
        job_start = start_assessment_job(
            repo,
            settings,
            runtime,
            cycle_id=cycle_id,
            portal_id=portal_id,
            triggered_by="api",
            actor_id=body.actor_id,
        )
        job = job_start.job
        session_id = ensure_session(repo, cycle_id)
        st = job_status(repo, session_id, cycle_id, portal_id)

        return AssessmentTriggerResponse(
            job_id=job.job_id,
            state=job.state,
            cycle_id=job.cycle_id,
            portal_id=job.portal_id,
            questions_total=job.questions_total,
            questions_completed=st.questions_completed,
            already_running=job_start.already_running,
            created_at=job.created_at,
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/assessment",
        response_model=AssessmentStatusResponse,
    )
    def get_assessment_status(
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
        st = job_status(repo, session_id, cycle_id, portal_id)

        return AssessmentStatusResponse(
            state=st.state,
            job_id=st.job_id,
            questions_total=st.questions_total,
            questions_completed=st.questions_completed,
            failure_cause=st.failure_cause,
            triggered_by=st.triggered_by,
            created_at=st.created_at,
            updated_at=st.updated_at,
            outcomes=st.outcomes,
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/results",
        response_model=AIResultsEnvelope,
    )
    def get_assessment_results(
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
        latest_job = repo.latest_assessment_job(cycle_id, portal_id)
        is_complete = bool(latest_job and latest_job.state == "done")
        st = job_status(repo, session_id, cycle_id, portal_id)

        terminal = {s.value for s in TERMINAL_UNIT_STATES}

        results = []
        for q in questions:
            unit = repo.get_unit(session_id, q.question_id, portal_id)
            unit_state = unit.get("state") if unit else None
            is_assessed = bool(unit_state in terminal)

            if is_assessed:
                review = build_question_review(
                    repo,
                    session_id,
                    q.question_id,
                    portal_id,
                    settings.confidence_acceptance_threshold,
                )
                if review:
                    evidence_url = (
                        review.evidence.url
                        if (review.evidence and review.evidence.url)
                        else portal.resolved_url
                    )
                    blank_reason = (
                        review.reason_tag.text
                        if hasattr(review.reason_tag, "text")
                        else str(review.reason_tag)
                        if review.reason_tag
                        else None
                    )
                    results.append(
                        AIQuestionResult(
                            question_id=q.question_id,
                            indicator_id=q.indicator_id,
                            assessed=True,
                            answer=None if review.escalated else (bool(review.delivered_answer) if review.delivered_answer is not None else None),
                            confidence=review.consensus_confidence,
                            justification=review.justification,
                            evidence_url=evidence_url,
                            evidence_missing=review.evidence_missing,
                            blocked=review.escalated,
                            blank_reason=blank_reason,
                        )
                    )
                else:
                    results.append(
                        AIQuestionResult(
                            question_id=q.question_id,
                            indicator_id=q.indicator_id,
                            assessed=True,
                            answer=None,
                            confidence=None,
                            justification=None,
                            evidence_url=portal.resolved_url,
                            evidence_missing=False,
                            blocked=False,
                            blank_reason=None,
                        )
                    )
            else:
                results.append(
                    AIQuestionResult(
                        question_id=q.question_id,
                        indicator_id=q.indicator_id,
                        assessed=False,
                        answer=None,
                        confidence=None,
                        justification=None,
                        evidence_url=portal.resolved_url,
                        evidence_missing=False,
                        blocked=False,
                        blank_reason=None,
                    )
                )

        return AIResultsEnvelope(
            complete=is_complete,
            questions_total=st.questions_total,
            questions_completed=st.questions_completed,
            results=results,
        )

    return router
