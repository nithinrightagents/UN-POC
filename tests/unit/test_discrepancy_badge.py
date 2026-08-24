"""Unit tests for discrepancy badge rendering (US5, FR-DR-040..046)."""

from __future__ import annotations

import pytest

from portal.reconciliation import UnitReconciliationState, render_badge

pytestmark = pytest.mark.unit


def test_render_badge_full_consensus():
    state = UnitReconciliationState(
        state="full_consensus",
        rate=0.0,
        compared_count=157,
        disputed_question_ids=[],
        tolerance_in_force=0.05,
        rounds_consumed=0,
        automatic_round_used=False,
    )
    badge = render_badge(state)
    assert "badge--yes" in badge
    assert "Full consensus — 0%" in badge
    assert "157 indicators" in badge
    assert "✓" in badge


def test_render_badge_within_tolerance():
    state = UnitReconciliationState(
        state="within_tolerance",
        rate=0.03,
        compared_count=100,
        disputed_question_ids=["Q1", "Q2", "Q3"],
        tolerance_in_force=0.05,
        rounds_consumed=0,
        automatic_round_used=False,
    )
    badge = render_badge(state)
    assert "badge--warn" in badge
    assert "3% — within 5% tolerance" in badge
    assert "100 indicators" in badge
    assert "✓" in badge


def test_render_badge_above_tolerance_in_progress():
    state = UnitReconciliationState(
        state="above_tolerance_in_progress",
        rate=0.333,
        compared_count=3,
        disputed_question_ids=["Q3"],
        tolerance_in_force=0.05,
        rounds_consumed=0,
        automatic_round_used=False,
    )
    badge = render_badge(state)
    assert "badge--flag" in badge
    assert "33.3% — above 5%, assessment in progress" in badge
    assert "3 indicators" in badge
    assert "⚠" in badge


def test_render_badge_reconciliation_open():
    state = UnitReconciliationState(
        state="reconciliation_open",
        rate=0.10,
        compared_count=50,
        disputed_question_ids=["Q1", "Q2", "Q3", "Q4", "Q5"],
        tolerance_in_force=0.05,
        rounds_consumed=1,
        automatic_round_used=True,
        open_round_id="rnd-123",
    )
    badge = render_badge(state)
    assert "badge--flag" in badge
    assert "10% — reconciliation open" in badge
    assert "50 indicators" in badge
    assert "⚠" in badge


def test_render_badge_persistent_discrepancy():
    state = UnitReconciliationState(
        state="persistent_discrepancy",
        rate=0.08,
        compared_count=100,
        disputed_question_ids=["Q1"],
        tolerance_in_force=0.05,
        rounds_consumed=1,
        automatic_round_used=True,
    )
    badge = render_badge(state)
    assert "badge--flag" in badge
    assert "8% — reconciliation exhausted, awaiting Senior Reviewer" in badge
    assert "100 indicators" in badge
    assert "⚠" in badge


def test_render_badge_awaiting_second_assessment():
    state = UnitReconciliationState(
        state="awaiting_second_assessment",
        rate=None,
        compared_count=0,
        disputed_question_ids=[],
        tolerance_in_force=0.05,
        rounds_consumed=0,
        automatic_round_used=False,
    )
    badge = render_badge(state)
    assert "badge--neutral" in badge
    assert "Awaiting second assessment" in badge
    # No rate displayed
    assert "%" not in badge


def test_render_badge_custom_project_tolerance():
    state = UnitReconciliationState(
        state="within_tolerance",
        rate=0.08,
        compared_count=100,
        disputed_question_ids=["Q1"],
        tolerance_in_force=0.10,
        rounds_consumed=0,
        automatic_round_used=False,
    )
    badge = render_badge(state)
    assert "8% — within 10% tolerance" in badge


def test_fifty_page_loads_write_no_discrepancy_cases_or_escalations(client, conn):
    from portal.common import ensure_session
    from shared.persistence.repositories import Repository
    from shared.state.entities import (
        AnswerType,
        AssessorRole,
        EvidenceLocus,
        HumanAssessorSubmission,
        ProjectType,
        Question,
        SurveyCycle,
        TargetPortal,
        new_id,
    )

    repo = Repository(conn)
    cycle_id = "badge-cycle"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Badge Cycle",
            questionnaire_ref="test",
            country_set=["DK"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.05,
        )
    )
    session_id = ensure_session(repo, cycle_id)
    portal_id = "portal-dk"
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="DK",
            unit_type="country",
            display_name="Denmark",
        )
    )
    q = Question(
        question_id=f"{cycle_id}:Q1",
        cycle_id=cycle_id,
        text="Q1",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        indicator_id="Q1",
        question_class="Core",
        title="Q1",
        what="W",
        why="Y",
        how={},
    )
    repo.insert_question(q)

    # Assessor A submits answer
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=q.question_id,
            portal_id=portal_id,
            role=AssessorRole.A,
            assessor_actor_id="actor-a",
            answer=True,
        )
    )

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    cases_before = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    esc_before = cursor.fetchone()[0]

    # Perform 50 page loads of admin project detail (SC-010)
    for _ in range(50):
        resp = client.get(f"/admin/projects/{cycle_id}")
        assert resp.status_code == 200

    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    cases_after = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    esc_after = cursor.fetchone()[0]

    assert cases_after == cases_before
    assert esc_after == esc_before


def test_publish_refused_re_render_produces_identical_badge(client, conn):
    from portal.common import ensure_session
    from shared.persistence.repositories import Repository
    from shared.state.entities import (
        AnswerType,
        AssessorRole,
        EvidenceLocus,
        HumanAssessorSubmission,
        ProjectType,
        Question,
        SurveyCycle,
        TargetPortal,
        new_id,
    )

    repo = Repository(conn)
    cycle_id = "pub-refuse-cycle"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Refuse Cycle",
            questionnaire_ref="test",
            country_set=["SE"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.08,
        )
    )
    session_id = ensure_session(repo, cycle_id)
    portal_id = "portal-se"
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="SE",
            unit_type="country",
            display_name="Sweden",
        )
    )
    q = Question(
        question_id=f"{cycle_id}:Q1",
        cycle_id=cycle_id,
        text="Q1",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        indicator_id="Q1",
        question_class="Core",
        title="Q1",
        what="W",
        why="Y",
        how={},
    )
    repo.insert_question(q)

    # Both assessors submit different answers
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=q.question_id,
            portal_id=portal_id,
            role=AssessorRole.A,
            assessor_actor_id="actor-a",
            answer=True,
        )
    )
    repo.insert_human_submission(
        HumanAssessorSubmission(
            submission_id=new_id("sub"),
            session_id=session_id,
            cycle_id=cycle_id,
            question_id=q.question_id,
            portal_id=portal_id,
            role=AssessorRole.B,
            assessor_actor_id="actor-b",
            answer=False,
        )
    )

    # 1. Normal GET render
    resp_get = client.get(f"/admin/projects/{cycle_id}")
    assert resp_get.status_code == 200
    assert "100% — above 8%, assessment in progress" in resp_get.text

    # 2. Publish refused (incomplete assessor completion) -> 400 render
    resp_pub = client.post(
        f"/admin/projects/{cycle_id}/units/{portal_id}/publish",
        data={"actor_id": "senior-reviewer"},
    )
    assert resp_pub.status_code == 400
    assert "100% — above 8%, assessment in progress" in resp_pub.text

