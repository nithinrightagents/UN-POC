"""Admin surface (spec 005 Section 3.2 / 3.6).

Project (cycle) creation, indicator management, unit (country/city + URL)
assignment, triggering the live 001 assessment pipeline (link resolution ->
N independent Vertex AI agents -> validator -> adjudicator, see
portal/live_prefill.py) as a background run, MSQ upload, and the Senior
Reviewer's one-click publish. CLI equivalents of most of this already existed
in 001 (`aiq question add`, `aiq run`); this is the UI Deniz asked for on top
of the same repository/entity layer.
"""

from __future__ import annotations

import logging
import pathlib
import tempfile

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from api.finalize import final_answer, publication_readiness
from api.identity import compose_question_id
from api.jobs import job_status, start_assessment_job
from portal.common import ensure_session, repo_factory
from portal.discrepancy import compute_portal_discrepancy
from portal.msq import ingest_msq_pdf
from review.escalations import dispose_escalation, list_escalation_queue
from shared.config.settings import Settings
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    ProjectType,
    PublicationRecord,
    Question,
    SurveyCycle,
    TargetPortal,
    TERMINAL_UNIT_STATES,
    UnitState,
    new_id,
)

_log = logging.getLogger(__name__)


def build_admin_router(database_path: str, settings: Settings, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    repo = repo_factory(database_path)

    @router.get("/admin", response_class=HTMLResponse)
    def projects_page(request: Request):
        r = repo()
        cycles = r.list_cycles()
        return templates.TemplateResponse(
            request, "admin_projects.html", {"cycles": cycles}
        )

    @router.post("/admin/projects")
    def create_project(
        cycle_id: str = Form(...),
        name: str = Form(...),
        questionnaire_ref: str = Form("UN MSQ 2026 Indicator Set"),
        project_type: str = Form("national_osi"),
    ):
        r = repo()
        r.insert_cycle(
            SurveyCycle(
                cycle_id=cycle_id, name=name, questionnaire_ref=questionnaire_ref,
                country_set=[], project_type=ProjectType(project_type),
            )
        )
        ensure_session(r, cycle_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.get("/admin/projects/{cycle_id}", response_class=HTMLResponse)
    def project_detail(request: Request, cycle_id: str):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)
        questions = r.list_questions(cycle_id)
        units = r.list_portals(cycle_id)
        session_id = ensure_session(r, cycle_id)

        unit_rows = []
        for u in units:
            unit_states = r.list_units_for_portal(session_id, u.portal_id)
            states_seen = {row["state"] for row in unit_states}
            terminal = {s.value for s in TERMINAL_UNIT_STATES}
            assessed_count = sum(1 for row in unit_states if row["state"] in terminal)
            msq = r.find_msq_document(cycle_id, u.country_id)
            publication = r.latest_publication(cycle_id, u.portal_id)
            case = compute_portal_discrepancy(
                r, session_id, u.portal_id, [q.question_id for q in questions],
                settings.human_discrepancy_rate_threshold,
            )
            st = job_status(r, session_id, cycle_id, u.portal_id)
            readiness = publication_readiness(r, session_id, cycle_id, u.portal_id)
            unit_rows.append({
                "portal": u,
                "assessed_count": assessed_count,
                "started_count": len(unit_states),
                "total_questions": len(questions),
                "run_in_progress": st.state == "running" or bool(states_seen - terminal),
                "msq": msq,
                "publication": publication,
                "discrepancy": case,
                "readiness": readiness,
                "job_status": st,
                "prefill_summary": st.summary,
            })

        return templates.TemplateResponse(
            request, "admin_project_detail.html",
            {
                "cycle": cycle, "questions": questions,
                "units": unit_rows, "session_id": session_id,
                "any_run_in_progress": any(row["run_in_progress"] for row in unit_rows),
            },
        )

    @router.post("/admin/projects/{cycle_id}/questions")
    def add_question(
        cycle_id: str,
        question_id: str = Form(...),
        title: str = Form(...),
        what: str = Form(...),
        why: str = Form(...),
        how: str = Form(...),
        module: str = Form("Custom Indicators"),
        evidence_locus: str = Form("national_portal_only"),
        benchmark_case: str = Form(""),
    ):
        r = repo()
        text = f"{title} — {what}"
        how_data = {
            "evidence_locus": evidence_locus,
            "scoring_guidance": how,
            "criteria_for_yes": "Evidence found on the designated government portal satisfying the What specification.",
            "criteria_for_no": "No evidence found or feature unreachable within reasonable navigation.",
        }
        # question_id is a global primary key (schema.py) -- cycle-prefix it
        # so the same indicator code can be reused across different projects.
        r.insert_question(
            Question(
                question_id=compose_question_id(cycle_id, question_id),
                cycle_id=cycle_id,
                text=text,
                answer_type=AnswerType.BINARY,
                evidence_locus=EvidenceLocus(evidence_locus),
                is_custom=True,
                indicator_id=question_id,
                question_class=module,
                title=title,
                what=what,
                why=why,
                how=how_data,
                benchmark_case=benchmark_case or None,
            )
        )

        # Branch into a distinct custom questionnaire set for this project
        cycle = r.get_cycle(cycle_id)
        if cycle:
            existing_questions = r.list_questions(cycle_id)
            total_count = len(existing_questions)
            custom_ref_name = f"{cycle.name} Custom Questionnaire Set ({total_count} indicators)"
            cycle.questionnaire_ref = custom_ref_name
            r.insert_cycle(cycle)  # append-only superseding cycle record

        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units")
    def add_unit(
        cycle_id: str, country_id: str = Form(...), display_name: str = Form(...),
        url: str = Form(...), unit_type: str = Form("country"),
    ):
        r = repo()
        r.insert_portal(
            TargetPortal(
                portal_id=new_id("portal"), cycle_id=cycle_id, country_id=country_id,
                resolved_url=url, unit_type=unit_type, display_name=display_name,
            )
        )
        cycle = r.get_cycle(cycle_id)
        if cycle and country_id not in cycle.country_set:
            cycle.country_set.append(country_id)
            r.insert_cycle(cycle)  # append-only: superseding row, latest read wins via get_cycle
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/assess")
    async def run_assessment(cycle_id: str, portal_id: str):
        r = repo()
        session_id = ensure_session(r, cycle_id)
        start_assessment_job(
            r,
            settings,
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            triggered_by="portal",
            actor="admin",
        )
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/msq")
    async def upload_msq(cycle_id: str, portal_id: str, msq_file: UploadFile):
        r = repo()
        portal = r.get_portal(portal_id)
        if portal:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(await msq_file.read())
                tmp_path = tmp.name
            try:
                doc = ingest_msq_pdf(tmp_path, cycle_id, portal.country_id, msq_file.filename or "upload.pdf")
                r.insert_msq_document(doc)
            finally:
                pathlib.Path(tmp_path).unlink(missing_ok=True)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/publish")
    def publish_unit(
        request: Request,
        cycle_id: str,
        portal_id: str,
        actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        session_id = ensure_session(r, cycle_id)
        readiness = publication_readiness(r, session_id, cycle_id, portal_id)
        if not readiness.ready:
            cycle = r.get_cycle(cycle_id)
            questions = r.list_questions(cycle_id)
            units = r.list_portals(cycle_id)
            unit_rows = []
            for u in units:
                unit_states = r.list_units_for_portal(session_id, u.portal_id)
                states_seen = {row["state"] for row in unit_states}
                terminal = {s.value for s in TERMINAL_UNIT_STATES}
                assessed_count = sum(1 for row in unit_states if row["state"] in terminal)
                msq = r.find_msq_document(cycle_id, u.country_id)
                publication = r.latest_publication(cycle_id, u.portal_id)
                case = compute_portal_discrepancy(
                    r, session_id, u.portal_id, [q.question_id for q in questions],
                    settings.human_discrepancy_rate_threshold,
                )
                st = job_status(r, session_id, cycle_id, u.portal_id)
                u_readiness = publication_readiness(r, session_id, cycle_id, u.portal_id)
                unit_rows.append({
                    "portal": u,
                    "assessed_count": assessed_count,
                    "started_count": len(unit_states),
                    "total_questions": len(questions),
                    "run_in_progress": st.state == "running" or bool(states_seen - terminal),
                    "msq": msq,
                    "publication": publication,
                    "discrepancy": case,
                    "readiness": u_readiness,
                })
            return templates.TemplateResponse(
                request, "admin_project_detail.html",
                {
                    "cycle": cycle,
                    "questions": questions,
                    "units": unit_rows,
                    "session_id": session_id,
                    "any_run_in_progress": any(row["run_in_progress"] for row in unit_rows),
                    "error_message": readiness.blocking_reason,
                },
                status_code=400,
            )

        questions = r.list_questions(cycle_id)
        breakdown: dict[str, bool] = {}
        for q in questions:
            final = final_answer(r, session_id, q.question_id, portal_id)
            if final is not None:
                breakdown[q.question_id] = bool(final)
        affirmative = sum(1 for v in breakdown.values() if v)
        score = (affirmative / len(breakdown)) if breakdown else 0.0
        r.insert_publication(
            PublicationRecord(
                publication_id=new_id("pub"), cycle_id=cycle_id, portal_id=portal_id,
                published_by_actor_id=actor_id, score=score, score_breakdown=breakdown,
            )
        )
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.get("/admin/projects/{cycle_id}/escalations", response_class=HTMLResponse)
    def escalations_page(request: Request, cycle_id: str):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)
        session_id = ensure_session(r, cycle_id)
        views = list_escalation_queue(r, session_id)
        return templates.TemplateResponse(
            request, "admin_escalations.html",
            {"cycle": cycle, "views": views, "session_id": session_id},
        )

    @router.post("/admin/projects/{cycle_id}/escalations/{item_id}/dispose")
    async def dispose(
        request: Request, cycle_id: str, item_id: str, resolution: str = Form(...),
        notes: str = Form(""), actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        # Per-question resolved answers arrive as dynamically-named fields
        # (resolved__<question_id>) since the disagreement set varies per
        # escalation -- read them off the raw form rather than a fixed Form(...).
        form = await request.form()
        resolved_answers = {
            key[len("resolved__"):]: value == "true"
            for key, value in form.items()
            if key.startswith("resolved__") and value in ("true", "false")
        }
        dispose_escalation(r, item_id, resolution, actor_id, notes, resolved_answers or None)
        return RedirectResponse(f"/admin/projects/{cycle_id}/escalations", status_code=303)

    return router
