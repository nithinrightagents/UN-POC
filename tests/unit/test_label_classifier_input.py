"""Unit tests for classifier input assembly and constraints (Scenario 3)."""

import json
from pathlib import Path
import pytest

from portal.label_classifier import (
    ClassifierInput,
    compute_input_digest,
    order_positions,
    render_classifier_payload,
)
from shared.state.entities import (
    AssessorRole,
    HumanAssessorSubmission,
    Prefill,
    new_id,
    utcnow,
)

pytestmark = pytest.mark.unit


def test_label_classifier_module_does_not_import_prefill():
    """T025: Structural guarantee: label_classifier.py must not import Prefill."""
    module_path = Path("src/portal/label_classifier.py")
    source = module_path.read_text(encoding="utf-8")
    assert "import Prefill" not in source
    assert "Prefill" not in [line.split("#")[0] for line in source.splitlines() if "import" in line]


def test_classifier_input_payload_fields_and_prohibitions():
    """T025: Payload contains indicator text, positions, interval and NO prohibited fields."""
    sub_a = HumanAssessorSubmission(
        submission_id="sub-A",
        session_id="sess-1",
        cycle_id="c-1",
        question_id="q1",
        portal_id="port-1",
        role=AssessorRole.A,
        assessor_actor_id="actor-A-secret",
        answer=True,
        evidence_url="https://gov.example/service",
        ai_suggested_answer=False,
        ai_suggestion_accepted=True,
        notes="Service is clearly operational.",
        submitted_at=utcnow(),
    )
    sub_b = HumanAssessorSubmission(
        submission_id="sub-B",
        session_id="sess-1",
        cycle_id="c-1",
        question_id="q1",
        portal_id="port-1",
        role=AssessorRole.B,
        assessor_actor_id="actor-B-secret",
        answer=False,
        evidence_url="https://gov.example/service",
        ai_suggested_answer=True,
        ai_suggestion_accepted=False,
        notes="Requires login to access details.",
        submitted_at=utcnow(),
    )

    positions, _ = order_positions(sub_a, sub_b)
    input_obj = ClassifierInput(
        indicator_text="Is the e-service available online?",
        positions=positions,
        interval_seconds=3600,
    )

    rendered = render_classifier_payload(input_obj)
    serialized = json.dumps(rendered)

    # Allowed top-level fields
    assert set(rendered.keys()) == {"prompt_version", "indicator_text", "positions", "interval_seconds"}

    # Prohibited fields must not appear in serialized string
    assert "actor-A-secret" not in serialized
    assert "actor-B-secret" not in serialized
    assert "assessor_actor_id" not in serialized
    assert "role" not in serialized
    assert "ai_suggested_answer" not in serialized


def test_distinctive_prefill_justification_absent():
    """T025 / FR-DL-037: Prefill justification is absent from rendered payload."""
    distinctive_text = "DISTINCTIVE_PREFILL_EVIDENCE_XYZ_12345"
    _ = Prefill(
        prefill_id=new_id("pref"),
        run_id="run-1",
        session_id="sess-1",
        cycle_id="c-1",
        question_id="q1",
        portal_id="port-1",
        suggested=True,
        answer=True,
        justification=distinctive_text,
    )

    sub_a = HumanAssessorSubmission(
        submission_id="sub-1",
        session_id="sess-1",
        cycle_id="c-1",
        question_id="q1",
        portal_id="port-1",
        role=AssessorRole.A,
        assessor_actor_id="act-1",
        answer=True,
        evidence_url="https://example.com/page",
        notes="Looked at the portal.",
        submitted_at=utcnow(),
    )
    sub_b = HumanAssessorSubmission(
        submission_id="sub-2",
        session_id="sess-1",
        cycle_id="c-1",
        question_id="q1",
        portal_id="port-1",
        role=AssessorRole.B,
        assessor_actor_id="act-2",
        answer=False,
        evidence_url="https://example.com/page",
        notes="Could not find the service.",
        submitted_at=utcnow(),
    )

    positions, _ = order_positions(sub_a, sub_b)
    input_obj = ClassifierInput(
        indicator_text="Test question",
        positions=positions,
        interval_seconds=100,
    )
    serialized = json.dumps(render_classifier_payload(input_obj))
    assert distinctive_text not in serialized


def test_symmetry_role_swap_produces_identical_payload_and_digest():
    """T025 / FR-DL-038: Swapping assessor A and B produces identical payload and digest."""
    sub_a = HumanAssessorSubmission(
        submission_id="sub-1",
        session_id="sess-1",
        cycle_id="c-1",
        question_id="q1",
        portal_id="port-1",
        role=AssessorRole.A,
        assessor_actor_id="act-a",
        answer=True,
        evidence_url="https://example.com/portal",
        notes="First notes",
        submitted_at=utcnow(),
    )
    sub_b = HumanAssessorSubmission(
        submission_id="sub-2",
        session_id="sess-1",
        cycle_id="c-1",
        question_id="q1",
        portal_id="port-1",
        role=AssessorRole.B,
        assessor_actor_id="act-b",
        answer=False,
        evidence_url="https://example.com/portal",
        notes="Second notes",
        submitted_at=utcnow(),
    )

    pos_ab, order_ab = order_positions(sub_a, sub_b)
    pos_ba, order_ba = order_positions(sub_b, sub_a)

    payload_ab = render_classifier_payload(ClassifierInput("Q text", pos_ab, 60))
    payload_ba = render_classifier_payload(ClassifierInput("Q text", pos_ba, 60))

    assert payload_ab == payload_ba
    assert compute_input_digest(payload_ab) == compute_input_digest(payload_ba)

