"""Unit tests for labelling attempts, retry cap, exhaustion, and CLI drain (T050, T051, T052, T057).

Covers Scenario 5, FR-DL-011, FR-DL-012, FR-DL-052, FR-DL-057, FR-DL-058, FR-DL-059.
"""

from __future__ import annotations

import datetime
from datetime import timezone
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from cli import main
from portal.assignment import set_role_assignment
from portal.common import ensure_session
from portal.disagreement_labels import (
    dispatch_labelling_pass,
    run_labelling_pass,
    unit_labelling_state,
)
from portal.discrepancy import recompute_portal_discrepancy
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    Assessor,
    AssessorRole,
    DisagreementLabel,
    EvidenceLocus,
    HumanAssessorSubmission,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
    utcnow,
)

pytestmark = pytest.mark.unit


class MockRuntime:
    def __init__(self, provider):
        self.provider = provider


def _setup_cycle_and_unit(repo: Repository, cycle_id: str = "retry-cycle", portal_id: str = "portal-retry"):
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Retry Test Cycle",
            questionnaire_ref="test",
            country_set=["TEST"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.0,
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="TEST",
            unit_type="country",
            display_name="Test Country",
        )
    )
    repo.insert_question(
        Question(
            question_id="q1",
            cycle_id=cycle_id,
            text="Indicator 1 Text",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id="IND-01",
        )
    )
    repo.upsert_assessor(Assessor(assessor_id="actor-a", display_name="Assessor A", email="a@test.gov"))
    repo.upsert_assessor(Assessor(assessor_id="actor-b", display_name="Assessor B", email="b@test.gov"))
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.A, "actor-a", "admin")
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.B, "actor-b", "admin")


@pytest.mark.asyncio
async def test_scenario_5_retry_cap_exhaustion_and_amendment_immobility(
    conn, settings, disputed_unit, raising_provider, fake_label_provider
):
    """T050, T051: Three runs under raising provider yield 3 attempt rows and state exhausted. 4th run makes no model calls. Amending submission does not bring exhausted back."""
    repo = Repository(conn)
    cycle_id = "retry-cycle"
    portal_id = "portal-retry"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1"], 0.0, cycle_id=cycle_id)

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    failing_provider = raising_provider(RuntimeError("API timeout"))
    runtime_failing = MockRuntime(failing_provider)

    # Run 1: 1 attempt row recorded, state is 'awaiting'
    res1 = await run_labelling_pass(settings.database_path, settings, runtime_failing, pass_.pass_id)
    assert res1.attempts_recorded == 1
    assert repo.count_attempts(pass_.pass_id, "q1") == 1
    state1 = unit_labelling_state(repo, session_id, portal_id)
    assert state1["q1"].state == "awaiting"
    assert state1["q1"].badge == "Labelling not yet complete"

    # Run 2: 2nd attempt recorded, state still 'awaiting'
    res2 = await run_labelling_pass(settings.database_path, settings, runtime_failing, pass_.pass_id)
    assert res2.attempts_recorded == 1
    assert repo.count_attempts(pass_.pass_id, "q1") == 2
    state2 = unit_labelling_state(repo, session_id, portal_id)
    assert state2["q1"].state == "awaiting"

    # Run 3: 3rd attempt recorded, state transitions to 'exhausted'
    res3 = await run_labelling_pass(settings.database_path, settings, runtime_failing, pass_.pass_id)
    assert res3.attempts_recorded == 1
    assert repo.count_attempts(pass_.pass_id, "q1") == 3
    state3 = unit_labelling_state(repo, session_id, portal_id)
    assert state3["q1"].state == "exhausted"
    assert state3["q1"].badge == "Labelling was attempted and could not be completed"

    # Run 4: dispute is exhausted, skipped without model call
    calls_before = failing_provider.call_count
    res4 = await run_labelling_pass(settings.database_path, settings, runtime_failing, pass_.pass_id)
    assert res4.attempts_recorded == 0
    assert res4.skipped_already_complete == 1
    assert failing_provider.call_count == calls_before
    assert repo.count_attempts(pass_.pass_id, "q1") == 3

    # Amending a submission does not bring an exhausted dispute back into scope (FR-DL-059)
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id="q1",
            portal_id=portal_id,
            role=AssessorRole.A,
            assessor_actor_id="actor-a",
            answer=True,
            evidence_url="https://gov.example/updated",
            notes="Updated notes",
            submitted_at=utcnow(),
        )
    )

    state_after_amend = unit_labelling_state(repo, session_id, portal_id)
    assert state_after_amend["q1"].state == "exhausted"

    # Running the pass again with a working provider still skips the exhausted dispute
    working_provider = fake_label_provider()
    runtime_working = MockRuntime(working_provider)
    res5 = await run_labelling_pass(settings.database_path, settings, runtime_working, pass_.pass_id)
    assert res5.labelled_classifier == 0
    assert res5.skipped_already_complete == 1
    assert len(working_provider.calls) == 0


@pytest.mark.asyncio
async def test_two_failures_then_success_establishes_label(
    conn, settings, disputed_unit, raising_provider, fake_label_provider
):
    """A provider failing twice then succeeding produces 2 attempt rows and 1 established label."""
    repo = Repository(conn)
    cycle_id = "retry2-cycle"
    portal_id = "portal-retry2"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1"], 0.0, cycle_id=cycle_id)

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    failing_provider = raising_provider(RuntimeError("Transient 503"))
    runtime_failing = MockRuntime(failing_provider)

    # Attempt 1
    await run_labelling_pass(settings.database_path, settings, runtime_failing, pass_.pass_id)
    assert repo.count_attempts(pass_.pass_id, "q1") == 1

    # Attempt 2
    await run_labelling_pass(settings.database_path, settings, runtime_failing, pass_.pass_id)
    assert repo.count_attempts(pass_.pass_id, "q1") == 2

    # Attempt 3: succeeds with working provider
    working_provider = fake_label_provider()
    runtime_working = MockRuntime(working_provider)
    res = await run_labelling_pass(settings.database_path, settings, runtime_working, pass_.pass_id)
    assert res.labelled_classifier == 1
    assert repo.count_attempts(pass_.pass_id, "q1") == 2

    labels = repo.list_labels_for_unit(session_id, portal_id)
    assert len(labels) == 1
    assert labels[0].label == DisagreementLabel.DIFFERENT_JUDGEMENT

    state = unit_labelling_state(repo, session_id, portal_id)
    assert state["q1"].state == "established"


@pytest.mark.asyncio
async def test_schema_rejected_counts_as_attempt(
    conn, settings, disputed_unit, fake_label_provider
):
    """T052: Confirm that a schema_rejected response counts as an attempt and writes failure='schema_rejected'."""
    repo = Repository(conn)
    cycle_id = "schema-cycle"
    portal_id = "portal-schema"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1"], 0.0, cycle_id=cycle_id)

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    # Invalid enum returned: 'different_sources' is not in CLASSIFIER_LABELS
    provider = fake_label_provider({
        "label": "different_sources",
        "reason": "Sources differ",
        "position_1_notes_contradict_answer": False,
        "position_2_notes_contradict_answer": False,
    })
    runtime = MockRuntime(provider)

    res = await run_labelling_pass(settings.database_path, settings, runtime, pass_.pass_id)
    assert res.attempts_recorded == 1
    assert res.labelled_classifier == 0

    attempts = conn.execute("SELECT * FROM labelling_attempts WHERE pass_id = ?", (pass_.pass_id,)).fetchall()
    assert len(attempts) == 1
    assert attempts[0]["failure"] == "schema_rejected"


def test_cli_label_drain_consumes_attempt_and_completes_without_new_pass(
    conn, settings, disputed_unit, fake_label_provider, raising_provider
):
    """T057: aiq label drain completes existing pass without creating a new pass row, consuming one attempt then establishing."""
    repo = Repository(conn)
    cycle_id = "drain-cycle"
    portal_id = "portal-drain"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1"], 0.0, cycle_id=cycle_id)

    # Pass was dispatched when provider was available
    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_ids=["q1"],
        threshold=0.0,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    pass_count_initial = conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0]
    assert pass_count_initial == 1

    # Record 1 attempt already failed
    from shared.state.entities import LabellingAttempt
    repo.insert_labelling_attempt(
        LabellingAttempt(new_id("att"), pass_.pass_id, "q1", "provider_error", "First failure")
    )
    assert repo.count_attempts(pass_.pass_id, "q1") == 1

    runner = CliRunner()

    # 1. Drain with failing provider: consumes 1 more attempt -> now 2 attempts
    failing_p = raising_provider(RuntimeError("503 Down"))
    with patch("api.runtime.AIRuntime") as mock_rt_cls:
        mock_rt = AsyncMock()
        mock_rt.provider = failing_p
        mock_rt_cls.return_value = mock_rt

        result = runner.invoke(
            main,
            ["label", "drain", "--cycle", cycle_id],
            obj={"settings": settings},
        )
        assert result.exit_code == 0
        assert "Before drain:" in result.output
        assert "After drain:" in result.output

    # No new pass row created!
    pass_count_after = conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0]
    assert pass_count_after == 1
    assert repo.count_attempts(pass_.pass_id, "q1") == 2
    state = unit_labelling_state(repo, session_id, portal_id)
    assert state["q1"].state == "awaiting"

    # 2. Drain with working provider: completes the dispute and establishes label
    working_p = fake_label_provider()
    with patch("api.runtime.AIRuntime") as mock_rt_cls:
        mock_rt = AsyncMock()
        mock_rt.provider = working_p
        mock_rt_cls.return_value = mock_rt

        result2 = runner.invoke(
            main,
            ["label", "drain", "--cycle", cycle_id],
            obj={"settings": settings},
        )
        assert result2.exit_code == 0

    # Still exactly 1 pass row
    assert conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0] == 1
    # Label is now established
    labels = repo.list_labels_for_unit(session_id, portal_id)
    assert len(labels) == 1
    assert labels[0].label == DisagreementLabel.DIFFERENT_JUDGEMENT
    state_final = unit_labelling_state(repo, session_id, portal_id)
    assert state_final["q1"].state == "established"
