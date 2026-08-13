"""Confidence acceptance rules.

Confidence is a numeric value 0-100, displayed as a percentage everywhere it
appears. There are no named tiers (FR-041, FR-042) — the acceptance threshold
(default 75, FR-134) is the single boundary the system draws on the scale.

Pure logic, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceGateResult:
    accepted: bool
    should_retry: bool
    retries_exhausted: bool


def meets_acceptance_threshold(confidence: int, threshold: int) -> bool:
    return confidence >= threshold


def evaluate_confidence_gate(
    confidence: int,
    threshold: int,
    retry_count: int,
    retry_limit: int,
) -> ConfidenceGateResult:
    """Decide whether an Assessor Agent output should be retried for low confidence.

    FR-134: >= threshold -> proceeds unchanged, no retry.
    FR-135/FR-137: < threshold and under the retry limit -> retry that agent only.
    FR-138: still under threshold after the retry limit -> admit unchanged, deliver
        marked low confidence. Never escalate on this basis alone.
    """
    if meets_acceptance_threshold(confidence, threshold):
        return ConfidenceGateResult(accepted=True, should_retry=False, retries_exhausted=False)

    if retry_count < retry_limit:
        return ConfidenceGateResult(accepted=False, should_retry=True, retries_exhausted=False)

    # Retry limit reached and still below threshold: admit unchanged (FR-138).
    return ConfidenceGateResult(accepted=True, should_retry=False, retries_exhausted=True)


def cap_confidence_for_missing_evidence(confidence: int, threshold: int) -> int:
    """FR-024: missing/unresolvable evidence caps confidence below the acceptance
    threshold, regardless of what the agent reported."""
    return min(confidence, threshold - 1)


def cap_confidence_for_best_effort(confidence: int, ceiling: int) -> int:
    """FR-018: out-of-set-language best-effort answers are capped at the
    configured ceiling (default 74, one below the acceptance threshold)."""
    return min(confidence, ceiling)


def is_below_acceptance_threshold(confidence: int, threshold: int) -> bool:
    """FR-139: whether a delivered answer must be visibly marked low confidence."""
    return confidence < threshold


def validate_ceiling_below_threshold(ceiling: int, threshold: int) -> None:
    """Startup validation (contracts/configuration.md): the best-effort ceiling
    must be strictly below the acceptance threshold, or a translated answer could
    clear the threshold on its own, defeating FR-018."""
    if ceiling >= threshold:
        raise ValueError(
            f"AIQ_BEST_EFFORT_CONFIDENCE_CEILING ({ceiling}) must be below "
            f"AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD ({threshold})"
        )
