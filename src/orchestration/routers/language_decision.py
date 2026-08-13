"""Language decision flow (FR-016–FR-020).

When a portal's detected language is outside the supported set, a
decision is raised to a human -- never silently attempted, never silently
escalated (FR-017). An authorized best-effort attempt proceeds with
confidence capped; a decline or an expired response window escalates. A
pending decision never blocks the rest of the batch (FR-020) -- callers
must not await this synchronously inside the main scheduling loop for
other units.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shared.state.entities import LanguageDecision, LanguageDecisionOutcome, new_id


def language_requires_decision(detected_language: str | None, supported_languages: list[str]) -> bool:
    if not detected_language or detected_language == "unknown":
        return True
    return detected_language not in supported_languages


def create_pending_decision(
    portal_id: str, session_id: str, detected_language: str
) -> LanguageDecision:
    """FR-017: raises the decision. `decision` starts unset -- represented
    here as EXPIRED with resolution_manner left for the caller to correct
    once resolved; callers should not persist this placeholder, only use it
    to know a decision is needed, then persist the actual resolution once
    it happens via `resolve_decision`."""
    return LanguageDecision(
        decision_id=new_id("langdec"),
        portal_id=portal_id,
        session_id=session_id,
        detected_language=detected_language,
        decision=LanguageDecisionOutcome.EXPIRED,  # placeholder until resolved
        decided_by_actor_id=None,
        resolution_manner="pending",
    )


def resolve_decision_authorized(pending: LanguageDecision, actor_id: str) -> LanguageDecision:
    return LanguageDecision(
        decision_id=pending.decision_id,
        portal_id=pending.portal_id,
        session_id=pending.session_id,
        detected_language=pending.detected_language,
        decision=LanguageDecisionOutcome.AUTHORIZED,
        decided_by_actor_id=actor_id,
        resolution_manner="explicit",
    )


def resolve_decision_declined(pending: LanguageDecision, actor_id: str) -> LanguageDecision:
    return LanguageDecision(
        decision_id=pending.decision_id,
        portal_id=pending.portal_id,
        session_id=pending.session_id,
        detected_language=pending.detected_language,
        decision=LanguageDecisionOutcome.DECLINED,
        decided_by_actor_id=actor_id,
        resolution_manner="explicit",
    )


def resolve_decision_expired(pending: LanguageDecision) -> LanguageDecision:
    """FR-019: no response within the configured window."""
    return LanguageDecision(
        decision_id=pending.decision_id,
        portal_id=pending.portal_id,
        session_id=pending.session_id,
        detected_language=pending.detected_language,
        decision=LanguageDecisionOutcome.EXPIRED,
        decided_by_actor_id=None,
        resolution_manner="window_expired",
    )


def window_has_expired(pending_created_at: datetime, window_hours: int) -> bool:
    return datetime.now(timezone.utc) - pending_created_at > timedelta(hours=window_hours)


def apply_best_effort_confidence_cap(confidence: int, ceiling: int) -> int:
    """FR-018: authorized best-effort answers are capped at the configured
    ceiling regardless of what the agent reported."""
    return min(confidence, ceiling)
