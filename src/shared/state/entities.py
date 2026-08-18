"""Core entities for EKAP AIQ.

Pure dataclasses — no I/O, no framework dependency. See
specs/001-ekap-aiq-assessment/data-model.md for field-by-field rationale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Enums ---------------------------------------------------------------


class SessionMode(str, Enum):
    PRODUCTION = "production"
    BENCHMARK = "benchmark"


class SessionStatus(str, Enum):
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    COMPLETE = "complete"


class AnswerType(str, Enum):
    BINARY = "binary"
    SCALAR = "scalar"
    ENUM = "enum"


class EvidenceLocus(str, Enum):
    NATIONAL_PORTAL_ONLY = "national_portal_only"
    ANY_GOVERNMENT_DOMAIN = "any_government_domain"


class LinkSource(str, Enum):
    PRIOR_SURVEY_KB = "prior_survey_kb"
    MSQ = "msq"
    SEARCH = "search"


class UnitState(str, Enum):
    """The unit state machine. Exactly four terminal states — see data-model.md §3."""

    PENDING = "pending"
    RESOLVING_LINK = "resolving_link"
    RESOLVED = "resolved"
    ASSESSING = "assessing"
    ADJUDICATING = "adjudicating"
    RETRYING = "retrying"
    DELIVERED = "delivered"  # terminal
    ESCALATED = "escalated"  # terminal — retained for historical rows and review/seed_demo.py, no longer reachable from the pipeline
    UNASSESSABLE = "unassessable"  # terminal
    NO_SUGGESTION = "no_suggestion"  # terminal


TERMINAL_UNIT_STATES = frozenset(
    {
        UnitState.DELIVERED,
        UnitState.ESCALATED,
        UnitState.UNASSESSABLE,
        UnitState.NO_SUGGESTION,
    }
)


class PrefillReason(str, Enum):
    """Reason taxonomy for when the prefill pipeline produces no suggestion (spec 008)."""

    NO_USABLE_EVIDENCE = "no_usable_evidence"
    EVIDENCE_UNREACHABLE = "evidence_unreachable"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    ACCESS_BOUNDARY = "access_boundary"
    INSUFFICIENT_POSITIONS = "insufficient_positions"
    UNRESOLVED_DISAGREEMENT = "unresolved_disagreement"
    FAILED_FINAL_VALIDATION = "failed_final_validation"
    ASSESSMENT_FAILURE = "assessment_failure"
    BUDGET_REACHED = "budget_reached"



class AgentRunState(str, Enum):
    """Assessor Agent Run states. See FR-067a/FR-067b for resume semantics."""

    PENDING = "pending"
    ASSESSING = "assessing"
    ASSESSED = "assessed"
    CONFIDENCE_RETRY = "confidence_retry"
    VALIDATING = "validating"
    VALIDATED_PASS = "validated_pass"  # terminal
    VALIDATION_FAILED_RETRYABLE = "validation_failed_retryable"
    VALIDATION_FAILED_TERMINAL = "validation_failed_terminal"  # terminal


TERMINAL_AGENT_RUN_STATES = frozenset(
    {AgentRunState.VALIDATED_PASS, AgentRunState.VALIDATION_FAILED_TERMINAL}
)


class VerificationOutcome(str, Enum):
    CONFIRMED = "confirmed"
    ELEMENT_ABSENT = "element_absent"
    TEXT_MISMATCH = "text_mismatch"
    TARGET_UNREACHABLE = "target_unreachable"


class EscalationReason(str, Enum):
    UNRESOLVED_DISAGREEMENT = "unresolved_disagreement"
    PORTAL_DISCREPANCY = "portal_discrepancy"
    NO_USABLE_URL = "no_usable_url"
    UNREACHABLE_PORTAL = "unreachable_portal"
    UNVERIFIABLE_TARGET = "unverifiable_target"
    REQUIRES_AUTHENTICATED_ACCESS = "requires_authenticated_access"
    LANGUAGE_DECLINED = "language_declined"
    LANGUAGE_NOT_SUPPORTED = "language_not_supported"


class LanguageDecisionOutcome(str, Enum):
    AUTHORIZED = "authorized"
    DECLINED = "declined"
    EXPIRED = "expired"


class AssessorAction(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT_OVERRIDE = "reject_override"


class AnswerProvenance(str, Enum):
    SYSTEM_PROPOSED = "system_proposed"
    HUMAN_EDITED = "human_edited"
    HUMAN_OVERRIDDEN = "human_overridden"


class AssessorRole(str, Enum):
    """The two blind human assessors recruited per country (spec 005,
    UN_Project_Scope_Meeting_Transcript_Compacted.md Section 2). Distinct from
    AssessorAgentRun.agent_index, which indexes independent AI agents."""

    A = "A"
    B = "B"


class ProjectType(str, Enum):
    """National OSI survey vs. a city-level LOSI project (transcript Section
    4) -- same schema, different unit granularity and public presentation."""

    NATIONAL_OSI = "national_osi"
    LOSI_CITY = "losi_city"


# --- Entities --------------------------------------------------------------


@dataclass
class SurveyCycle:
    cycle_id: str
    name: str
    questionnaire_ref: str
    country_set: list[str]
    status: str = "active"
    project_type: ProjectType = ProjectType.NATIONAL_OSI


@dataclass
class AssessmentSession:
    session_id: str
    cycle_id: str | None
    mode: SessionMode
    config_snapshot_id: str
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.RUNNING


@dataclass
class Question:
    question_id: str
    cycle_id: str
    text: str
    answer_type: AnswerType
    evidence_locus: EvidenceLocus
    is_custom: bool = False
    author_actor_id: str | None = None
    requires_authenticated_access: bool = False
    question_class: str | None = None
    indicator_id: str | None = None
    title: str | None = None
    what: str | None = None
    why: str | None = None
    how: dict | str | None = None
    benchmark_case: str | None = None
    reference_links: list[str] = field(default_factory=list)


@dataclass
class ResolutionAttempt:
    source: LinkSource
    order: int
    returned: str | None
    usable: bool
    rejection_reason: str | None = None


@dataclass
class TargetPortal:
    portal_id: str
    cycle_id: str
    country_id: str
    resolved_url: str | None = None
    supplying_source: LinkSource | None = None
    resolution_history: list[ResolutionAttempt] = field(default_factory=list)
    detected_language: str | None = None
    language_in_supported_set: bool | None = None
    unit_type: str = "country"  # "country" | "city" -- LOSI projects assess cities
    display_name: str | None = None


@dataclass
class LanguageDecision:
    decision_id: str
    portal_id: str
    session_id: str
    detected_language: str
    decision: LanguageDecisionOutcome
    decided_by_actor_id: str | None
    resolution_manner: str  # "explicit" | "window_expired"
    decided_at: datetime = field(default_factory=utcnow)


@dataclass
class ElementReference:
    css_path: str
    text_hash: str
    sibling_index: int = 0


@dataclass
class EvidenceArtifact:
    artifact_id: str
    resolved_url: str
    capture_ref: str
    element_reference: ElementReference
    element_text: str
    element_text_original_language: str | None = None
    element_text_translation: str | None = None
    captured_at: datetime = field(default_factory=utcnow)
    verified_at: datetime | None = None
    verifiability_status: str = "unverified"  # unverified | verified | no_longer_verifiable


@dataclass
class AssessorAgentRun:
    run_id: str
    session_id: str
    question_id: str
    portal_id: str
    agent_index: int
    round_number: int
    answer: object | None = None
    confidence: int | None = None
    justification: str | None = None
    evidence_artifact_id: str | None = None
    confidence_retry_count: int = 0
    validation_retry_count: int = 0
    state: AgentRunState = AgentRunState.PENDING
    auth_boundary_observed: bool = False
    auth_boundary_url: str | None = None
    model_identity: str | None = None
    below_acceptance_threshold: bool = False
    detected_language: str | None = None


@dataclass
class ValidationResult:
    validation_id: str
    run_id: str
    session_id: str
    quality_score: float
    gaps: list[str]
    passed: bool
    retry_number: int
    verification_outcome: VerificationOutcome
    verification_attempts: int


@dataclass
class AdjudicationResult:
    adjudication_id: str
    session_id: str
    question_id: str
    portal_id: str
    round_number: int
    input_run_ids: list[str]
    discrepancy_flagged: bool
    flag_reason: str | None
    max_pairwise_confidence_delta: int
    consensus_answer: object | None
    consensus_confidence: int | None
    below_acceptance_threshold: bool | None


@dataclass
class DiscrepancyCase:
    case_id: str
    scope: str  # "question" | "portal"
    session_id: str
    question_id: str | None = None
    portal_id: str | None = None
    points_of_disagreement: list[str] = field(default_factory=list)
    retry_count: int = 0
    addenda_issued: list[str] = field(default_factory=list)
    differing_answer_rate: float | None = None
    affirmative_rate_gap: float | None = None
    thresholds_in_force: dict | None = None
    outcome: str | None = None


@dataclass
class EscalationQueueItem:
    item_id: str
    session_id: str
    reason: EscalationReason
    context: dict
    disposition: dict | None = None
    disposed_by_actor_id: str | None = None
    disposed_at: datetime | None = None
    question_id: str | None = None
    portal_id: str | None = None


@dataclass
class AssessorDecision:
    decision_id: str
    session_id: str
    question_id: str
    portal_id: str
    action: AssessorAction
    system_proposed_answer: object
    delivered_answer: object
    actor_id: str
    rejection_reason: str | None = None
    decided_at: datetime = field(default_factory=utcnow)


@dataclass
class ConfigurationSnapshot:
    snapshot_id: str
    session_id: str
    values: dict
    captured_at: datetime = field(default_factory=utcnow)


@dataclass
class PriorSurveyLink:
    link_id: str
    question_id: str
    country_id: str
    url: str
    origin_cycle_id: str
    origin_session_id: str
    recorded_at: datetime = field(default_factory=utcnow)


@dataclass
class MSQLinkCandidate:
    candidate_id: str
    submission_id: str
    question_id: str
    country_id: str
    url: str
    submitted_at: datetime = field(default_factory=utcnow)


@dataclass
class BenchmarkSet:
    set_id: str
    name: str
    labelled_by_class: bool = False


@dataclass
class GroundTruthAnswer:
    truth_id: str
    set_id: str
    question_id: str
    country_id: str
    correct_answer: object
    label_source: str
    assigned_by: str
    question_class: str | None = None


@dataclass
class BenchmarkRunResult:
    result_id: str
    session_id: str
    config_snapshot_id: str
    overall_accuracy: float
    accuracy_by_class: dict
    accuracy_by_confidence_band: dict
    discrepancy_flag_rate: float
    portal_measures: dict
    escalations_by_reason: dict


@dataclass
class AnswerExport:
    export_id: str
    cycle_id: str
    produced_at: datetime
    produced_by_actor_id: str
    record_ids: list[str]
    exclusion_report: list[dict]


# --- Assessment & Workflow Engine entities --------------------------------
# Human blind assessors A/B, MSQ ingestion, and one-click publication -- see
# specs/005-un-ekap-platform/spec.md.


@dataclass
class HumanAssessorSubmission:
    """One append-only answer from one human assessor (A or B) for one
    question on one unit. A's rows are never queried while rendering B's
    screen and vice versa (src/portal/assessor.py) -- blindness is a query
    shape, not a UI toggle. `ai_suggested_answer` records what the pipeline
    pre-fill proposed, purely so the review surface can show whether the
    assessor agreed with or corrected the AI, never fed back into scoring."""

    submission_id: str
    session_id: str
    cycle_id: str
    question_id: str
    portal_id: str
    role: AssessorRole
    assessor_actor_id: str
    answer: object
    evidence_url: str | None = None
    notes: str | None = None
    ai_suggested_answer: object | None = None
    ai_suggestion_accepted: bool | None = None
    submitted_at: datetime = field(default_factory=utcnow)


@dataclass
class Prefill:
    """One append-only prefill record for one question on one unit (spec 008)."""

    prefill_id: str
    run_id: str
    session_id: str
    cycle_id: str
    question_id: str
    portal_id: str
    suggested: bool
    answer: bool | None = None
    confidence: int | None = None
    justification: str | None = None
    evidence_url: str | None = None
    supplying_source: LinkSource | str | None = None
    agreement_outcome: str | None = None
    confidence_gap: int | None = None
    resolver_decision: dict | None = None
    unselected_position: dict | None = None
    position_run_ids: list[str] = field(default_factory=list)
    reason: PrefillReason | str | None = None
    terminal_state: UnitState | str = UnitState.DELIVERED
    created_at: datetime | str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        if self.suggested:
            if self.answer is None or self.reason is not None:
                raise ValueError(
                    "When suggested=True, answer must be non-null and reason must be None"
                )
        else:
            if self.answer is not None or self.reason is None:
                raise ValueError(
                    "When suggested=False, answer must be None and reason must be non-null"
                )


@dataclass
class AssessorCompletion:
    """Explicit declaration of assessment completion by a human assessor role (spec 008)."""

    completion_id: str
    session_id: str
    cycle_id: str
    portal_id: str
    role: str
    actor_id: str
    indicator_count_at_declaration: int
    declared_at: datetime | str = field(default_factory=utcnow)


@dataclass
class MSQDocument:
    """A parsed Member State Questionnaire, attached to a country as context
    for assessors (transcript Section 3: MSQ never influences scoring, only
    guides where to look). `sections` is {section_title: [{"question": ...,
    "answer": ...}, ...]}, produced by src/portal/msq.py structural parsing --
    not a semantic match to indicators."""

    msq_id: str
    country_id: str
    cycle_id: str
    source_filename: str
    raw_text: str
    sections: dict
    extracted_urls: list[str] = field(default_factory=list)
    uploaded_at: datetime = field(default_factory=utcnow)


@dataclass
class PublicationRecord:
    """Append-only "this cycle+unit was published with this score at this
    time" marker written by the Senior Reviewer's one-click publish action
    (src/portal/admin.py). The public knowledge base
    (src/portal/public.py) reads only the latest row per (cycle_id,
    portal_id) -- never a manual export/import step."""

    publication_id: str
    cycle_id: str
    portal_id: str
    published_by_actor_id: str
    score: float
    score_breakdown: dict
    published_at: datetime = field(default_factory=utcnow)
