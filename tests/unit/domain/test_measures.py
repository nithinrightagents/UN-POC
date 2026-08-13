"""Portal-level agreement measures — FR-035–FR-037.

The load-bearing fixture: two agents each answering yes to 50 of 100 questions
while disagreeing on 40 individual questions produce an affirmative-rate gap of
exactly zero against a 40% differing-answer rate. Differing-answer rate must be
the primary trigger (FR-036), or this case goes undetected.
"""

import pytest

from shared.state.entities import AgentRunState, AssessorAgentRun
from shared.state.measures import compute_portal_measures, eligible_for_portal_measures

pytestmark = pytest.mark.unit


def _validated_run(question_id, agent_index, answer):
    return AssessorAgentRun(
        run_id=f"{question_id}-{agent_index}",
        session_id="s1",
        question_id=question_id,
        portal_id="p1",
        agent_index=agent_index,
        round_number=1,
        answer=answer,
        state=AgentRunState.VALIDATED_PASS,
    )


def _build_5050_disagree40_fixture():
    """100 questions. Agent 0 says yes to q0..q49. Agent 1 says yes to a
    different set of 50 such that exactly 40 questions differ between them."""
    runs_by_question = {}
    # Agent 0: yes for 0-49, no for 50-99.
    # Agent 1: yes for 20-69 (50 yes), no otherwise.
    # Differences: questions where a0 != a1.
    #   0-19: a0=yes a1=no -> differ (20)
    #   20-49: a0=yes a1=yes -> same (30)
    #   50-69: a0=no a1=yes -> differ (20)
    #   70-99: a0=no a1=no -> same (30)
    # Total differing = 40. Agent0 affirmative=50/100, Agent1 affirmative=50/100 -> gap 0.
    for i in range(100):
        qid = f"q{i}"
        a0 = i < 50
        a1 = 20 <= i < 70
        runs_by_question[qid] = [
            _validated_run(qid, 0, a0),
            _validated_run(qid, 1, a1),
        ]
    return runs_by_question


def test_zero_affirmative_gap_but_high_differing_rate_still_flags():
    fixture = _build_5050_disagree40_fixture()
    measures = compute_portal_measures(
        fixture,
        configured_agent_count=2,
        differing_answer_rate_threshold=0.10,
        affirmative_rate_gap_threshold=0.10,
    )
    assert measures.affirmative_rate_gap == pytest.approx(0.0)
    assert measures.differing_answer_rate == pytest.approx(0.40)
    assert measures.flagged is True
    assert measures.triggering_measure == "differing_answer_rate"


def test_agreement_below_threshold_does_not_flag():
    fixture = {}
    for i in range(20):
        qid = f"q{i}"
        answer = i % 3 == 0  # agents agree on every question
        fixture[qid] = [_validated_run(qid, 0, answer), _validated_run(qid, 1, answer)]
    measures = compute_portal_measures(
        fixture,
        configured_agent_count=2,
        differing_answer_rate_threshold=0.10,
        affirmative_rate_gap_threshold=0.10,
    )
    assert measures.differing_answer_rate == 0.0
    assert measures.flagged is False


def test_eligibility_requires_all_configured_agents_validated():
    runs = {"q1": [_validated_run("q1", 0, True)]}  # only agent 0
    assert not eligible_for_portal_measures(runs, "q1", configured_agent_count=2)
    runs["q1"].append(_validated_run("q1", 1, False))
    assert eligible_for_portal_measures(runs, "q1", configured_agent_count=2)


def test_ineligible_questions_excluded_from_measures():
    fixture = _build_5050_disagree40_fixture()
    # Add a partially-covered custom question (only 1 of 2 agents assessed it).
    fixture["custom-1"] = [_validated_run("custom-1", 0, True)]
    measures = compute_portal_measures(
        fixture,
        configured_agent_count=2,
        differing_answer_rate_threshold=0.10,
        affirmative_rate_gap_threshold=0.10,
    )
    # Still 40% over the 100 eligible questions -- the ineligible one must not skew it.
    assert measures.differing_answer_rate == pytest.approx(0.40)
