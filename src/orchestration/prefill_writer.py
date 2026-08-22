"""Prefill writer module (spec 008 FR-PF-001, FR-PF-002, SC-008).

The single seam through which every pipeline exit writes a `prefills` row.
Ensures the invariant that every indicator in a prefill run ends with a prefill record.
"""

from __future__ import annotations

from typing import Any

from shared.persistence.repositories import Repository
from shared.state import unit_state
from shared.state.entities import (
    LinkSource,
    Prefill,
    PrefillReason,
    UnitState,
    new_id,
    prefill_answer_category,
)


def write_prefill(
    repo: Repository,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    question_id: str,
    run_id: str,
    suggested: bool,
    answer: bool | None = None,
    confidence: int | None = None,
    justification: str | None = None,
    evidence_url: str | None = None,
    supplying_source: LinkSource | str | None = None,
    agreement_outcome: str | None = None,
    confidence_gap: int | None = None,
    resolver_decision: dict[str, Any] | None = None,
    unselected_position: dict[str, Any] | None = None,
    position_run_ids: list[str] | None = None,
    reason: PrefillReason | str | None = None,
    terminal_state: UnitState = UnitState.NO_SUGGESTION,
    current_state_ref: list[UnitState] | None = None,
    unit_context: dict[str, Any] | None = None,
    advance_state: bool = True,
) -> Prefill:
    """Write a prefill row and optionally transition the assessment unit to its terminal state."""
    # A delivered prefill's own terminal_state must reflect DELIVERED
    # regardless of whether this call also drives the unit-level transition
    # (advance_state=False callers, e.g. the delivered path in
    # scheduler.py, perform that transition separately) -- otherwise the
    # record is stamped with the `terminal_state` default/param meant for
    # the non-delivered case.
    target_state = UnitState.DELIVERED if suggested else terminal_state

    prefill = Prefill(
        prefill_id=new_id("pf"),
        run_id=run_id,
        session_id=session_id,
        cycle_id=cycle_id,
        question_id=question_id,
        portal_id=portal_id,
        suggested=suggested,
        answer=answer,
        confidence=confidence,
        justification=justification,
        evidence_url=evidence_url,
        supplying_source=supplying_source,
        agreement_outcome=agreement_outcome,
        confidence_gap=confidence_gap,
        resolver_decision=resolver_decision,
        unselected_position=unselected_position,
        position_run_ids=position_run_ids or [],
        reason=reason,
        terminal_state=target_state,
    )
    repo.insert_prefill(prefill)

    if advance_state:
        if current_state_ref is not None and len(current_state_ref) > 0:
            from_state = current_state_ref[0]
            if unit_state.can_transition(from_state, target_state):
                unit_state.transition(from_state, target_state)
                current_state_ref[0] = target_state

        ctx = dict(unit_context or {})
        ctx["answer_category"] = prefill_answer_category(suggested, answer, reason)
        if reason:
            reason_val = reason.value if hasattr(reason, "value") else str(reason)
            ctx["prefill_reason"] = reason_val
        if suggested:
            ctx["consensus_answer"] = answer
            ctx["consensus_confidence"] = confidence
            if agreement_outcome:
                ctx["agreement_outcome"] = agreement_outcome

        repo.upsert_unit(
            session_id=session_id,
            question_id=question_id,
            portal_id=portal_id,
            state=target_state.value,
            data=ctx,
        )

    return prefill
