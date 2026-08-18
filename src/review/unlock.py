"""Per-portal review unlocking (FR-043a, FR-043b, FR-043c).

A portal becomes available for Assessor review only once every question for
that portal has reached a terminal pipeline state -- a delivered consensus
answer or an escalation. Review is presented per portal over the complete
pre-filled set, not question-by-question as individual answers complete.
Escalated questions appear within the set marked as such, so one unresolved
question does not withhold the rest of the portal.

In-run touchpoints (language decisions, escalation queue items) are NOT
gated by this -- they are queried directly by the escalation/language-
decision views, which never call this module.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.state.entities import TERMINAL_UNIT_STATES, UnitState
from shared.state.reason_tags import is_blocked
from shared.persistence.repositories import Repository

_TERMINAL = {s.value for s in TERMINAL_UNIT_STATES}


@dataclass
class PortalReviewStatus:
    portal_id: str
    unlocked: bool
    total_questions: int
    terminal_count: int
    pending_question_ids: list[str]
    escalated_question_ids: list[str]


def portal_review_status(
    repo: Repository, session_id: str, portal_id: str, expected_question_ids: list[str]
) -> PortalReviewStatus:
    pending: list[str] = []
    escalated: list[str] = []
    terminal_count = 0

    for qid in expected_question_ids:
        unit = repo.get_unit(session_id, qid, portal_id)
        state = unit["state"] if unit else UnitState.PENDING.value
        if state in _TERMINAL:
            terminal_count += 1
            if is_blocked(state):
                escalated.append(qid)
        else:
            pending.append(qid)

    unlocked = terminal_count == len(expected_question_ids) and len(expected_question_ids) > 0

    return PortalReviewStatus(
        portal_id=portal_id,
        unlocked=unlocked,
        total_questions=len(expected_question_ids),
        terminal_count=terminal_count,
        pending_question_ids=pending,
        escalated_question_ids=escalated,
    )


def list_unlocked_portals(
    repo: Repository, session_id: str, portal_ids: list[str], question_ids: list[str]
) -> list[str]:
    return [
        pid
        for pid in portal_ids
        if portal_review_status(repo, session_id, pid, question_ids).unlocked
    ]
