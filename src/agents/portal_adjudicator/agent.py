"""Portal-level adjudication (FR-035–FR-039).

Compares the same agents over the same questions as per-question
adjudication -- it is an aggregate view of the same signal, not an
independent detector (spec, Assumptions). Runs once a portal's question
set is complete, over first-round positions only (before any retry), so a
portal whose agents initially read it very differently is flagged for
joint human review even after every individual disagreement later
converged.
"""

from __future__ import annotations

from core.base_agent import BaseAgent
from shared.state.entities import AssessorAgentRun, DiscrepancyCase, new_id
from shared.state.measures import PortalMeasures, compute_portal_measures


def adjudicate_portal(
    session_id: str,
    portal_id: str,
    first_round_runs_by_question: dict[str, list[AssessorAgentRun]],
    configured_agent_count: int,
    differing_answer_rate_threshold: float,
    affirmative_rate_gap_threshold: float,
) -> tuple[PortalMeasures, DiscrepancyCase | None]:
    measures = compute_portal_measures(
        first_round_runs_by_question,
        configured_agent_count,
        differing_answer_rate_threshold,
        affirmative_rate_gap_threshold,
    )

    if not measures.flagged:
        return measures, None

    per_question_breakdown = [
        {
            "question_id": qid,
            "answers": {r.agent_index: r.answer for r in runs},
        }
        for qid, runs in first_round_runs_by_question.items()
    ]

    case = DiscrepancyCase(
        case_id=new_id("case"),
        scope="portal",
        session_id=session_id,
        portal_id=portal_id,
        differing_answer_rate=measures.differing_answer_rate,
        affirmative_rate_gap=measures.affirmative_rate_gap,
        thresholds_in_force={
            "differing_answer_rate": differing_answer_rate_threshold,
            "affirmative_rate_gap": affirmative_rate_gap_threshold,
        },
        outcome="flagged_for_review",
        points_of_disagreement=[str(b) for b in per_question_breakdown],
    )
    return measures, case


class PortalAdjudicatorAgent(BaseAgent):
    """Portal Adjudicator Agent implementation."""

    def __init__(self, name: str = "PortalAdjudicatorAgent", description: str = ""):
        super().__init__(name=name, description=description or "Portal-level adjudication agent.")

    async def run(self, input_data: dict, **kwargs):
        """`input_data` carries the portal/session identity and the
        per-question run data; `kwargs` carries the configured thresholds,
        mirroring AssessorAgent.run's split."""
        return adjudicate_portal(
            session_id=input_data["session_id"],
            portal_id=input_data["portal_id"],
            first_round_runs_by_question=input_data["first_round_runs_by_question"],
            **kwargs,
        )

