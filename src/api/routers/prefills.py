"""Prefills router (spec 008 FR-PF-012, FR-PF-013)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.deps import make_repo_dependency
from api.schemas import (
    NotFound,
    PrefillItem,
    PrefillsResponse,
)
from portal.common import ensure_session
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.reason_tags import prefill_reason_tag


def build_prefills_router(
    database_path: str, settings: Settings
) -> APIRouter:
    router = APIRouter(tags=["prefills"])
    get_repo = make_repo_dependency(database_path)

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/prefills",
        response_model=PrefillsResponse,
    )
    def get_prefills(
        cycle_id: str,
        portal_id: str,
        run_id: str | None = Query(None, description="Optional specific run ID"),
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

        items: list[PrefillItem] = []
        found_runs: set[str] = set()
        latest_ts = None
        has_missing = False

        if run_id:
            run_prefills = repo.list_prefills_for_run(run_id)
            p_by_q = {p.question_id: p for p in run_prefills}
        else:
            p_by_q = {}
            for q in questions:
                p = repo.latest_prefill(session_id, q.question_id, portal_id)
                if p:
                    p_by_q[q.question_id] = p

        for q in questions:
            p = p_by_q.get(q.question_id)
            if p is None:
                has_missing = True
                continue

            if p.run_id:
                found_runs.add(p.run_id)
            if p.generated_at:
                p_ts = (
                    p.generated_at.isoformat()
                    if hasattr(p.generated_at, "isoformat")
                    else str(p.generated_at)
                )
                if latest_ts is None or p_ts > latest_ts:
                    latest_ts = p_ts

            reason_str = None
            reason_text_val = None
            if p.reason:
                reason_str = (
                    p.reason.value if hasattr(p.reason, "value") else str(p.reason)
                )
                try:
                    reason_text_val = prefill_reason_tag(reason_str).text
                except KeyError:
                    pass

            resolver_reasoning = None
            if p.resolver_decision:
                if isinstance(p.resolver_decision, dict):
                    resolver_reasoning = p.resolver_decision.get("reasoning")
                elif hasattr(p.resolver_decision, "reasoning"):
                    resolver_reasoning = p.resolver_decision.reasoning

            unselected_dict = None
            if p.unselected_position:
                if isinstance(p.unselected_position, dict):
                    unselected_dict = p.unselected_position
                elif hasattr(p.unselected_position, "__dict__"):
                    unselected_dict = {
                        k: v
                        for k, v in p.unselected_position.__dict__.items()
                        if not k.startswith("_")
                    }

            items.append(
                PrefillItem(
                    question_id=q.question_id,
                    indicator_id=q.indicator_id,
                    suggested=p.suggested,
                    answer=p.answer,
                    confidence=p.confidence,
                    justification=p.justification,
                    evidence_url=p.evidence_url,
                    capture_ref=p.capture_ref,
                    supplying_source=p.supplying_source,
                    agreement_outcome=p.agreement_outcome,
                    confidence_gap=p.confidence_gap,
                    unselected_position=unselected_dict,
                    resolver_reasoning=resolver_reasoning,
                    reason=reason_str,
                    reason_text=reason_text_val,
                )
            )

        resp_run_id = (
            run_id
            if run_id
            else (list(found_runs)[0] if len(found_runs) == 1 else None)
        )
        complete = not has_missing and (len(items) == len(questions))

        return PrefillsResponse(
            run_id=resp_run_id,
            generated_at=latest_ts,
            complete=complete,
            prefills=items,
        )

    return router
