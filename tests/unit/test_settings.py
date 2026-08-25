"""Unit tests for configuration settings loading and model parameter mapping."""

import pytest

from shared.config.settings import Settings, load_settings


@pytest.mark.unit
def test_default_settings_models():
    settings = Settings()
    assert settings.agent_1_model == "gemini-2.5-flash"
    assert settings.agent_2_model == "gemini-2.5-flash"
    assert settings.agent_models == ["gemini-2.5-flash", "gemini-2.5-flash"]
    assert settings.validator_model == "gemini-2.5-flash"


@pytest.mark.unit
def test_load_settings_from_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AIQ_AGENT_1_MODEL=gemini-2.5-flash\n"
        "AIQ_AGENT_2_MODEL=gemini-2.5-flash\n"
        "AIQ_VALIDATOR_MODEL=gemini-2.5-flash\n"
    )
    settings = load_settings(str(env_file))
    assert settings.agent_1_model == "gemini-2.5-flash"
    assert settings.agent_2_model == "gemini-2.5-flash"
    assert settings.agent_models == ["gemini-2.5-flash", "gemini-2.5-flash"]
    assert settings.validator_model == "gemini-2.5-flash"


@pytest.mark.unit
def test_load_settings_individual_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AIQ_AGENT_1_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("AIQ_AGENT_2_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("AIQ_VALIDATOR_MODEL", "gemini-2.5-flash")
    monkeypatch.delenv("AIQ_AGENT_MODELS", raising=False)
    
    settings = load_settings(str(tmp_path / "nonexistent.env"))
    assert settings.agent_models == ["gemini-2.5-flash", "gemini-2.5-flash"]
    assert settings.validator_model == "gemini-2.5-flash"


@pytest.mark.unit
def test_api_key_is_masked_everywhere(monkeypatch, tmp_path):
    # 1. Direct Settings masking
    s1 = Settings(api_key="super-secret-key")
    assert s1.api_key == "super-secret-key"
    assert s1.as_dict()["api_key"] == "***"

    s_empty = Settings(api_key="")
    assert s_empty.api_key == ""
    assert s_empty.as_dict()["api_key"] == ""

    # 2. Loaded from env
    monkeypatch.setenv("AIQ_API_KEY", "env-secret-token")
    s_loaded = load_settings(str(tmp_path / "nonexistent.env"))
    assert s_loaded.api_key == "env-secret-token"
    d_loaded = s_loaded.as_dict()
    assert d_loaded["api_key"] == "***"
    assert "env-secret-token" not in str(d_loaded)

