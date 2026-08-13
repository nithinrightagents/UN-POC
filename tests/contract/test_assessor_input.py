"""FR-010: no field on AssessorAgentInput can carry another agent's output.

Asserts the closed schema is actually closed -- extra fields, and fields
shaped like another agent's answer/confidence/evidence, are rejected by
Pydantic validation rather than silently accepted.
"""

import pytest
from pydantic import ValidationError

from shared.state.schemas import (
    AssessorAgentInput,
    AssessorAgentOutput,
    PortalInput,
    QuestionInput,
    RetryAddendum,
)

pytestmark = pytest.mark.contract


def _valid_input_kwargs():
    return dict(
        session_id="s1",
        agent_index=0,
        round_number=1,
        question=QuestionInput(
            question_id="q1",
            text="Does X exist?",
            answer_type="binary",
            evidence_locus="national_portal_only",
        ),
        portal=PortalInput(portal_id="p1", resolved_url="https://example.gov"),
    )


def test_valid_input_is_accepted():
    AssessorAgentInput(**_valid_input_kwargs())


def test_extra_top_level_field_rejected():
    kwargs = _valid_input_kwargs()
    kwargs["other_agent_output"] = {"answer": True, "confidence": 99}
    with pytest.raises(ValidationError):
        AssessorAgentInput(**kwargs)


def test_extra_field_on_question_rejected():
    with pytest.raises(ValidationError):
        QuestionInput(
            question_id="q1",
            text="Does X exist?",
            answer_type="binary",
            evidence_locus="national_portal_only",
            peer_agent_answer=True,  # a leak attempt
        )


def test_extra_field_on_portal_rejected():
    with pytest.raises(ValidationError):
        PortalInput(
            portal_id="p1",
            resolved_url="https://example.gov",
            other_agents_confidence=95,  # a leak attempt
        )


def test_addendum_only_accepts_declared_kinds():
    with pytest.raises(ValidationError):
        RetryAddendum(kind="agent_1_said_yes", items=["Agent 1 answered yes"])


def test_addendum_cannot_carry_arbitrary_fields():
    with pytest.raises(ValidationError):
        RetryAddendum(
            kind="disagreement_points",
            items=["the answers differ"],
            attributed_agent_index=1,  # a leak attempt -- FR-031
        )


def test_no_field_path_exists_for_another_agents_full_output():
    """There is no field anywhere on AssessorAgentInput whose declared type
    is AssessorAgentOutput or a container of it -- structurally, not just by
    convention."""
    for name, field in AssessorAgentInput.model_fields.items():
        assert field.annotation is not AssessorAgentOutput
        assert "AssessorAgentOutput" not in str(field.annotation)


def test_auth_boundary_output_forbids_an_answer():
    with pytest.raises(ValidationError):
        AssessorAgentOutput(
            answer=True,
            confidence=50,
            justification="x",
            evidence=None,
            auth_boundary_observed=True,
        )


def test_auth_boundary_output_with_null_answer_is_valid():
    AssessorAgentOutput(
        answer=None,
        confidence=0,
        justification="hit a login wall",
        evidence=None,
        auth_boundary_observed=True,
        auth_boundary_url="https://example.gov/login",
    )
