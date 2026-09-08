"""Unit tests for classifier output validation and handling (T026, Scenario 4).

Covers FR-DL-033 to FR-DL-035.
"""

from __future__ import annotations

import json
import pytest

from portal.disagreement_labels import (
    dispatch_labelling_pass,
    run_labelling_pass,
    unit_labelling_state,
)
from portal.label_classifier import (
    CLASSIFIER_RESPONSE_SCHEMA,
    InvalidResponseError,
    SchemaRejectedError,
    classify,
)
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    CLASSIFIER_LABELS,
    DETERMINISTIC_LABELS,
    DisagreementLabel,
    EvidenceLocus,
    Question,
)

pytestmark = pytest.mark.unit


class MockRuntime:
    def __init__(self, provider):
        self.provider = provider


def test_response_schema_enum_is_exactly_four_labels():
    """Schema enum is exactly the four classifier labels with deterministic ones absent."""
    enum_values = CLASSIFIER_RESPONSE_SCHEMA["properties"]["label"]["enum"]
    assert set(enum_values) == {l.value for l in CLASSIFIER_LABELS}
    for det_label in DETERMINISTIC_LABELS:
        assert det_label.value not in enum_values
    assert "different_sources" not in enum_values
    assert "one_found_nothing" not in enum_values


@pytest.mark.asyncio
async def test_schema_rejected_stores_nothing_and_records_attempt(conn, db_path, settings, disputed_unit, fake_label_provider):
    """A provider returning 'different_sources' is rejected, stores no label, and records schema_rejected."""
    repo = Repository(conn)
    repo.insert_question(
        Question(
            question_id="q1",
            cycle_id="c1",
            text="Indicator 1",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
    )

    # Both cite same host so deterministic pre-pass doesn't fire
    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={
            "q1": (True, "https://gov.example/portal", "Notes A", False, "https://gov.example/portal", "Notes B")
        },
    )

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        question_ids=["q1"],
        threshold=0.2,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    fake_provider = fake_label_provider(
        canned_response={
            "label": "different_sources",
            "reason": "Used different sources",
            "position_1_notes_contradict_answer": False,
            "position_2_notes_contradict_answer": False,
        }
    )

    result = await run_labelling_pass(
        database_path=db_path,
        settings=settings,
        runtime=MockRuntime(fake_provider),
        pass_id=pass_.pass_id,
    )

    assert result.labelled_classifier == 0
    assert result.attempts_recorded == 1

    labels = repo.list_labels_for_unit("s1", "p1")
    assert labels == []

    cursor = conn.execute("SELECT * FROM labelling_attempts WHERE pass_id = ?", (pass_.pass_id,))
    attempts = cursor.fetchall()
    assert len(attempts) == 1
    assert attempts[0]["failure"] == "schema_rejected"


@pytest.mark.asyncio
async def test_malformed_json_and_missing_key_rejected(conn, db_path, settings, disputed_unit, fake_label_provider):
    """Malformed JSON and missing key responses are rejected and recorded as invalid_response."""
    repo = Repository(conn)
    repo.insert_question(
        Question(
            question_id="q1",
            cycle_id="c1",
            text="Indicator 1",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
    )

    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={
            "q1": (True, "https://gov.example/portal", "Notes A", False, "https://gov.example/portal", "Notes B")
        },
    )

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        question_ids=["q1"],
        threshold=0.2,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    # 1. Malformed JSON
    fake_malformed = fake_label_provider(canned_response="NOT VALID JSON AT ALL {{{")
    await run_labelling_pass(
        database_path=db_path,
        settings=settings,
        runtime=MockRuntime(fake_malformed),
        pass_id=pass_.pass_id,
    )

    cursor = conn.execute("SELECT * FROM labelling_attempts WHERE pass_id = ?", (pass_.pass_id,))
    attempts = cursor.fetchall()
    assert len(attempts) == 1
    assert attempts[0]["failure"] == "invalid_response"

    # 2. Missing key
    fake_missing_key = fake_label_provider(canned_response={"reason": "Missing label key"})
    await run_labelling_pass(
        database_path=db_path,
        settings=settings,
        runtime=MockRuntime(fake_missing_key),
        pass_id=pass_.pass_id,
    )

    cursor = conn.execute("SELECT * FROM labelling_attempts WHERE pass_id = ?", (pass_.pass_id,))
    attempts = cursor.fetchall()
    assert len(attempts) == 2
    assert attempts[1]["failure"] == "invalid_response"


@pytest.mark.asyncio
async def test_not_enough_notes_stored_as_substantive_label(conn, db_path, settings, disputed_unit, fake_label_provider):
    """not_enough_notes is stored as a substantive label and is never conflated with awaiting."""
    repo = Repository(conn)
    repo.insert_question(
        Question(
            question_id="q1",
            cycle_id="c1",
            text="Indicator 1",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
    )

    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={
            "q1": (True, "https://gov.example/portal", "", False, "https://gov.example/portal", "")
        },
    )

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        question_ids=["q1"],
        threshold=0.2,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    fake_provider = fake_label_provider(
        canned_response={
            "label": "not_enough_notes",
            "reason": "Notes were absent on both sides.",
            "position_1_notes_contradict_answer": False,
            "position_2_notes_contradict_answer": False,
        }
    )

    result = await run_labelling_pass(
        database_path=db_path,
        settings=settings,
        runtime=MockRuntime(fake_provider),
        pass_id=pass_.pass_id,
    )

    assert result.labelled_classifier == 1
    assert result.attempts_recorded == 0

    labels = repo.list_labels_for_unit("s1", "p1")
    assert len(labels) == 1
    rec = labels[0]
    assert rec.label == DisagreementLabel.NOT_ENOUGH_NOTES
    assert rec.established_by == "classifier"

    # Verify state projection is established, not awaiting
    state_map = unit_labelling_state(repo, "s1", "p1")
    assert "q1" in state_map
    dispute_state = state_map["q1"]
    assert dispute_state.state == "established"
    assert dispute_state.badge == "Not enough notes"
    assert dispute_state.state != "awaiting"
