"""Review API (FR-043).

JSON endpoints returning, for each question awaiting review: the proposed
answer, justification, numeric confidence as a percentage, resolved URL,
supplying source, and the complete evidence set -- everything a reviewer
needs without navigating to an external tool (FR-023).

Request-body models are deliberately defined at module scope, not nested
inside build_router(). FastAPI resolves parameter annotations via
typing.get_type_hints() against the function's __globals__; a class name
that only exists as a local variable inside an enclosing function is
invisible to that resolution once this module uses
`from __future__ import annotations` (which turns every annotation into a
string evaluated lazily). Nesting them silently made FastAPI treat each
body model as an unrecognized query parameter instead of a request body --
caught by exercising every action against the running server.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from review import actions
from review.query import build_question_review
from review.unlock import portal_review_status
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


class ApproveBody(BaseModel):
    actor_id: str


class EditBody(BaseModel):
    actor_id: str
    edited_answer: Any


class RejectBody(BaseModel):
    actor_id: str
    override_answer: Any
    rejection_reason: str


def build_router(get_conn, get_settings) -> APIRouter:
    router = APIRouter(prefix="/api")

    def repo_dep() -> Repository:
        conn: sqlite3.Connection = get_conn()
        return Repository(conn)

    def settings_dep() -> Settings:
        return get_settings()

    @router.get("/sessions/{session_id}/portals/{portal_id}/status")
    def portal_status(session_id: str, portal_id: str, repo: Repository = Depends(repo_dep)):
        questions = repo.list_questions(_cycle_id_for_portal(repo, portal_id))
        status = portal_review_status(repo, session_id, portal_id, [q.question_id for q in questions])
        return asdict(status)

    @router.get("/sessions/{session_id}/portals/{portal_id}/questions/{question_id}")
    def question_review(
        session_id: str,
        portal_id: str,
        question_id: str,
        repo: Repository = Depends(repo_dep),
        settings: Settings = Depends(settings_dep),
    ):
        view = build_question_review(
            repo, session_id, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        if not view:
            raise HTTPException(404, "question not found")
        return _serialize_view(view)

    @router.post("/sessions/{session_id}/portals/{portal_id}/questions/{question_id}/approve")
    def approve(
        session_id: str,
        portal_id: str,
        question_id: str,
        body: ApproveBody,
        repo: Repository = Depends(repo_dep),
        settings: Settings = Depends(settings_dep),
    ):
        view = build_question_review(
            repo, session_id, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        if not view:
            raise HTTPException(404, "question not found")
        decision = actions.approve(
            repo, session_id, question_id, portal_id, view.system_proposed_answer, body.actor_id
        )
        return {"decision_id": decision.decision_id, "action": "approve"}

    @router.post("/sessions/{session_id}/portals/{portal_id}/questions/{question_id}/edit")
    def edit(
        session_id: str,
        portal_id: str,
        question_id: str,
        body: EditBody,
        repo: Repository = Depends(repo_dep),
        settings: Settings = Depends(settings_dep),
    ):
        view = build_question_review(
            repo, session_id, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        if not view:
            raise HTTPException(404, "question not found")
        decision = actions.edit(
            repo, session_id, question_id, portal_id,
            view.system_proposed_answer, body.edited_answer, body.actor_id,
        )
        return {"decision_id": decision.decision_id, "action": "edit"}

    @router.post("/sessions/{session_id}/portals/{portal_id}/questions/{question_id}/reject")
    def reject(
        session_id: str,
        portal_id: str,
        question_id: str,
        body: RejectBody,
        repo: Repository = Depends(repo_dep),
        settings: Settings = Depends(settings_dep),
    ):
        view = build_question_review(
            repo, session_id, question_id, portal_id, settings.confidence_acceptance_threshold
        )
        if not view:
            raise HTTPException(404, "question not found")
        try:
            decision = actions.reject_and_override(
                repo, session_id, question_id, portal_id,
                view.system_proposed_answer, body.override_answer, body.rejection_reason, body.actor_id,
            )
        except actions.MissingRejectionReasonError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"decision_id": decision.decision_id, "action": "reject_override"}

    return router


def _cycle_id_for_portal(repo: Repository, portal_id: str) -> str:
    portal = repo.get_portal(portal_id)
    if not portal:
        raise HTTPException(404, "portal not found")
    return portal.cycle_id


def _serialize_view(view) -> dict:
    d = asdict(view)
    # Evidence is a nested dataclass with its own nested dataclass (element_reference);
    # asdict handles that recursively already. Datetimes need string coercion.
    if view.evidence and view.evidence.captured_at:
        d["evidence"]["captured_at"] = view.evidence.captured_at.isoformat()
        if view.evidence.verified_at:
            d["evidence"]["verified_at"] = view.evidence.verified_at.isoformat()
    return d
