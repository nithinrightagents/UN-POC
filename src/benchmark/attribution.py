"""Pipeline stage attribution for link resolution and assessment failures.

Implements FR-LD-022, FR-LD-023, FR-LD-024, FR-LD-025, FR-LD-026, FR-LD-027, FR-LD-028.
Attributes every divergence to a single stage from a closed set with that stage's stated reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from benchmark.trace import UnitResolutionTrace
from benchmark.urlmatch import urls_equivalent
from shared.state.entities import GroundTruthAnswer


class PipelineStage(str, Enum):
    PRIOR_SURVEY_KB = "prior_survey_kb"
    MSQ = "msq"
    SITEMAP = "sitemap"
    SEARCH = "search"
    PORTAL_DEFAULT = "portal_default"
    LOCUS_GATE = "locus_gate"
    OFF_PORTAL_ESCALATION = "off_portal_escalation"
    PAGE_RETRIEVAL = "page_retrieval"
    ASSESSMENT = "assessment"
    ENVIRONMENT = "environment"


@dataclass
class StageAttribution:
    stage: PipelineStage
    reason: str
    source_details: list[dict] = field(default_factory=list)
    refused_url: str | None = None
    escalation_status: str | None = None  # "never_widened" | "widened_and_failed" | "not_applicable"
    page_truncated: bool = False
    excess_chars: int = 0


def _is_environment_error(reason_str: str | None) -> bool:
    if not reason_str:
        return False
    r = reason_str.lower()
    return any(
        kw in r
        for kw in (
            "unreachable",
            "timeout",
            "timed out",
            "connection refused",
            "quota",
            "rate limit",
            "429",
            "503",
            "502",
            "network error",
            "econnrefused",
        )
    )


def _map_source_to_stage(source_name: str | None) -> PipelineStage:
    if not source_name:
        return PipelineStage.SEARCH
    s = source_name.lower()
    if "sitemap" in s:
        return PipelineStage.SITEMAP
    if "prior_survey" in s or "kb" in s:
        return PipelineStage.PRIOR_SURVEY_KB
    if "msq" in s:
        return PipelineStage.MSQ
    if "portal_default" in s or "homepage" in s:
        return PipelineStage.PORTAL_DEFAULT
    if "search" in s:
        return PipelineStage.SEARCH
    return PipelineStage.SEARCH


def attribute(
    trace: UnitResolutionTrace, reference: GroundTruthAnswer
) -> StageAttribution:
    """Attribute the outcome of a unit to a responsible pipeline stage."""
    # 1. Environmental failures (FR-LD-028)
    if trace.portal_unreachable:
        return StageAttribution(
            stage=PipelineStage.ENVIRONMENT,
            reason="Portal or target host unreachable during run",
            escalation_status="not_applicable",
        )

    for item in trace.resolution_history:
        rej = item.get("rejection_reason")
        if rej and _is_environment_error(rej):
            return StageAttribution(
                stage=PipelineStage.ENVIRONMENT,
                reason=f"Environmental failure during link resolution: {rej}",
                source_details=list(trace.resolution_history),
                escalation_status="not_applicable",
            )

    if trace.prefill_reason and _is_environment_error(trace.prefill_reason):
        return StageAttribution(
            stage=PipelineStage.ENVIRONMENT,
            reason=f"Environmental failure: {trace.prefill_reason}",
            escalation_status="not_applicable",
        )

    # 2. Evidence Locus Gate Refusal (FR-LD-025)
    if trace.evidence_locus_violation:
        refused_url = None
        reason = "Candidate refused by evidence-locus gate"
        if isinstance(trace.evidence_locus_violation, dict):
            refused_url = trace.evidence_locus_violation.get("candidate_url") or trace.evidence_locus_violation.get("url")
            reason = trace.evidence_locus_violation.get("reason", reason)
        elif isinstance(trace.evidence_locus_violation, str):
            reason = trace.evidence_locus_violation

        if not refused_url:
            refused_url = trace.resolved_url

        return StageAttribution(
            stage=PipelineStage.LOCUS_GATE,
            reason=f"Evidence locus gate refused URL: {reason}",
            refused_url=refused_url,
            escalation_status="not_applicable",
        )

    # 3. Check link match
    link_matched = False
    if reference.no_valid_link:
        # Documented correct behaviour for no valid link is portal root or None or recognized portal page (FR-LD-019)
        if (
            trace.resolved_url is None
            or urls_equivalent(trace.resolved_url, "https://www.usa.gov/")
            or urls_equivalent(trace.resolved_url, "https://www.usa.gov")
            or any(urls_equivalent(trace.resolved_url, alt) for alt in reference.accepted_alternatives)
        ):
            link_matched = True
    else:
        if urls_equivalent(trace.resolved_url, reference.reference_url):
            link_matched = True
        elif any(urls_equivalent(trace.resolved_url, alt) for alt in reference.accepted_alternatives):
            link_matched = True

    # 4. Link matched branch
    if link_matched:
        # Check answer divergence (FR-LD-026)
        if trace.assessor_answer is not None and reference.correct_answer is not None:
            ans_bool = bool(trace.assessor_answer) if isinstance(trace.assessor_answer, bool) else (str(trace.assessor_answer).lower() in ("true", "yes", "1"))
            ref_bool = bool(reference.correct_answer) if isinstance(reference.correct_answer, bool) else (str(reference.correct_answer).lower() in ("true", "yes", "1"))

            if ans_bool != ref_bool:
                # Failure in assessment (FR-LD-026, FR-LD-027)
                reason = (
                    trace.assessor_justification
                    or trace.fill_gap_reason
                    or f"Assessor answered {trace.assessor_answer} (expected {reference.correct_answer})"
                )
                return StageAttribution(
                    stage=PipelineStage.ASSESSMENT,
                    reason=reason,
                    escalation_status="not_applicable",
                    page_truncated=trace.page_text_truncated,
                    excess_chars=trace.page_text_excess_chars,
                )

        # Match succeeded end-to-end
        stage = _map_source_to_stage(trace.supplying_source)
        return StageAttribution(
            stage=stage,
            reason=f"Link matched via {trace.supplying_source or 'resolved source'}",
            source_details=list(trace.resolution_history),
            escalation_status="not_applicable",
            page_truncated=trace.page_text_truncated,
            excess_chars=trace.page_text_excess_chars,
        )

    # 5. Link diverged / missed branch
    # Determine escalation status (FR-LD-024)
    if trace.link_escalated_off_portal:
        escalation_status = "widened_and_failed"
    else:
        escalation_status = "never_widened"

    source_details = list(trace.resolution_history)

    # If search never widened and defaulted to portal (FR-LD-024)
    if not trace.link_escalated_off_portal and (
        trace.supplying_source == "portal_default"
        or urls_equivalent(trace.resolved_url, "https://www.usa.gov/")
        or urls_equivalent(trace.resolved_url, "https://www.usa.gov")
    ):
        return StageAttribution(
            stage=PipelineStage.OFF_PORTAL_ESCALATION,
            reason="Search never widened beyond portal because portal returned candidate or defaulted",
            source_details=source_details,
            escalation_status="never_widened",
        )

    # If resolution history has sources that failed (FR-LD-023)
    if source_details:
        first_attempt = source_details[0]
        failing_stage = _map_source_to_stage(first_attempt.get("source"))
        reasons = [
            f"{s.get('source')}: {s.get('rejection_reason') or ('returned ' + str(s.get('returned')))}"
            for s in source_details
        ]
        combined_reason = "; ".join(reasons)
        return StageAttribution(
            stage=failing_stage,
            reason=f"Sources exhausted without finding reference link: {combined_reason}",
            source_details=source_details,
            escalation_status=escalation_status,
        )

    if trace.terminal_state in ("unassessable", "terminal_failure"):
        return StageAttribution(
            stage=PipelineStage.PAGE_RETRIEVAL,
            reason=trace.prefill_reason or "Page retrieval failed",
            escalation_status=escalation_status,
        )

    return StageAttribution(
        stage=PipelineStage.SEARCH,
        reason="Link resolution failed to discover reference URL",
        source_details=source_details,
        escalation_status=escalation_status,
    )
