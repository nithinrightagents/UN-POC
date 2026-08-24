"""Human Assessor A/B discrepancy engine (spec 005 Section 3.4).

Reuses 001's existing DiscrepancyCase/EscalationQueueItem entities and
escalation-queue/disposition machinery (review/escalations.py,
review/actions.py) untouched -- only the *inputs* change, from AI-agent pairs
to human blind-assessor pairs. scope="portal_human" distinguishes these cases
from the AI-vs-AI cases the original pipeline writes, so both can coexist in
the same table without confusion.
"""

from __future__ import annotations

from datetime import datetime, timezone

from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessorRole,
    DiscrepancyCase,
    EscalationQueueItem,
    EscalationReason,
    new_id,
)


def _compare(
    repo: Repository, session_id: str, portal_id: str, question_ids: list[str], threshold: float
) -> tuple[list[str], list[str], float, bool] | None:
    """Shared comparison logic with joint-answer overlay (spec 012).
    Returns (common, disagreements, rate, flagged),
    or None if neither role has any overlapping answered question yet."""
    a_answers: dict[str, object] = {}
    b_answers: dict[str, object] = {}
    for qid in question_ids:
        a_sub = repo.latest_human_submission(session_id, qid, portal_id, AssessorRole.A)
        b_sub = repo.latest_human_submission(session_id, qid, portal_id, AssessorRole.B)
        if a_sub:
            a_answers[qid] = a_sub.answer
        if b_sub:
            b_answers[qid] = b_sub.answer

    common = sorted(set(a_answers) & set(b_answers))
    if not common:
        return None

    disagreements: list[str] = []
    for qid in common:
        joint = repo.latest_joint_answer(session_id, portal_id, qid)
        if joint is not None:
            continue
        if a_answers[qid] != b_answers[qid]:
            disagreements.append(qid)

    rate = len(disagreements) / len(common)
    flagged = rate > threshold
    return common, disagreements, rate, flagged


def compute_portal_discrepancy(
    repo: Repository, session_id: str, portal_id: str, question_ids: list[str], threshold: float
) -> DiscrepancyCase | None:
    """Read-only: same comparison as recompute_portal_discrepancy but writes
    nothing. Safe to call from GET routes (e.g. the admin project-detail page)
    that just need the current rate/flag for display, without spamming a new
    audit-trail DiscrepancyCase row -- and a new EscalationQueueItem -- on
    every page view."""
    result = _compare(repo, session_id, portal_id, question_ids, threshold)
    if result is None:
        return None
    common, disagreements, rate, flagged = result
    return DiscrepancyCase(
        case_id="(unsaved-preview)",
        scope="portal_human",
        session_id=session_id,
        portal_id=portal_id,
        points_of_disagreement=disagreements,
        differing_answer_rate=rate,
        thresholds_in_force={"differing_answer_rate_threshold": threshold},
        outcome="flagged_for_arbitration" if flagged else "within_threshold",
    )


def recompute_portal_discrepancy(
    repo: Repository,
    session_id: str,
    portal_id: str,
    question_ids: list[str],
    threshold: float,
    cycle_id: str | None = None,
) -> DiscrepancyCase | None:
    """Compares the latest Assessor A vs Assessor B submission for every
    question on this unit. Returns None if neither role has any overlapping
    answered question yet (nothing to compare). Writes a DiscrepancyCase
    always once there is overlap; opens an automatic reconciliation round and
    writes an EscalationQueueItem only when both assessors have completed the unit
    and the differing-answer rate strictly exceeds `threshold` (spec 012).

    Call this only at genuine state-change points (a new human submission,
    a completion declaration, the seed script) -- never from a GET/display path.
    Use compute_portal_discrepancy for read-only display so repeated page views
    don't spam duplicate audit rows and duplicate escalation-queue entries."""
    result = _compare(repo, session_id, portal_id, question_ids, threshold)
    if result is None:
        return None
    common, disagreements, rate, flagged = result

    case = DiscrepancyCase(
        case_id=new_id("hcase"),
        scope="portal_human",
        session_id=session_id,
        portal_id=portal_id,
        points_of_disagreement=disagreements,
        differing_answer_rate=rate,
        thresholds_in_force={"differing_answer_rate_threshold": threshold},
        outcome="flagged_for_arbitration" if flagged else "within_threshold",
    )
    repo.insert_discrepancy_case(case)

    # Step 3: rate > tolerance in force strictly greater?
    if not flagged:
        return case

    # Step 4: a round is already open for this unit?
    open_round = repo.open_round_for_unit(session_id, portal_id)
    if open_round is not None:
        return case

    # Step 5: both roles have an AssessorCompletion? (FR-DR-008)
    comp_a = repo.latest_assessor_completion(session_id, portal_id, "A")
    comp_b = repo.latest_assessor_completion(session_id, portal_id, "B")
    if not (comp_a and comp_b):
        return case

    # Step 6: an automatic round has already been used for this unit? (FR-DR-030, FR-DR-036)
    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    if any(r.opened_by == "automatic" for r in rounds):
        return case

    # Step 7: open round #n, opened_by='automatic'
    if not cycle_id:
        target_p = repo.get_portal(portal_id)
        cycle_id = target_p.cycle_id if target_p else (comp_a.cycle_id if comp_a else "")

    from portal.reconciliation import open_automatic_round

    new_round = open_automatic_round(
        repo,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=disagreements,
        rate=rate,
        tolerance=threshold,
    )
    if not new_round:
        return case

    # Step 8: queue the EscalationQueueItem with context containing round_id
    already_queued = any(
        item.portal_id == portal_id
        and item.reason == EscalationReason.PORTAL_DISCREPANCY
        and item.context.get("disagreements") == disagreements
        for item in repo.list_escalations(session_id, unresolved_only=True)
    )
    if not already_queued:
        item = EscalationQueueItem(
            item_id=new_id("esc"),
            session_id=session_id,
            reason=EscalationReason.PORTAL_DISCREPANCY,
            context={
                "portal_id": portal_id,
                "differing_answer_rate": rate,
                "threshold": threshold,
                "disagreements": disagreements,
                "compared_questions": len(common),
                "round_id": new_round.round_id,
            },
            portal_id=portal_id,
        )
        repo.insert_escalation(item)

    return case


def find_resolved_answer(
    repo: Repository, session_id: str, portal_id: str, question_id: str
) -> bool | None:
    """Looks for a disposed PORTAL_DISCREPANCY escalation covering this
    question that recorded an arbitrated answer (admin.py's dispose route).
    Returns None if this question was never part of a disagreement, or was
    but hasn't been arbitrated yet.

    Stops at the *newest* escalation item that covers this question_id
    (list_escalations is newest-first) rather than searching all history:
    a resubmission can re-open a question that was already arbitrated once,
    producing a second, unresolved item for the same question_id -- that
    current item is authoritative, and an older arbitration must not leak
    through as if it still applied."""
    for item in repo.list_escalations(session_id):
        if item.portal_id != portal_id or item.reason != EscalationReason.PORTAL_DISCREPANCY:
            continue
        if question_id not in (item.context.get("disagreements") or []):
            continue
        disposition = repo.get_disposition(item.item_id)
        resolved_answers = (disposition or {}).get("resolved_answers") or {}
        if question_id in resolved_answers:
            return bool(resolved_answers[question_id])
        return None  # newest item covering this question exists but isn't (fully) arbitrated yet
    return None


def portal_answers_by_role(
    repo: Repository, session_id: str, portal_id: str, question_ids: list[str], role: AssessorRole
) -> dict[str, object]:
    out = {}
    for qid in question_ids:
        sub = repo.latest_human_submission(session_id, qid, portal_id, role)
        if sub:
            out[qid] = sub.answer
    return out
