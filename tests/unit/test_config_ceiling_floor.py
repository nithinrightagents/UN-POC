"""Regression test for the config invariant Step 2 broke:
AIQ_BEST_EFFORT_CONFIDENCE_CEILING must stay strictly below
AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD (config/validation.py:47), or the app
fails validate_settings() at startup -- exactly what happened when Step 2
lowered the acceptance threshold from 75 to 60 without lowering the ceiling
from 74. The benchmark script never caught this because it doesn't call
validate_settings(); the CLI, API, and portal all do.
"""

from __future__ import annotations

import pytest

from shared.config.settings import Settings, load_settings
from shared.config.validation import ConfigurationError, validate_settings

pytestmark = pytest.mark.unit


_REQUIRED = {"google_cloud_project": "test-project", "google_cloud_location": "us-central1"}


def test_default_settings_pass_validation():
    validate_settings(Settings(**_REQUIRED))


def test_env_loaded_settings_pass_validation():
    # Catches .env / dataclass-default drift that Settings() alone cannot --
    # this is the exact path (load_settings(), not Settings()) that the
    # real CLI/API/portal entrypoints use at startup.
    validate_settings(load_settings())


def test_ceiling_at_or_above_threshold_is_rejected():
    with pytest.raises(ConfigurationError):
        validate_settings(
            Settings(best_effort_confidence_ceiling=74, confidence_acceptance_threshold=60, **_REQUIRED)
        )


def test_ceiling_below_threshold_is_accepted():
    validate_settings(
        Settings(best_effort_confidence_ceiling=55, confidence_acceptance_threshold=60, **_REQUIRED)
    )
