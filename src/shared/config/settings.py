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
    # Gemini Developer API key (used only when google_genai_use_vertexai is
    # false -- e.g. for model lines not yet served on the Vertex AI endpoint).
    google_api_key: str = ""
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
    adjudication_retry_limit: int = 2  # Deprecated in spec 008 (intra-run retries superseded by resolver); kept for backwards compatibility
    validation_retry_limit: int = 2
    validation_quality_threshold: float = 0.60  # score is computed over exactly 3 booleans: 1/3=0.333, 2/3=0.667, 3/3=1.0 — 0.70 meant all-three-must-pass (effectively 100%); 0.60 means two-of-three-must-pass
    per_question_confidence_threshold: int = 10
    # T016: minimum number of VALIDATED_PASS runs required before a position is delivered.
    # assessor_agent_count=2 agents still both run; this controls how many must survive
    # validation, not how many run. 1 means one validated position is sufficient.
    min_validated_positions: int = 1
    max_link_resolution_retries: int = 3  # Maximum attempts for link re-resolution when runs flag URL wrong/unreachable (T024)

    # --- Confidence acceptance gate ---
    confidence_acceptance_threshold: int = 60  # lowered from 75: a well-evidenced answer the model honestly scores 60-74 now proceeds (T021)
    confidence_retry_limit: int = 1
    best_effort_confidence_ceiling: int = 55
    # A negative (No) answer that PASSED validation -- a second model
    # confirmed the anchor supports it -- is more trustworthy than the raw
    # evidence-weight number reads, since thin-evidence calibration
    # (prompts/profiles.py) scores every anchored negative in the 30-65
    # range regardless of how well it was confirmed. Applied only to
    # validated negatives at prefill-write time (never in the prompt, never
    # for best-effort/needs_human_review rows) so it can't push an
    # unconfirmed answer above best_effort_confidence_ceiling.
    validated_negative_confidence_floor: int = 55

    # --- Portal-level discrepancy ---
    portal_differing_answer_rate_threshold: float = 0.10
    portal_affirmative_rate_gap_threshold: float = 0.10

    # --- Human Assessor A/B discrepancy (spec 005) ---
    # Deliberately separate from portal_differing_answer_rate_threshold above:
    # that setting governs the AI-vs-AI consensus threshold, while
    # this one governs the human blind-assessor pipeline, whose
    # transcript-specified trigger is explicitly ">5%" (spec 005 Section 3.4).
    human_discrepancy_rate_threshold: float = 0.05

    # --- Disagreement Labelling (spec 017) ---
    # Disabling labelling suppresses dispatch only. Existing labels stay readable,
    # because a stored label is history and does not depend on the feature being switched on.
    disagreement_labelling_enabled: bool = True
    disagreement_label_model: str = "gemini-2.5-flash-lite"
    disagreement_label_temperature: float = 0.0

    # --- Link resolution ---
    kb_link_source_enabled: bool = True
    msq_link_source_enabled: bool = True
    url_resolution_mode: str = "historical_first"

    # --- Language handling ---
    # Language is detected inline by the assessor LLM itself as part of its
    # normal structured response (agents/assessor/agent.py) and compared
    # against this allow-list in orchestration/scheduler.py -- no separate
    # detection package or pre-fetch step.
    supported_languages: list[str] = field(default_factory=lambda: ["en", "da"])
    language_decision_window_hours: int = 48

    # --- Crawling / access policy ---
    rate_limit_per_domain_rps: float = 0.5
    unresponsive_portal_attempt_bound: int = 3
    verification_attempt_bound: int = 3
    user_agent: str = "EKAP-AIQ-PoC/0.1"
    # 15s (the original hardcoded default) sits right at the observed
    # domcontentloaded time for legitimately slow but reachable government
    # sites (e.g. justitsministeriet.dk measured at ~13.7s); 25s (the next
    # value tried) still isn't enough for every real site either -- a
    # direct repro against opendata.dk timed out twice at 25s and needed
    # ~44s on the attempt that did complete. Both are nondeterministic
    # "unreachable: timeout" outcomes caused by real network/server latency
    # on a genuinely live page, independent of which country's portal is
    # being fetched -- not an outage, just a slow one.
    page_navigation_timeout_ms: int = 45000

    # --- Persistence ---
    database_path: str = "./data/aiq.db"

    # --- Review surface ---
    serve_host: str = "127.0.0.1"
    serve_port: int = 8080

    # --- Programmatic interface (spec 007) ---
    api_key: str = ""
    max_concurrent_assessment_runs: int = 2

    # --- Prefill pipeline (spec 008) ---
    prefill_confidence_gap_tolerance: int = 10
    prefill_run_budget: float = 0.0

    # --- Search / Firecrawl ---
    firecrawl_api_key: str = ""
    serper_api_key: str = ""

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
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        if d.get("api_key"):
            d["api_key"] = "***"
        if d.get("google_api_key"):
            d["google_api_key"] = "***"
        return d

    @classmethod
    def defaults(cls) -> Settings:
        return cls()


_ENV_MAP = {
    "google_genai_use_vertexai": ("GOOGLE_GENAI_USE_VERTEXAI", _bool),
    "google_cloud_project": ("GOOGLE_CLOUD_PROJECT", str),
    "google_cloud_location": ("GOOGLE_CLOUD_LOCATION", str),
    "google_api_key": ("GOOGLE_API_KEY", str),
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
    "min_validated_positions": ("AIQ_MIN_VALIDATED_POSITIONS", int),
    "confidence_acceptance_threshold": ("AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD", int),
    "confidence_retry_limit": ("AIQ_CONFIDENCE_RETRY_LIMIT", int),
    "best_effort_confidence_ceiling": ("AIQ_BEST_EFFORT_CONFIDENCE_CEILING", int),
    "validated_negative_confidence_floor": ("AIQ_VALIDATED_NEGATIVE_CONFIDENCE_FLOOR", int),
    "portal_differing_answer_rate_threshold": (
        "AIQ_PORTAL_DIFFERING_ANSWER_RATE_THRESHOLD",
        float,
    ),
    "portal_affirmative_rate_gap_threshold": (
        "AIQ_PORTAL_AFFIRMATIVE_RATE_GAP_THRESHOLD",
        float,
    ),
    "human_discrepancy_rate_threshold": (
        "AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD",
        float,
    ),
    "disagreement_labelling_enabled": ("AIQ_DISAGREEMENT_LABELLING_ENABLED", _bool),
    "disagreement_label_model": ("AIQ_DISAGREEMENT_LABEL_MODEL", str),
    "disagreement_label_temperature": ("AIQ_DISAGREEMENT_LABEL_TEMPERATURE", float),
    "kb_link_source_enabled": ("AIQ_KB_LINK_SOURCE_ENABLED", _bool),
    "msq_link_source_enabled": ("AIQ_MSQ_LINK_SOURCE_ENABLED", _bool),
    "url_resolution_mode": ("AIQ_URL_RESOLUTION_MODE", str),
    "supported_languages": ("AIQ_SUPPORTED_LANGUAGES", _split_csv),
    "language_decision_window_hours": ("AIQ_LANGUAGE_DECISION_WINDOW_HOURS", int),
    "rate_limit_per_domain_rps": ("AIQ_RATE_LIMIT_PER_DOMAIN_RPS", float),
    "unresponsive_portal_attempt_bound": ("AIQ_UNRESPONSIVE_PORTAL_ATTEMPT_BOUND", int),
    "verification_attempt_bound": ("AIQ_VERIFICATION_ATTEMPT_BOUND", int),
    "user_agent": ("AIQ_USER_AGENT", str),
    "page_navigation_timeout_ms": ("AIQ_PAGE_NAVIGATION_TIMEOUT_MS", int),
    "database_path": ("AIQ_DATABASE_PATH", str),
    "serve_host": ("AIQ_SERVE_HOST", str),
    "serve_port": ("AIQ_SERVE_PORT", int),
    "api_key": ("AIQ_API_KEY", str),
    "max_concurrent_assessment_runs": ("AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS", int),
    "prefill_confidence_gap_tolerance": ("AIQ_PREFILL_CONFIDENCE_GAP_TOLERANCE", int),
    "prefill_run_budget": ("AIQ_PREFILL_RUN_BUDGET", float),
    "firecrawl_api_key": ("FIRECRAWL_API_KEY", str),
    "serper_api_key": ("SERPER_API_KEY", str),
}


def _sync_langsmith_env(env_vars: dict[str, str | None]) -> None:
    """Ensure LangSmith environment variables in os.environ are consistently set and normalized."""
    tracing_val = env_vars.get("LANGCHAIN_TRACING_V2") or env_vars.get("LANGSMITH_TRACING")
    if tracing_val:
        normalized_tracing = "true" if tracing_val.strip().lower() in ("true", "1", "yes", "on") else "false"
        os.environ.setdefault("LANGCHAIN_TRACING_V2", normalized_tracing)
        if os.environ.get("LANGCHAIN_TRACING_V2") != normalized_tracing:
            os.environ["LANGCHAIN_TRACING_V2"] = normalized_tracing

    api_key = env_vars.get("LANGSMITH_API_KEY")
    if api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", api_key.strip())

    project = env_vars.get("LANGSMITH_PROJECT") or env_vars.get("LANGCHAIN_PROJECT")
    if project:
        os.environ.setdefault("LANGSMITH_PROJECT", project.strip())

    endpoint = env_vars.get("LANGCHAIN_ENDPOINT") or env_vars.get("LANGSMITH_ENDPOINT")
    if endpoint:
        os.environ.setdefault("LANGCHAIN_ENDPOINT", endpoint.strip())

    try:
        from langsmith.utils import get_env_var
        get_env_var.cache_clear()
    except Exception:
        pass


def load_settings(env_path: str = ".env") -> Settings:
    """Load settings from .env (if present) then process environment, falling
    back to dataclass defaults. Env vars take precedence over .env file, which
    takes precedence over the coded default (FR-072, FR-073)."""
    file_values = dotenv_values(env_path) if os.path.exists(env_path) else {}

    # Sync tracing variables to os.environ for LangSmith SDK
    _sync_langsmith_env(file_values)

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
