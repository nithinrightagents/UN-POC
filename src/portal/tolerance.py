"""Tolerance resolution for SurveyCycle and discrepancy comparisons (spec 012).

This module is the single place a tolerance is resolved across the system.
Per-project tolerance (`SurveyCycle.discrepancy_rate_threshold`) takes precedence
over the process-wide default (`settings.human_discrepancy_rate_threshold`).

Read per call -- never cached at module level (SC-009).
"""

from __future__ import annotations

from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def effective_tolerance(
    repo: Repository, cycle_id: str | None, settings: Settings
) -> float:
    """Returns the discrepancy rate threshold in force for the given cycle_id.
    If cycle_id is specified and that cycle has an explicit discrepancy_rate_threshold set,
    that value is returned. Otherwise, returns settings.human_discrepancy_rate_threshold.
    """
    if cycle_id:
        cycle = repo.get_cycle(cycle_id)
        if cycle and cycle.discrepancy_rate_threshold is not None:
            return float(cycle.discrepancy_rate_threshold)
    return float(settings.human_discrepancy_rate_threshold)
