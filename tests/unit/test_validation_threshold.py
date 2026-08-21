"""T012: Failing unit test that pins the 0.70/three-check arithmetic.

Asserts that a validator judgment with two of three booleans true returns
passed=True, pinning fact 1 so the 0.70/three-check arithmetic can never
silently regress.

Initially fails until T013 sets validation_quality_threshold to 0.60.
"""
import pytest

pytestmark = pytest.mark.unit


def test_two_of_three_checks_should_pass():
    """2/3 = 0.667. With threshold=0.60, this passes. With threshold=0.70, it fails.

    This test documents the intent: two out of three quality booleans must be
    sufficient to pass validation (pin fact 1 from specs/010-recall-recovery/tasks.md).
    """
    from shared.config.settings import Settings

    settings = Settings()
    checks_passed = 2  # e.g. evidence_supports_answer=True, justification_consistent=True
    quality_score = checks_passed / 3.0  # = 0.6667

    # With threshold=0.60 (T013 change), this should pass
    assert quality_score >= settings.validation_quality_threshold, (
        f"2/3 quality score ({quality_score:.4f}) should meet the threshold "
        f"({settings.validation_quality_threshold}). "
        "If this fails, validation_quality_threshold is > 0.667 which means "
        "ALL THREE checks must pass — effectively requiring 100% perfection. "
        "Fix: lower threshold to 0.60 (T013)."
    )


def test_one_of_three_checks_should_fail():
    """1/3 = 0.333. Must stay below threshold even after T013."""
    from shared.config.settings import Settings

    settings = Settings()
    checks_passed = 1
    quality_score = checks_passed / 3.0  # = 0.333

    assert quality_score < settings.validation_quality_threshold, (
        f"1/3 quality score ({quality_score:.4f}) should NOT meet the threshold "
        f"({settings.validation_quality_threshold})."
    )


def test_three_of_three_checks_always_passes():
    """3/3 = 1.0. Must always pass regardless of threshold."""
    from shared.config.settings import Settings

    settings = Settings()
    checks_passed = 3
    quality_score = checks_passed / 3.0  # = 1.0

    assert quality_score >= settings.validation_quality_threshold, (
        "3/3 quality score (1.0) should always meet the threshold."
    )
