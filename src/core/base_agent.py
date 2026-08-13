"""Abstract Base Agent wrapper (core engine infrastructure).

Defines the contract for self-contained agent modules (Assessor, Validator, Adjudicator, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Abstract Base Agent for all agent modules."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description

    @abstractmethod
    async def run(self, input_data: InputT, **kwargs: Any) -> OutputT:
        """Executes reasoning logic & model invocation for the agent."""
        pass
