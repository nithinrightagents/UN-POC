"""Pydantic schemas and API exceptions for EKAP REST API (spec 007, 008, 012 & headless full capabilities)."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


# --- Error Envelope & Exceptions (T020) -------------------------------------


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class ApiError(Exception):
    def __init__(
        self,
        code: str,
        http_status: int,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message
        self.details = details or {}


class Unauthorized(ApiError):
    def __init__(
        self,
        message: str = "Authentication required.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("unauthorized", 401, message, details)


class NotConfigured(ApiError):
    def __init__(
        self,
        message: str = "Programmatic API access is not configured on this server.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("not_configured", 503, message, details)


class NotFound(ApiError):
    def __init__(
        self,
        message: str = "Resource not found.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("not_found", 404, message, details)


class Conflict(ApiError):
    def __init__(
        self,
        message: str = "Resource conflict.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("conflict", 409, message, details)


class InvalidRequest(ApiError):
    def __init__(
        self,
        message: str = "Invalid request.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("invalid_request", 422, message, details)


class PreconditionFailed(ApiError):
    def __init__(
        self,
        message: str = "Precondition failed.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("precondition_failed", 409, message, details)


class IncompleteAssessment(ApiError):
    def __init__(
        self,
        message: str = "Assessment incomplete.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("incomplete_assessment", 409, message, details)


class AssessmentIncomplete(ApiError):
    def __init__(
        self,
        message: str = "Assessment incomplete.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("assessment_incomplete", 409, message, details)


class CapacityReached(ApiError):
    def __init__(
        self,
        retry_after_seconds: int = 30,
        message: str = "Concurrent run capacity reached. Please retry later.",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("capacity_reached", 429, message, details)
        self.retry_after_seconds = retry_after_seconds


# --- Reference & Metadata Schemas -------------------------------------------


class QuestionSetSummary(BaseModel):
    set_id: str
    label: str
    description: str
    indicator_count: int


class QuestionSetListResponse(BaseModel):
    question_sets: list[QuestionSetSummary]


class CountryItem(BaseModel):
    code: str
    name: str
    most_populous_city: str


class CountryListResponse(BaseModel):
    countries: list[CountryItem]


# --- Cycle Schemas ----------------------------------------------------------


class CycleCreateRequest(BaseModel):
    cycle_id: str
    name: str
    questionnaire_ref: str = "UN MSQ 2026 Indicator Set"
    project_type: str = "national_osi"
    discrepancy_rate_threshold: float | None = None
    question_set_id: str | None = None
    country_ids: list[str] = Field(default_factory=list)


class CycleResponse(BaseModel):
    cycle_id: str
    name: str
    questionnaire_ref: str
    project_type: str
    country_set: list[str] = Field(default_factory=list)
    created_at: str
    discrepancy_rate_threshold: float | None = None


class CycleDetailResponse(BaseModel):
    cycle_id: str
    name: str
    questionnaire_ref: str
    project_type: str
    country_set: list[str] = Field(default_factory=list)
    created_at: str
    question_count: int
    unit_count: int
    discrepancy_rate_threshold: float | None = None


class CycleListResponse(BaseModel):
    cycles: list[CycleResponse]


class ToleranceUpdateRequest(BaseModel):
    tolerance: float = Field(..., ge=0.0, le=100.0, description="Tolerance percentage between 0 and 100")
    actor_id: str = "senior-reviewer"


class ToleranceUpdateResponse(BaseModel):
    cycle_id: str
    previous_tolerance: float | None = None
    new_tolerance: float
    changed_by: str
    changed_at: str
    closed_rounds_count: int = 0


# --- Question Schemas -------------------------------------------------------


class QuestionCreateRequest(BaseModel):
    indicator_id: str
    title: str
    what: str
    why: str
    how: str
    module: str = "Custom Indicators"
    evidence_locus: str = "national_portal_only"
    benchmark_case: str | None = None


class QuestionEditRequest(BaseModel):
    text: str | None = None
    title: str | None = None
    what: str | None = None
    why: str | None = None
    how: str | None = None
    editor_actor_id: str = "admin"


class QuestionResponse(BaseModel):
    question_id: str
    indicator_id: str
    title: str
    what: str
    why: str
    how: dict[str, Any]
    module: str
    evidence_locus: str
    benchmark_case: str | None = None
    answer_type: str = "binary"


class QuestionListResponse(BaseModel):
    questions: list[QuestionResponse]


# --- Unit Schemas -----------------------------------------------------------


class UnitCreateRequest(BaseModel):
    country_id: str
    display_name: str
    url: str | None = None
    unit_type: str = "country"


class UnitBulkCreateRequest(BaseModel):
    units: list[UnitCreateRequest]


class UnitResponse(BaseModel):
    portal_id: str
    country_id: str
    display_name: str
    unit_type: str
    resolved_url: str | None
    has_msq: bool = False
    latest_job_state: str | None = None
    published: bool = False


class UnitListResponse(BaseModel):
    units: list[UnitResponse]


class UnitBulkCreateResponse(BaseModel):
    created_count: int
    units: list[UnitResponse]


# --- MSQ Schemas ------------------------------------------------------------


class MSQUploadTextRequest(BaseModel):
    text: str
    page_count: int = 1


class MSQUploadResponse(BaseModel):
    country_id: str
    cycle_id: str
    page_count: int
    extracted_links_count: int
    extracted_links: dict[str, str] = Field(default_factory=dict)


class MSQDetailResponse(BaseModel):
    has_msq: bool
    cycle_id: str
    country_id: str
    page_count: int | None = None
    text_snippet: str | None = None
    matched_candidate_count: int = 0


# --- Assessment Job Schemas -------------------------------------------------


class AssessmentTriggerRequest(BaseModel):
    actor_id: str = "integration-client"


class AssessmentTriggerResponse(BaseModel):
    job_id: str
    state: str
    cycle_id: str
    portal_id: str
    questions_total: int
    questions_completed: int
    already_running: bool
    created_at: str


class AssessmentStatusResponse(BaseModel):
    state: str
    job_id: str | None = None
    questions_total: int = 0
    questions_completed: int = 0
    failure_cause: str | None = None
    triggered_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    outcomes: dict[str, Any] | None = None


class BatchAssessmentRequest(BaseModel):
    actor_id: str = "integration-client"
    portal_ids: list[str] | None = None
    question_ids: list[str] | None = None


class BatchAssessmentResponse(BaseModel):
    cycle_id: str
    jobs_triggered: list[AssessmentTriggerResponse]
    total_jobs: int


class AIQuestionResult(BaseModel):
    question_id: str
    indicator_id: str
    assessed: bool
    answer: bool | None = None
    confidence: int | None = None
    justification: str | None = None
    evidence_url: str | None = None
    evidence_missing: bool = False
    blocked: bool = False
    blank_reason: str | None = None


class AIResultsEnvelope(BaseModel):
    complete: bool
    questions_total: int
    questions_completed: int
    results: list[AIQuestionResult]


# --- Human Assessor Schemas -------------------------------------------------


class HumanSubmissionRequest(BaseModel):
    question_id: str
    role: str
    actor_id: str
    answer: bool
    evidence_url: str | None = None
    notes: str | None = None


class HumanSubmissionResponse(BaseModel):
    submission_id: str
    role: str
    answer: bool
    submitted_at: str


class HumanAnswerItem(BaseModel):
    question_id: str
    indicator_id: str
    answered: bool
    answer: bool | None = None
    evidence_url: str | None = None
    notes: str | None = None
    actor_id: str | None = None
    submitted_at: str | None = None


class HumanAnswersResponse(BaseModel):
    role: str
    answers: list[HumanAnswerItem]


# --- Publication Schemas ----------------------------------------------------


class PublicationCreateRequest(BaseModel):
    actor_id: str = "senior-reviewer"


class PublicationBreakdownItem(BaseModel):
    question_id: str
    indicator_id: str
    final_answer: bool


class PublicationResponse(BaseModel):
    publication_id: str
    score: float
    published_by: str
    published_at: str
    breakdown: list[PublicationBreakdownItem]


class PublicationStatusResponse(BaseModel):
    published: bool
    score: float | None = None
    published_by: str | None = None
    published_at: str | None = None
    publication_id: str | None = None
    breakdown: list[PublicationBreakdownItem] = Field(default_factory=list)


# --- Prefill & Completion Schemas (spec 008) --------------------------------


class PrefillItem(BaseModel):
    question_id: str
    indicator_id: str
    suggested: bool
    answer: bool | None = None
    confidence: int | None = None
    justification: str | None = None
    evidence_url: str | None = None
    supplying_source: str | None = None
    supplying_source_label: str | None = None
    agreement_outcome: str | None = None
    confidence_gap: int | None = None
    unselected_position: dict[str, Any] | None = None
    resolver_reasoning: str | None = None
    reason: str | None = None
    reason_text: str | None = None


class PrefillsResponse(BaseModel):
    run_id: str | None = None
    generated_at: str | None = None
    complete: bool
    prefills: list[PrefillItem]


class CompletionCreateRequest(BaseModel):
    role: str
    actor_id: str


class CompletionCreateResponse(BaseModel):
    completion_id: str
    role: str
    actor_id: str
    declared_at: str
    indicator_count: int


class RoleCompletionStatus(BaseModel):
    declared: bool
    actor_id: str | None = None
    declared_at: str | None = None
    answered_count: int
    total_indicators: int
    outstanding_question_ids: list[str] = Field(default_factory=list)
    complete: bool


class CompletionsStatusResponse(BaseModel):
    ready_to_publish: bool
    roles: dict[str, RoleCompletionStatus]
    blocking_reason: str | None = None


# --- Discrepancy & Reconciliation Schemas (Spec 012) ------------------------


class DiscrepancyStateResponse(BaseModel):
    portal_id: str
    state: str
    differing_answer_rate: float | None = None
    compared_count: int
    disputed_question_ids: list[str] = Field(default_factory=list)
    tolerance_in_force: float
    rounds_consumed: int
    automatic_round_used: bool
    open_round_id: str | None = None


class ReconciliationDisputeRow(BaseModel):
    question_id: str
    indicator_id: str | None = None
    title: str | None = None
    my_answer: bool | None = None
    my_evidence: str | None = None
    my_notes: str | None = None
    peer_answer: bool | None = None
    peer_evidence: str | None = None
    peer_notes: str | None = None
    peer_actor_id: str | None = None
    joint_answer: bool | None = None
    joint_justification: str | None = None
    joint_committed_by: str | None = None
    is_disputed: bool = True


class ReconciliationSettledRow(BaseModel):
    question_id: str
    indicator_id: str | None = None
    title: str | None = None
    my_answer: bool | None = None
    joint_answer: bool | None = None
    is_disputed: bool = False


class ReconciliationWorkspaceResponse(BaseModel):
    portal_id: str
    cycle_id: str
    role: str
    peer_role: str
    state: str
    round_id: str | None = None
    rate_pct: str
    tolerance_pct: str
    compared_count: int
    disputed_rows: list[ReconciliationDisputeRow]
    settled_rows: list[ReconciliationSettledRow]


class JointAnswerRequest(BaseModel):
    role: str
    actor_id: str
    answer: bool
    justification: str


class JointAnswerResponse(BaseModel):
    joint_answer_id: str
    round_id: str
    question_id: str
    answer: bool
    justification: str
    committed_by_role: str
    round_closed: bool = False


class EscalationItemResponse(BaseModel):
    item_id: str
    session_id: str
    portal_id: str | None = None
    question_id: str | None = None
    reason: str
    context: dict[str, Any] = Field(default_factory=dict)
    disposition: dict[str, Any] | None = None
    disposed_by_actor_id: str | None = None
    disposed_at: str | None = None


class EscalationsListResponse(BaseModel):
    escalations: list[EscalationItemResponse]


class EscalationDispositionRequest(BaseModel):
    resolution: str
    notes: str = ""
    actor_id: str = "senior-reviewer"
    resolved_answers: dict[str, bool] | None = None


class EscalationDispositionResponse(BaseModel):
    item_id: str
    resolution: str
    resolved_by: str
    resolved_at: str
    notes: str = ""


# --- Public Reporting Schemas -----------------------------------------------


class PublicCycleItem(BaseModel):
    cycle_id: str
    name: str
    project_type: str
    published_units_count: int


class PublicCycleListResponse(BaseModel):
    cycles: list[PublicCycleItem]


class PublicRankingItem(BaseModel):
    portal_id: str
    country_id: str
    display_name: str
    unit_type: str
    score: float
    published_at: str


class PublicRankingsResponse(BaseModel):
    cycle_id: str
    cycle_name: str
    project_type: str
    rankings: list[PublicRankingItem]


class PublicProfileBreakdownItem(BaseModel):
    question_id: str
    indicator_id: str | None = None
    title: str | None = None
    module: str | None = None
    answer: bool


class PublicProfileResponse(BaseModel):
    cycle_id: str
    portal_id: str
    country_id: str
    display_name: str
    unit_type: str
    score: float
    published_at: str
    published_by: str
    breakdown: list[PublicProfileBreakdownItem]


# --- AI Review Schemas ------------------------------------------------------


class ReviewActionRequest(BaseModel):
    actor_id: str
    edited_answer: Any | None = None
    override_answer: Any | None = None
    rejection_reason: str | None = None


class ReviewActionResponse(BaseModel):
    decision_id: str
    action: str


class ReviewStatusResponse(BaseModel):
    session_id: str
    portal_id: str
    cycle_id: str
    status: dict[str, Any]


class ReviewQuestionResponse(BaseModel):
    session_id: str
    portal_id: str
    question_id: str
    view: dict[str, Any]


# --- Export Schemas ---------------------------------------------------------


class ExportTriggerRequest(BaseModel):
    output_dir: str = "./data/exports"
    actor_id: str = "system-exporter"


class ExportResponse(BaseModel):
    cycle_id: str
    ndjson_path: str
    exclusion_report_path: str
    exported_at: str


# --- Telemetry & Audit Schemas ----------------------------------------------


class TelemetrySummaryResponse(BaseModel):
    session_id: str
    summary: dict[str, Any]


class TimingsReportResponse(BaseModel):
    session_id: str
    timings: dict[str, Any]


class FetchesReportResponse(BaseModel):
    session_id: str
    fetches: dict[str, Any]


class CostReportResponse(BaseModel):
    session_id: str
    cost: dict[str, Any]


class AuditSummaryResponse(BaseModel):
    session_id: str
    summary: dict[str, Any]


class QuestionAuditResponse(BaseModel):
    session_id: str
    question_id: str
    portal_id: str
    history: dict[str, Any]


# --- Verification Schemas ---------------------------------------------------


class VerifyRequest(BaseModel):
    checks: list[str] = Field(
        default_factory=lambda: [
            "independence",
            "evidence",
            "resume",
            "telemetry",
            "credentials",
        ]
    )


class VerifyResponse(BaseModel):
    clean: bool
    findings: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


# --- Benchmark & Diagnostics Schemas ---------------------------------------


class BenchmarkRunRequest(BaseModel):
    set_id: str
    dataset_path: str = "data/benchmark/module_2_1.json"


class BenchmarkRunResponse(BaseModel):
    session_id: str
    overall_accuracy: float
    discrepancy_flag_rate: float
    total_evaluated: int


class BenchmarkCompareRequest(BaseModel):
    session_id_a: str
    session_id_b: str


class BenchmarkCompareResponse(BaseModel):
    session_id_a: str
    session_id_b: str
    comparison: dict[str, Any]


class DiagnosticRunRequest(BaseModel):
    cycle_id: str = "usa-test-2026"
    reference_set_id: str = "bm-reference-links-us"
    fixture_path: str = "data/benchmark/reference_links_us.json"
    questions_filter: list[str] | None = None
    resolve_only: bool = False
    check_staleness: bool = False


class DiagnosticRunResponse(BaseModel):
    summary: str
    diagnostic_result: dict[str, Any]


class DiagnosticCompareRequest(BaseModel):
    session_a: str
    session_b: str
    fail_on_regression: bool = False


class DiagnosticCompareResponse(BaseModel):
    session_a: str
    session_b: str
    has_regression: bool
    summary: str


# --- System Config & Health Schemas ----------------------------------------


class SystemConfigResponse(BaseModel):
    valid: bool
    error: str | None = None
    parameters: dict[str, dict[str, Any]]


class SystemHealthResponse(BaseModel):
    status: str
    database_path: str
    ai_runtime_active: bool
    timestamp: str
