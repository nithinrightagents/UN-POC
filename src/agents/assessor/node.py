"""Assessor Agent Node — Graph step bridge mapping state to agent."""

from __future__ import annotations

from typing import Any

from agents.assessor.agent import AssessorAgent
from shared.state.entities import AssessorAgentRun
from shared.state.schemas import AssessorAgentInput


async def assessor_node(
    state: dict[str, Any],
    agent_index: int,
    round_number: int,
    assessor_agent: AssessorAgent,
    **kwargs,
) -> AssessorAgentRun:
    """Node step bridge that maps state dict to AssessorAgentInput and executes agent."""
    input_data = AssessorAgentInput(
        session_id=state["session_id"],
        agent_index=agent_index,
        round_number=round_number,
        question=state["question"],
        portal=state["portal"],
        addendum=state.get("addendum"),
    )
    return await assessor_agent.run(input_data, **kwargs)


__all__ = ["assessor_node"]
