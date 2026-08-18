"""Resolver node for workflow orchestration (spec 008)."""

from __future__ import annotations

from typing import Any

from agents.resolver.agent import ResolverAgent
from agents.resolver.schema import ResolverDecision
from core.llm_factory import ModelProvider
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.stage_events import StageEventLog
from shared.config.settings import Settings


async def resolver_node(
    state: dict[str, Any],
    agent: ResolverAgent,
    *,
    settings: Settings,
    provider: ModelProvider | None = None,
    stage_log: StageEventLog | None = None,
    cost_ledger: CostLedger | None = None,
) -> ResolverDecision:
    return await agent.resolve(
        question_text=state["question_text"],
        portal_url=state["portal_url"],
        runs=state["runs"],
        disagreement_points=state["disagreement_points"],
        settings=settings,
        provider=provider,
        stage_log=stage_log,
        cost_ledger=cost_ledger,
    )
