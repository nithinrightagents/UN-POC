"""Terminal-state exhaustiveness for the unit state machine — SC-009.

Asserts no path leaves the machine without a delivered answer or a recorded
reason (unassessable / no_suggestion).
"""

import pytest

from shared.state.entities import TERMINAL_UNIT_STATES, UnitState
from shared.state.unit_state import (
    IllegalTransitionError,
    _ALLOWED,
    assert_exhaustive_terminal_coverage,
    can_transition,
    is_terminal,
    transition,
)

pytestmark = pytest.mark.unit


def test_exactly_four_terminal_states():
    assert TERMINAL_UNIT_STATES == {
        UnitState.DELIVERED,
        UnitState.ESCALATED,
        UnitState.UNASSESSABLE,
        UnitState.NO_SUGGESTION,
    }


def test_terminal_states_have_no_outgoing_transitions():
    for state in TERMINAL_UNIT_STATES:
        for other in UnitState:
            assert not can_transition(state, other)


def test_every_prefill_terminal_is_reachable():
    assert_exhaustive_terminal_coverage()


def test_escalated_has_zero_inbound_edges():
    for src, targets in _ALLOWED.items():
        assert UnitState.ESCALATED not in targets, f"{src} has inbound transition to ESCALATED"


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransitionError):
        transition(UnitState.PENDING, UnitState.DELIVERED)


def test_legal_transition_succeeds():
    assert transition(UnitState.PENDING, UnitState.RESOLVING_LINK) == UnitState.RESOLVING_LINK


def test_delivered_is_terminal():
    assert is_terminal(UnitState.DELIVERED)


def test_no_suggestion_is_terminal():
    assert is_terminal(UnitState.NO_SUGGESTION)


def test_pending_is_not_terminal():
    assert not is_terminal(UnitState.PENDING)


@pytest.mark.parametrize(
    "path",
    [
        [UnitState.PENDING, UnitState.RESOLVING_LINK, UnitState.UNASSESSABLE],
        [
            UnitState.PENDING,
            UnitState.RESOLVING_LINK,
            UnitState.RESOLVED,
            UnitState.NO_SUGGESTION,
        ],
        [
            UnitState.PENDING,
            UnitState.RESOLVING_LINK,
            UnitState.RESOLVED,
            UnitState.ASSESSING,
            UnitState.ADJUDICATING,
            UnitState.DELIVERED,
        ],
        [
            UnitState.PENDING,
            UnitState.RESOLVING_LINK,
            UnitState.RESOLVED,
            UnitState.ASSESSING,
            UnitState.ADJUDICATING,
            UnitState.NO_SUGGESTION,
        ],
        [
            UnitState.PENDING,
            UnitState.RESOLVING_LINK,
            UnitState.RESOLVED,
            UnitState.ASSESSING,
            UnitState.NO_SUGGESTION,
        ],
    ],
)
def test_realistic_paths_are_all_legal(path):
    for a, b in zip(path, path[1:]):
        transition(a, b)
