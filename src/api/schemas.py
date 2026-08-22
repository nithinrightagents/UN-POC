"""Pydantic schemas and API exceptions for EKAP REST API (spec 007)."""

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


# --- Cycle Schemas ----------------------------------------------------------


class CycleCreateRequest(BaseModel):
    cycle_id: str
    name: str
    questionnaire_ref: str = "UN MSQ 2026 Indicator Set"
    project_type: str = "national_osi"


class CycleResponse(BaseModel):
    cycle_id: str
    name: str
    questionnaire_ref: str
    project_type: str
    country_set: list[str] = Field(default_factory=list)
    created_at: str


class CycleDetailResponse(BaseModel):
    cycle_id: str
    name: str
    questionnaire_ref: str
    project_type: str
    country_set: list[str] = Field(default_factory=list)
    created_at: str
    question_count: int
    unit_count: int


class CycleListResponse(BaseModel):
    cycles: list[CycleResponse]


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
    url: str
    unit_type: str = "country"


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

