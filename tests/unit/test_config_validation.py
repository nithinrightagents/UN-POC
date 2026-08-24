"""Unit tests for configuration validation rules (including spec 012 threshold checks)."""

from __future__ import annotations

import pytest

from shared.config.settings import Settings
from shared.config.validation import ConfigurationError, validate_settings

pytestmark = pytest.mark.unit

_REQUIRED = {"google_cloud_project": "test-project", "google_cloud_location": "us-central1"}


def test_human_discrepancy_rate_threshold_valid_range():
    # 0.0 and 1.0 are valid boundary values
    validate_settings(Settings(human_discrepancy_rate_threshold=0.0, **_REQUIRED))
    validate_settings(Settings(human_discrepancy_rate_threshold=0.05, **_REQUIRED))
    validate_settings(Settings(human_discrepancy_rate_threshold=1.0, **_REQUIRED))


def test_human_discrepancy_rate_threshold_invalid_values_rejected():
    # 50 (e.g. 50% written without decimal) must be rejected
    with pytest.raises(ConfigurationError, match="AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD"):
        validate_settings(Settings(human_discrepancy_rate_threshold=50.0, **_REQUIRED))

    # -0.1 must be rejected
    with pytest.raises(ConfigurationError, match="AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD"):
        validate_settings(Settings(human_discrepancy_rate_threshold=-0.1, **_REQUIRED))

    # 1.01 must be rejected
    with pytest.raises(ConfigurationError, match="AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD"):
        validate_settings(Settings(human_discrepancy_rate_threshold=1.01, **_REQUIRED))
