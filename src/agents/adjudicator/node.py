"""Adjudicator Agent Node — Graph step bridge mapping state to adjudicator agent."""

from __future__ import annotations

from typing import Any

from agents.adjudicator.agent import AdjudicationDecision, AdjudicatorAgent


async def adjudicator_node(
    state: dict[str, Any],
    adjudicator_agent: AdjudicatorAgent,
    **kwargs,
) -> AdjudicationDecision:
    return await adjudicator_agent.run(state, **kwargs)


__all__ = ["adjudicator_node"]
