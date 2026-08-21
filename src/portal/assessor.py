"""Assessor Portal (spec 005 Section 3.3, spec 008).

Two blind human assessors (A/B) per unit, replacing the manual Google Sheets
workflow from the transcript. Each role only ever sees its own prior
submissions -- never the other role's -- enforced by querying
`latest_human_submission(..., role=...)` scoped to exactly that role, never a
cross-role read. The pipeline pre-fill is shown to both roles identically as a
starting suggestion (spec 008 FR-PF-008, FR-PF-012) -- AI proposes, both humans
independently verify or override. Completion is an explicit attributed declaration.
"""

from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from portal.common import ensure_session, repo_factory
from portal.discrepancy import recompute_portal_discrepancy
from shared.config.settings import Settings
from shared.state.entities import (
    AssessorCompletion,
    AssessorRole,
    HumanAssessorSubmission,
    new_id,
)
from shared.state.reason_tags import prefill_reason_tag

# Human-readable labels for LinkSource values (shared/state/entities.py),
# shown to the assessor alongside the AI's evidence link.
_SUPPLYING_SOURCE_LABELS = {
    "prior_survey_kb": "Prior Questionnaire",
    "msq": "MSQ",
    "search": "Web",
}


def _supplying_source_label(source: str | None) -> str | None:
    if not source:
        return None
    value = source.value if hasattr(source, "value") else str(source)
    return _SUPPLYING_SOURCE_LABELS.get(value, value)


def build_assessor_router(database_path: str, settings: Settings, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    repo = repo_factory(database_path)

    @router.get("/assessor", response_class=HTMLResponse)
    def picker(request: Request):
        r = repo()
        cycles = r.list_cycles()
        units_by_cycle = {c.cycle_id: r.list_portals(c.cycle_id) for c in cycles}
        return templates.TemplateResponse(
            request, "assessor_picker.html",
            {"cycles": cycles, "units_by_cycle": units_by_cycle},
        )

    @router.get("/assessor/{cycle_id}/{portal_id}", response_class=HTMLResponse)
    def unit_form(
        request: Request,
        cycle_id: str,
        portal_id: str,
        role: AssessorRole,
        actor_id: str = "assessor-1",
        error: str | None = None,
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        portal = r.get_portal(portal_id)
        if cycle is None or portal is None:
            return HTMLResponse("Unknown project or unit.", status_code=404)
        questions = r.list_questions(cycle_id)
        session_id = ensure_session(r, cycle_id)
        assessor_role = role

        rows = []
        answered_count = 0
        outstanding_question_ids = []
        for q in questions:
            prefill = r.latest_prefill(session_id, q.question_id, portal_id)
            mine = r.latest_human_submission(session_id, q.question_id, portal_id, assessor_role)
            if mine is not None and mine.answer is not None:
                answered_count += 1
            else:
                outstanding_question_ids.append(q.question_id)

            prefill_dict = None
            if prefill:
                reason_tag_obj = None
                if prefill.reason:
                    try:
                        reason_val = prefill.reason.value if hasattr(prefill.reason, "value") else str(prefill.reason)
                        reason_tag_obj = prefill_reason_tag(reason_val)
                    except KeyError:
                        pass
                resolver_reasoning = None
                if prefill.resolver_decision:
                    if isinstance(prefill.resolver_decision, dict):
                        resolver_reasoning = prefill.resolver_decision.get("reasoning")
                    elif hasattr(prefill.resolver_decision, "reasoning"):
                        resolver_reasoning = prefill.resolver_decision.reasoning

                prefill_dict = {
                    "suggested": prefill.suggested,
                    "answer": prefill.answer,
                    "confidence": prefill.confidence,
                    "justification": prefill.justification,
                    "evidence_url": prefill.evidence_url,
                    "supplying_source": prefill.supplying_source,
                    "supplying_source_label": _supplying_source_label(prefill.supplying_source),
                    "agreement_outcome": prefill.agreement_outcome,
                    "confidence_gap": prefill.confidence_gap,
                    "resolver_decision": prefill.resolver_decision,
                    "resolver_reasoning": resolver_reasoning,
                    "unselected_position": prefill.unselected_position,
                    "reason": prefill.reason,
                    "reason_text": reason_tag_obj.text if reason_tag_obj else None,
                }

            rows.append({
                "question": q,
                "ai": prefill_dict,
                "mine": mine,
            })

        completion = r.latest_assessor_completion(session_id, portal_id, assessor_role.value)
        is_declared = completion is not None
        is_complete = is_declared and (answered_count == len(questions))

        return templates.TemplateResponse(
            request, "assessor_unit.html",
            {
                "cycle": cycle,
                "portal": portal,
                "rows": rows,
                "role": role.value,
                "actor_id": actor_id,
                "answered_count": answered_count,
                "total_questions": len(questions),
                "outstanding_question_ids": outstanding_question_ids,
                "can_complete": answered_count == len(questions),
                "is_declared": is_declared,
                "is_complete": is_complete,
                "completion": completion,
                "error_message": error,
            },
        )

    @router.post("/assessor/{cycle_id}/{portal_id}/question/{question_id}/submit")
    def submit(
        cycle_id: str,
        portal_id: str,
        question_id: str,
        role: AssessorRole = Form(...),
        actor_id: str = Form(...),
        answer: str = Form(...),
        evidence_url: str = Form(""),
        notes: str = Form(""),
    ):
        r = repo()
        session_id = ensure_session(r, cycle_id)
        questions = r.list_questions(cycle_id)
        assessor_role = role

        prefill = r.latest_prefill(session_id, question_id, portal_id)
        bool_answer = answer == "true"
        ai_suggested_answer = prefill.answer if (prefill and prefill.suggested) else None
        ai_suggestion_accepted = (
            bool(prefill.answer) == bool_answer if (prefill and prefill.suggested) else None
        )

        r.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=question_id,
                portal_id=portal_id,
                role=assessor_role,
                assessor_actor_id=actor_id,
                answer=bool_answer,
                evidence_url=evidence_url or None,
                notes=notes or None,
                ai_suggested_answer=ai_suggested_answer,
                ai_suggestion_accepted=ai_suggestion_accepted,
            )
        )

        recompute_portal_discrepancy(
            r,
            session_id,
            portal_id,
            [q.question_id for q in questions],
            settings.human_discrepancy_rate_threshold,
        )

        return RedirectResponse(
            f"/assessor/{cycle_id}/{portal_id}?role={role.value}&actor_id={actor_id}",
            status_code=303,
        )

    @router.post("/assessor/{cycle_id}/{portal_id}/complete")
    def complete_unit(
        cycle_id: str,
        portal_id: str,
        role: AssessorRole = Form(...),
        actor_id: str = Form(...),
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        portal = r.get_portal(portal_id)
        if cycle is None or portal is None:
            return HTMLResponse("Unknown project or unit.", status_code=404)

        questions = r.list_questions(cycle_id)
        session_id = ensure_session(r, cycle_id)

        outstanding = []
        for q in questions:
            sub = r.latest_human_submission(session_id, q.question_id, portal_id, role)
            if sub is None or sub.answer is None:
                outstanding.append(q.question_id)

        if outstanding:
            cnt = len(outstanding)
            s = "indicator" if cnt == 1 else "indicators"
            first_q = outstanding[0]
            error_msg = f"Cannot complete assessment: {cnt} {s} outstanding ({first_q})."
            return RedirectResponse(
                f"/assessor/{cycle_id}/{portal_id}?role={role.value}&actor_id={actor_id}&error={urllib.parse.quote(error_msg)}",
                status_code=303,
            )

        r.insert_assessor_completion(
            AssessorCompletion(
                completion_id=new_id("comp"),
                session_id=session_id,
                cycle_id=cycle_id,
                portal_id=portal_id,
                role=role.value,
                actor_id=actor_id,
                indicator_count_at_declaration=len(questions),
            )
        )

        return RedirectResponse(
            f"/assessor/{cycle_id}/{portal_id}?role={role.value}&actor_id={actor_id}",
            status_code=303,
        )

    return router
