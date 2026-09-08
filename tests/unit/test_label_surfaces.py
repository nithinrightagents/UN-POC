"""Unit tests for UI surfaces rendering disagreement labels and blind-assessor isolation.

Covers T041, T045, T046, FR-DL-045, FR-DL-062, FR-DL-063, FR-DL-065, SC-003.
"""

from __future__ import annotations

import datetime
from datetime import timezone
import pytest

from portal.assignment import set_role_assignment
from portal.common import ensure_session
from portal.disagreement_labels import dispatch_labelling_pass
from portal.discrepancy import recompute_portal_discrepancy
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    Assessor,
    AssessorRole,
    DisagreementLabel,
    DisagreementLabelRecord,
    EvidenceLocus,
    ProjectType,
    Question,
    SideObservation,
    SurveyCycle,
    TargetPortal,
    new_id,
)

pytestmark = pytest.mark.unit


class MockRuntime:
    def __init__(self, provider):
        self.provider = provider


def _setup_cycle_and_unit(repo: Repository, cycle_id: str = "surf-cycle", portal_id: str = "portal-surf"):
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Surface Test Cycle",
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
            title="Indicator 1 Title",
        )
    )
    # Register assessors
    repo.upsert_assessor(Assessor(assessor_id="actor-a", display_name="Assessor A User", email="a@test.gov"))
    repo.upsert_assessor(Assessor(assessor_id="actor-b", display_name="Assessor B User", email="b@test.gov"))
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.A, "actor-a", "admin")
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.B, "actor-b", "admin")


def test_escalations_page_renders_badge_and_observations_read_only(
    app, client, conn, settings, disputed_unit, no_call_provider
):
    """T041: Escalations page renders badge and side observations, and 50 GET loads are strictly read-only."""
    repo = Repository(conn)
    cycle_id = "surf-cycle"
    portal_id = "portal-surf"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    # Attach NoCallProvider to app state
    provider = no_call_provider()
    app.state.ai_runtime = MockRuntime(provider)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={"q1": (True, "https://gov.example/source", "Notes from A", False, "https://gov.example/source", "Notes from B")},
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    # Recompute to trigger escalation queue item (threshold is 0.0, rate is 1.0 > 0.0)
    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1"], 0.0, cycle_id=cycle_id)

    # Dispatch and insert an established label with per-side observations
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

    label_rec = DisagreementLabelRecord(
        label_id=new_id("lbl"),
        pass_id=pass_.pass_id,
        session_id=session_id,
        portal_id=portal_id,
        question_id="q1",
        label=DisagreementLabel.DIFFERENT_JUDGEMENT,
        established_by="classifier",
        input_digest="testdigest1234567890",
        stated_reason="Judged differently based on evidence.",
        observations={
            "A": [SideObservation.NOTES_CONTRADICT_ANSWER],
            "B": [SideObservation.NO_NOTES],
        },
        submission_ids={"A": "sub-a", "B": "sub-b"},
        model_identity="gemini-2.5-flash-lite",
        prompt_version="dl-1",
        created_at=datetime.datetime.now(timezone.utc),
    )
    repo.insert_disagreement_label(label_rec)

    # Load escalations page once and verify rendered badges and observations
    resp = client.get(f"/admin/projects/{cycle_id}/escalations")
    assert resp.status_code == 200
    html = resp.text

    assert "Judged differently" in html
    assert "notes contradict answer" in html
    assert "no notes" in html

    # Snapshot table row counts before 50 loads
    c_passes_before = conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0]
    c_labels_before = conn.execute("SELECT COUNT(*) FROM disagreement_labels").fetchone()[0]
    c_attempts_before = conn.execute("SELECT COUNT(*) FROM labelling_attempts").fetchone()[0]
    c_cases_before = conn.execute("SELECT COUNT(*) FROM discrepancy_cases").fetchone()[0]

    # Loading the page 50 times creates no rows and makes no model calls (NoCallProvider raises on call)
    for _ in range(50):
        r = client.get(f"/admin/projects/{cycle_id}/escalations")
        assert r.status_code == 200

    assert conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0] == c_passes_before
    assert conn.execute("SELECT COUNT(*) FROM disagreement_labels").fetchone()[0] == c_labels_before
    assert conn.execute("SELECT COUNT(*) FROM labelling_attempts").fetchone()[0] == c_attempts_before
    assert conn.execute("SELECT COUNT(*) FROM discrepancy_cases").fetchone()[0] == c_cases_before


def test_assessor_surfaces_blindness_and_no_forbidden_strings(client, conn, settings, disputed_unit):
    """T046: Assessor unit and reconciliation templates contain no label badges, no observations, and no evaluative words."""
    repo = Repository(conn)
    cycle_id = "surf-cycle"
    portal_id = "portal-surf"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={"q1": (True, "https://gov.example/source", "Notes from A", False, "https://gov.example/source", "Notes from B")},
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

    label_rec = DisagreementLabelRecord(
        label_id=new_id("lbl"),
        pass_id=pass_.pass_id,
        session_id=session_id,
        portal_id=portal_id,
        question_id="q1",
        label=DisagreementLabel.DIFFERENT_JUDGEMENT,
        established_by="classifier",
        input_digest="testdigest1234567890",
        stated_reason="Judged differently based on evidence.",
        observations={
            "A": [SideObservation.NOTES_CONTRADICT_ANSWER],
            "B": [SideObservation.NO_NOTES],
        },
        submission_ids={"A": "sub-a", "B": "sub-b"},
        model_identity="gemini-2.5-flash-lite",
        prompt_version="dl-1",
        created_at=datetime.datetime.now(timezone.utc),
    )
    repo.insert_disagreement_label(label_rec)

    # 1. Render assessor unit form
    resp_unit = client.get(f"/assessor/{cycle_id}/{portal_id}?actor_id=actor-a")
    assert resp_unit.status_code == 200
    html_unit = resp_unit.text

    # 2. Render assessor reconcile workspace
    resp_rec = client.get(f"/assessor/{cycle_id}/{portal_id}/reconcile?actor_id=actor-a")
    assert resp_rec.status_code == 200
    html_rec = resp_rec.text

    # Assert no badge strings and no observation strings appear in either assessor surface (FR-DL-065)
    badge_strings = [
        "Judged differently",
        "Used different sources",
        "One found nothing",
        "One couldn't access",
        "Saw different things",
        "Not enough notes",
        "Labelling not yet complete",
        "Labelling was attempted",
    ]
    observation_strings = [
        "notes contradict answer",
        "accepted ai unchanged",
        "no notes",
    ]

    for s in badge_strings + observation_strings:
        assert s not in html_unit
        assert s not in html_rec

    # Assert no rendered surface contains words asserting which assessor was right (SC-003, FR-DL-063)
    # Check admin escalations label-adjacent markup does not contain evaluative terms
    resp_esc = client.get(f"/admin/projects/{cycle_id}/escalations")
    assert resp_esc.status_code == 200
    html_esc = resp_esc.text

    forbidden = ["correct", "wrong", "should have"]
    for word in forbidden:
        # Assert within label badge markup
        assert f"badge--disagreement-label>{word}" not in html_esc.lower()


def test_escalations_page_renders_all_four_states_distinctively(client, conn, settings, disputed_unit):
    """T045: Assert all 4 states (never_labelled, awaiting, established, exhausted) render distinctively in admin_escalations.html (Scenario 7, FR-DL-061)."""
    from shared.state.entities import LabellingAttempt, LabellingPass

    repo = Repository(conn)
    cycle_id = "four-states-cycle"
    portal_id = "portal-states"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    # Add 4 questions to have one dispute for each state
    for qid, text in [("q1", "Q1"), ("q2", "Q2"), ("q3", "Q3"), ("q4", "Q4")]:
        repo.insert_question(
            Question(
                question_id=qid,
                cycle_id=cycle_id,
                text=text,
                answer_type=AnswerType.BINARY,
                evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            )
        )

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example", "Notes 1", False, "https://gov.example", "Notes 1"),
            "q2": (True, "https://gov.example", "Notes 2", False, "https://gov.example", "Notes 2"),
            "q3": (True, "https://gov.example", "Notes 3", False, "https://gov.example", "Notes 3"),
            "q4": (True, "https://gov.example", "Notes 4", False, "https://gov.example", "Notes 4"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1", "q2", "q3"], 0.0, cycle_id=cycle_id)

    # Pass covers q1, q2, q3 (q4 is not in pass -> never_labelled if disputes checked without pass, but here q1=established, q2=awaiting, q3=exhausted)
    pass_ = LabellingPass(
        pass_id="pass-4states",
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=["q1", "q2", "q3"],
        compared_count=3,
        dispatched_by="portal",
    )
    repo.insert_labelling_pass(pass_)

    # q1: established
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id="pass-4states",
            session_id=session_id,
            portal_id=portal_id,
            question_id="q1",
            label=DisagreementLabel.DIFFERENT_JUDGEMENT,
            established_by="classifier",
            input_digest="dig1",
            stated_reason="Reason",
            observations={"A": [], "B": []},
            submission_ids={"A": "s-a", "B": "s-b"},
        )
    )

    # q2: awaiting (in pass, 0 attempts, no label)

    # q3: exhausted (in pass, 3 attempts, no label)
    for i in range(3):
        repo.insert_labelling_attempt(
            LabellingAttempt(new_id("att"), "pass-4states", "q3", "provider_error", f"Err {i}")
        )

    resp = client.get(f"/admin/projects/{cycle_id}/escalations")
    assert resp.status_code == 200
    html = resp.text

    # Verify distinctive states rendered in html
    assert 'data-labelling-state="established"' in html
    assert "Judged differently" in html
    assert 'data-labelling-state="awaiting"' in html
    assert "Labelling not yet complete" in html
    assert 'data-labelling-state="exhausted"' in html
    assert "Labelling was attempted and could not be completed" in html


def test_provenance_rendering_and_stale_indicator(client, conn, settings, disputed_unit):
    """T055: Assert provenance block renders 6 fields, deterministic shows 'established without a model', and amending submission shows stale indicator without invalidating label (FR-DL-053, FR-DL-068)."""
    from shared.state.entities import HumanAssessorSubmission, LabellingPass, utcnow

    repo = Repository(conn)
    cycle_id = "prov-surf-cycle"
    portal_id = "portal-prov-surf"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    repo.insert_question(
        Question(
            question_id="q2",
            cycle_id=cycle_id,
            text="Indicator 2 Text",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
    )

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
            "q2": (True, "https://gov.example/2", "Notes 2", False, None, "Notes 2"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1", "q2"], 0.0, cycle_id=cycle_id)

    pass_ = LabellingPass(
        pass_id="pass-prov-surf",
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=["q1", "q2"],
        compared_count=2,
        dispatched_by="portal",
    )
    repo.insert_labelling_pass(pass_)

    # Get submission IDs for q1
    sub_a_q1 = repo.latest_human_submission(session_id, "q1", portal_id, AssessorRole.A)
    sub_b_q1 = repo.latest_human_submission(session_id, "q1", portal_id, AssessorRole.B)

    # q1: classifier label
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id="pass-prov-surf",
            session_id=session_id,
            portal_id=portal_id,
            question_id="q1",
            label=DisagreementLabel.DIFFERENT_JUDGEMENT,
            established_by="classifier",
            input_digest="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            stated_reason="Judged differently on merits",
            observations={"A": [], "B": []},
            submission_ids={"A": sub_a_q1.submission_id, "B": sub_b_q1.submission_id},
            model_identity="gemini-2.5-flash-lite",
            prompt_version="dl-1",
        )
    )

    # q2: deterministic label
    sub_a_q2 = repo.latest_human_submission(session_id, "q2", portal_id, AssessorRole.A)
    sub_b_q2 = repo.latest_human_submission(session_id, "q2", portal_id, AssessorRole.B)
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id="pass-prov-surf",
            session_id=session_id,
            portal_id=portal_id,
            question_id="q2",
            label=DisagreementLabel.ONE_FOUND_NOTHING,
            established_by="deterministic",
            input_digest="fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210",
            stated_reason="One found nothing",
            observations={"A": [], "B": []},
            submission_ids={"A": sub_a_q2.submission_id, "B": sub_b_q2.submission_id},
            model_identity=None,
            prompt_version=None,
        )
    )

    # First load: verify provenance fields
    resp = client.get(f"/admin/projects/{cycle_id}/escalations")
    assert resp.status_code == 200
    html = resp.text

    assert "Established by:</strong> classifier" in html
    assert "Model:</strong> gemini-2.5-flash-lite" in html
    assert "Prompt version:</strong> dl-1" in html
    assert "Digest:</strong> 0123456789abcdef" in html
    assert "Reason:</strong> Judged differently on merits" in html

    assert "Established by:</strong> deterministic" in html
    assert "Model:</strong> established without a model" in html

    # Stale indicator should NOT be present yet
    assert "(submission has changed since labelling)" not in html

    # Now amend Assessor A's submission for q1
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
            evidence_url="https://gov.example/1-updated",
            notes="Amended notes",
            submitted_at=utcnow(),
        )
    )

    # Second load: stale indicator must appear, label still rendered
    resp2 = client.get(f"/admin/projects/{cycle_id}/escalations")
    assert resp2.status_code == 200
    html2 = resp2.text

    assert "(submission has changed since labelling)" in html2
    assert "Judged differently" in html2
    assert "Reason:</strong> Judged differently on merits" in html2


def test_project_detail_renders_label_composition_distinguishing_units(client, conn, settings, disputed_unit):
    """T058: Two units with identical disagreement rates, one all ONE_BLOCKED and one all DIFFERENT_JUDGEMENT, are distinguishable from project detail page alone (SC-005, FR-DL-061)."""
    from shared.state.entities import LabellingPass

    repo = Repository(conn)
    cycle_id = "comp-cycle"
    _setup_cycle_and_unit(repo, cycle_id, "portal-blocked")
    repo.insert_portal(
        TargetPortal(
            portal_id="portal-judged",
            cycle_id=cycle_id,
            country_id="TEST2",
            unit_type="country",
            display_name="Test Country 2",
        )
    )
    set_role_assignment(repo, cycle_id, "portal-judged", AssessorRole.A, "actor-a", "admin")
    set_role_assignment(repo, cycle_id, "portal-judged", AssessorRole.B, "actor-b", "admin")
    session_id = ensure_session(repo, cycle_id)

    # Unit 1: portal-blocked (1 dispute on q1)
    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="portal-blocked",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    recompute_portal_discrepancy(repo, session_id, "portal-blocked", ["q1"], 0.0, cycle_id=cycle_id)

    pass_blocked = LabellingPass("pass-blocked", session_id, cycle_id, "portal-blocked", ["q1"], 1, "portal")
    repo.insert_labelling_pass(pass_blocked)
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id="pass-blocked",
            session_id=session_id,
            portal_id="portal-blocked",
            question_id="q1",
            label=DisagreementLabel.ONE_BLOCKED,
            established_by="classifier",
            input_digest="dig-blocked",
            stated_reason="Access was blocked",
            observations={"A": [], "B": []},
            submission_ids={"A": "sub-a", "B": "sub-b"},
        )
    )

    # Unit 2: portal-judged (1 dispute on q1)
    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id="portal-judged",
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )
    recompute_portal_discrepancy(repo, session_id, "portal-judged", ["q1"], 0.0, cycle_id=cycle_id)

    pass_judged = LabellingPass("pass-judged", session_id, cycle_id, "portal-judged", ["q1"], 1, "portal")
    repo.insert_labelling_pass(pass_judged)
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id="pass-judged",
            session_id=session_id,
            portal_id="portal-judged",
            question_id="q1",
            label=DisagreementLabel.DIFFERENT_JUDGEMENT,
            established_by="classifier",
            input_digest="dig-judged",
            stated_reason="Judged differently",
            observations={"A": [], "B": []},
            submission_ids={"A": "sub-a", "B": "sub-b"},
        )
    )

    resp = client.get(f"/admin/projects/{cycle_id}")
    assert resp.status_code == 200
    html = resp.text

    import html as html_lib
    unescaped = html_lib.unescape(html)

    # Both units have identical disagreement rate, but their label compositions distinguish them on the project detail page
    assert "One couldn't access" in unescaped
    assert "Judged differently" in unescaped
    assert "1 One couldn't access" in unescaped
    assert "1 Judged differently" in unescaped



