"""Agreement classification mapping for the prefill pipeline (spec 008 FR-PF-023–027).

Maps `adjudicate()` output onto FR-PF-023–027 without modifying `adjudicate()` itself.
The underlying `adjudicate()` decision table and invariants stay untouched (R3).
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.adjudicator.agent import compute_consensus_confidence
from shared.state.entities import AssessorAgentRun


@dataclass(frozen=True)
class AgreementOutcome:
    kind: str                 # uncontested | agreed_with_gap | disputed | unresolved
    answer: object | None     # None only for disputed (before the resolver) and unresolved
    confidence: int | None
    confidence_gap: int       # max pairwise delta, always recorded (FR-PF-025)
    position_run_ids: list[str]


def classify_agreement(
    validated_runs: list[AssessorAgentRun],
    per_question_confidence_threshold: int = 10,
    gap_tolerance: int = 10,
) -> AgreementOutcome:
    """Classify agreement between validated assessor runs per contracts/prefill-pipeline.md §2."""
    if len(validated_runs) < 2:
        return AgreementOutcome(
            kind="unresolved",
            answer=None,
            confidence=None,
            confidence_gap=0,
            position_run_ids=[r.run_id for r in validated_runs],
        )

    position_run_ids = [r.run_id for r in validated_runs]
    answers = [r.answer for r in validated_runs]
    confidences = [r.confidence for r in validated_runs if r.confidence is not None]
    max_delta = max((abs(a - b) for a in confidences for b in confidences), default=0)

    # Invariant: If answers differ, kind is always "disputed"
    if len(set(answers)) > 1:
        return AgreementOutcome(
            kind="disputed",
            answer=None,
            confidence=None,
            confidence_gap=max_delta,
            position_run_ids=position_run_ids,
        )

    # Answers are identical
    single_answer = answers[0]
    raw_consensus = compute_consensus_confidence(confidences, max_delta)

    if max_delta > gap_tolerance:
        # Confidence gap exceeds tolerance -> agreed_with_gap
        # Confidence is consensus confidence minus gap penalty, floored at 0
        penalized_confidence = max(0, raw_consensus - max_delta)
        return AgreementOutcome(
            kind="agreed_with_gap",
            answer=single_answer,
            confidence=penalized_confidence,
            confidence_gap=max_delta,
            position_run_ids=position_run_ids,
        )

    return AgreementOutcome(
        kind="uncontested",
        answer=single_answer,
        confidence=raw_consensus,
        confidence_gap=max_delta,
        position_run_ids=position_run_ids,
    )
