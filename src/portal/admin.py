"""Admin surface (spec 005 Section 3.2 / 3.6).

Project (cycle) creation, indicator management, unit (country/city + URL)
assignment, MSQ upload, and the Senior Reviewer's one-click publish.
"""

from __future__ import annotations

import logging
import pathlib
import re
import tempfile
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from api.finalize import final_answer_detail, publication_readiness
from api.identity import compose_question_id
from api.jobs import job_status, start_assessment_job
from api.schemas import ApiError
from portal.assignment import (
    clear_role_assignment,
    create_units,
    set_role_assignment,
    staffing_summary,
)
from portal.common import ensure_session, repo_factory, session_id_for_cycle
from portal.discrepancy import _compare, compute_portal_discrepancy, recompute_portal_discrepancy
from portal.msq import ingest_msq_pdf, match_msq_links
from portal.reconciliation import open_reviewer_round, render_badge, unit_reconciliation_state
from portal.tolerance import effective_tolerance
from review.escalations import dispose_escalation, list_escalation_queue
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.questionnaires.pdf_ingest import extract_candidate_indicators
from shared.questionnaires.registry import (
    delete_questionnaire,
    get_questionnaire_detail,
    list_question_sets,
    load_question_set,
    save_custom_question_set,
)
from shared.reference.countries import list_countries
from shared.state.entities import (
    AnswerType,
    Assessor,
    AssessorRole,
    EvidenceLocus,
    PendingIndicator,
    ProjectType,
    PublicationRecord,
    Question,
    SurveyCycle,
    TargetPortal,
    TERMINAL_UNIT_STATES,
    ToleranceChange,
    UnitAssessorAssignment,
    UnitState,
    UnstaffedReason,
    new_id,
)

_log = logging.getLogger(__name__)


def _blocked_if_work_started(r: Repository, cycle_id: str) -> RedirectResponse | None:
    """Units and questions freeze once assessment has actually begun --
    a mid-assessment unit/question change would silently skew
    recompute_portal_discrepancy() and
    AssessorCompletion.indicator_count_at_declaration, which both assume a
    fixed question set per unit."""
    if r.has_any_human_activity(session_id_for_cycle(cycle_id)):
        return RedirectResponse(f"/admin/projects/{cycle_id}?lock_error=1", status_code=303)
    return None



def _remove_unit(r: Repository, cycle_id: str, portal_id: str) -> None:
    portal = r.get_portal(portal_id)
    r.delete_portal(cycle_id, portal_id)
    cycle = r.get_cycle(cycle_id)
    # Only drop the country from country_set if no other unit in this
    # cycle still targets it (LOSI projects use unit_type="city" but
    # key by country_id, so in principle a country could reappear).
    if cycle and portal and portal.country_id in cycle.country_set:
        remaining = r.list_portals(cycle_id)
        if not any(u.country_id == portal.country_id for u in remaining):
            cycle.country_set.remove(portal.country_id)
            r.insert_cycle(cycle)


def _build_unit_rows(
    r: Repository,
    session_id: str,
    cycle_id: str,
    units: list[TargetPortal],
    questions: list[Question],
    settings: Settings,
    assignments: dict[str, UnitAssessorAssignment] | None = None,
    roster: dict[str, Assessor] | None = None,
) -> list[dict]:
    unit_rows = []
    eff_tol = effective_tolerance(r, cycle_id, settings)
    question_ids = [q.question_id for q in questions]

    for u in units:
        unit_states = r.list_units_for_portal(session_id, u.portal_id)
        states_seen = {row["state"] for row in unit_states}
        terminal = {s.value for s in TERMINAL_UNIT_STATES}
        assessed_count = sum(1 for row in unit_states if row["state"] in terminal)
        st = job_status(r, session_id, cycle_id, u.portal_id, questions_total=len(questions))

        msq = r.find_msq_document(cycle_id, u.country_id)
        publication = r.latest_publication(cycle_id, u.portal_id)

        # Batch load human submissions for this portal (1 SQL query instead of 204)
        submissions = r.list_human_submissions(session_id, u.portal_id)

        # Compute comparison once per portal
        cmp_res = _compare(r, session_id, u.portal_id, question_ids, eff_tol, submissions=submissions)

        case = compute_portal_discrepancy(
            r, session_id, u.portal_id, question_ids,
            eff_tol, submissions=submissions, cmp_res=cmp_res,
        )
        recon_state = unit_reconciliation_state(
            r, session_id, cycle_id, u.portal_id, questions, settings,
            tolerance=eff_tol, submissions=submissions, cmp_res=cmp_res,
        )
        readiness = publication_readiness(
            r, session_id, cycle_id, u.portal_id, questions=questions, submissions=submissions
        )

        disputes_detail = []
        if recon_state.disputed_question_ids:
            subs_by_role_qid = {}
            for sub in submissions:
                subs_by_role_qid[(sub.role, sub.question_id)] = sub
            for qid in recon_state.disputed_question_ids:
                sub_a = subs_by_role_qid.get((AssessorRole.A, qid))
                sub_b = subs_by_role_qid.get((AssessorRole.B, qid))
                joint = r.latest_joint_answer(session_id, u.portal_id, qid)
                disputes_detail.append({
                    "question_id": qid,
                    "answer_a": sub_a.answer if sub_a else None,
                    "answer_b": sub_b.answer if sub_b else None,
                    "joint_answer": joint.answer if joint else None,
                    "joint_justification": joint.justification if joint else None,
                    "joint_committed_by": joint.committed_by_role if joint else None,
                })

        asmt = assignments.get(u.portal_id) if assignments else None
        if asmt is None:
            staffing = {"is_staffed": False, "reason": UnstaffedReason.NO_MAPPING_ENTRY}
        elif asmt.is_staffed:
            staffing = {"is_staffed": True, "reason": None}
        else:
            staffing = {"is_staffed": False, "reason": asmt.ingest_defect or UnstaffedReason.NO_MAPPING_ENTRY}

        assessor_a = roster.get(asmt.role_a.assessor_id) if (asmt and asmt.role_a and roster) else None
        assessor_b = roster.get(asmt.role_b.assessor_id) if (asmt and asmt.role_b and roster) else None

        # Genuinely resolved count vs homepage fallbacks (T019)
        genuinely_resolved_count = 0
        homepage_fallback_count = 0
        for row in unit_states:
            udata = row.get("data") or {}
            if isinstance(udata, str):
                import json
                try:
                    udata = json.loads(udata)
                except Exception:
                    udata = {}
            if udata.get("resolved_via_homepage_fallback"):
                homepage_fallback_count += 1
            elif udata.get("resolved_url"):
                genuinely_resolved_count += 1

        portal_health = {
            "status": "healthy" if (u.resolved_url and u.resolved_url.startswith("http")) else "unset",
            "detail": "Registered portal URL" if u.resolved_url else "No portal URL registered",
        }

        unit_rows.append({
            "portal": u,
            "assessed_count": assessed_count,
            "started_count": len(unit_states),
            "total_questions": len(questions),
            "genuinely_resolved_count": genuinely_resolved_count,
            "homepage_fallback_count": homepage_fallback_count,
            "portal_health": portal_health,
            "run_in_progress": st.state == "running" or bool(states_seen - terminal),
            "job_status": st,
            "prefill_summary": st.summary,
            "msq": msq,
            "publication": publication,
            "discrepancy": case,
            "reconciliation_state": recon_state,
            "badge_html": render_badge(recon_state),
            "readiness": readiness,
            "disputes_detail": disputes_detail,
            "assignment": asmt,
            "staffing": staffing,
            "assessor_a": assessor_a,
            "assessor_b": assessor_b,
        })
    return unit_rows


def build_admin_router(database_path: str, settings: Settings, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    repo = repo_factory(database_path)

    @router.get("/admin", response_class=HTMLResponse)
    def projects_page(request: Request):
        r = repo()
        cycles = r.list_cycles()
        return templates.TemplateResponse(
            request, "admin_projects.html",
            {
                "cycles": cycles,
                "question_sets": list_question_sets(),
                "countries": list_countries(),
            },
        )

    @router.get("/admin/assessors", response_class=HTMLResponse)
    def assessors_page(request: Request):
        r = repo()
        assessors = r.list_assessors()
        return templates.TemplateResponse(
            request, "admin_assessors.html",
            {
                "assessors": assessors,
            },
        )

    @router.get("/admin/questionnaires", response_class=HTMLResponse)
    def questionnaires_page(
        request: Request,
        deleted: str | None = None,
        name: str | None = None,
        error: str | None = None,
    ):
        qsets = list_question_sets()
        templates_count = sum(1 for s in qsets if s.kind == "template")
        custom_count = sum(1 for s in qsets if s.kind == "custom")
        modules_count = sum(1 for s in qsets if s.kind == "module")

        return templates.TemplateResponse(
            request, "admin_questionnaires.html",
            {
                "question_sets": qsets,
                "templates_count": templates_count,
                "custom_count": custom_count,
                "modules_count": modules_count,
                "deleted": deleted,
                "deleted_name": name,
                "error": error,
            },
        )

    @router.get("/admin/questionnaires/{set_id}", response_class=HTMLResponse)
    def questionnaire_detail_page(
        request: Request,
        set_id: str,
        error: str | None = None,
    ):
        detail = get_questionnaire_detail(set_id)
        if detail is None:
            return HTMLResponse("Unknown questionnaire.", status_code=404)

        return templates.TemplateResponse(
            request, "admin_questionnaire_detail.html",
            {
                "questionnaire": detail,
                "error": error,
            },
        )

    @router.post("/admin/questionnaires/{set_id}/delete")
    def delete_questionnaire_endpoint(set_id: str):
        try:
            ok, label = delete_questionnaire(set_id)
            return RedirectResponse(
                f"/admin/questionnaires?deleted=1&name={quote(label)}",
                status_code=303,
            )
        except ValueError as e:
            return RedirectResponse(
                f"/admin/questionnaires?error={quote(str(e))}",
                status_code=303,
            )
        except FileNotFoundError as e:
            return RedirectResponse(
                f"/admin/questionnaires?error={quote(str(e))}",
                status_code=303,
            )

    @router.post("/admin/projects")
    def create_project(
        cycle_id: str = Form(...),
        name: str = Form(...),
        question_set_id: str = Form(...),
        project_type: str = Form("national_osi"),
    ):
        r = repo()
        ptype = ProjectType(project_type)
        # Both National and LOSI projects default to tagging every UN member
        # state at init (LOSI contributing each country's most-populous city
        # as the starting unit) -- admins narrow the unit list down
        # afterward in Manage Workspace (add/remove) rather than
        # hand-picking countries up front.
        target_countries = list_countries()

        question_set = next((s for s in list_question_sets() if s.set_id == question_set_id), None)
        questionnaire_ref = question_set.label if question_set else question_set_id

        r.insert_cycle(
            SurveyCycle(
                cycle_id=cycle_id, name=name, questionnaire_ref=questionnaire_ref,
                country_set=[c.code for c in target_countries], project_type=ptype,
            )
        )
        ensure_session(r, cycle_id)

        questions = load_question_set(question_set_id, cycle_id)
        r.insert_questions(questions)

        # No resolved_url on bulk-tagged units: link resolution searches
        # live per question (see api/jobs.py) rather than depending on a
        # pre-fetched portal URL, and pre-verifying ~193 country URLs here
        # would be an unreliable, slow synchronous step at creation time.
        portals = []
        for c in target_countries:
            if ptype is ProjectType.NATIONAL_OSI:
                display_name = c.name
                unit_type = "country"
            else:
                display_name = f"{c.most_populous_city}, {c.name}"
                unit_type = "city"
            portals.append(
                TargetPortal(
                    portal_id=new_id("portal"), cycle_id=cycle_id, country_id=c.code,
                    resolved_url=None, unit_type=unit_type, display_name=display_name,
                )
            )
        create_units(r, cycle_id, portals)

        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.get("/admin/projects/{cycle_id}", response_class=HTMLResponse)
    def admin_project_detail(
        request: Request,
        cycle_id: str,
        msq_error: str | None = None,
        assess_error: str | None = None,
        tolerance_error: str | None = None,
        edit_error: str | None = None,
        custom_set_saved: str | None = None,
        ingest_error: str | None = None,
        lock_error: str | None = None,
        assign_error: str | None = None,
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)
        questions = r.list_questions(cycle_id, include_retired=True)
        units = r.list_portals(cycle_id)
        pending_indicator_count = len(r.list_pending_indicators(cycle_id))
        session_id = ensure_session(r, cycle_id)
        # Unit progress/discrepancy math must only count live indicators --
        # retired ones stay in the table above (for visibility) but drop out here.
        active_questions = [q for q in questions if q.status != "retired"]
        assignments = r.list_unit_assignments(cycle_id)
        roster = r.load_assessor_index()
        unit_rows = _build_unit_rows(
            r, session_id, cycle_id, units, active_questions, settings,
            assignments=assignments, roster=roster,
        )
        summary = staffing_summary(r, cycle_id)

        eff_tol = effective_tolerance(r, cycle_id, settings)
        eff_pct = int(round(eff_tol * 100)) if abs(eff_tol * 100 - round(eff_tol * 100)) < 1e-4 else round(eff_tol * 100, 1)
        work_started = r.has_any_human_activity(session_id)

        return templates.TemplateResponse(
            request, "admin_project_detail.html",
            {
                "cycle": cycle, "questions": questions,
                "units": unit_rows, "session_id": session_id,
                "work_started": work_started,
                "any_run_in_progress": any(row["run_in_progress"] for row in unit_rows),
                "msq_error": msq_error,
                "assess_error": assess_error,
                "tolerance_error": tolerance_error,
                "edit_error": edit_error,
                "custom_set_saved": custom_set_saved,
                "ingest_error": ingest_error,
                "lock_error": lock_error,
                "assign_error": assign_error,
                "pending_indicator_count": pending_indicator_count,
                "effective_tolerance_pct": eff_pct,
                "tolerance_is_inherited": cycle.discrepancy_rate_threshold is None,
                "countries": list_countries(),
                "staffing_summary": summary,
                "roster": roster,
                "roster_list": list(roster.values()),
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
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
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

        # Branch this project's full indicator set (starting template plus
        # every custom indicator added so far) into a distinct, named,
        # reusable questionnaire -- persisted to data/questionnaires/custom/
        # and tagged with this project's scope so it's offered to future
        # national/local projects in the admin create-project picker,
        # instead of only ever renaming the label in place.
        cycle = r.get_cycle(cycle_id)
        if cycle:
            live_questions = [q for q in r.list_questions(cycle_id) if q.status != "retired"]
            saved_set = save_custom_question_set(cycle, live_questions)
            cycle.questionnaire_ref = saved_set.label
            r.insert_cycle(cycle)  # upsert on cycle_id primary key

        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/questions/save-custom-set")
    def save_custom_indicator_set(cycle_id: str, label: str = Form("")):
        # Explicit counterpart to the auto-save inside add_question() above --
        # this is the path for an admin who only retired/reactivated/edited
        # indicators (no new custom question added) but still wants the
        # resulting set persisted as a named, reusable questionnaire.
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return RedirectResponse("/admin", status_code=303)
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        live_questions = [q for q in r.list_questions(cycle_id) if q.status != "retired"]
        saved_set = save_custom_question_set(cycle, live_questions, label=label.strip() or None)
        cycle.questionnaire_ref = saved_set.label
        r.insert_cycle(cycle)  # upsert on cycle_id primary key
        return RedirectResponse(f"/admin/projects/{cycle_id}?custom_set_saved=1", status_code=303)

    @router.post("/admin/projects/{cycle_id}/indicators/upload")
    async def upload_indicator_pdf(
        cycle_id: str,
        pdf_file: UploadFile,
        module: str = Form(...),
        prefix: str = Form(""),
        evidence_locus: str = Form("national_portal_only"),
    ):
        # Generalizes the same What/Why/How slide layout the original UN
        # OSI/LOSI questionnaires were manually extracted from (see
        # src/data/extract_modules.py) to any admin-uploaded PDF of that
        # format -- but nothing here is trusted directly: every parsed
        # candidate lands in the review queue below, never straight into
        # the live questionnaire.
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return RedirectResponse("/admin", status_code=303)
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp

        contents = await pdf_file.read()
        derived_prefix = re.sub(r"[^A-Za-z0-9]", "", prefix or module)[:8].upper() or "CUSTOM"

        try:
            candidates = extract_candidate_indicators(contents, module, derived_prefix, evidence_locus)
        except ValueError:
            return RedirectResponse(f"/admin/projects/{cycle_id}?ingest_error=unreadable", status_code=303)

        if not candidates:
            return RedirectResponse(f"/admin/projects/{cycle_id}?ingest_error=no_indicators_found", status_code=303)

        pending = [
            PendingIndicator(
                pending_id=new_id("pending"),
                cycle_id=cycle_id,
                module=c["module"],
                title=c["title"],
                what=c["what"],
                why=c["why"],
                how={
                    "evidence_locus": c["evidence_locus"],
                    "scoring_guidance": c["how_scoring_guidance"],
                    "criteria_for_yes": "Evidence found on the designated government portal satisfying the What specification.",
                    "criteria_for_no": "No evidence found or feature unreachable within reasonable navigation.",
                },
                indicator_id=c["indicator_id"],
                benchmark_case=c["benchmark_case"] or None,
                reference_links=c["reference_links"],
                evidence_locus=EvidenceLocus(c["evidence_locus"]),
                source_pdf_filename=pdf_file.filename or "upload.pdf",
                source_page=c["source_page"],
            )
            for c in candidates
        ]
        r.insert_pending_indicators(pending)
        return RedirectResponse(f"/admin/projects/{cycle_id}/indicators/review", status_code=303)

    @router.get("/admin/projects/{cycle_id}/indicators/review", response_class=HTMLResponse)
    def review_pending_indicators(request: Request, cycle_id: str):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)
        pending = r.list_pending_indicators(cycle_id)
        return templates.TemplateResponse(
            request, "admin_indicator_review.html",
            {"cycle": cycle, "pending": pending},
        )

    @router.post("/admin/projects/{cycle_id}/indicators/review/{pending_id}/approve")
    def approve_pending_indicator(
        cycle_id: str,
        pending_id: str,
        indicator_id: str = Form(...),
        title: str = Form(...),
        what: str = Form(...),
        why: str = Form(...),
        how: str = Form(...),
        module: str = Form("Custom Indicators"),
        evidence_locus: str = Form("national_portal_only"),
        benchmark_case: str = Form(""),
    ):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        pending = r.get_pending_indicator(pending_id)
        if pending is None or pending.cycle_id != cycle_id:
            return RedirectResponse(f"/admin/projects/{cycle_id}/indicators/review", status_code=303)

        text = f"{title} — {what}"
        how_data = {
            "evidence_locus": evidence_locus,
            "scoring_guidance": how,
            "criteria_for_yes": "Evidence found on the designated government portal satisfying the What specification.",
            "criteria_for_no": "No evidence found or feature unreachable within reasonable navigation.",
        }
        r.insert_question(
            Question(
                question_id=compose_question_id(cycle_id, indicator_id),
                cycle_id=cycle_id,
                text=text,
                answer_type=AnswerType.BINARY,
                evidence_locus=EvidenceLocus(evidence_locus),
                is_custom=True,
                indicator_id=indicator_id,
                question_class=module,
                title=title,
                what=what,
                why=why,
                how=how_data,
                benchmark_case=benchmark_case or None,
                reference_links=pending.reference_links,
            )
        )
        r.delete_pending_indicator(pending_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}/indicators/review", status_code=303)

    @router.post("/admin/projects/{cycle_id}/indicators/review/{pending_id}/reject")
    def reject_pending_indicator(cycle_id: str, pending_id: str):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        pending = r.get_pending_indicator(pending_id)
        if pending is not None and pending.cycle_id == cycle_id:
            r.delete_pending_indicator(pending_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}/indicators/review", status_code=303)

    @router.post("/admin/projects/{cycle_id}/indicators/review/bulk-reject")
    def bulk_reject_pending_indicators(cycle_id: str):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        r.delete_pending_indicators_for_cycle(cycle_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}/indicators/review", status_code=303)

    @router.post("/admin/projects/{cycle_id}/questions/{question_id}/retire")
    def retire_question(
        cycle_id: str, question_id: str, actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        r.set_question_status(question_id, "retired", revised_by=actor_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/questions/{question_id}/reactivate")
    def reactivate_question(
        cycle_id: str, question_id: str, actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        r.set_question_status(question_id, "active", revised_by=actor_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/questions/bulk-retire")
    async def bulk_retire_questions(request: Request, cycle_id: str):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        form = await request.form()
        actor_id = form.get("actor_id") or "senior-reviewer"
        for question_id in form.getlist("question_ids"):
            r.set_question_status(question_id, "retired", revised_by=actor_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/questions/bulk-reactivate")
    async def bulk_reactivate_questions(request: Request, cycle_id: str):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        form = await request.form()
        actor_id = form.get("actor_id") or "senior-reviewer"
        for question_id in form.getlist("question_ids"):
            r.set_question_status(question_id, "active", revised_by=actor_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/questions/{question_id}/edit")
    def edit_question(
        cycle_id: str,
        question_id: str,
        title: str = Form(...),
        what: str = Form(...),
        why: str = Form(...),
        how: str = Form(...),
        module: str = Form("Custom Indicators"),
        evidence_locus: str = Form("national_portal_only"),
        benchmark_case: str = Form(""),
        actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        existing = r.get_question(question_id)
        if existing is None or not existing.is_custom:
            # Default/master indicators are immutable content -- only custom
            # ones support in-place edits (retire/reactivate works on both).
            return RedirectResponse(f"/admin/projects/{cycle_id}?edit_error=not_editable", status_code=303)
        existing.text = f"{title} — {what}"
        existing.evidence_locus = EvidenceLocus(evidence_locus)
        existing.question_class = module
        existing.title = title
        existing.what = what
        existing.why = why
        how_data = existing.how if isinstance(existing.how, dict) else {}
        how_data = {**how_data, "evidence_locus": evidence_locus, "scoring_guidance": how}
        existing.how = how_data
        existing.benchmark_case = benchmark_case or None
        r.update_question(existing, revised_by=actor_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/delete")
    def delete_project(cycle_id: str):
        r = repo()
        r.delete_cycle(cycle_id)
        return RedirectResponse("/admin", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units")
    def add_unit(
        cycle_id: str, country_id: str = Form(...), display_name: str = Form(...),
        url: str = Form(""), unit_type: str = Form("country"),
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        clean_url = url.strip() if url else None
        derived_unit_type = "city" if (cycle and cycle.project_type == ProjectType.LOSI_CITY) else "country"
        portal = TargetPortal(
            portal_id=new_id("portal"), cycle_id=cycle_id, country_id=country_id,
            resolved_url=clean_url or None, unit_type=derived_unit_type, display_name=display_name,
        )
        create_units(r, cycle_id, [portal])
        if cycle and country_id not in cycle.country_set:
            cycle.country_set.append(country_id)
            r.insert_cycle(cycle)  # upsert on cycle_id primary key
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/remove")
    def remove_unit(cycle_id: str, portal_id: str):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        _remove_unit(r, cycle_id, portal_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/bulk-remove")
    async def bulk_remove_units(request: Request, cycle_id: str):
        r = repo()
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        form = await request.form()
        for portal_id in form.getlist("portal_ids"):
            _remove_unit(r, cycle_id, portal_id)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/bulk-add")
    async def bulk_add_units(request: Request, cycle_id: str):
        r = repo()
        form = await request.form()
        country_codes = form.getlist("country_codes")
        cycle = r.get_cycle(cycle_id)
        if (resp := _blocked_if_work_started(r, cycle_id)) is not None:
            return resp
        if cycle and country_codes:
            derived_unit_type = "city" if cycle.project_type == ProjectType.LOSI_CITY else "country"
            countries_by_code = {c.code: c for c in list_countries()}
            portals = []
            for code in country_codes:
                c = countries_by_code.get(code)
                if c is None:
                    continue
                if derived_unit_type == "city":
                    display_name = f"{c.most_populous_city}, {c.name}"
                else:
                    display_name = c.name
                portals.append(
                    TargetPortal(
                        portal_id=new_id("portal"), cycle_id=cycle_id, country_id=c.code,
                        resolved_url=None, unit_type=derived_unit_type, display_name=display_name,
                    )
                )
                if c.code not in cycle.country_set:
                    cycle.country_set.append(c.code)
            if portals:
                create_units(r, cycle_id, portals)
                r.insert_cycle(cycle)
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/assessors")
    def override_unit_assessor(
        cycle_id: str,
        portal_id: str,
        role: str = Form(...),
        assessor_id: str = Form(""),
        actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)
        portal = r.get_portal(portal_id)
        if portal is None or portal.cycle_id != cycle_id:
            return HTMLResponse("Unknown unit.", status_code=404)

        clean_assessor_id = assessor_id.strip()
        try:
            if not clean_assessor_id:
                clear_role_assignment(r, cycle_id, portal_id, role, actor_id)
            else:
                set_role_assignment(r, cycle_id, portal_id, role, clean_assessor_id, actor_id)
        except ValueError as exc:
            err_type = str(exc)
            if err_type in ("duplicate", "unknown"):
                return RedirectResponse(
                    f"/admin/projects/{cycle_id}?assign_error={err_type}",
                    status_code=303,
                )
            return RedirectResponse(
                f"/admin/projects/{cycle_id}?assign_error=unknown",
                status_code=303,
            )

        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/assess")
    async def run_assessment(request: Request, cycle_id: str, portal_id: str):
        r = repo()
        runtime = getattr(request.app.state, "ai_runtime", None)
        assess_error = None
        if runtime is None:
            assess_error = "AI runtime is not configured on this server."
        else:
            try:
                start_assessment_job(
                    r,
                    settings,
                    runtime,
                    cycle_id=cycle_id,
                    portal_id=portal_id,
                    triggered_by="portal",
                    actor_id="admin",
                )
            except ApiError as exc:
                assess_error = exc.message
            except Exception as exc:
                _log.exception("Assessment job dispatch failed: %s", exc)
                assess_error = "Could not schedule assessment job. See server logs for details."
        suffix = f"?assess_error={quote(assess_error)}" if assess_error else ""
        return RedirectResponse(f"/admin/projects/{cycle_id}{suffix}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/msq")
    async def upload_msq_pdf(
        request: Request, cycle_id: str, portal_id: str, msq_file: UploadFile = ...
    ):
        r = repo()
        portal = r.get_portal(portal_id)
        if portal is None or not portal.country_id:
            return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

        msq_error = None
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            contents = await msq_file.read()
            tmp.write(contents)

        # tmp must be closed before ingest_msq_pdf reopens it and before
        # unlinking -- on Windows a still-open handle cannot be deleted or
        # reliably reread by a second file object.
        try:
            doc = ingest_msq_pdf(tmp_path, cycle_id, portal.country_id, msq_file.filename or "msq.pdf")
            if not doc.raw_text or not doc.raw_text.strip():
                msq_error = "msq_unreadable"
            else:
                r.insert_msq_document(doc)
                runtime = getattr(request.app.state, "ai_runtime", None)
                if runtime and getattr(runtime, "provider", None):
                    try:
                        questions = r.list_questions(cycle_id)
                        candidates = await match_msq_links(
                            doc, questions, runtime.provider, settings.validator_model
                        )
                        for candidate in candidates:
                            r.insert_msq_link_candidate(candidate)
                    except Exception:
                        _log.warning(
                            "MSQ link matching failed for cycle=%s country=%s; document stored, "
                            "no per-question candidates extracted", cycle_id, portal.country_id,
                        )
        except Exception:
            _log.exception(
                "MSQ ingestion failed for cycle=%s country=%s file=%s",
                cycle_id, portal.country_id, msq_file.filename,
            )
            msq_error = "msq_error"
        finally:
            pathlib.Path(tmp_path).unlink(missing_ok=True)
        suffix = f"?msq_error={msq_error}" if msq_error else ""
        return RedirectResponse(f"/admin/projects/{cycle_id}{suffix}", status_code=303)

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
            questions = r.list_questions(cycle_id, include_retired=True)
            active_questions = [q for q in questions if q.status != "retired"]
            units = r.list_portals(cycle_id)
            unit_rows = _build_unit_rows(r, session_id, cycle_id, units, active_questions, settings)
            eff_tol = effective_tolerance(r, cycle_id, settings)
            eff_pct = int(round(eff_tol * 100)) if abs(eff_tol * 100 - round(eff_tol * 100)) < 1e-4 else round(eff_tol * 100, 1)
            return templates.TemplateResponse(
                request, "admin_project_detail.html",
                {
                    "cycle": cycle,
                    "questions": questions,
                    "units": unit_rows,
                    "session_id": session_id,
                    "error_message": readiness.blocking_reason,
                    "effective_tolerance_pct": eff_pct,
                    "tolerance_is_inherited": cycle.discrepancy_rate_threshold is None,
                },
                status_code=400,
            )
        questions = r.list_questions(cycle_id)
        breakdown: dict[str, bool] = {}
        contested_ids: list[str] = []
        for q in questions:
            final, source = final_answer_detail(r, session_id, q.question_id, portal_id)
            if final is not None:
                breakdown[q.question_id] = bool(final)
            if source == "contested_a_wins":
                contested_ids.append(q.question_id)

        affirmative = sum(1 for v in breakdown.values() if v)
        score = (affirmative / len(breakdown)) if breakdown else 0.0
        r.insert_publication(
            PublicationRecord(
                publication_id=new_id("pub"),
                cycle_id=cycle_id,
                portal_id=portal_id,
                published_by_actor_id=actor_id,
                score=score,
                score_breakdown=breakdown,
                contested_question_ids=contested_ids,
            )
        )
        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/tolerance")
    def update_project_tolerance(
        request: Request,
        cycle_id: str,
        tolerance: str = Form(...),
        actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)

        try:
            val = float(tolerance)
            if val < 0.0 or val > 100.0:
                raise ValueError("Tolerance must be between 0 and 100 inclusive.")
        except (ValueError, TypeError):
            return RedirectResponse(f"/admin/projects/{cycle_id}?tolerance_error=invalid_range", status_code=303)

        new_ratio = val / 100.0
        prev_ratio = cycle.discrepancy_rate_threshold
        cycle.discrepancy_rate_threshold = new_ratio
        r.insert_cycle(cycle)

        r.insert_tolerance_change(
            ToleranceChange(
                change_id=new_id("tol"),
                cycle_id=cycle_id,
                previous_value=prev_ratio,
                new_value=new_ratio,
                changed_by_actor_id=actor_id.strip() or "senior-reviewer",
                changed_at=datetime.now(UTC),
            )
        )

        # On tolerance change: close any open round whose unit now falls within the new tolerance as 'not_required' (FR-DR-037)
        from portal.discrepancy import _compare, recompute_portal_discrepancy
        from shared.state.entities import EscalationReason

        session_id = ensure_session(r, cycle_id)
        questions = r.list_questions(cycle_id)
        q_ids = [q.question_id for q in questions]
        units = r.list_portals(cycle_id)
        for u in units:
            open_rnd = r.open_round_for_unit(session_id, u.portal_id)
            if open_rnd is not None:
                cmp_res = _compare(r, session_id, u.portal_id, q_ids, new_ratio)
                if cmp_res is not None:
                    rate = cmp_res[2]
                    if rate <= new_ratio:
                        now = datetime.now(UTC)
                        r.close_round(open_rnd.round_id, "not_required", now)
                        for item in r.list_escalations(session_id, unresolved_only=True):
                            if item.portal_id == u.portal_id and item.reason == EscalationReason.PORTAL_DISCREPANCY:
                                if item.context.get("round_id") == open_rnd.round_id or not item.context.get("round_id"):
                                    r.record_disposition(
                                        item.item_id,
                                        {
                                            "resolution": "tolerance_adjusted_within_threshold",
                                            "resolved_by_actor_id": actor_id,
                                            "notes": f"Tolerance changed to {val}%; round no longer required.",
                                        },
                                    )
                        recompute_portal_discrepancy(r, session_id, u.portal_id, q_ids, new_ratio, cycle_id=cycle_id)

        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.get("/admin/projects/{cycle_id}/escalations", response_class=HTMLResponse)
    def escalations_page(request: Request, cycle_id: str, error: str | None = None):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)
        session_id = ensure_session(r, cycle_id)
        views = list_escalation_queue(r, session_id)
        questions_by_id = {q.question_id: q for q in r.list_questions(cycle_id, include_retired=True)}

        disputed_details_by_item: dict[str, list[dict]] = {}
        for v in views:
            qids = v.item.context.get("disagreements") or []
            if not qids:
                continue
            submissions = r.list_human_submissions(session_id, v.item.portal_id)
            subs_by_role_qid = {(sub.role, sub.question_id): sub for sub in submissions}
            details = []
            for qid in qids:
                q = questions_by_id.get(qid)
                sub_a = subs_by_role_qid.get((AssessorRole.A, qid))
                sub_b = subs_by_role_qid.get((AssessorRole.B, qid))
                details.append({
                    "question_id": qid,
                    "question": q,
                    "sub_a": sub_a,
                    "sub_b": sub_b,
                })
            disputed_details_by_item[v.item.item_id] = details

        return templates.TemplateResponse(
            request, "admin_escalations.html",
            {
                "cycle": cycle, "views": views, "session_id": session_id, "error": error,
                "questions_by_id": questions_by_id,
                "disputed_details_by_item": disputed_details_by_item,
            },
        )

    @router.post("/admin/projects/{cycle_id}/escalations/{item_id}/dispose")
    async def dispose(
        request: Request, cycle_id: str, item_id: str, resolution: str = Form(...),
        notes: str = Form(""), actor_id: str = Form("senior-reviewer"),
    ):
        r = repo()
        session_id = ensure_session(r, cycle_id)
        form = await request.form()
        resolved_answers = {
            key[len("resolved__"):]: value == "true"
            for key, value in form.items()
            if key.startswith("resolved__") and value in ("true", "false")
        }

        items = r.list_escalations(session_id)
        matching_item = next((it for it in items if it.item_id == item_id), None)
        if not matching_item:
            return RedirectResponse(
                f"/admin/projects/{cycle_id}/escalations?error={quote('Escalation item not found.')}",
                status_code=303,
            )

        if resolution == "returned_for_reconciliation":
            if not notes or not notes.strip():
                error_msg = "A stated reason is required to return a unit for reconciliation."
                return RedirectResponse(
                    f"/admin/projects/{cycle_id}/escalations?error={quote(error_msg)}",
                    status_code=303,
                )
            try:
                open_reviewer_round(
                    r, session_id, cycle_id, matching_item.portal_id, actor_id, notes, settings
                )
            except ValueError as e:
                return RedirectResponse(
                    f"/admin/projects/{cycle_id}/escalations?error={quote(str(e))}",
                    status_code=303,
                )
        elif resolution == "senior_reviewer_decision":
            disputed_qids = matching_item.context.get("disagreements") or []
            missing = [qid for qid in disputed_qids if qid not in resolved_answers]
            if missing:
                error_msg = "Select Yes or No for every disputed indicator before recording a decision."
                return RedirectResponse(
                    f"/admin/projects/{cycle_id}/escalations?error={quote(error_msg)}",
                    status_code=303,
                )
        else:
            return RedirectResponse(
                f"/admin/projects/{cycle_id}/escalations?error={quote('Unknown resolution method.')}",
                status_code=303,
            )

        ok = dispose_escalation(r, item_id, resolution, actor_id, notes, resolved_answers or None)
        if not ok:
            error_msg = "Escalation has already been decided by another reviewer."
            return RedirectResponse(
                f"/admin/projects/{cycle_id}/escalations?error={quote(error_msg)}",
                status_code=303,
            )

        if resolution == "senior_reviewer_decision":
            # A Senior Reviewer decision settles the disputed indicators by
            # fiat, so it must also close the round that raised them --
            # otherwise the round stays "open" forever (only an assessor
            # committing joint answers ever closes one) and publish stays
            # blocked with "reconciliation round is currently open" even
            # though the disagreement has in fact been resolved.
            open_round = r.open_round_for_unit(session_id, matching_item.portal_id)
            if open_round is not None:
                r.close_round(open_round.round_id, "resolved", datetime.now(UTC))
                questions = r.list_questions(cycle_id)
                q_ids = [q.question_id for q in questions]
                tolerance = effective_tolerance(r, cycle_id, settings)
                recompute_portal_discrepancy(
                    r, session_id, matching_item.portal_id, q_ids, tolerance, cycle_id=cycle_id
                )

        return RedirectResponse(f"/admin/projects/{cycle_id}/escalations", status_code=303)

    return router
