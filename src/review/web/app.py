"""Review web surface (FR-042, FR-043, FR-119, FR-120).

Server-rendered HTML — no separate JS build, so keyboard and screen-reader
behaviour comes from real HTML semantics (<form>, <details>, <label>)
rather than reimplemented widgets. Confidence is always shown as a 0-100
percentage; there is no named tier anywhere in this surface (FR-042).
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from review import actions
from review.api import build_router
from review.query import build_question_review
from review.unlock import portal_review_status
from review.web.detail import render_agent_detail_html, render_attempt_history_html
from review.web.evidence import render_evidence_html

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def build_app(database_path: str, settings: Settings) -> FastAPI:
    app = FastAPI(title="EKAP AIQ Review")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    def get_conn() -> sqlite3.Connection:
        conn = sqlite3.connect(database_path)
        conn.row_factory = sqlite3.Row
        return conn

    app.include_router(build_router(get_conn, lambda: settings))

    def repo() -> Repository:
        return Repository(get_conn())

    @app.get("/", response_class=HTMLResponse)
    def portals_page(request: Request, session: str):
        r = repo()
        session_obj = r.get_session(session)
        cycle_id = session_obj.cycle_id if session_obj else None
        portal_rows = r.list_portals(cycle_id) if cycle_id else []
        questions = r.list_questions(cycle_id) if cycle_id else []
        qids = [q.question_id for q in questions]

        portals = []
        for p in portal_rows:
            status = portal_review_status(r, session, p.portal_id, qids)
            portals.append({**asdict(p), **asdict(status)})

        return templates.TemplateResponse(
            "portals.html", {"request": request, "session_id": session, "portals": portals}
        )

    @app.get("/portal/{portal_id}", response_class=HTMLResponse)
    def questions_page(request: Request, portal_id: str, session: str):
        r = repo()
        portal = r.get_portal(portal_id)
        questions = r.list_questions(portal.cycle_id) if portal else []
        qids = [q.question_id for q in questions]
        status = portal_review_status(r, session, portal_id, qids)

        return templates.TemplateResponse(
            "questions.html",
            {
                "request": request,
                "session_id": session,
                "portal": portal,
                "questions": questions,
                "status": status,
            },
        )

    @app.get("/portal/{portal_id}/question/{question_id}", response_class=HTMLResponse)
    def question_page(request: Request, portal_id: str, question_id: str, session: str):
        r = repo()
        view = build_question_review(
            r, session, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        evidence_html = render_evidence_html(view.evidence, view.evidence_missing)
        detail_html = render_agent_detail_html(view.agent_positions, view.discrepancy_flagged)
        attempt_history_html = (
            render_attempt_history_html(view.attempt_history) if view.escalated else ""
        )
        return templates.TemplateResponse(
            "question.html",
            {
                "request": request,
                "session_id": session,
                "view": view,
                "evidence_html": evidence_html,
                "detail_html": detail_html,
                "attempt_history_html": attempt_history_html,
            },
        )

    @app.post("/portal/{portal_id}/question/{question_id}/approve")
    def do_approve(portal_id: str, question_id: str, session: str, actor_id: str = Form(...)):
        r = repo()
        view = build_question_review(
            r, session, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        actions.approve(r, session, question_id, portal_id, view.system_proposed_answer, actor_id)
        return RedirectResponse(
            f"/portal/{portal_id}/question/{question_id}?session={session}", status_code=303
        )

    @app.post("/portal/{portal_id}/question/{question_id}/edit")
    def do_edit(
        portal_id: str,
        question_id: str,
        session: str,
        actor_id: str = Form(...),
        edited_answer: str = Form(...),
    ):
        r = repo()
        view = build_question_review(
            r, session, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        actions.edit(r, session, question_id, portal_id, view.system_proposed_answer, edited_answer, actor_id)
        return RedirectResponse(
            f"/portal/{portal_id}/question/{question_id}?session={session}", status_code=303
        )

    @app.post("/portal/{portal_id}/question/{question_id}/reject")
    def do_reject(
        portal_id: str,
        question_id: str,
        session: str,
        actor_id: str = Form(...),
        override_answer: str = Form(...),
        rejection_reason: str = Form(...),
    ):
        r = repo()
        view = build_question_review(
            r, session, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        actions.reject_and_override(
            r, session, question_id, portal_id,
            view.system_proposed_answer, override_answer, rejection_reason, actor_id,
        )
        return RedirectResponse(
            f"/portal/{portal_id}/question/{question_id}?session={session}", status_code=303
        )

    return app
