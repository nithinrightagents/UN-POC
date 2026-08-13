"""Resume semantics — FR-067a, FR-067b.

The subtle case: an agent run interrupted mid-validation-retry has a completed
assessment but incomplete validation. The whole run must be discarded and the
agent re-run from scratch, not resumed at the validation step.
"""

import pytest

from shared.state.entities import AgentRunState, AssessorAgentRun, UnitState
from shared.state.resume import remaining_work

pytestmark = pytest.mark.unit


def _run(agent_index, state, run_id=None):
    return AssessorAgentRun(
        run_id=run_id or f"run-{agent_index}-{state.value}",
        session_id="s1",
        question_id="q1",
        portal_id="p1",
        agent_index=agent_index,
        round_number=1,
        state=state,
    )


def test_terminal_pass_is_retained_and_not_redispatched():
    runs = [_run(0, AgentRunState.VALIDATED_PASS), _run(1, AgentRunState.VALIDATED_PASS)]
    plan = remaining_work(UnitState.ASSESSING, runs, configured_agent_count=2)
    assert plan.agents_to_dispatch == []
    assert set(plan.retained_run_ids) == {r.run_id for r in runs}
    assert plan.discarded_run_ids == []
    assert plan.ready_for_adjudication


def test_mid_validation_retry_is_discarded_and_agent_redispatched():
    """The subtle case (research R8): assessed but not yet validated -> whole run
    discarded, agent re-dispatched from scratch."""
    partial = _run(0, AgentRunState.VALIDATING)
    complete = _run(1, AgentRunState.VALIDATED_PASS)
    plan = remaining_work(UnitState.ASSESSING, [partial, complete], configured_agent_count=2)

    assert plan.agents_to_dispatch == [0]
    assert partial.run_id in plan.discarded_run_ids
    assert complete.run_id in plan.retained_run_ids
    assert not plan.ready_for_adjudication


def test_mid_assessment_interruption_is_discarded():
    partial = _run(0, AgentRunState.ASSESSING)
    plan = remaining_work(UnitState.ASSESSING, [partial], configured_agent_count=2)
    assert 0 in plan.agents_to_dispatch
    assert 1 in plan.agents_to_dispatch
    assert partial.run_id in plan.discarded_run_ids


def test_validation_failed_terminal_is_retained_not_redispatched():
    failed = _run(0, AgentRunState.VALIDATION_FAILED_TERMINAL)
    passed = _run(1, AgentRunState.VALIDATED_PASS)
    plan = remaining_work(UnitState.ASSESSING, [failed, passed], configured_agent_count=2)
    assert plan.agents_to_dispatch == []
    assert plan.ready_for_adjudication


def test_no_runs_dispatches_all_agents():
    plan = remaining_work(UnitState.ASSESSING, [], configured_agent_count=2)
    assert plan.agents_to_dispatch == [0, 1]
    assert not plan.ready_for_adjudication


def test_terminal_unit_requires_no_resume_work():
    runs = [_run(0, AgentRunState.VALIDATING)]  # even a partial run doesn't matter
    plan = remaining_work(UnitState.DELIVERED, runs, configured_agent_count=2)
    assert plan.agents_to_dispatch == []
