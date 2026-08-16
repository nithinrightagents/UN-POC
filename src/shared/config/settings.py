"""Typed settings object. Loaded from .env at process start (FR-072, FR-074).

Every operational parameter is here — nothing operational is a literal
elsewhere in the codebase. See contracts/configuration.md for the full
parameter table and defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields

from dotenv import dotenv_values


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _bool(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # --- Model provider (research R2) ---
    google_genai_use_vertexai: bool = True
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    agent_1_model: str = "gemini-2.5-flash"
    agent_2_model: str = "gemini-2.5-flash"
    agent_models: list[str] = field(default_factory=lambda: ["gemini-2.5-flash", "gemini-2.5-flash"])
    agent_temperatures: list[float] = field(default_factory=lambda: [0.2, 0.7])
    agent_prompt_profiles: list[str] = field(
        default_factory=lambda: ["literal", "inferential"]
    )
    validator_model: str = "gemini-2.5-flash"
    allow_identical_agent_models: bool = True

    # --- Independent assessment ---
    assessor_agent_count: int = 2
    batch_size: int = 50
    adjudication_retry_limit: int = 2
    validation_retry_limit: int = 2
    validation_quality_threshold: float = 0.70
    per_question_confidence_threshold: int = 10

    # --- Confidence acceptance gate ---
    confidence_acceptance_threshold: int = 75
    confidence_retry_limit: int = 1
    best_effort_confidence_ceiling: int = 74

    # --- Portal-level discrepancy ---
    portal_differing_answer_rate_threshold: float = 0.10
    portal_affirmative_rate_gap_threshold: float = 0.10

    # --- Link resolution ---
    kb_link_source_enabled: bool = True
    msq_link_source_enabled: bool = True
    url_resolution_mode: str = "historical_first"

    # --- Language handling ---
    # Language is detected inline by the assessor LLM itself as part of its
    # normal structured response (agents/assessor/agent.py) and compared
    # against this allow-list in orchestration/scheduler.py -- no separate
    # detection package or pre-fetch step.
    supported_languages: list[str] = field(default_factory=lambda: ["en"])
    language_decision_window_hours: int = 48

    # --- Crawling / access policy ---
    rate_limit_per_domain_rps: float = 0.5
    unresponsive_portal_attempt_bound: int = 3
    verification_attempt_bound: int = 3
    user_agent: str = "EKAP-AIQ-PoC/0.1"

    # --- Persistence ---
    database_path: str = "./data/aiq.db"

    # --- Review surface ---
    serve_host: str = "127.0.0.1"
    serve_port: int = 8080

    @property
    def resolution_order(self) -> list[str]:
        """The three named modes (FR-003)."""
        modes = {
            "historical_first": ["prior_survey_kb", "msq", "search"],
            "msq_first": ["msq", "prior_survey_kb", "search"],
            "search_first": ["search", "prior_survey_kb", "msq"],
        }
        return modes[self.url_resolution_mode]

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def defaults(cls) -> dict:
        return cls().as_dict()


_ENV_MAP = {
    "google_genai_use_vertexai": ("GOOGLE_GENAI_USE_VERTEXAI", _bool),
    "google_cloud_project": ("GOOGLE_CLOUD_PROJECT", str),
    "google_cloud_location": ("GOOGLE_CLOUD_LOCATION", str),
    "agent_1_model": ("AIQ_AGENT_1_MODEL", str),
    "agent_2_model": ("AIQ_AGENT_2_MODEL", str),
    "agent_models": ("AIQ_AGENT_MODELS", _split_csv),
    "agent_temperatures": ("AIQ_AGENT_TEMPERATURES", lambda v: [float(x) for x in _split_csv(v)]),
    "agent_prompt_profiles": ("AIQ_AGENT_PROMPT_PROFILES", _split_csv),
    "validator_model": ("AIQ_VALIDATOR_MODEL", str),
    "allow_identical_agent_models": ("AIQ_ALLOW_IDENTICAL_AGENT_MODELS", _bool),
    "assessor_agent_count": ("AIQ_ASSESSOR_AGENT_COUNT", int),
    "batch_size": ("AIQ_BATCH_SIZE", int),
    "adjudication_retry_limit": ("AIQ_ADJUDICATION_RETRY_LIMIT", int),
    "validation_retry_limit": ("AIQ_VALIDATION_RETRY_LIMIT", int),
    "validation_quality_threshold": ("AIQ_VALIDATION_QUALITY_THRESHOLD", float),
    "per_question_confidence_threshold": ("AIQ_PER_QUESTION_CONFIDENCE_THRESHOLD", int),
    "confidence_acceptance_threshold": ("AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD", int),
    "confidence_retry_limit": ("AIQ_CONFIDENCE_RETRY_LIMIT", int),
    "best_effort_confidence_ceiling": ("AIQ_BEST_EFFORT_CONFIDENCE_CEILING", int),
    "portal_differing_answer_rate_threshold": (
        "AIQ_PORTAL_DIFFERING_ANSWER_RATE_THRESHOLD",
        float,
    ),
    "portal_affirmative_rate_gap_threshold": (
        "AIQ_PORTAL_AFFIRMATIVE_RATE_GAP_THRESHOLD",
        float,
    ),
    "kb_link_source_enabled": ("AIQ_KB_LINK_SOURCE_ENABLED", _bool),
    "msq_link_source_enabled": ("AIQ_MSQ_LINK_SOURCE_ENABLED", _bool),
    "url_resolution_mode": ("AIQ_URL_RESOLUTION_MODE", str),
    "supported_languages": ("AIQ_SUPPORTED_LANGUAGES", _split_csv),
    "language_decision_window_hours": ("AIQ_LANGUAGE_DECISION_WINDOW_HOURS", int),
    "rate_limit_per_domain_rps": ("AIQ_RATE_LIMIT_PER_DOMAIN_RPS", float),
    "unresponsive_portal_attempt_bound": ("AIQ_UNRESPONSIVE_PORTAL_ATTEMPT_BOUND", int),
    "verification_attempt_bound": ("AIQ_VERIFICATION_ATTEMPT_BOUND", int),
    "user_agent": ("AIQ_USER_AGENT", str),
    "database_path": ("AIQ_DATABASE_PATH", str),
    "serve_host": ("AIQ_SERVE_HOST", str),
    "serve_port": ("AIQ_SERVE_PORT", int),
}


def load_settings(env_path: str = ".env") -> Settings:
    """Load settings from .env (if present) then process environment, falling
    back to dataclass defaults. Env vars take precedence over .env file, which
    takes precedence over the coded default (FR-072, FR-073)."""
    file_values = dotenv_values(env_path) if os.path.exists(env_path) else {}
    settings = Settings()

    # Check for individual agent model env vars (AIQ_AGENT_1_MODEL / AIQ_AGENT1_MODEL, etc.)
    a1_val = os.environ.get("AIQ_AGENT_1_MODEL", os.environ.get("AIQ_AGENT1_MODEL", file_values.get("AIQ_AGENT_1_MODEL", file_values.get("AIQ_AGENT1_MODEL"))))
    a2_val = os.environ.get("AIQ_AGENT_2_MODEL", os.environ.get("AIQ_AGENT2_MODEL", file_values.get("AIQ_AGENT_2_MODEL", file_values.get("AIQ_AGENT2_MODEL"))))

    if a1_val:
        settings.agent_1_model = a1_val
    if a2_val:
        settings.agent_2_model = a2_val

    for attr, (env_key, caster) in _ENV_MAP.items():
        raw = os.environ.get(env_key, file_values.get(env_key))
        if raw is None or raw == "":
            continue
        setattr(settings, attr, caster(raw))

    # If AIQ_AGENT_MODELS is not explicitly set, construct agent_models from individual params
    raw_models = os.environ.get("AIQ_AGENT_MODELS", file_values.get("AIQ_AGENT_MODELS"))
    if not raw_models:
        settings.agent_models = [settings.agent_1_model, settings.agent_2_model]

    return settings
