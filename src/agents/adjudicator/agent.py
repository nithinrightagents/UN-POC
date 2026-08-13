"""Per-question adjudication (FR-027–FR-034).

Compares N *validated* Assessor Agent positions into a consensus answer.
Mechanical, not a model call: the decision table is deterministic (FR-028),
so no third agent or "judge model" ever sees more than one position at a
time -- adjudication is a comparison the Adjudicator performs over already-
independent, already-validated positions, not a fresh AI opinion.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from core.base_agent import BaseAgent
from shared.state.entities import AdjudicationResult, AssessorAgentRun, new_id


@dataclass(frozen=True)
class AdjudicationDecision:
    discrepancy_flagged: bool
    flag_reason: str | None  # "answers_differ" | "confidence_delta"
    max_pairwise_confidence_delta: int
    consensus_answer: object | None
    consensus_confidence: int | None


def adjudicate(
    validated_runs: list[AssessorAgentRun],
    per_question_confidence_threshold: int,
) -> AdjudicationDecision:
    """FR-027: requires >= 2 validated positions -- the caller is
    responsible for routing pairs with fewer than 2 to escalation (FR-082,
    SC-016) rather than calling this function at all."""
    if len(validated_runs) < 2:
        raise ValueError("adjudicate() requires at least 2 validated runs (FR-027, SC-016)")

    answers = [r.answer for r in validated_runs]
    confidences = [r.confidence for r in validated_runs if r.confidence is not None]

    answers_differ = len(set(answers)) > 1
    max_delta = max(
        (abs(a - b) for a, b in combinations(confidences, 2)), default=0
    )
    delta_exceeds_threshold = max_delta > per_question_confidence_threshold

    if answers_differ:
        return AdjudicationDecision(
            discrepancy_flagged=True,
            flag_reason="answers_differ",
            max_pairwise_confidence_delta=max_delta,
            consensus_answer=None,
            consensus_confidence=None,
        )

    if delta_exceeds_threshold:
        # FR-028: agreement on the answer alone is not sufficient to deliver.
        # Agents that agree on the answer but diverge sharply on confidence
        # are disagreeing about how well the evidence supports it.
        return AdjudicationDecision(
            discrepancy_flagged=True,
            flag_reason="confidence_delta",
            max_pairwise_confidence_delta=max_delta,
            consensus_answer=None,
            consensus_confidence=None,
        )

    consensus_confidence = compute_consensus_confidence(confidences, max_delta)
    return AdjudicationDecision(
        discrepancy_flagged=False,
        flag_reason=None,
        max_pairwise_confidence_delta=max_delta,
        consensus_answer=answers[0],
        consensus_confidence=consensus_confidence,
    )


def compute_consensus_confidence(confidences: list[int], max_delta: int) -> int:
    """FR-034: reflects agreement across agents IN ADDITION TO per-agent
    confidence -- not a bare average. Tight agreement (small max_delta)
    should not simply regress to the mean of two already-close values; it
    should read as at least as confident as the average, since agreement
    is itself evidence. A wide-but-under-threshold delta pulls the
    consensus down slightly. Recorded separately; per-agent values are
    never altered."""
    if not confidences:
        return 0
    avg = sum(confidences) / len(confidences)
    # Agreement bonus: up to +5 points for max_delta == 0, linearly to 0 at
    # the point the delta would have flagged (the caller already excluded
    # anything past that threshold, so this stays bounded).
    agreement_bonus = max(0.0, 5.0 * (1 - max_delta / 10.0)) if max_delta <= 10 else 0.0
    return round(min(100.0, avg + agreement_bonus))


def build_adjudication_result(
    session_id: str,
    question_id: str,
    portal_id: str,
    round_number: int,
    validated_runs: list[AssessorAgentRun],
    decision: AdjudicationDecision,
    confidence_acceptance_threshold: int,
) -> AdjudicationResult:
    from shared.state.confidence import is_below_acceptance_threshold

    below_threshold = (
        is_below_acceptance_threshold(decision.consensus_confidence, confidence_acceptance_threshold)
        if decision.consensus_confidence is not None
        else None
    )
    return AdjudicationResult(
        adjudication_id=new_id("adj"),
        session_id=session_id,
        question_id=question_id,
        portal_id=portal_id,
        round_number=round_number,
        input_run_ids=[r.run_id for r in validated_runs],
        discrepancy_flagged=decision.discrepancy_flagged,
        flag_reason=decision.flag_reason,
        max_pairwise_confidence_delta=decision.max_pairwise_confidence_delta,
        consensus_answer=decision.consensus_answer,
        consensus_confidence=decision.consensus_confidence,
        below_acceptance_threshold=below_threshold,
    )


class AdjudicatorAgent(BaseAgent):
    """Adjudicator Agent implementation."""

    def __init__(self, name: str = "AdjudicatorAgent", description: str = ""):
        super().__init__(name=name, description=description or "Per-question adjudication agent.")

    async def run(self, input_data: dict, **kwargs) -> AdjudicationDecision:
        """`input_data` carries the positions being adjudicated; `kwargs`
        carries the configured threshold, mirroring AssessorAgent.run's split."""
        validated_runs = input_data["validated_runs"]
        threshold = kwargs.get("per_question_confidence_threshold", 10)
        return adjudicate(validated_runs, threshold)

