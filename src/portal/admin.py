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

from datetime import datetime, timezone
import logging
import pathlib
import tempfile
from urllib.parse import quote

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from api.finalize import final_answer, final_answer_detail, publication_readiness
from api.identity import compose_question_id
from api.jobs import job_status, start_assessment_job
from api.schemas import ApiError
from portal.common import ensure_session, repo_factory
from portal.discrepancy import _compare, compute_portal_discrepancy
from portal.reconciliation import open_reviewer_round, render_badge, unit_reconciliation_state
from portal.tolerance import effective_tolerance
from portal.msq import ingest_msq_pdf, match_msq_links
from review.escalations import dispose_escalation, list_escalation_queue
from shared.config.settings import Settings
from shared.questionnaires.registry import list_question_sets, load_question_set
from shared.reference.countries import list_countries
from shared.state.entities import (
    AnswerType,
    AssessorRole,
    EvidenceLocus,
    ProjectType,
    PublicationRecord,
    Question,
    SurveyCycle,
    TargetPortal,
    TERMINAL_UNIT_STATES,
    ToleranceChange,
    UnitState,
    new_id,
)

_log = logging.getLogger(__name__)


def _build_unit_rows(
    r: Repository,
    session_id: str,
    cycle_id: str,
    units: list[TargetPortal],
    questions: list[Question],
    settings: Settings,
) -> list[dict]:
    from portal.reconciliation import render_badge, unit_reconciliation_state

    unit_rows = []
    eff_tol = effective_tolerance(r, cycle_id, settings)
    question_ids = [q.question_id for q in questions]
    q_count = len(questions)
    terminal = {s.value for s in TERMINAL_UNIT_STATES}

    for u in units:
        unit_states = r.list_units_for_portal(session_id, u.portal_id)
        states_seen = {row["state"] for row in unit_states}
        assessed_count = sum(1 for row in unit_states if row["state"] in terminal)
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
        st = job_status(r, session_id, cycle_id, u.portal_id, questions_total=q_count)
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

        unit_rows.append({
            "portal": u,
            "assessed_count": assessed_count,
            "started_count": len(unit_states),
            "total_questions": q_count,
            "run_in_progress": st.state == "running" or bool(states_seen - terminal),
            "msq": msq,
            "publication": publication,
            "discrepancy": case,
            "reconciliation_state": recon_state,
            "badge_html": render_badge(recon_state),
            "readiness": readiness,
            "job_status": st,
            "prefill_summary": st.summary,
            "disputes_detail": disputes_detail,
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

    @router.post("/admin/projects")
    def create_project(
        cycle_id: str = Form(...),
        name: str = Form(...),
        question_set_id: str = Form(...),
        project_type: str = Form("national_osi"),
        country_ids: list[str] = Form([]),
    ):
        r = repo()
        ptype = ProjectType(project_type)
        all_countries = list_countries()

        # NOSI auto-tags every UN member state; LOSI targets only the
        # countries picked in the multi-select (each contributing its
        # most-populous city as the initial unit -- more cities can be added
        # afterward via the existing add-unit form).
        if ptype is ProjectType.NATIONAL_OSI:
            target_countries = all_countries
        else:
            selected = set(country_ids)
            target_countries = [c for c in all_countries if c.code in selected]

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
        r.insert_portals(portals)

        return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

    @router.get("/admin/projects/{cycle_id}", response_class=HTMLResponse)
    def project_detail(
        request: Request,
        cycle_id: str,
        msq_error: str | None = None,
        assess_error: str | None = None,
        tolerance_error: str | None = None,
    ):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        if cycle is None:
            return HTMLResponse("Unknown project.", status_code=404)
        questions = r.list_questions(cycle_id)
        units = r.list_portals(cycle_id)
        session_id = ensure_session(r, cycle_id)
        unit_rows = _build_unit_rows(r, session_id, cycle_id, units, questions, settings)

        eff_tol = effective_tolerance(r, cycle_id, settings)
        eff_pct = int(round(eff_tol * 100)) if abs(eff_tol * 100 - round(eff_tol * 100)) < 1e-4 else round(eff_tol * 100, 1)

        return templates.TemplateResponse(
            request, "admin_project_detail.html",
            {
                "cycle": cycle, "questions": questions,
                "units": unit_rows, "session_id": session_id,
                "any_run_in_progress": any(row["run_in_progress"] for row in unit_rows),
                "msq_error": msq_error,
                "assess_error": assess_error,
                "tolerance_error": tolerance_error,
                "effective_tolerance_pct": eff_pct,
                "tolerance_is_inherited": cycle.discrepancy_rate_threshold is None,
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
            r.insert_cycle(cycle)  # upsert on cycle_id primary key

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
            r.insert_cycle(cycle)  # upsert on cycle_id primary key
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
                # Surface the precondition (e.g. "unit has no URL", "cycle
                # has no indicators") on the redirected page instead of
                # 500-ing or dumping JSON at the admin user.
                assess_error = exc.message
            except Exception as exc:
                _log.exception("Assessment job dispatch failed: %s", exc)
                assess_error = "Could not schedule assessment job. See server logs for details."
        suffix = f"?assess_error={quote(assess_error)}" if assess_error else ""
        return RedirectResponse(f"/admin/projects/{cycle_id}{suffix}", status_code=303)

    @router.post("/admin/projects/{cycle_id}/units/{portal_id}/msq")
    async def upload_msq_pdf(
        cycle_id: str, portal_id: str, msq_file: UploadFile = ...
    ):
        r = repo()
        portal = r.get_portal(portal_id)
        if portal is None or not portal.country_id:
            return RedirectResponse(f"/admin/projects/{cycle_id}", status_code=303)

        msq_error = None
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
            try:
                contents = await msq_file.read()
                tmp.write(contents)
                tmp.flush()

                text, page_count = ingest_msq_pdf(tmp_path)
                if not text or not text.strip():
                    msq_error = "msq_unreadable"
                else:
                    r.insert_msq_document(cycle_id, portal.country_id, text, page_count)
                    try:
                        questions = r.list_questions(cycle_id)
                        extracted = match_msq_links(text, questions)
                        for q_id, url in extracted.items():
                            r.insert_prefill_candidate(cycle_id, portal.country_id, q_id, url, "msq_match")
                    except Exception:
                        _log.warning(
                            "MSQ link matching failed for cycle=%s country=%s; document stored, "
                            "no per-question candidates extracted", cycle_id, portal.country_id,
                        )
            except Exception:
                _log.exception(
                    "MSQ ingestion failed for cycle=%s country=%s file=%s; "
                    "resolution will fall through to search", cycle_id, portal.country_id, msq_file.filename,
                )
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
            questions = r.list_questions(cycle_id)
            units = r.list_portals(cycle_id)
            unit_rows = _build_unit_rows(r, session_id, cycle_id, units, questions, settings)
            eff_tol = effective_tolerance(r, cycle_id, settings)
            eff_pct = int(round(eff_tol * 100)) if abs(eff_tol * 100 - round(eff_tol * 100)) < 1e-4 else round(eff_tol * 100, 1)
            return templates.TemplateResponse(
                request, "admin_project_detail.html",
                {
                    "cycle": cycle,
                    "questions": questions,
                    "units": unit_rows,
                    "session_id": session_id,
                    "any_run_in_progress": any(row["run_in_progress"] for row in unit_rows),
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
                changed_at=datetime.now(timezone.utc),
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
                        now = datetime.now(timezone.utc)
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
        return templates.TemplateResponse(
            request, "admin_escalations.html",
            {"cycle": cycle, "views": views, "session_id": session_id, "error": error},
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

        if resolution == "returned_for_reconciliation":
            if not notes or not notes.strip():
                error_msg = "A stated reason is required to return a unit for reconciliation."
                return RedirectResponse(
                    f"/admin/projects/{cycle_id}/escalations?error={quote(error_msg)}",
                    status_code=303,
                )
            items = r.list_escalations(session_id)
            matching_item = next((it for it in items if it.item_id == item_id), None)
            if not matching_item:
                return RedirectResponse(
                    f"/admin/projects/{cycle_id}/escalations?error={quote('Escalation item not found.')}",
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

        ok = dispose_escalation(r, item_id, resolution, actor_id, notes, resolved_answers or None)
        if not ok:
            error_msg = "Escalation has already been decided by another reviewer."
            return RedirectResponse(
                f"/admin/projects/{cycle_id}/escalations?error={quote(error_msg)}",
                status_code=303,
            )

        return RedirectResponse(f"/admin/projects/{cycle_id}/escalations", status_code=303)

    return router
