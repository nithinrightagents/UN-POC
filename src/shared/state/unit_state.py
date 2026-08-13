"""The question-portal unit state machine.

Exactly three terminal states exist: DELIVERED, ESCALATED, UNASSESSABLE. This is a
structural guarantee behind SC-009 — a unit cannot leave the machine without either a
delivered answer or a recorded reason. See data-model.md §The unit state machine.

Pure logic, no I/O.
"""

from __future__ import annotations

from .entities import TERMINAL_UNIT_STATES, UnitState

# Allowed transitions: from_state -> set of legal to_states.
_ALLOWED: dict[UnitState, set[UnitState]] = {
    UnitState.PENDING: {UnitState.RESOLVING_LINK},
    UnitState.RESOLVING_LINK: {UnitState.RESOLVED, UnitState.UNASSESSABLE},
    UnitState.RESOLVED: {UnitState.ASSESSING, UnitState.ESCALATED},
    UnitState.ASSESSING: {UnitState.ADJUDICATING, UnitState.ESCALATED},
    UnitState.ADJUDICATING: {UnitState.DELIVERED, UnitState.RETRYING, UnitState.ESCALATED},
    UnitState.RETRYING: {UnitState.ADJUDICATING, UnitState.ESCALATED},
    UnitState.DELIVERED: set(),
    UnitState.ESCALATED: set(),
    UnitState.UNASSESSABLE: set(),
}


class IllegalTransitionError(ValueError):
    pass


def is_terminal(state: UnitState) -> bool:
    return state in TERMINAL_UNIT_STATES


def can_transition(from_state: UnitState, to_state: UnitState) -> bool:
    return to_state in _ALLOWED.get(from_state, set())


def transition(from_state: UnitState, to_state: UnitState) -> UnitState:
    """Validate and perform a transition. Raises IllegalTransitionError otherwise."""
    if not can_transition(from_state, to_state):
        raise IllegalTransitionError(
            f"{from_state.value} -> {to_state.value} is not a legal transition"
        )
    return to_state


def assert_exhaustive_terminal_coverage() -> None:
    """Every reachable non-terminal state must have at least one path to a terminal
    state, and every terminal state must have zero outgoing transitions. Called by
    tests/unit/domain/test_unit_state.py — see SC-009.
    """
    for state in UnitState:
        if is_terminal(state):
            assert _ALLOWED[state] == set(), f"{state} is terminal but has transitions"
        else:
            assert _ALLOWED[state], f"{state} is non-terminal but has no transitions"

    # BFS reachability: every non-terminal state must reach a terminal state.
    for start in UnitState:
        if is_terminal(start):
            continue
        seen = {start}
        frontier = [start]
        reached_terminal = False
        while frontier:
            cur = frontier.pop()
            for nxt in _ALLOWED.get(cur, set()):
                if is_terminal(nxt):
                    reached_terminal = True
                    break
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
            if reached_terminal:
                break
        assert reached_terminal, f"{start} cannot reach any terminal state"
