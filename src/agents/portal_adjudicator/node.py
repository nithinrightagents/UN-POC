"""Portal Adjudicator Agent Node — Graph step bridge mapping state to portal adjudicator."""

from __future__ import annotations

from typing import Any

from agents.portal_adjudicator.agent import PortalAdjudicatorAgent
from shared.state.entities import DiscrepancyCase
from shared.state.measures import PortalMeasures


async def portal_adjudicator_node(
    state: dict[str, Any],
    portal_adjudicator_agent: PortalAdjudicatorAgent,
    **kwargs,
) -> tuple[PortalMeasures, DiscrepancyCase | None]:
    return await portal_adjudicator_agent.run(state, **kwargs)


__all__ = ["portal_adjudicator_node"]
