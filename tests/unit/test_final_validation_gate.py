"""Stub: delivery-time final validation gate was removed in T018.

The gate at scheduler.py:779-819 (FR-PF-030) was deleted because it re-ran
the same validation that had already passed the per-agent loop minutes earlier.
Any answer reaching delivery already holds at least min_validated_positions=1
VALIDATED_PASS result. The gate could only remove correct answers, never add ones.

See test_final_validation.py for retained per-agent validation loop coverage.
"""
import pytest

pytestmark = pytest.mark.unit


def test_failed_final_validation_reason_still_defined():
    """PrefillReason.FAILED_FINAL_VALIDATION must remain defined (historical rows use it)."""
    from shared.state.entities import PrefillReason
    assert hasattr(PrefillReason, "FAILED_FINAL_VALIDATION"), (
        "PrefillReason.FAILED_FINAL_VALIDATION must remain defined for historical DB rows"
    )
