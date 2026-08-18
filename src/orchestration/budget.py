"""Run budget enforcement for prefill generation (spec 008 FR-PF-041)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunBudget:
    """In-process cost budget for a prefill batch run."""

    limit: float = 0.0  # 0.0 = uncapped
    spent: float = 0.0  # in-process accumulator

    def record(self, cost: float) -> None:
        """Record model spend against this run's budget."""
        if cost > 0.0:
            self.spent += cost

    def exhausted(self) -> bool:
        """True if a positive limit exists and accumulated spend meets or exceeds it."""
        if self.limit <= 0.0:
            return False
        return self.spent >= self.limit
