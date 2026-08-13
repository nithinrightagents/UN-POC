"""Approve, edit, and reject-and-override handlers (FR-044–FR-047, FR-052).

Every action is a NEW AssessorDecision record -- FR-052 forbids mutating
existing records. The system-proposed answer is always preserved unchanged
(FR-046); an override requires a reason (FR-047); every action carries the
acting person's identity and a timestamp (FR-045).
"""

from __future__ import annotations

from shared.state.entities import (
    AssessorAction,
    AssessorDecision,
    new_id,
)
from shared.persistence.repositories import Repository


class MissingRejectionReasonError(ValueError):
    pass


def approve(
    repo: Repository,
    session_id: str,
    question_id: str,
    portal_id: str,
    system_proposed_answer: object,
    actor_id: str,
) -> AssessorDecision:
    decision = AssessorDecision(
        decision_id=new_id("dec"),
        session_id=session_id,
        question_id=question_id,
        portal_id=portal_id,
        action=AssessorAction.APPROVE,
        system_proposed_answer=system_proposed_answer,
        delivered_answer=system_proposed_answer,
        actor_id=actor_id,
    )
    repo.insert_assessor_decision(decision)
    return decision


def edit(
    repo: Repository,
    session_id: str,
    question_id: str,
    portal_id: str,
    system_proposed_answer: object,
    edited_answer: object,
    actor_id: str,
) -> AssessorDecision:
    decision = AssessorDecision(
        decision_id=new_id("dec"),
        session_id=session_id,
        question_id=question_id,
        portal_id=portal_id,
        action=AssessorAction.EDIT,
        system_proposed_answer=system_proposed_answer,
        delivered_answer=edited_answer,
        actor_id=actor_id,
    )
    repo.insert_assessor_decision(decision)
    return decision


def reject_and_override(
    repo: Repository,
    session_id: str,
    question_id: str,
    portal_id: str,
    system_proposed_answer: object,
    override_answer: object,
    rejection_reason: str,
    actor_id: str,
) -> AssessorDecision:
    if not rejection_reason or not rejection_reason.strip():
        raise MissingRejectionReasonError("A rejection reason is required (FR-047)")

    decision = AssessorDecision(
        decision_id=new_id("dec"),
        session_id=session_id,
        question_id=question_id,
        portal_id=portal_id,
        action=AssessorAction.REJECT_OVERRIDE,
        system_proposed_answer=system_proposed_answer,
        delivered_answer=override_answer,
        rejection_reason=rejection_reason,
        actor_id=actor_id,
    )
    repo.insert_assessor_decision(decision)
    return decision


def current_delivered_answer(repo: Repository, session_id: str, question_id: str, portal_id: str):
    """The most recent decision determines the delivered answer. Earlier
    decisions on the same question remain in the audit trail (FR-052) but
    are superseded for display purposes."""
    latest = repo.latest_assessor_decision(session_id, question_id, portal_id)
    return latest
