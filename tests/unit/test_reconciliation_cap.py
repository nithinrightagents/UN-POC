"""Unit tests for Reconciliation Cap and Persistent Discrepancy (User Story 3, SC-006)."""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from portal.common import ensure_session
from portal.discrepancy import recompute_portal_discrepancy
from portal.reconciliation import (
    close_round_if_complete,
    open_automatic_round,
    round_history,
    unit_reconciliation_state,
)
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    AssessorCompletion,
    AssessorRole,
    EvidenceLocus,
    HumanAssessorSubmission,
    JointAnswer,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


def _setup_cap_unit(repo: Repository, total: int = 100, disputes: int = 10):
    cycle_id = "c-cap"
    portal_id = "DK"
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Cap Test Cycle",
            questionnaire_ref="un_osi_2024",
            country_set=["DK"],
            discrepancy_rate_threshold=0.05,
        )
    )
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="DK",
            resolved_url="https://dk.example.com",
            display_name="Denmark Cap",
        )
    )
    questions = []
    for i in range(total):
        q = Question(
            question_id=f"PF-{i:03d}",
            cycle_id=cycle_id,
            text=f"Indicator {i}",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
        repo.insert_question(q)
        questions.append(q)

    session_id = ensure_session(repo, cycle_id)

    # Assessor A submits True for all questions
    for q in questions:
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

    # Assessor B submits False for first `disputes` questions, True for the rest
    for i, q in enumerate(questions):
        ans = False if i < disputes else True
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=q.question_id,
                portal_id=portal_id,
                role=AssessorRole.B,
                assessor_actor_id="actor-b",
                answer=ans,
            )
        )

    # Both declare completion
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="A",
            actor_id="actor-a",
            indicator_count_at_declaration=total,
        )
    )
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_id,
            cycle_id=cycle_id,
            portal_id=portal_id,
            role="B",
            actor_id="actor-b",
            indicator_count_at_declaration=total,
        )
    )

    disputed_ids = [q.question_id for q in questions[:disputes]]
    round_obj = open_automatic_round(
        repo,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=disputed_ids,
        rate=disputes / total,
        tolerance=0.05,
    )
    return cycle_id, portal_id, session_id, questions, round_obj


def test_round_ending_above_tolerance_closes_exhausted_and_becomes_persistent_discrepancy(
    conn, client, settings
):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_cap_unit(repo, total=100, disputes=10)

    # In a 10-dispute unit with tolerance 5%, commit joint answers for all 10 disputes,
    # but 8 of them agree on False and 2 on True — wait, joint answers agree on ONE value for both sides,
    # so a joint answer ALWAYS creates agreement on that indicator.
    # To end above tolerance, suppose round was opened on 10 disputes, and joint answers are provided
    # for all 10, but other indicators later have disagreements, OR let's test a round where only some disputes are settled
    # Wait, how does a round end above tolerance?
    # Suppose a unit has 100 questions. 10 were disputed.
    # If 2 joint answers are committed and 8 are committed as False, all 10 have joint answers, so rate becomes 0%.
    # BUT if in the meantime another indicator was modified to disagree (or if tolerance is 0.01 and 2 disputes remain unsettled... wait, round only closes when ALL 10 disputed indicators have joint answers).
    # If all 10 have joint answers, rate is 0/100 <= 0.05.
    # What if tolerance is 0.05, 10 indicators were in round's disputed set, but meanwhile 6 other indicators outside the round were changed to disagree? Then when the round's 10 joint answers are committed, remaining disagreements = 6 / 100 = 6% > 5% tolerance!
    # Let's verify:
    # Modify 6 other indicators (PF-010 to PF-015) to disagree:
    for i in range(10, 16):
        qid = f"PF-{i:03d}"
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=qid,
                portal_id=portal_id,
                role=AssessorRole.B,
                assessor_actor_id="actor-b",
                answer=False,  # now disagrees with A's True
            )
        )

    # Now settle all 10 questions in the opening round (PF-000..PF-009)
    for i in range(10):
        qid = f"PF-{i:03d}"
        ja = JointAnswer(
            joint_answer_id=new_id("joint"),
            session_id=session_id,
            portal_id=portal_id,
            question_id=qid,
            round_id=round_obj.round_id,
            data={
                "answer": True,
                "justification": f"Settled {qid}",
                "submitted_by_role": "A",
                "submitted_by_actor_id": "actor-a",
            },
            created_at=datetime.now(timezone.utc),
        )
        repo.insert_joint_answer(ja)

    # Close round if complete
    closed_rnd = close_round_if_complete(
        repo, round_obj.round_id, session_id, cycle_id, portal_id, questions, settings
    )
    assert closed_rnd is not None
    assert closed_rnd.state == "exhausted"

    # Unit reconciliation state is now persistent_discrepancy
    state = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings)
    assert state.state == "persistent_discrepancy"
    assert pytest.approx(state.rate, 0.001) == 0.06
    assert state.rounds_consumed == 1
    assert state.automatic_round_used is True

    # 50 further submissions produce NO second automatic round (SC-006)
    for step in range(50):
        qid = f"PF-{(step % 80) + 20:03d}"
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=qid,
                portal_id=portal_id,
                role=AssessorRole.A,
                assessor_actor_id="actor-a",
                answer=(step % 2 == 0),
            )
        )
        # Trigger recompute
        recompute_portal_discrepancy(
            repo, session_id, portal_id, [q.question_id for q in questions], 0.05, cycle_id=cycle_id
        )

    # Assert exactly 1 round exists across history
    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    assert len(rounds) == 1
    assert rounds[0].opened_by == "automatic"

    # Verify round history helper (T040)
    history = round_history(repo, session_id, portal_id)
    assert len(history) == 1
    assert history[0]["round_number"] == 1
    assert history[0]["opened_by"] == "automatic"
    assert history[0]["state"] == "exhausted"

    # Assessor visiting questionnaire sees persistent discrepancy notice and no workspace redirect (FR-DR-035)
    resp = client.get(f"/assessor/{cycle_id}/{portal_id}?role=A&actor_id=actor-a")
    assert resp.status_code == 200
    assert "Reconciliation Exhausted — Awaiting Senior Reviewer" in resp.text


def test_disagreement_after_resolved_round_goes_straight_to_persistent_discrepancy(
    conn, settings
):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_cap_unit(repo, total=100, disputes=4)

    # Settle all 4 disputes
    for i in range(4):
        qid = f"PF-{i:03d}"
        ja = JointAnswer(
            joint_answer_id=new_id("joint"),
            session_id=session_id,
            portal_id=portal_id,
            question_id=qid,
            round_id=round_obj.round_id,
            data={
                "answer": True,
                "justification": f"Settled {qid}",
                "submitted_by_role": "A",
                "submitted_by_actor_id": "actor-a",
            },
            created_at=datetime.now(timezone.utc),
        )
        repo.insert_joint_answer(ja)

    closed_rnd = close_round_if_complete(
        repo, round_obj.round_id, session_id, cycle_id, portal_id, questions, settings
    )
    assert closed_rnd.state == "resolved"

    # Unit was resolved (0% disagreement)
    state = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings)
    assert state.state == "full_consensus"

    # Now introduce 10 new disagreements (10% > 5% tolerance)
    for i in range(10, 20):
        qid = f"PF-{i:03d}"
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=qid,
                portal_id=portal_id,
                role=AssessorRole.B,
                assessor_actor_id="actor-b",
                answer=False,
            )
        )

    # Recompute discrepancy
    recompute_portal_discrepancy(
        repo, session_id, portal_id, [q.question_id for q in questions], 0.05, cycle_id=cycle_id
    )

    # Because automatic round is already spent, state goes straight to persistent_discrepancy (FR-DR-036)
    new_state = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings)
    assert new_state.state == "persistent_discrepancy"
    assert new_state.automatic_round_used is True

    # No second round was opened
    rounds = repo.list_rounds_for_unit(session_id, portal_id)
    assert len(rounds) == 1


def test_senior_reviewer_return_opens_round_2_and_routes_assessors_back(conn, client, settings):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_cap_unit(repo, total=100, disputes=10)

    # Put unit in persistent discrepancy by exhausting round 1
    for i in range(10, 16):
        qid = f"PF-{i:03d}"
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=qid,
                portal_id=portal_id,
                role=AssessorRole.B,
                assessor_actor_id="actor-b",
                answer=False,
            )
        )
    for i in range(10):
        qid = f"PF-{i:03d}"
        repo.insert_joint_answer(
            JointAnswer(
                joint_answer_id=new_id("joint"),
                session_id=session_id,
                portal_id=portal_id,
                question_id=qid,
                round_id=round_obj.round_id,
                data={
                    "answer": True,
                    "justification": f"Settled {qid}",
                    "submitted_by_role": "A",
                    "submitted_by_actor_id": "actor-a",
                },
                created_at=datetime.now(timezone.utc),
            )
        )
    close_round_if_complete(repo, round_obj.round_id, session_id, cycle_id, portal_id, questions, settings)

    # Unit is in persistent discrepancy
    assert unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings).state == "persistent_discrepancy"

    # Find the open escalation item
    items = repo.list_escalations(session_id, unresolved_only=True)
    esc_item = next(it for it in items if it.portal_id == portal_id)

    # Reviewer returns for another round with stated reason
    resp = client.post(
        f"/admin/projects/{cycle_id}/escalations/{esc_item.item_id}/dispose",
        data={
            "resolution": "returned_for_reconciliation",
            "notes": "Please re-check the 6 ministry indicators under national domain guidelines.",
            "actor_id": "senior-reviewer-sarah",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Round 2 is now open
    r2 = repo.open_round_for_unit(session_id, portal_id)
    assert r2 is not None
    assert r2.round_number == 2
    assert r2.opened_by == "senior_reviewer"
    assert r2.opened_by_actor_id == "senior-reviewer-sarah"
    assert r2.opened_reason == "Please re-check the 6 ministry indicators under national domain guidelines."
    assert r2.data["disputed_question_ids"] == [f"PF-{i:03d}" for i in range(10, 16)]

    # Unit reconciliation state is reconciliation_open
    recon_st = unit_reconciliation_state(repo, session_id, cycle_id, portal_id, questions, settings)
    assert recon_st.state == "reconciliation_open"
    assert recon_st.rounds_consumed == 2

    # Assessor visiting unit_form gets redirected to workspace (/reconcile)
    resp_assessor = client.get(f"/assessor/{cycle_id}/{portal_id}?role=A&actor_id=actor-a", follow_redirects=False)
    assert resp_assessor.status_code == 303
    assert f"/assessor/{cycle_id}/{portal_id}/reconcile" in resp_assessor.headers["location"]


def test_senior_reviewer_return_without_reason_refused(conn, client, settings):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_cap_unit(repo, total=100, disputes=10)

    # Exhaust round 1
    for i in range(10, 16):
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("sub"),
                session_id=session_id,
                cycle_id=cycle_id,
                question_id=f"PF-{i:03d}",
                portal_id=portal_id,
                role=AssessorRole.B,
                assessor_actor_id="actor-b",
                answer=False,
            )
        )
    for i in range(10):
        repo.insert_joint_answer(
            JointAnswer(
                joint_answer_id=new_id("joint"),
                session_id=session_id,
                portal_id=portal_id,
                question_id=f"PF-{i:03d}",
                round_id=round_obj.round_id,
                data={"answer": True, "justification": "Settled", "submitted_by_role": "A", "submitted_by_actor_id": "actor-a"},
                created_at=datetime.now(timezone.utc),
            )
        )
    close_round_if_complete(repo, round_obj.round_id, session_id, cycle_id, portal_id, questions, settings)

    items = repo.list_escalations(session_id, unresolved_only=True)
    esc_item = next(it for it in items if it.portal_id == portal_id)

    # Empty notes / reason
    resp = client.post(
        f"/admin/projects/{cycle_id}/escalations/{esc_item.item_id}/dispose",
        data={
            "resolution": "returned_for_reconciliation",
            "notes": "   ",
            "actor_id": "senior-reviewer-sarah",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert repo.open_round_for_unit(session_id, portal_id) is None


def test_concurrent_reviewer_dispositions_surfaces_already_decided(conn, client, settings):
    repo = Repository(conn)
    cycle_id, portal_id, session_id, questions, round_obj = _setup_cap_unit(repo, total=100, disputes=10)

    # First reviewer disposes
    items = repo.list_escalations(session_id, unresolved_only=True)
    esc_item = next(it for it in items if it.portal_id == portal_id)

    from review.escalations import dispose_escalation
    dispose_escalation(repo, esc_item.item_id, "senior_reviewer_override", "reviewer-1", "Resolved first")

    # Second reviewer tries disposing through admin POST route
    resp = client.post(
        f"/admin/projects/{cycle_id}/escalations/{esc_item.item_id}/dispose",
        data={
            "resolution": "published_unresolved",
            "notes": "Publish anyway",
            "actor_id": "reviewer-2",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "already%20been%20decided" in resp.headers["location"] or "already" in resp.headers["location"].lower()

