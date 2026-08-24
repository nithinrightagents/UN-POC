"""Discrepancy, reconciliation, and arbitration REST API router (spec 012 & headless extensions)."""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status

from api.deps import make_repo_dependency
from api.schemas import (
    Conflict,
    DiscrepancyStateResponse,
    EscalationDispositionRequest,
    EscalationDispositionResponse,
    EscalationItemResponse,
    EscalationsListResponse,
    InvalidRequest,
    JointAnswerRequest,
    JointAnswerResponse,
    NotFound,
    ReconciliationDisputeRow,
    ReconciliationSettledRow,
    ReconciliationWorkspaceResponse,
)
from portal.common import ensure_session
from portal.reconciliation import (
    _format_pct,
    close_round_if_complete,
    open_reviewer_round,
    unit_reconciliation_state,
)
from review.escalations import dispose_escalation, list_escalation_queue
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessorRole,
    JointAnswer,
    new_id,
)


def build_discrepancy_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["discrepancy"])
    get_repo = make_repo_dependency(database_path)

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/discrepancy",
        response_model=DiscrepancyStateResponse,
    )
    def get_unit_discrepancy_state(
        cycle_id: str,
        portal_id: str,
        repo: Repository = Depends(get_repo),
    ) -> DiscrepancyStateResponse:
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
        state_obj = unit_reconciliation_state(
            repo, session_id, cycle_id, portal_id, questions, settings
        )

        return DiscrepancyStateResponse(
            portal_id=portal_id,
            state=state_obj.state,
            differing_answer_rate=state_obj.rate,
            compared_count=state_obj.compared_count,
            disputed_question_ids=state_obj.disputed_question_ids,
            tolerance_in_force=state_obj.tolerance_in_force,
            rounds_consumed=state_obj.rounds_consumed,
            automatic_round_used=state_obj.automatic_round_used,
            open_round_id=state_obj.open_round_id,
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/reconciliation",
        response_model=ReconciliationWorkspaceResponse,
    )
    def get_reconciliation_workspace(
        cycle_id: str,
        portal_id: str,
        role: str = "A",
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
            role_enum = AssessorRole(role)
        except ValueError:
            raise InvalidRequest(
                f"Invalid role '{role}'. Must be 'A' or 'B'.",
                details={"role": role},
            )

        peer_role = AssessorRole.B if role_enum == AssessorRole.A else AssessorRole.A
        session_id = ensure_session(repo, cycle_id)
        open_round = repo.open_round_for_unit(session_id, portal_id)
        disputed_ids = set(open_round.data.get("disputed_question_ids", [])) if open_round else set()

        questions = repo.list_questions(cycle_id)
        recon_state = unit_reconciliation_state(
            repo, session_id, cycle_id, portal_id, questions, settings
        )

        disputed_rows: list[ReconciliationDisputeRow] = []
        settled_rows: list[ReconciliationSettledRow] = []

        for q in questions:
            my_sub = repo.latest_human_submission(
                session_id, q.question_id, portal_id, role_enum
            )
            joint = repo.latest_joint_answer(
                session_id, portal_id, q.question_id
            )

            if q.question_id in disputed_ids:
                peer_sub = repo.latest_human_submission(
                    session_id, q.question_id, portal_id, peer_role
                )
                disputed_rows.append(
                    ReconciliationDisputeRow(
                        question_id=q.question_id,
                        indicator_id=q.indicator_id,
                        title=q.title or q.text,
                        my_answer=my_sub.answer if my_sub else None,
                        my_evidence=my_sub.evidence_url if my_sub else "",
                        my_notes=my_sub.notes if my_sub else "",
                        peer_answer=peer_sub.answer if peer_sub else None,
                        peer_evidence=peer_sub.evidence_url if peer_sub else "",
                        peer_notes=peer_sub.notes if peer_sub else "",
                        peer_actor_id=peer_sub.assessor_actor_id if peer_sub else None,
                        joint_answer=joint.answer if joint else None,
                        joint_justification=joint.justification if joint else None,
                        joint_committed_by=joint.committed_by_role if joint else None,
                        is_disputed=True,
                    )
                )
            else:
                settled_rows.append(
                    ReconciliationSettledRow(
                        question_id=q.question_id,
                        indicator_id=q.indicator_id,
                        title=q.title or q.text,
                        my_answer=my_sub.answer if my_sub else None,
                        joint_answer=joint.answer if joint else None,
                        is_disputed=False,
                    )
                )

        return ReconciliationWorkspaceResponse(
            portal_id=portal_id,
            cycle_id=cycle_id,
            role=role_enum.value,
            peer_role=peer_role.value,
            state=recon_state.state,
            round_id=open_round.round_id if open_round else None,
            rate_pct=_format_pct(recon_state.rate) if recon_state.rate is not None else "0%",
            tolerance_pct=_format_pct(recon_state.tolerance_in_force),
            compared_count=recon_state.compared_count,
            disputed_rows=disputed_rows,
            settled_rows=settled_rows,
        )

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/reconciliation/{question_id}/joint",
        response_model=JointAnswerResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def commit_joint_answer(
        cycle_id: str,
        portal_id: str,
        question_id: str,
        body: JointAnswerRequest,
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
                details={"role": body.role},
            )

        session_id = ensure_session(repo, cycle_id)
        open_round = repo.open_round_for_unit(session_id, portal_id)
        if open_round is None:
            raise Conflict("No reconciliation round is currently open for this unit.")

        disputed_ids = set(open_round.data.get("disputed_question_ids", []))
        if question_id not in disputed_ids:
            raise InvalidRequest(
                f"Question '{question_id}' is not part of this round's disputed set.",
                details={"question_id": question_id},
            )

        if not body.justification or not body.justification.strip():
            raise InvalidRequest(
                "A justification is required to commit a joint answer.",
                details={"field": "justification"},
            )

        now = datetime.now(timezone.utc)
        joint = JointAnswer(
            joint_answer_id=new_id("joint"),
            session_id=session_id,
            portal_id=portal_id,
            question_id=question_id,
            round_id=open_round.round_id,
            data={
                "answer": bool(body.answer),
                "justification": body.justification.strip(),
                "submitted_by_role": role_enum.value,
                "submitted_by_actor_id": body.actor_id,
            },
            created_at=now,
        )
        repo.insert_joint_answer(joint)

        questions = repo.list_questions(cycle_id)
        closed_obj = close_round_if_complete(
            repo, open_round.round_id, session_id, cycle_id, portal_id, questions, settings
        )

        return JointAnswerResponse(
            joint_answer_id=joint.joint_answer_id,
            round_id=open_round.round_id,
            question_id=question_id,
            answer=body.answer,
            justification=body.justification,
            committed_by_role=role_enum.value,
            round_closed=bool(closed_obj),
        )

    # --- Escalations / Senior Review Queue ---

    @router.get(
        "/cycles/{cycle_id}/escalations",
        response_model=EscalationsListResponse,
    )
    def list_escalations(
        cycle_id: str,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        session_id = ensure_session(repo, cycle_id)
        views = list_escalation_queue(repo, session_id)

        items = []
        for v in views:
            disp_at_str = (
                v.item.disposed_at.isoformat()
                if hasattr(v.item.disposed_at, "isoformat")
                else str(v.item.disposed_at)
                if v.item.disposed_at
                else None
            )
            items.append(
                EscalationItemResponse(
                    item_id=v.item.item_id,
                    session_id=session_id,
                    portal_id=v.item.portal_id,
                    question_id=v.item.question_id,
                    reason=v.item.reason.value if hasattr(v.item.reason, "value") else str(v.item.reason),
                    context=v.item.context if isinstance(v.item.context, dict) else {},
                    disposition=v.disposition if isinstance(v.disposition, dict) else None,
                    disposed_by_actor_id=v.item.disposed_by_actor_id,
                    disposed_at=disp_at_str,
                )
            )

        return EscalationsListResponse(escalations=items)

    @router.post(
        "/cycles/{cycle_id}/escalations/{item_id}/dispose",
        response_model=EscalationDispositionResponse,
    )
    def dispose_escalation_item(
        cycle_id: str,
        item_id: str,
        body: EscalationDispositionRequest,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        session_id = ensure_session(repo, cycle_id)
        items = repo.list_escalations(session_id)
        matching_item = next((it for it in items if it.item_id == item_id), None)
        if not matching_item:
            raise NotFound(
                f"Escalation item '{item_id}' not found.",
                details={"item_id": item_id},
            )

        if body.resolution == "returned_for_reconciliation":
            if not body.notes or not body.notes.strip():
                raise InvalidRequest(
                    "A stated reason is required to return a unit for reconciliation.",
                    details={"field": "notes"},
                )
            try:
                open_reviewer_round(
                    repo,
                    session_id,
                    cycle_id,
                    matching_item.portal_id,
                    body.actor_id,
                    body.notes,
                    settings,
                )
            except ValueError as e:
                raise InvalidRequest(str(e))

        ok = dispose_escalation(
            repo,
            item_id,
            body.resolution,
            body.actor_id,
            body.notes,
            body.resolved_answers or None,
        )
        if not ok:
            raise Conflict("Escalation has already been decided by another reviewer.")

        now = datetime.now(timezone.utc)
        return EscalationDispositionResponse(
            item_id=item_id,
            resolution=body.resolution,
            resolved_by=body.actor_id,
            resolved_at=now.isoformat(),
            notes=body.notes,
        )

    return router
