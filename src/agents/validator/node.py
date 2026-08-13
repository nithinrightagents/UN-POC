"""Validator Agent Node — Graph step bridge mapping state to validator agent."""

from __future__ import annotations

from typing import Any

from agents.validator.agent import ValidatorAgent
from shared.state.entities import ValidationResult


async def validator_node(
    state: dict[str, Any],
    validator_agent: ValidatorAgent,
    **kwargs,
) -> ValidationResult:
    """Node step bridge that executes the validator agent."""
    return await validator_agent.run(state, **kwargs)


__all__ = ["validator_node"]
