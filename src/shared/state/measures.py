"""Portal-level agreement measures.

Taken on first-round positions only (FR-035), before any retry, so the measure
survives retry convergence — a portal whose agents initially read it very
differently is flagged for joint human review even after every individual
question later converged. See FR-035–FR-039 and contracts/adjudicator.md.

Pure logic, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from .entities import AgentRunState, AssessorAgentRun


@dataclass(frozen=True)
class PortalMeasures:
    differing_answer_rate: float
    affirmative_rate_gap: float
    flagged: bool
    triggering_measure: str | None


def eligible_for_portal_measures(
    first_round_runs_by_question: dict[str, list[AssessorAgentRun]],
    question_id: str,
    configured_agent_count: int,
) -> bool:
    """FR-058: a custom question added mid-run counts toward portal measures only
    if every configured agent produced a validated first-round position for it.

    Computed as a derived predicate at measure time, not stored, because FR-067a
    resume can retain a partial agent set even after the unit is delivered — see
    data-model.md §Portal Measure Eligibility.
    """
    runs = first_round_runs_by_question.get(question_id, [])
    validated_agents = {
        r.agent_index for r in runs if r.state == AgentRunState.VALIDATED_PASS
    }
    return len(validated_agents) == configured_agent_count


def compute_portal_measures(
    first_round_runs_by_question: dict[str, list[AssessorAgentRun]],
    configured_agent_count: int,
    differing_answer_rate_threshold: float,
    affirmative_rate_gap_threshold: float,
) -> PortalMeasures:
    """Compute the two portal-level measures across every eligible question.

    Requires exactly `configured_agent_count` agents (assumed == 2 for the
    pairwise affirmative-rate-gap definition, matching FR-035's "each agent's
    rate of affirmative answers"; generalizes to N via per-agent rates).
    """
    eligible_questions = [
        qid
        for qid in first_round_runs_by_question
        if eligible_for_portal_measures(
            first_round_runs_by_question, qid, configured_agent_count
        )
    ]

    if not eligible_questions:
        return PortalMeasures(0.0, 0.0, False, None)

    differing = 0
    # affirmative counts per agent index
    affirmative_counts: dict[int, int] = {}
    total = len(eligible_questions)

    for qid in eligible_questions:
        runs = sorted(
            (
                r
                for r in first_round_runs_by_question[qid]
                if r.state == AgentRunState.VALIDATED_PASS
            ),
            key=lambda r: r.agent_index,
        )
        answers = {r.agent_index: r.answer for r in runs}
        if len(set(answers.values())) > 1:
            differing += 1
        for idx, ans in answers.items():
            if bool(ans):
                affirmative_counts[idx] = affirmative_counts.get(idx, 0) + 1

    differing_answer_rate = differing / total

    rates = [
        affirmative_counts.get(i, 0) / total for i in range(configured_agent_count)
    ]
    affirmative_rate_gap = max(rates) - min(rates) if rates else 0.0

    flagged = False
    triggering: str | None = None
    if differing_answer_rate > differing_answer_rate_threshold:
        flagged = True
        triggering = "differing_answer_rate"
    if affirmative_rate_gap > affirmative_rate_gap_threshold:
        flagged = True
        triggering = triggering or "affirmative_rate_gap"

    return PortalMeasures(
        differing_answer_rate=differing_answer_rate,
        affirmative_rate_gap=affirmative_rate_gap,
        flagged=flagged,
        triggering_measure=triggering,
    )
