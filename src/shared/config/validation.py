"""Startup validation. The run is rejected — not warned — on any of these.

Rejection happens at startup rather than first use so a misconfiguration
cannot consume any of the shared per-domain budget before surfacing.
See contracts/configuration.md §Validation at startup.
"""

from __future__ import annotations

from .settings import Settings

_VALID_RESOLUTION_MODES = {"historical_first", "msq_first", "search_first"}


class ConfigurationError(ValueError):
    pass


def validate_settings(settings: Settings) -> None:
    errors: list[str] = []

    # Agent count below 1 rejects outright.
    if settings.assessor_agent_count < 1:
        errors.append(
            f"AIQ_ASSESSOR_AGENT_COUNT={settings.assessor_agent_count} must be >= 1"
        )

    # FR-API-014a: max concurrent assessment runs must be >= 1.
    if settings.max_concurrent_assessment_runs < 1:
        errors.append(
            f"AIQ_MAX_CONCURRENT_ASSESSMENT_RUNS={settings.max_concurrent_assessment_runs} must be >= 1 (FR-API-014a)"
        )

    # FR-PF-029: prefill confidence gap tolerance must be >= 0.
    if settings.prefill_confidence_gap_tolerance < 0:
        errors.append(
            f"AIQ_PREFILL_CONFIDENCE_GAP_TOLERANCE={settings.prefill_confidence_gap_tolerance} must be >= 0 (FR-PF-029)"
        )

    # FR-PF-041c: prefill run budget must be >= 0.0 (0.0 = uncapped).
    if settings.prefill_run_budget < 0.0:
        errors.append(
            f"AIQ_PREFILL_RUN_BUDGET={settings.prefill_run_budget} must be >= 0.0 (FR-PF-041c)"
        )

    # Confidence ceiling must be strictly below the acceptance threshold (FR-018).
    if settings.best_effort_confidence_ceiling >= settings.confidence_acceptance_threshold:
        errors.append(
            "AIQ_BEST_EFFORT_CONFIDENCE_CEILING "
            f"({settings.best_effort_confidence_ceiling}) must be below "
            f"AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD "
            f"({settings.confidence_acceptance_threshold})"
        )

    # Threshold ranges.
    for name, value, lo, hi in [
        ("AIQ_VALIDATION_QUALITY_THRESHOLD", settings.validation_quality_threshold, 0.0, 1.0),
        (
            "AIQ_PER_QUESTION_CONFIDENCE_THRESHOLD",
            settings.per_question_confidence_threshold,
            0,
            100,
        ),
        (
            "AIQ_PORTAL_DIFFERING_ANSWER_RATE_THRESHOLD",
            settings.portal_differing_answer_rate_threshold,
            0.0,
            1.0,
        ),
        (
            "AIQ_PORTAL_AFFIRMATIVE_RATE_GAP_THRESHOLD",
            settings.portal_affirmative_rate_gap_threshold,
            0.0,
            1.0,
        ),
        (
            "AIQ_HUMAN_DISCREPANCY_RATE_THRESHOLD",
            settings.human_discrepancy_rate_threshold,
            0.0,
            1.0,
        ),
        (
            "AIQ_CONFIDENCE_ACCEPTANCE_THRESHOLD",
            settings.confidence_acceptance_threshold,
            0,
            100,
        ),
        (
            "AIQ_DISAGREEMENT_LABEL_TEMPERATURE",
            settings.disagreement_label_temperature,
            0.0,
            2.0,
        ),
    ]:
        if not (lo <= value <= hi):
            errors.append(f"{name}={value} must be within [{lo}, {hi}]")

    # Resolution mode must be one of the three named modes.
    if settings.url_resolution_mode not in _VALID_RESOLUTION_MODES:
        errors.append(
            f"AIQ_URL_RESOLUTION_MODE={settings.url_resolution_mode!r} must be one "
            f"of {sorted(_VALID_RESOLUTION_MODES)}"
        )

    # Model-list length must match agent count.
    if len(settings.agent_models) != settings.assessor_agent_count:
        errors.append(
            f"AIQ_AGENT_MODELS has {len(settings.agent_models)} entries, expected "
            f"{settings.assessor_agent_count} (== AIQ_ASSESSOR_AGENT_COUNT)"
        )
    if settings.agent_temperatures and len(settings.agent_temperatures) != settings.assessor_agent_count:
        errors.append(
            f"AIQ_AGENT_TEMPERATURES has {len(settings.agent_temperatures)} entries, "
            f"expected {settings.assessor_agent_count}"
        )
    if settings.agent_prompt_profiles and len(settings.agent_prompt_profiles) != settings.assessor_agent_count:
        errors.append(
            f"AIQ_AGENT_PROMPT_PROFILES has {len(settings.agent_prompt_profiles)} "
            f"entries, expected {settings.assessor_agent_count}"
        )

    # Identical models require the explicit override (FR-011 independence risk).
    if len(set(settings.agent_models)) == 1 and not settings.allow_identical_agent_models:
        errors.append(
            "All entries in AIQ_AGENT_MODELS are identical. This satisfies FR-011 only "
            "with AIQ_ALLOW_IDENTICAL_AGENT_MODELS=true, which then relies on "
            "temperature/prompt-profile divergence alone."
        )

    # Agents identical on every axis at once is rejected unconditionally --
    # at that point there is no divergence left for FR-011 to stand on.
    # Exempted when there is only one assessor agent (2026-08-20 goal): FR-011
    # independence is a cross-agent property, so with a single agent there is
    # no second agent to diverge from and the check is vacuous rather than a
    # real independence violation.
    if (
        settings.assessor_agent_count > 1
        and len(set(settings.agent_models)) == 1
        and len(set(settings.agent_temperatures)) == 1
        and len(set(settings.agent_prompt_profiles)) == 1
    ):
        errors.append(
            "Assessor Agents are identical on every axis (model, temperature, and "
            "prompt profile) — no divergence remains for FR-011 independence."
        )

    if not settings.google_cloud_project:
        errors.append("GOOGLE_CLOUD_PROJECT is required and must be non-empty")
    if not settings.google_cloud_location:
        errors.append("GOOGLE_CLOUD_LOCATION is required and must be non-empty")

    # No link source available at all (FR-121, FR-122).
    if not settings.kb_link_source_enabled and not settings.msq_link_source_enabled:
        # search is always available as the final fallback, so this alone is not fatal,
        # but flag it since it means every link resolves via live search only.
        pass

    if errors:
        raise ConfigurationError(
            "Configuration rejected at startup:\n  - " + "\n  - ".join(errors)
        )
