"""Characterisation suite for src/portal/discrepancy.py (Scenario 0).

Pins the existing behaviour of the human A/B discrepancy engine before
modifications for 012-portal-discrepancy-reconciliation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import pytest

from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessorRole,
    EscalationReason,
    HumanAssessorSubmission,
    new_id,
)
from portal.discrepancy import (
    _compare,
    compute_portal_discrepancy,
    recompute_portal_discrepancy,
    find_resolved_answer,
)


def _submit(
    repo: Repository,
    session_id: str,
    portal_id: str,
    question_id: str,
    role: AssessorRole,
    answer: bool,
    actor_id: str = "test-actor",
):
    sub = HumanAssessorSubmission(
        submission_id=new_id("sub"),
        session_id=session_id,
        cycle_id="c-2024",
        question_id=question_id,
        portal_id=portal_id,
        role=role,
        assessor_actor_id=actor_id,
        answer=answer,
        evidence_url="https://example.com",
        notes="",
        ai_suggested_answer=None,
        ai_suggestion_accepted=None,
        submitted_at=datetime.now(timezone.utc),
    )
    repo.insert_human_submission(sub)
    return sub


def _declare_both(repo: Repository, session_id: str, portal_id: str, count: int = 2):
    from shared.state.entities import AssessorCompletion
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id="c-2024",
            portal_id=portal_id,
            role="A",
            actor_id="actor-A",
            indicator_count_at_declaration=count,
        )
    )
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id="c-2024",
            portal_id=portal_id,
            role="B",
            actor_id="actor-B",
            indicator_count_at_declaration=count,
        )
    )


@pytest.mark.unit
def test_no_overlap_returns_none_and_writes_nothing(conn):
    repo = Repository(conn)
    session_id = "s-no-overlap"
    portal_id = "DK"
    questions = ["Q1", "Q2"]

    # Only Assessor A answers Q1, only Assessor B answers Q2 (no common intersection)
    _submit(repo, session_id, portal_id, "Q1", AssessorRole.A, True)
    _submit(repo, session_id, portal_id, "Q2", AssessorRole.B, True)

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    cases_before = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    queue_before = cursor.fetchone()[0]

    res_compute = compute_portal_discrepancy(repo, session_id, portal_id, questions, 0.05)
    assert res_compute is None

    res_recompute = recompute_portal_discrepancy(repo, session_id, portal_id, questions, 0.05)
    assert res_recompute is None

    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    assert cursor.fetchone()[0] == cases_before
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    assert cursor.fetchone()[0] == queue_before


@pytest.mark.unit
def test_rate_computed_over_intersection_only(conn):
    repo = Repository(conn)
    session_id = "s-intersection"
    portal_id = "DK"
    questions = ["Q1", "Q2", "Q3", "Q4"]

    # A answers Q1, Q2, Q3. B answers Q2, Q3, Q4.
    # Intersection is {Q2, Q3} (len=2).
    # Suppose Q2 agree (True vs True), Q3 disagree (True vs False).
    # Disagreements = 1 / 2 = 0.5 (50%), not 1/4 (25%) or 3/4.
    _submit(repo, session_id, portal_id, "Q1", AssessorRole.A, True)
    _submit(repo, session_id, portal_id, "Q2", AssessorRole.A, True)
    _submit(repo, session_id, portal_id, "Q3", AssessorRole.A, True)

    _submit(repo, session_id, portal_id, "Q2", AssessorRole.B, True)
    _submit(repo, session_id, portal_id, "Q3", AssessorRole.B, False)
    _submit(repo, session_id, portal_id, "Q4", AssessorRole.B, True)

    cmp = _compare(repo, session_id, portal_id, questions, 0.05)
    assert cmp is not None
    common, disagreements, rate, flagged = cmp
    assert sorted(common) == ["Q2", "Q3"]
    assert disagreements == ["Q3"]
    assert rate == 0.5
    assert flagged is True


@pytest.mark.unit
def test_rate_equal_threshold_is_within_tolerance(conn):
    repo = Repository(conn)
    session_id = "s-threshold"
    portal_id = "DK"
    questions = [f"Q{i}" for i in range(20)]

    # 20 questions in common. 1 disagreement -> 1/20 = 0.05 (5.0%).
    # When threshold is 0.05, rate == threshold is NOT flagged (rate > threshold is required).
    for i in range(20):
        qid = f"Q{i}"
        _submit(repo, session_id, portal_id, qid, AssessorRole.A, True)
        # B disagrees on Q0 only
        _submit(repo, session_id, portal_id, qid, AssessorRole.B, False if i == 0 else True)

    cmp = _compare(repo, session_id, portal_id, questions, 0.05)
    assert cmp is not None
    common, disagreements, rate, flagged = cmp
    assert rate == 0.05
    assert flagged is False  # rate == threshold is within tolerance!

    # But with threshold 0.049, rate (0.05) > threshold (0.049) -> flagged
    cmp_flagged = _compare(repo, session_id, portal_id, questions, 0.049)
    assert cmp_flagged is not None
    assert cmp_flagged[3] is True


@pytest.mark.unit
def test_compute_portal_discrepancy_writes_nothing_after_50_calls(conn):
    repo = Repository(conn)
    session_id = "s-compute-nowrite"
    portal_id = "DK"
    questions = ["Q1", "Q2"]

    _submit(repo, session_id, portal_id, "Q1", AssessorRole.A, True)
    _submit(repo, session_id, portal_id, "Q1", AssessorRole.B, False)

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    cases_before = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    queue_before = cursor.fetchone()[0]

    for _ in range(50):
        res = compute_portal_discrepancy(repo, session_id, portal_id, questions, 0.05)
        assert res is not None
        assert res.outcome == "flagged_for_arbitration"

    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    assert cursor.fetchone()[0] == cases_before
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    assert cursor.fetchone()[0] == queue_before


@pytest.mark.unit
def test_recompute_writes_case_always_and_queue_item_only_when_flagged(conn):
    repo = Repository(conn)
    portal_id = "DK"
    questions = ["Q1", "Q2"]

    # Case 1: unflagged (both agree)
    session_unflagged = "s-unflagged"
    _submit(repo, session_unflagged, portal_id, "Q1", AssessorRole.A, True)
    _submit(repo, session_unflagged, portal_id, "Q1", AssessorRole.B, True)

    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    c0 = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    q0 = cursor.fetchone()[0]

    case1 = recompute_portal_discrepancy(repo, session_unflagged, portal_id, questions, 0.05)
    assert case1 is not None
    assert case1.outcome == "within_threshold"

    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    assert cursor.fetchone()[0] == c0 + 1
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    assert cursor.fetchone()[0] == q0  # No queue item created

    # Case 2: flagged (disagreement)
    session_flagged = "s-flagged"
    _submit(repo, session_flagged, portal_id, "Q1", AssessorRole.A, True)
    _submit(repo, session_flagged, portal_id, "Q1", AssessorRole.B, False)
    _declare_both(repo, session_flagged, portal_id, 2)

    case2 = recompute_portal_discrepancy(repo, session_flagged, portal_id, questions, 0.05)
    assert case2 is not None
    assert case2.outcome == "flagged_for_arbitration"

    cursor.execute("SELECT COUNT(*) FROM discrepancy_cases")
    assert cursor.fetchone()[0] == c0 + 2
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items")
    assert cursor.fetchone()[0] == q0 + 1


@pytest.mark.unit
def test_idempotency_guard_suppresses_duplicate_queue_item(conn):
    repo = Repository(conn)
    session_id = "s-idempotency"
    portal_id = "DK"
    questions = ["Q1", "Q2", "Q3"]

    # Q1 disagrees (A=True, B=False)
    _submit(repo, session_id, portal_id, "Q1", AssessorRole.A, True)
    _submit(repo, session_id, portal_id, "Q1", AssessorRole.B, False)
    _declare_both(repo, session_id, portal_id, 3)

    # First recompute -> creates 1 case, 1 queue item
    recompute_portal_discrepancy(repo, session_id, portal_id, questions, 0.05)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items WHERE session_id = ?", (session_id,))
    assert cursor.fetchone()[0] == 1

    # Second recompute with same disagreements (Q1) -> creates 2nd case, but suppresses 2nd queue item
    recompute_portal_discrepancy(repo, session_id, portal_id, questions, 0.05)
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items WHERE session_id = ?", (session_id,))
    assert cursor.fetchone()[0] == 1

    # Third recompute after adding disagreement on Q2 -> round is already open -> suppresses additional queue item (FR-DR-030)
    _submit(repo, session_id, portal_id, "Q2", AssessorRole.A, True)
    _submit(repo, session_id, portal_id, "Q2", AssessorRole.B, False)
    recompute_portal_discrepancy(repo, session_id, portal_id, questions, 0.05)
    cursor.execute("SELECT COUNT(*) FROM escalation_queue_items WHERE session_id = ?", (session_id,))
    assert cursor.fetchone()[0] == 1


@pytest.mark.unit
def test_find_resolved_answer_returns_newest_covering_item_arbitration(conn):
    repo = Repository(conn)
    session_id = "s-find-resolved"
    portal_id = "DK"
    qid = "Q1"

    # No items -> returns None
    assert find_resolved_answer(repo, session_id, portal_id, qid) is None

    # Insert older escalation covering Q1 and arbitrate it to False
    _submit(repo, session_id, portal_id, qid, AssessorRole.A, True)
    _submit(repo, session_id, portal_id, qid, AssessorRole.B, False)
    _declare_both(repo, session_id, portal_id, 1)
    recompute_portal_discrepancy(repo, session_id, portal_id, [qid], 0.05)

    items = repo.list_escalations(session_id)
    assert len(items) == 1
    item_old = items[0]
    repo.record_disposition(
        item_id=item_old.item_id,
        disposition={
            "action": "arbitrate",
            "actor_id": "senior-reviewer",
            "notes": "old arbitration",
            "resolved_answers": {qid: False},
        },
    )

    # Now find_resolved_answer returns False
    assert find_resolved_answer(repo, session_id, portal_id, qid) is False

    # Insert newer escalation (e.g. resubmission) covering Q1 that is not yet arbitrated
    # Note: we need different disagreements or fresh item
    repo.insert_escalation(
        from_item := items[0].__class__(
            item_id=new_id("esc"),
            session_id=session_id,
            reason=EscalationReason.PORTAL_DISCREPANCY,
            context={
                "portal_id": portal_id,
                "differing_answer_rate": 1.0,
                "threshold": 0.05,
                "disagreements": [qid, "Q2"],
                "compared_questions": 2,
            },
            portal_id=portal_id,
        )
    )

    # Newest item is unresolved -> find_resolved_answer returns None (older disposition doesn't leak)
    assert find_resolved_answer(repo, session_id, portal_id, qid) is None

    # Now arbitrate newest item to True -> find_resolved_answer returns True
    repo.record_disposition(
        item_id=from_item.item_id,
        disposition={
            "action": "arbitrate",
            "actor_id": "senior-reviewer",
            "notes": "new arbitration",
            "resolved_answers": {qid: True},
        },
    )
    assert find_resolved_answer(repo, session_id, portal_id, qid) is True
