"""Closed Assessor Agent input/output schemas (FR-010, contracts/assessor-agent.md).

The input schema is closed by construction: no field exists on
AssessorAgentInput capable of carrying another agent's answer, confidence,
justification, or evidence. FR-010 is therefore a schema property rather
than a review discipline -- a leak fails Pydantic validation at the
boundary instead of surviving into a run. See tests/contract/test_assessor_input.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class QuestionInput(BaseModel):
    model_config = {"extra": "forbid"}

    question_id: str
    text: str
    answer_type: Literal["binary", "scalar", "enum"]
    answer_options: list[str] | None = None
    evidence_locus: Literal["national_portal_only", "any_government_domain"]


class PortalInput(BaseModel):
    model_config = {"extra": "forbid"}

    portal_id: str
    resolved_url: str
    detected_language: str | None = None
    language_in_supported_set: bool = True


class RetryAddendum(BaseModel):
    """FR-030, FR-080, FR-136: retry guidance. Never attributes a position to
    an identified agent (FR-031), and a confidence-retry addendum never
    requests a higher number (FR-136) -- only these three literal kinds are
    representable, so a caller cannot smuggle another agent's answer through
    the addendum channel either."""

    model_config = {"extra": "forbid"}

    kind: Literal["validation_gaps", "disagreement_points", "seek_better_evidence"]
    items: list[str] = Field(default_factory=list)


class AssessorAgentInput(BaseModel):
    """Closed schema -- extra='forbid' on every nested model means an
    attempt to attach another agent's output anywhere in this structure is
    a validation error, not a silent pass-through."""

    model_config = {"extra": "forbid"}

    session_id: str
    agent_index: int = Field(ge=0)
    round_number: int = Field(ge=1)
    question: QuestionInput
    portal: PortalInput
    addendum: RetryAddendum | None = None


class ElementReferenceOutput(BaseModel):
    model_config = {"extra": "forbid"}

    css_path: str
    text_hash: str
    sibling_index: int = 0


class EvidenceOutput(BaseModel):
    model_config = {"extra": "forbid"}

    resolved_url: str
    capture_ref: str | None = None
    element_reference: ElementReferenceOutput | None = None
    element_text: str
    element_text_original_language: str | None = None
    element_text_translation: str | None = None


class AssessorAgentOutput(BaseModel):
    """FR-012, FR-013, FR-108. Invariant A5: when auth_boundary_observed is
    true, `answer` MUST be null -- no answer inferred from a public page
    reached in place of gated content."""

    model_config = {"extra": "forbid"}

    answer: bool | float | str | None
    confidence: int = Field(ge=0, le=100)
    justification: str
    evidence: EvidenceOutput | None
    auth_boundary_observed: bool = False
    auth_boundary_url: str | None = None
    model_identity: str = ""

    @model_validator(mode="after")
    def _auth_boundary_implies_no_answer(self) -> "AssessorAgentOutput":
        if self.auth_boundary_observed and self.answer is not None:
            raise ValueError(
                "auth_boundary_observed=True requires answer=None (invariant A5, FR-108)"
            )
        return self
