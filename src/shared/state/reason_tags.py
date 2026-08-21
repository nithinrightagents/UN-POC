"""Canonical, deterministic reason tags for blank-field fallback (FR-BF-005, FR-BF-006)
and prefill reason taxonomy (spec 008 FR-PF-034).

See specs/004-blank-field-fallback/contracts/reason-tags.md and data-model.md's
template table. `reason_tag()` is the single source of the human-readable
"Left blank: ..." text shown on the review screen and carried into the export
exclusion report -- every call site (review/query.py, export/writer.py) goes
through this module rather than composing its own wording.
`prefill_reason_tag()` provides canonical tags for prefill reasons.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.state.entities import EscalationReason, PrefillReason, UnitState

BLOCKED_UNIT_STATES = frozenset(
    {UnitState.ESCALATED.value, UnitState.UNASSESSABLE.value, UnitState.NO_SUGGESTION.value}
)


def is_blocked(state: str) -> bool:
    """A unit is "blocked" when it reached a terminal state other than DELIVERED."""
    return state in BLOCKED_UNIT_STATES


@dataclass(frozen=True)
class ReasonTag:
    text: str
    condition: EscalationReason | PrefillReason


_LANGUAGE_DECLINED_EXPLICIT = "Left blank: Reviewer declined to proceed in unsupported language '{language}'"
_LANGUAGE_DECLINED_WINDOW_EXPIRED = "Left blank: Language decision window expired without a response"

REASON_TAGS: dict[EscalationReason, str] = {
    EscalationReason.REQUIRES_AUTHENTICATED_ACCESS: "Left blank: Login authentication barrier observed",
    EscalationReason.UNRESOLVED_DISAGREEMENT: "Left blank: Unresolved AI disagreement after retry limit",
    EscalationReason.LANGUAGE_NOT_SUPPORTED: "Left blank: Unsupported language '{language}' detected",
    EscalationReason.LANGUAGE_DECLINED: _LANGUAGE_DECLINED_EXPLICIT,
    EscalationReason.UNREACHABLE_PORTAL: "Left blank: Portal unreachable after {attempts} attempts",
    EscalationReason.UNVERIFIABLE_TARGET: "Left blank: Evidence could not be independently verified",
    EscalationReason.NO_USABLE_URL: "Left blank: No usable URL could be resolved for this question",
}

PREFILL_REASON_TAGS: dict[PrefillReason, str] = {
    PrefillReason.NO_USABLE_EVIDENCE: "No suggestion: no usable URL could be resolved for this indicator",
    PrefillReason.EVIDENCE_UNREACHABLE: "No suggestion: evidence URL was unreachable",
    PrefillReason.UNSUPPORTED_LANGUAGE: "No suggestion: unsupported language '{language}' detected",
    PrefillReason.ACCESS_BOUNDARY: "No suggestion: login authentication barrier observed",
    PrefillReason.INSUFFICIENT_POSITIONS: "No suggestion: insufficient validated assessor positions",
    PrefillReason.UNRESOLVED_DISAGREEMENT: "No suggestion: the two independent assessments could not be reconciled",
    PrefillReason.FAILED_FINAL_VALIDATION: "No suggestion: resolved position failed final validation",
    PrefillReason.ASSESSMENT_FAILURE: "No suggestion: assessment execution failed",
    PrefillReason.BUDGET_REACHED: "No suggestion: the run's budget was reached before this indicator",
    PrefillReason.NEEDS_HUMAN_REVIEW: "Needs review: a resolved link and a confident answer exist, but validation could not fully confirm it",
}


def reason_tag(
    escalation_reason: str, context: dict, resolution_manner: str | None = None
) -> ReasonTag:
    """Look up the canonical tag for a blocking condition.

    `context` is the unit's stored data dict -- `{language}` is filled from
    `context.get("detected_language")`, `{attempts}` from the attempt count the
    triggering condition recorded. `resolution_manner` ("explicit" |
    "window_expired") only affects `LANGUAGE_DECLINED`, which has two templates.

    Raises KeyError if `escalation_reason` doesn't match any EscalationReason
    value -- a future untagged reason must fail loudly in tests, not render a
    generic label live (contracts/reason-tags.md).
    """
    try:
        condition = EscalationReason(escalation_reason)
    except ValueError:
        raise KeyError(escalation_reason) from None

    if condition is EscalationReason.LANGUAGE_DECLINED:
        template = (
            _LANGUAGE_DECLINED_WINDOW_EXPIRED
            if resolution_manner == "window_expired"
            else _LANGUAGE_DECLINED_EXPLICIT
        )
    else:
        template = REASON_TAGS[condition]

    text = template.format(
        language=context.get("detected_language", ""),
        attempts=context.get("attempts", context.get("reachability_attempts", 0)),
    )
    return ReasonTag(text=text, condition=condition)


def prefill_reason_tag(
    reason: str, context: dict | None = None
) -> ReasonTag:
    """Look up the canonical tag for a prefill no-suggestion reason.

    Raises KeyError if `reason` doesn't match any PrefillReason value.
    """
    try:
        condition = PrefillReason(reason)
    except ValueError:
        raise KeyError(reason) from None

    template = PREFILL_REASON_TAGS[condition]
    ctx = context or {}
    text = template.format(
        language=ctx.get("detected_language", ""),
        attempts=ctx.get("attempts", ctx.get("reachability_attempts", 0)),
    )
    return ReasonTag(text=text, condition=condition)
