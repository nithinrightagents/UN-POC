"""Resolver decision schemas and models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolverDecision:
    disagreement_characterization: str   # FR-PF-026b
    selected_run_id: str | None          # None ⟺ undetermined (FR-PF-026d)
    reasoning: str
    confidence: int | None
    undetermined: bool

    def __post_init__(self) -> None:
        if self.undetermined != (self.selected_run_id is None):
            raise ValueError("undetermined must be True iff selected_run_id is None")
