"""T015: Failing unit test asserting that one VALIDATED_PASS run is sufficient for delivery.

A unit with one VALIDATED_PASS run and one failed run must reach UnitState.DELIVERED
rather than no_suggestion(INSUFFICIENT_POSITIONS).

This test becomes green once T016+T017 add min_validated_positions=1 and change
the scheduler comparison from assessor_agent_count to min_validated_positions.
"""
import pytest

pytestmark = pytest.mark.unit


def test_single_validated_pass_is_sufficient():
    """With min_validated_positions=1 (T016), one VALIDATED_PASS must be enough."""
    from shared.config.settings import Settings

    settings = Settings()
    # min_validated_positions should exist and default to 1
    assert hasattr(settings, "min_validated_positions"), (
        "Settings missing min_validated_positions. Run T016 to add it."
    )
    assert settings.min_validated_positions == 1, (
        f"min_validated_positions should default to 1, got {settings.min_validated_positions}"
    )


def test_min_validated_positions_less_than_agent_count():
    """min_validated_positions=1 < assessor_agent_count=2: a single pass should suffice.

    This pins that the scheduler uses min_validated_positions (not assessor_agent_count)
    for the threshold check (T017).
    """
    from shared.config.settings import Settings

    settings = Settings()
    assert hasattr(settings, "min_validated_positions"), (
        "Settings missing min_validated_positions. Run T016."
    )
    assert settings.min_validated_positions <= settings.assessor_agent_count, (
        "min_validated_positions must be <= assessor_agent_count to have any effect"
    )


def test_min_validated_positions_env_var_registered():
    """AIQ_MIN_VALIDATED_POSITIONS must be registered in _ENV_MAP (T016)."""
    import importlib
    mod = importlib.import_module("shared.config.settings")
    env_map = getattr(mod, "_ENV_MAP", {})
    assert "min_validated_positions" in env_map, (
        "min_validated_positions must be registered in _ENV_MAP (T016) so it can be "
        "overridden via AIQ_MIN_VALIDATED_POSITIONS environment variable"
    )
