"""Human Assessor A/B reconciliation lifecycle and state projection.

This module manages the lifecycle of reconciliation rounds for human A/B assessments
under spec 012 (Automated Dynamic Discrepancy Detection and Reconciliation).

It is deliberately NOT wired to `agents/resolver/` or `agents/adjudicator/`
(spec.md Out of Scope). The AI disagreement path and the human A/B path are separate
by design.

`reconciliation_rounds` is a lifecycle table with mutable `state` following the
`assessment_jobs` precedent, rather than an append-only audit table (research.md R1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from portal.discrepancy import _compare
from portal.tolerance import effective_tolerance
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessorCompletion,
    AssessorRole,
    EscalationQueueItem,
    EscalationReason,
    Question,
    ReconciliationRound,
    new_id,
)


@dataclass
class UnitReconciliationState:
    state: str  # 'awaiting_second_assessment' | 'full_consensus' | 'within_tolerance' | 'above_tolerance_in_progress' | 'reconciliation_open' | 'persistent_discrepancy'
    rate: float | None
    compared_count: int
    disputed_question_ids: list[str]
    tolerance_in_force: float
    rounds_consumed: int
    automatic_round_used: bool
    open_round_id: str | None = None


def unit_reconciliation_state(
    repo: Repository,
    session_id: str,
    cycle_id: str | None,
    portal_id: str,
    questions: list[Question] | list[str],
    settings: Settings,
) -> UnitReconciliationState:
    """Computes the live derived reconciliation state for a unit (data-model.md §7).
    One function for the badge, the assessor routes, and publication readiness.
    """
    tolerance = effective_tolerance(repo, cycle_id, settings)
    question_ids = [q.question_id if hasattr(q, "question_id") else str(q) for q in questions]

    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    rounds_consumed = len(rounds)
    automatic_round_used = any(r.opened_by == "automatic" for r in rounds)
    open_round = repo.open_round_for_unit(session_id, portal_id)
    open_round_id = open_round.round_id if open_round else None

    cmp_res = _compare(repo, session_id, portal_id, question_ids, tolerance)

    if cmp_res is None:
        rate = None
        compared_count = 0
        disputed_question_ids = []
        if open_round is not None:
            state = "reconciliation_open"
        else:
            state = "awaiting_second_assessment"
    else:
        common, disagreements, rate, _ = cmp_res
        compared_count = len(common)
        disputed_question_ids = disagreements

        # Evaluation order per data-model.md §7:
        # 1. reconciliation_open
        # 2. persistent_discrepancy
        # 3. rate bands (full_consensus -> within_tolerance -> above_tolerance_in_progress)
        if open_round is not None:
            state = "reconciliation_open"
        elif automatic_round_used and rate > tolerance:
            state = "persistent_discrepancy"
        elif rate == 0.0:
            state = "full_consensus"
        elif rate <= tolerance:
            state = "within_tolerance"
        else:
            state = "above_tolerance_in_progress"

    return UnitReconciliationState(
        state=state,
        rate=rate,
        compared_count=compared_count,
        disputed_question_ids=disputed_question_ids,
        tolerance_in_force=tolerance,
        rounds_consumed=rounds_consumed,
        automatic_round_used=automatic_round_used,
        open_round_id=open_round_id,
    )


def open_automatic_round(
    repo: Repository,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    disputed_question_ids: list[str],
    rate: float,
    tolerance: float,
) -> ReconciliationRound | None:
    """Opens an automatic reconciliation round for a unit (FR-DR-009, FR-DR-030).
    Permitted at most once across unit history.
    Refuses to open over an empty disputed set.
    """
    if not disputed_question_ids:
        return None

    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    if any(r.opened_by == "automatic" for r in rounds):
        return None

    round_number = len(rounds) + 1
    round_id = new_id("rnd")
    round_obj = ReconciliationRound(
        round_id=round_id,
        session_id=session_id,
        portal_id=portal_id,
        cycle_id=cycle_id,
        round_number=round_number,
        opened_by="automatic",
        opened_by_actor_id=None,
        opened_reason=None,
        state="open",
        data={
            "disputed_question_ids": list(disputed_question_ids),
            "rate_at_open": float(rate),
            "tolerance_at_open": float(tolerance),
        },
        opened_at=datetime.now(timezone.utc),
        closed_at=None,
    )
    ok = repo.insert_reconciliation_round(round_obj)
    if not ok:
        return repo.open_round_for_unit(session_id, portal_id)

    total_q = len(repo.list_questions(cycle_id)) if cycle_id else (round(len(disputed_question_ids) / rate) if rate > 0 else len(disputed_question_ids))
    repo.insert_escalation(
        EscalationQueueItem(
            item_id=new_id("esc"),
            session_id=session_id,
            reason=EscalationReason.PORTAL_DISCREPANCY,
            portal_id=portal_id,
            context={
                "portal_id": portal_id,
                "disagreements": list(disputed_question_ids),
                "differing_answer_rate": float(rate),
                "rate": float(rate),
                "threshold": float(tolerance),
                "round_id": round_id,
                "compared_questions": total_q,
            },
        )
    )
    return round_obj


def open_reviewer_round(
    repo: Repository,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    actor_id: str,
    reason: str,
    settings: Settings,
) -> ReconciliationRound:
    """Opens a Senior Reviewer-initiated reconciliation round (FR-DR-056).
    Requires non-empty actor_id and reason. Sets opened_by='senior_reviewer'.
    Refuses if the current disputed set is empty.
    """
    if not actor_id or not actor_id.strip():
        raise ValueError("actor_id is required to return a unit for reconciliation.")
    if not reason or not reason.strip():
        raise ValueError("A stated reason is required to return a unit for reconciliation.")

    existing_open = repo.open_round_for_unit(session_id, portal_id)
    if existing_open:
        return existing_open

    tolerance = effective_tolerance(repo, cycle_id, settings)
    questions = repo.list_questions(cycle_id)
    q_ids = [q.question_id for q in questions]
    cmp_res = _compare(repo, session_id, portal_id, q_ids, tolerance)
    if not cmp_res or not cmp_res[1]:
        raise ValueError("Cannot return unit: no indicators are currently in dispute.")

    disputed = cmp_res[1]
    rate = cmp_res[2]

    prior_rounds = repo.list_rounds_for_unit(session_id, portal_id)
    round_number = max((r.round_number for r in prior_rounds), default=0) + 1
    round_id = new_id("rnd")

    round_obj = ReconciliationRound(
        round_id=round_id,
        session_id=session_id,
        portal_id=portal_id,
        cycle_id=cycle_id,
        round_number=round_number,
        opened_by="senior_reviewer",
        opened_by_actor_id=actor_id.strip(),
        opened_reason=reason.strip(),
        state="open",
        data={
            "disputed_question_ids": list(disputed),
            "rate_at_open": float(rate),
            "tolerance_at_open": float(tolerance),
        },
        opened_at=datetime.now(timezone.utc),
        closed_at=None,
    )
    ok = repo.insert_reconciliation_round(round_obj)
    if not ok:
        return repo.open_round_for_unit(session_id, portal_id)

    repo.insert_escalation(
        EscalationQueueItem(
            item_id=new_id("esc"),
            session_id=session_id,
            reason=EscalationReason.PORTAL_DISCREPANCY,
            portal_id=portal_id,
            context={
                "portal_id": portal_id,
                "disagreements": list(disputed),
                "differing_answer_rate": float(rate),
                "rate": float(rate),
                "threshold": float(tolerance),
                "round_id": round_id,
                "compared_questions": len(q_ids),
            },
        )
    )

    from portal.discrepancy import recompute_portal_discrepancy

    recompute_portal_discrepancy(repo, session_id, portal_id, q_ids, tolerance, cycle_id=cycle_id)

    return round_obj



def _format_pct(val: float) -> str:
    pct = val * 100
    if abs(pct - round(pct)) < 1e-4:
        return f"{int(round(pct))}%"
    return f"{pct:.1f}%"


def render_badge(state: UnitReconciliationState) -> str:
    """Renders the HTML badge for a unit's reconciliation state (FR-DR-040..046)."""
    st = state.state
    tol_str = _format_pct(state.tolerance_in_force)
    rate_str = _format_pct(state.rate) if state.rate is not None else ""
    cnt_str = f" ({state.compared_count} indicators)" if state.compared_count > 0 else ""

    if st == "full_consensus":
        return f'<span class="badge badge--yes"><span class="badge-icon">✓</span> Full consensus — 0%{cnt_str}</span>'
    elif st == "within_tolerance":
        return f'<span class="badge badge--warn"><span class="badge-icon">✓</span> {rate_str} — within {tol_str} tolerance{cnt_str}</span>'
    elif st == "above_tolerance_in_progress":
        return f'<span class="badge badge--flag"><span class="badge-icon">⚠</span> {rate_str} — above {tol_str}, assessment in progress{cnt_str}</span>'
    elif st == "reconciliation_open":
        return f'<span class="badge badge--flag"><span class="badge-icon">⚠</span> {rate_str} — reconciliation open{cnt_str}</span>'
    elif st == "persistent_discrepancy":
        return f'<span class="badge badge--flag"><span class="badge-icon">⚠</span> {rate_str} — reconciliation exhausted, awaiting Senior Reviewer{cnt_str}</span>'
    else:  # awaiting_second_assessment
        return '<span class="badge badge--neutral">Awaiting second assessment</span>'


def close_round_if_complete(
    repo: Repository,
    round_id: str,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    questions: list[Question] | list[str],
    settings: Settings,
) -> ReconciliationRound | None:
    """Closes an open reconciliation round if all opening disputed questions are answered (FR-DR-026, FR-DR-032).
    Closes as 'resolved' if final rate <= tolerance, or 'exhausted' if rate > tolerance.
    Also disposes the associated EscalationQueueItem (FR-DR-050).
    """
    open_round = repo.open_round_for_unit(session_id, portal_id)
    if not open_round or open_round.round_id != round_id:
        return None

    disputed = open_round.data.get("disputed_question_ids", [])
    if not disputed:
        return open_round

    joint_answers = repo.list_joint_answers_for_round(round_id)
    answered_qids = {ja.question_id for ja in joint_answers}
    if not all(qid in answered_qids for qid in disputed):
        return open_round

    tolerance = effective_tolerance(repo, cycle_id, settings)
    question_ids = [q.question_id if hasattr(q, "question_id") else str(q) for q in questions]
    cmp_res = _compare(repo, session_id, portal_id, question_ids, tolerance)
    rate = cmp_res[2] if cmp_res else 0.0

    terminal_state = "resolved" if rate <= tolerance else "exhausted"
    now = datetime.now(timezone.utc)
    repo.close_round(round_id, terminal_state, now)

    if terminal_state == "resolved":
        # Close the associated work item in escalation queue as resolved by joint assessor review (FR-DR-050)
        for item in repo.list_escalations(session_id, unresolved_only=True):
            if item.portal_id == portal_id and item.reason == EscalationReason.PORTAL_DISCREPANCY:
                if item.context.get("round_id") == round_id or not item.context.get("round_id"):
                    repo.record_disposition(
                        item.item_id,
                        {
                            "resolution": "reconciled_by_joint_review",
                            "resolved_by_actor_id": "system",
                            "notes": f"Reconciliation round {open_round.round_number} closed as resolved.",
                        },
                    )

    # Recompute to write the audit case with overlay in force
    from portal.discrepancy import recompute_portal_discrepancy

    recompute_portal_discrepancy(repo, session_id, portal_id, question_ids, tolerance, cycle_id=cycle_id)

    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    return next((r for r in rounds if r.round_id == round_id), open_round)


def round_history(repo: Repository, session_id: str, portal_id: str) -> list[dict]:
    """Returns round history details for a unit (FR-DR-031).
    Each dict contains: round_number, opened_by, opened_by_actor_id, opened_reason, state, opened_at, closed_at.
    """
    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    return [
        {
            "round_number": r.round_number,
            "opened_by": r.opened_by,
            "opened_by_actor_id": r.opened_by_actor_id,
            "opened_reason": r.opened_reason,
            "state": r.state,
            "opened_at": r.opened_at.isoformat() if hasattr(r.opened_at, "isoformat") else str(r.opened_at),
            "closed_at": (
                r.closed_at.isoformat() if hasattr(r.closed_at, "isoformat") else str(r.closed_at)
            ) if r.closed_at else None,
            "disputed_count": len(r.data.get("disputed_question_ids", [])),
            "rate_at_open": r.data.get("rate_at_open"),
            "tolerance_at_open": r.data.get("tolerance_at_open"),
        }
        for r in rounds
    ]




