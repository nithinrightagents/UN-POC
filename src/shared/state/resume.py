"""Resume semantics: (unit_state, agent_run_states) -> remaining work.

Pure function, no I/O — see FR-067a, FR-067b and data-model.md §Resume semantics.

The state machine is the only source of resumability truth. Terminal agent runs are
retained; non-terminal ones (including a run interrupted mid-validation-retry, which
has a completed assessment but incomplete validation) are discarded and re-run from
scratch. This is the single most subtle rule in the resume design: retaining the
assessment while re-running only validation would leave a validation result for an
assessment formed under a partially-applied retry addendum, which the pipeline never
otherwise produces.
"""

from __future__ import annotations

from dataclasses import dataclass

from .entities import (
    TERMINAL_AGENT_RUN_STATES,
    TERMINAL_UNIT_STATES,
    AgentRunState,
    AssessorAgentRun,
    UnitState,
)


@dataclass
class ResumePlan:
    unit_state: UnitState
    retained_run_ids: list[str]
    discarded_run_ids: list[str]
    agents_to_dispatch: list[int]
    ready_for_adjudication: bool


def remaining_work(
    unit_state: UnitState,
    agent_runs: list[AssessorAgentRun],
    configured_agent_count: int,
) -> ResumePlan:
    """Compute what work remains for one unit on resume.

    `agent_runs` is every AssessorAgentRun recorded for the unit's current round,
    regardless of state. Terminal runs are kept as-is; every other run's output is
    treated as discarded and that agent index is re-dispatched from scratch.
    """
    if unit_state in TERMINAL_UNIT_STATES:
        # Terminal units need no resume work at all.
        return ResumePlan(
            unit_state=unit_state,
            retained_run_ids=[r.run_id for r in agent_runs],
            discarded_run_ids=[],
            agents_to_dispatch=[],
            ready_for_adjudication=False,
        )

    terminal_by_agent: dict[int, AssessorAgentRun] = {}
    non_terminal: list[AssessorAgentRun] = []
    for run in agent_runs:
        if run.state in TERMINAL_AGENT_RUN_STATES:
            # Keep the latest terminal run per agent index.
            terminal_by_agent[run.agent_index] = run
        else:
            non_terminal.append(run)

    retained_ids = [r.run_id for r in terminal_by_agent.values()]
    discarded_ids = [r.run_id for r in non_terminal]

    covered_indices = set(terminal_by_agent.keys())
    all_indices = set(range(configured_agent_count))
    agents_to_dispatch = sorted(all_indices - covered_indices)

    ready = len(covered_indices) == configured_agent_count and not agents_to_dispatch

    return ResumePlan(
        unit_state=unit_state,
        retained_run_ids=retained_ids,
        discarded_run_ids=discarded_ids,
        agents_to_dispatch=agents_to_dispatch,
        ready_for_adjudication=ready,
    )


def is_agent_run_terminal(state: AgentRunState) -> bool:
    return state in TERMINAL_AGENT_RUN_STATES
