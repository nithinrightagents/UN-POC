"""Escalation queue and portal-level discrepancy case views (FR-049, FR-050).

Presents escalation items with the disagreement summary and all Assessor
Agent positions, and portal-level discrepancy cases with both agreement
measures, their configured thresholds, and the per-question breakdown that
produced them.

Concurrency safety (FR-049 -- exactly one delivered disposition even under
concurrent action) is enforced in persistence/repositories.py via a UNIQUE
constraint on escalation_dispositions.item_id: the first concurrent writer
wins, the second gets a False return from record_disposition() rather than
silently overwriting the first.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from shared.state.entities import EscalationQueueItem
from shared.persistence.repositories import Repository


@dataclass
class EscalationView:
    item: EscalationQueueItem
    already_resolved: bool
    disposition: dict | None


def list_escalation_queue(repo: Repository, session_id: str) -> list[EscalationView]:
    items = repo.list_escalations(session_id)
    views = []
    for item in items:
        disposition = repo.get_disposition(item.item_id)
        views.append(
            EscalationView(item=item, already_resolved=disposition is not None, disposition=disposition)
        )
    return views


def dispose_escalation(
    repo: Repository,
    item_id: str,
    resolution: str,
    resolved_by_actor_id: str,
    notes: str = "",
    resolved_answers: dict[str, bool] | None = None,
) -> bool:
    """Returns True if this call recorded the disposition, False if another
    concurrent caller already resolved it first (FR-049) -- the caller
    should tell the user "already resolved" in that case, never silently
    overwrite.

    resolved_answers (spec 005 Section 3.4/3.6): optional per-question_id
    answers the arbitrator settled on for a portal_human discrepancy --
    admin.py's publish route reads these back (via
    portal/discrepancy.find_resolved_answer) so a disagreement that went
    through joint review actually publishes the arbitrated answer instead of
    an arbitrary Assessor-A-wins default."""
    disposition = {
        "resolution": resolution,
        "resolved_by_actor_id": resolved_by_actor_id,
        "notes": notes,
        "resolved_answers": resolved_answers or {},
    }
    return repo.record_disposition(item_id, disposition)


@dataclass
class PortalDiscrepancyView:
    case_id: str
    portal_id: str
    differing_answer_rate: float
    affirmative_rate_gap: float
    thresholds_in_force: dict
    per_question_breakdown: list


def portal_discrepancy_cases(repo: Repository, session_id: str) -> list[PortalDiscrepancyView]:
    # Note: query uses scope="portal", while the human engine writes scope="portal_human".
    # This pre-existing inconsistency is deliberately preserved (see spec 012 research.md R12).
    cases = repo.list_discrepancy_cases(session_id, scope="portal")
    return [
        PortalDiscrepancyView(
            case_id=c.case_id,
            portal_id=c.portal_id,
            differing_answer_rate=c.differing_answer_rate or 0.0,
            affirmative_rate_gap=c.affirmative_rate_gap or 0.0,
            thresholds_in_force=c.thresholds_in_force or {},
            per_question_breakdown=c.points_of_disagreement,
        )
        for c in cases
    ]
