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
from datetime import UTC

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from portal.assignment import resolve_actor_role
from portal.common import ensure_session, repo_factory
from portal.discrepancy import recompute_portal_discrepancy
from portal.reconciliation import (
    _format_pct,
    close_round_if_complete,
    render_badge,
    unit_reconciliation_state,
)
from portal.tolerance import effective_tolerance
from shared.config.settings import Settings
from shared.state.entities import (
    AssessorCompletion,
    AssessorRole,
    HumanAssessorSubmission,
    JointAnswer,
    new_id,
)


def build_assessor_router(database_path: str, settings: Settings, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    repo = repo_factory(database_path)

    @router.get("/assessor", response_class=HTMLResponse)
    def picker(request: Request, actor_id: str | None = None):
        r = repo()
        roster = r.list_assessors()
        cycles_map = {c.cycle_id: c for c in r.list_cycles()}

        assigned_units = []
        if actor_id:
            all_assignments = r.list_all_unit_assignments()
            portals_map = {}
            for c_id in cycles_map:
                for p in r.list_portals(c_id):
                    portals_map[(c_id, p.portal_id)] = p

            for asmt in all_assignments:
                if not asmt.is_staffed:
                    continue
                role_val = None
                if asmt.role_a and asmt.role_a.assessor_id == actor_id:
                    role_val = "A"
                elif asmt.role_b and asmt.role_b.assessor_id == actor_id:
                    role_val = "B"

                if role_val:
                    cycle = cycles_map.get(asmt.cycle_id)
                    portal = portals_map.get((asmt.cycle_id, asmt.portal_id))
                    if cycle and portal:
                        assigned_units.append({
                            "cycle": cycle,
                            "portal": portal,
                            "role": role_val,
                        })

        return templates.TemplateResponse(
            request, "assessor_picker.html",
            {
                "roster": roster,
                "selected_actor_id": actor_id,
                "assigned_units": assigned_units,
            },
        )

    @router.get("/assessor/{cycle_id}/{portal_id}", response_class=HTMLResponse)
    def unit_form(
        request: Request,
        cycle_id: str,
        portal_id: str,
        actor_id: str,
        error: str | None = None,
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        portal = r.get_portal(portal_id)
        if cycle is None or portal is None:
            return HTMLResponse("Unknown project or unit.", status_code=404)

        assigned_role = resolve_actor_role(r, cycle_id, portal_id, actor_id)
        if assigned_role is None:
            return HTMLResponse("You are not assigned to this unit.", status_code=403)

        questions = r.list_questions(cycle_id)
        session_id = ensure_session(r, cycle_id)

        recon_state = unit_reconciliation_state(r, session_id, cycle_id, portal_id, questions, settings)
        if recon_state.state == "reconciliation_open":
            return RedirectResponse(
                f"/assessor/{cycle_id}/{portal_id}/reconcile?actor_id={urllib.parse.quote(actor_id)}",
                status_code=303,
            )

        assessor_role = assigned_role

        rows = []
        answered_count = 0
        outstanding_question_ids = []
        for q in questions:
            mine = r.latest_human_submission(session_id, q.question_id, portal_id, assessor_role)
            if mine is not None and mine.answer is not None:
                answered_count += 1
            else:
                outstanding_question_ids.append(q.question_id)

            rows.append({
                "question": q,
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
                "role": assigned_role.value,
                "actor_id": actor_id,
                "answered_count": answered_count,
                "total_questions": len(questions),
                "outstanding_question_ids": outstanding_question_ids,
                "can_complete": answered_count == len(questions),
                "is_declared": is_declared,
                "is_complete": is_complete,
                "completion": completion,
                "recon_state": recon_state,
                "recon_badge": render_badge(recon_state),
                "error_message": error,
            },
        )

    @router.post("/assessor/{cycle_id}/{portal_id}/question/{question_id}/submit")
    def submit(
        request: Request,
        cycle_id: str,
        portal_id: str,
        question_id: str,
        actor_id: str = Form(...),
        answer: str = Form(...),
        evidence_url: str = Form(""),
        notes: str = Form(""),
    ):
        r = repo()
        assigned_role = resolve_actor_role(r, cycle_id, portal_id, actor_id)
        if assigned_role is None:
            return HTMLResponse("You are not assigned to this unit.", status_code=403)

        session_id = ensure_session(r, cycle_id)
        questions = r.list_questions(cycle_id)
        assessor_role = assigned_role

        bool_answer = answer == "true"

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
            )
        )

        recompute_portal_discrepancy(
            r,
            session_id,
            portal_id,
            [q.question_id for q in questions],
            effective_tolerance(r, cycle_id, settings),
        )

        # Calculate unanswered questions for intelligent auto-advance
        question_ids = [q.question_id for q in questions]
        unanswered: list[str] = []
        for q in questions:
            sub = r.latest_human_submission(session_id, q.question_id, portal_id, assessor_role)
            if sub is None or sub.answer is None:
                unanswered.append(q.question_id)

        next_unanswered: str | None = None
        if unanswered:
            curr_idx = question_ids.index(question_id) if question_id in question_ids else -1
            # Find next unanswered in sequence after the current question
            next_unanswered = next((qid for qid in question_ids[curr_idx + 1:] if qid in unanswered), None)
            if not next_unanswered:
                # Wrap around to the first unanswered
                next_unanswered = unanswered[0]

        target_anchor = f"q_{next_unanswered}" if next_unanswered else "assessment-progress-panel"

        # Check if request prefers JSON (AJAX / Fetch API)
        accept_header = request.headers.get("accept", "")
        if "application/json" in accept_header or request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JSONResponse({
                "status": "success",
                "saved_question_id": question_id,
                "answer": bool_answer,
                "evidence_url": evidence_url or "",
                "notes": notes or "",
                "answered_count": len(questions) - len(unanswered),
                "total_questions": len(questions),
                "outstanding_question_ids": unanswered,
                "next_unsubmitted_id": next_unanswered,
                "can_complete": len(unanswered) == 0,
            })

        return RedirectResponse(
            f"/assessor/{cycle_id}/{portal_id}?actor_id={urllib.parse.quote(actor_id)}#{target_anchor}",
            status_code=303,
        )

    @router.post("/assessor/{cycle_id}/{portal_id}/complete")
    def complete_unit(
        cycle_id: str,
        portal_id: str,
        actor_id: str = Form(...),
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        portal = r.get_portal(portal_id)
        if cycle is None or portal is None:
            return HTMLResponse("Unknown project or unit.", status_code=404)

        assigned_role = resolve_actor_role(r, cycle_id, portal_id, actor_id)
        if assigned_role is None:
            return HTMLResponse("You are not assigned to this unit.", status_code=403)

        role = assigned_role

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
                f"/assessor/{cycle_id}/{portal_id}?actor_id={urllib.parse.quote(actor_id)}&error={urllib.parse.quote(error_msg)}",
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

        recompute_portal_discrepancy(
            r,
            session_id,
            portal_id,
            [q.question_id for q in questions],
            effective_tolerance(r, cycle_id, settings),
            cycle_id=cycle_id,
        )

        return RedirectResponse(
            f"/assessor/{cycle_id}/{portal_id}?actor_id={urllib.parse.quote(actor_id)}",
            status_code=303,
        )

    @router.get("/assessor/{cycle_id}/{portal_id}/reconcile", response_class=HTMLResponse)
    def reconcile_workspace(
        request: Request,
        cycle_id: str,
        portal_id: str,
        actor_id: str,
        error: str | None = None,
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        portal = r.get_portal(portal_id)
        if cycle is None or portal is None:
            return HTMLResponse("Unknown project or unit.", status_code=404)

        assigned_role = resolve_actor_role(r, cycle_id, portal_id, actor_id)
        if assigned_role is None:
            return HTMLResponse("You are not assigned to this unit.", status_code=403)

        role = assigned_role

        session_id = ensure_session(r, cycle_id)
        open_round = r.open_round_for_unit(session_id, portal_id)
        if open_round is None:
            error_msg = "No reconciliation round is currently open for this unit."
            return RedirectResponse(
                f"/assessor/{cycle_id}/{portal_id}?actor_id={urllib.parse.quote(actor_id)}&error={urllib.parse.quote(error_msg)}",
                status_code=303,
            )

        questions = r.list_questions(cycle_id)
        disputed_ids = set(open_round.data.get("disputed_question_ids", []))
        peer_role = AssessorRole.B if role == AssessorRole.A else AssessorRole.A
        recon_state = unit_reconciliation_state(r, session_id, cycle_id, portal_id, questions, settings)
        badge_html = render_badge(recon_state)

        disputed_rows = []
        settled_rows = []

        for q in questions:
            my_sub = r.latest_human_submission(session_id, q.question_id, portal_id, role)
            joint = r.latest_joint_answer(session_id, portal_id, q.question_id)

            if q.question_id in disputed_ids:
                peer_sub = r.latest_human_submission(session_id, q.question_id, portal_id, peer_role)
                disputed_rows.append({
                    "question": q,
                    "my_answer": my_sub.answer if my_sub else None,
                    "my_evidence": my_sub.evidence_url if my_sub else "",
                    "my_notes": my_sub.notes if my_sub else "",
                    "peer_answer": peer_sub.answer if peer_sub else None,
                    "peer_evidence": peer_sub.evidence_url if peer_sub else "",
                    "peer_notes": peer_sub.notes if peer_sub else "",
                    "peer_actor_id": peer_sub.assessor_actor_id if peer_sub else None,
                    "joint_answer": joint.answer if joint else None,
                    "joint_justification": joint.justification if joint else None,
                    "joint_committed_by": joint.committed_by_role if joint else None,
                    "is_disputed": True,
                })
            else:
                settled_rows.append({
                    "question": q,
                    "my_answer": my_sub.answer if my_sub else None,
                    "joint_answer": joint.answer if joint else None,
                    "peer_answer": None,  # peer answer omitted for settled indicators (FR-DR-017, SC-011)
                    "is_disputed": False,
                })

        return templates.TemplateResponse(
            request, "assessor_reconcile.html",
            {
                "cycle": cycle,
                "portal": portal,
                "round": open_round,
                "role": role.value,
                "peer_role": peer_role.value,
                "actor_id": actor_id,
                "disputed_rows": disputed_rows,
                "settled_rows": settled_rows,
                "recon_state": recon_state,
                "recon_state_badge": badge_html,
                "rate_pct": _format_pct(recon_state.rate) if recon_state.rate is not None else "0%",
                "tolerance_pct": _format_pct(recon_state.tolerance_in_force),
                "compared_count": recon_state.compared_count,
                "error": error,
            },
        )

    @router.post("/assessor/{cycle_id}/{portal_id}/reconcile/{question_id}/joint")
    def commit_joint_answer(
        request: Request,
        cycle_id: str,
        portal_id: str,
        question_id: str,
        actor_id: str = Form(...),
        answer: bool = Form(...),
        justification: str = Form(""),
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        portal = r.get_portal(portal_id)
        if cycle is None or portal is None:
            return HTMLResponse("Unknown project or unit.", status_code=404)

        assigned_role = resolve_actor_role(r, cycle_id, portal_id, actor_id)
        if assigned_role is None:
            return HTMLResponse("You are not assigned to this unit.", status_code=403)

        role = assigned_role

        session_id = ensure_session(r, cycle_id)
        open_round = r.open_round_for_unit(session_id, portal_id)
        if open_round is None:
            error_msg = "No reconciliation round is currently open for this unit."
            return RedirectResponse(
                f"/assessor/{cycle_id}/{portal_id}?actor_id={urllib.parse.quote(actor_id)}&error={urllib.parse.quote(error_msg)}",
                status_code=303,
            )

        disputed_ids = set(open_round.data.get("disputed_question_ids", []))
        if question_id not in disputed_ids:
            error_msg = f"Question '{question_id}' is not part of this round's disputed set."
            return RedirectResponse(
                f"/assessor/{cycle_id}/{portal_id}/reconcile?actor_id={urllib.parse.quote(actor_id)}&error={urllib.parse.quote(error_msg)}",
                status_code=303,
            )

        if not justification or not justification.strip():
            error_msg = "A justification is required to commit a joint answer."
            return RedirectResponse(
                f"/assessor/{cycle_id}/{portal_id}/reconcile?actor_id={urllib.parse.quote(actor_id)}&error={urllib.parse.quote(error_msg)}#dispute-{question_id}",
                status_code=303,
            )

        from datetime import datetime
        joint = JointAnswer(
            joint_answer_id=new_id("joint"),
            session_id=session_id,
            portal_id=portal_id,
            question_id=question_id,
            round_id=open_round.round_id,
            data={
                "answer": bool(answer),
                "justification": justification.strip(),
                "submitted_by_role": role.value,
                "submitted_by_actor_id": actor_id,
            },
            created_at=datetime.now(UTC),
        )
        r.insert_joint_answer(joint)

        questions = r.list_questions(cycle_id)
        close_round_if_complete(
            r, open_round.round_id, session_id, cycle_id, portal_id, questions, settings
        )

        return RedirectResponse(
            f"/assessor/{cycle_id}/{portal_id}/reconcile?actor_id={urllib.parse.quote(actor_id)}",
            status_code=303,
        )

    return router
