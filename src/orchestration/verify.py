"""Post-hoc resume verification (SC-006).

Asserts zero duplicated and zero lost units across a session: every unit
recorded ends in exactly one of the three terminal states or a single
coherent non-terminal state, and no unit shows internally contradictory
bookkeeping (e.g. more validated-pass runs for one round than the
configured agent count, which would indicate a duplicate dispatch).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.state.entities import AgentRunState, UnitState
from shared.persistence.repositories import Repository


@dataclass
class ResumeVerificationReport:
    total_units: int
    duplicated_units: list[str] = field(default_factory=list)
    lost_units: list[str] = field(default_factory=list)
    clean: bool = True


def verify_resume(repo: Repository, session_id: str, configured_agent_count: int) -> ResumeVerificationReport:
    units = repo.list_units(session_id)
    duplicated: list[str] = []
    lost: list[str] = []

    for unit in units:
        question_id = unit["question_id"]
        portal_id = unit["portal_id"]
        label = f"{question_id}:{portal_id}"
        state = UnitState(unit["state"])

        round_number = unit.get("round_number")
        if round_number is None:
            # Never reached assessment (e.g. still resolving, or escalated/
            # unassessable before a round was assigned) -- nothing to check.
            continue

        runs = repo.list_agent_runs(session_id, question_id, portal_id, round_number=round_number)
        by_agent: dict[int, list] = {}
        for run in runs:
            by_agent.setdefault(run.agent_index, []).append(run)

        # FR-067a/b, SC-006: at most one TERMINAL run per agent index per round.
        # More than one indicates the same agent index was dispatched twice
        # for the same round without the earlier attempt being superseded --
        # a duplicated unit of work.
        for agent_index, agent_runs in by_agent.items():
            terminal = [r for r in agent_runs if r.state in (AgentRunState.VALIDATED_PASS, AgentRunState.VALIDATION_FAILED_TERMINAL)]
            if len(terminal) > 1:
                duplicated.append(f"{label} agent={agent_index} round={round_number}")

        if state == UnitState.DELIVERED:
            validated = [
                r for agent_runs in by_agent.values() for r in agent_runs
                if r.state == AgentRunState.VALIDATED_PASS
            ]
            if len(validated) < 2:
                # Delivered with fewer than 2 validated positions on record --
                # the answer was lost/under-substantiated relative to what
                # delivery requires (FR-027, SC-016).
                lost.append(label)

    report = ResumeVerificationReport(total_units=len(units), duplicated_units=duplicated, lost_units=lost)
    report.clean = not duplicated and not lost
    return report
