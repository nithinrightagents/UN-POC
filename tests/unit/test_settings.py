"""Unit tests for configuration settings loading and model parameter mapping."""

import pytest
from shared.config.settings import Settings, load_settings


@pytest.mark.unit
def test_default_settings_models():
    settings = Settings()
    assert settings.agent_1_model == "gemini-3.5-flash"
    assert settings.agent_2_model == "gemini-3.5-flash"
    assert settings.agent_models == ["gemini-3.5-flash", "gemini-3.5-flash"]
    assert settings.validator_model == "gemini-3.5-flash"


@pytest.mark.unit
def test_load_settings_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AIQ_AGENT_1_MODEL=gemini-3.5-flash\n"
        "AIQ_AGENT_2_MODEL=gemini-3.5-flash\n"
        "AIQ_VALIDATOR_MODEL=gemini-3.5-flash\n"
    )
    settings = load_settings(str(env_file))
    assert settings.agent_1_model == "gemini-3.5-flash"
    assert settings.agent_2_model == "gemini-3.5-flash"
    assert settings.agent_models == ["gemini-3.5-flash", "gemini-3.5-flash"]
    assert settings.validator_model == "gemini-3.5-flash"


@pytest.mark.unit
def test_load_settings_individual_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AIQ_AGENT_1_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("AIQ_AGENT_2_MODEL", "gemini-3.5-flash")
    monkeypatch.setenv("AIQ_VALIDATOR_MODEL", "gemini-3.5-flash")
    monkeypatch.delenv("AIQ_AGENT_MODELS", raising=False)
    
    settings = load_settings(str(tmp_path / "nonexistent.env"))
    assert settings.agent_models == ["gemini-3.5-flash", "gemini-3.5-flash"]
    assert settings.validator_model == "gemini-3.5-flash"
