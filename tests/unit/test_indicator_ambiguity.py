"""Unit tests for indicator ambiguity measures and thin evidence reporting.

Covers T063, T064, T065, T066, T067, T068, T069, T070, T071.
Scenarios 8 & 9 (FR-DL-070 to FR-DL-075, SC-006, SC-007).
"""

from __future__ import annotations

import pytest

from portal.common import ensure_session
from portal.disagreement_labels import (
    IndicatorAmbiguity,
    indicator_ambiguity,
    insufficient_notes_proportion,
    run_labelling_pass,
)
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    AssessorRole,
    DisagreementLabel,
    DisagreementLabelRecord,
    EvidenceLocus,
    HumanAssessorSubmission,
    LabellingPass,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
    utcnow,
)

pytestmark = pytest.mark.unit


def _create_cycle(repo: Repository, cycle_id: str, name: str = "Test Cycle") -> None:
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name=name,
            questionnaire_ref="test-ref",
            country_set=["TEST"],
            project_type=ProjectType.NATIONAL_OSI,
            discrepancy_rate_threshold=0.0,
        )
    )


def _create_question(
    repo: Repository,
    cycle_id: str,
    question_id: str,
    indicator_id: str | None = None,
    title: str = "Test Question",
) -> None:
    repo.insert_question(
        Question(
            question_id=question_id,
            cycle_id=cycle_id,
            text=f"Text for {question_id}",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id=indicator_id,
            title=title,
        )
    )


def _create_portal_and_pass(
    repo: Repository,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    disputed_qids: list[str],
) -> LabellingPass:
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id=portal_id.upper()[:4],
            unit_type="country",
            display_name=f"Country {portal_id}",
        )
    )
    p = LabellingPass(
        pass_id=f"pass-{portal_id}",
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=disputed_qids,
        compared_count=len(disputed_qids),
        dispatched_by="portal",
    )
    repo.insert_labelling_pass(p)
    return p


def _insert_label(
    repo: Repository,
    pass_id: str,
    session_id: str,
    portal_id: str,
    question_id: str,
    label: DisagreementLabel,
    established_by: str = "classifier",
) -> None:
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id=pass_id,
            session_id=session_id,
            portal_id=portal_id,
            question_id=question_id,
            label=label,
            established_by=established_by,
            input_digest=f"dig-{portal_id}-{question_id}",
            stated_reason=f"Reason for {label.value}",
            observations={"A": [], "B": []},
            submission_ids={"A": "sub-a", "B": "sub-b"},
        )
    )


def test_scenario_8_indicator_ambiguity_ranking_and_exclusions(conn):
    """T063, T064, T065: Scenario 8.

    - Indicator disputed in 8 units with 6 DIFFERENT_JUDGEMENT ranks above one with 6 ONE_BLOCKED.
    - DIFFERENT_CONTENT does not count toward the ambiguity measure (FR-DL-071).
    - units_measured and labelled_share are present on every row.
    """
    repo = Repository(conn)
    cycle_id = "amb-cycle"
    _create_cycle(repo, cycle_id, "Ambiguity Cycle")
    session_id = ensure_session(repo, cycle_id)

    # 3 Indicators:
    # IND-01: 8 disputed units -> 6 DIFFERENT_JUDGEMENT, 2 DIFFERENT_SOURCES
    # IND-02: 8 disputed units -> 6 ONE_BLOCKED, 2 DIFFERENT_SOURCES
    # IND-03: 4 disputed units -> 4 DIFFERENT_CONTENT
    _create_question(repo, cycle_id, "q1", indicator_id="IND-01", title="Question 1")
    _create_question(repo, cycle_id, "q2", indicator_id="IND-02", title="Question 2")
    _create_question(repo, cycle_id, "q3", indicator_id="IND-03", title="Question 3")

    for i in range(1, 9):
        portal_id = f"unit-{i}"
        disputed = ["q1", "q2"]
        if i <= 4:
            disputed.append("q3")
        p = _create_portal_and_pass(repo, session_id, cycle_id, portal_id, disputed)

        # Labels for q1
        if i <= 6:
            _insert_label(repo, p.pass_id, session_id, portal_id, "q1", DisagreementLabel.DIFFERENT_JUDGEMENT)
        else:
            _insert_label(repo, p.pass_id, session_id, portal_id, "q1", DisagreementLabel.DIFFERENT_SOURCES, established_by="deterministic")

        # Labels for q2
        if i <= 6:
            _insert_label(repo, p.pass_id, session_id, portal_id, "q2", DisagreementLabel.ONE_BLOCKED)
        else:
            _insert_label(repo, p.pass_id, session_id, portal_id, "q2", DisagreementLabel.DIFFERENT_SOURCES, established_by="deterministic")

        # Labels for q3 (only first 4 units)
        if i <= 4:
            _insert_label(repo, p.pass_id, session_id, portal_id, "q3", DisagreementLabel.DIFFERENT_CONTENT)

    report = indicator_ambiguity(repo, cycle_id=cycle_id)
    assert len(report) == 3

    # Ranking: IND-01 must rank highest (6 DIFFERENT_JUDGEMENT)
    first = report[0]
    assert first.indicator_key == "IND-01"
    assert first.judged_differently == 6
    assert first.units_measured == 8
    assert first.units_total == 8
    assert first.labelled_share == 1.0

    # IND-02 has 0 judged_differently (ONE_BLOCKED excluded per FR-DL-071)
    ind_02 = next(r for r in report if r.indicator_key == "IND-02")
    assert ind_02.judged_differently == 0
    assert ind_02.units_measured == 8
    assert ind_02.units_total == 8
    assert ind_02.labelled_share == 1.0

    # IND-03 has 0 judged_differently (DIFFERENT_CONTENT excluded per FR-DL-071)
    ind_03 = next(r for r in report if r.indicator_key == "IND-03")
    assert ind_03.judged_differently == 0
    assert ind_03.units_measured == 4
    assert ind_03.units_total == 8
    assert ind_03.labelled_share == 1.0

    # IND-01 strictly ranks above IND-02 and IND-03
    assert report[0].indicator_key == "IND-01"
    # Tied at 0 judged_differently, IND-02 has more units_measured (8 > 4), so it ranks 2nd
    assert report[1].indicator_key == "IND-02"
    assert report[2].indicator_key == "IND-03"


def test_indicator_ambiguity_partial_labelling(conn):
    """T065: units_measured and labelled_share are accurate when only part of the cycle is labelled."""
    repo = Repository(conn)
    cycle_id = "partial-cycle"
    _create_cycle(repo, cycle_id, "Partial Cycle")
    session_id = ensure_session(repo, cycle_id)

    _create_question(repo, cycle_id, "q1", indicator_id="IND-PARTIAL")

    # 10 units had disputed q1
    for i in range(1, 11):
        portal_id = f"port-{i}"
        p = _create_portal_and_pass(repo, session_id, cycle_id, portal_id, ["q1"])
        # Only first 3 units have been labelled so far
        if i <= 3:
            _insert_label(repo, p.pass_id, session_id, portal_id, "q1", DisagreementLabel.DIFFERENT_JUDGEMENT)

    report = indicator_ambiguity(repo, cycle_id=cycle_id)
    assert len(report) == 1
    row = report[0]
    assert row.indicator_key == "IND-PARTIAL"
    assert row.judged_differently == 3
    assert row.units_measured == 3
    assert row.units_total == 10
    assert row.labelled_share == pytest.approx(0.3)


def test_indicator_ambiguity_cross_project_rollup(conn):
    """T063, T064: indicator_ambiguity(cycle_id=X) vs indicator_ambiguity() (FR-DL-075, R11).

    Same code path returns per-project view when cycle_id given, and rolls up matching indicator_id
    across cycles when cycle_id=None.
    """
    repo = Repository(conn)
    _create_cycle(repo, "cycle-a", "Cycle A")
    _create_cycle(repo, "cycle-b", "Cycle B")
    session_a = ensure_session(repo, "cycle-a")
    session_b = ensure_session(repo, "cycle-b")

    # Both cycles define an indicator with identical indicator_id but cycle-scoped question_id
    _create_question(repo, "cycle-a", "qa_1", indicator_id="SHARED-IND")
    _create_question(repo, "cycle-b", "qb_1", indicator_id="SHARED-IND")

    # 2 units in cycle-a
    p1 = _create_portal_and_pass(repo, session_a, "cycle-a", "u-a1", ["qa_1"])
    p2 = _create_portal_and_pass(repo, session_a, "cycle-a", "u-a2", ["qa_1"])
    _insert_label(repo, p1.pass_id, session_a, "u-a1", "qa_1", DisagreementLabel.DIFFERENT_JUDGEMENT)
    _insert_label(repo, p2.pass_id, session_a, "u-a2", "qa_1", DisagreementLabel.DIFFERENT_JUDGEMENT)

    # 3 units in cycle-b
    p3 = _create_portal_and_pass(repo, session_b, "cycle-b", "u-b1", ["qb_1"])
    p4 = _create_portal_and_pass(repo, session_b, "cycle-b", "u-b2", ["qb_1"])
    p5 = _create_portal_and_pass(repo, session_b, "cycle-b", "u-b3", ["qb_1"])
    _insert_label(repo, p3.pass_id, session_b, "u-b1", "qb_1", DisagreementLabel.DIFFERENT_JUDGEMENT)
    _insert_label(repo, p4.pass_id, session_b, "u-b2", "qb_1", DisagreementLabel.DIFFERENT_JUDGEMENT)
    _insert_label(repo, p5.pass_id, session_b, "u-b3", "qb_1", DisagreementLabel.DIFFERENT_JUDGEMENT)

    # Per-project view for cycle-a
    rep_a = indicator_ambiguity(repo, cycle_id="cycle-a")
    assert len(rep_a) == 1
    assert rep_a[0].indicator_key == "SHARED-IND"
    assert rep_a[0].judged_differently == 2
    assert rep_a[0].units_total == 2

    # Per-project view for cycle-b
    rep_b = indicator_ambiguity(repo, cycle_id="cycle-b")
    assert len(rep_b) == 1
    assert rep_b[0].indicator_key == "SHARED-IND"
    assert rep_b[0].judged_differently == 3
    assert rep_b[0].units_total == 3

    # Cross-project view (cycle_id=None) rolls up both cycles under SHARED-IND
    rep_all = indicator_ambiguity(repo, cycle_id=None)
    assert len(rep_all) == 1
    assert rep_all[0].indicator_key == "SHARED-IND"
    assert rep_all[0].judged_differently == 5
    assert rep_all[0].units_measured == 5
    assert rep_all[0].units_total == 5


def test_insufficient_notes_proportion_and_thin_dispute(conn, settings):
    """T069, T070: NOT_ENOUGH_NOTES proportion is reportable for a cycle (FR-DL-074, SC-007).

    A dispute where neither assessor wrote notes and both cited the same portal carries NOT_ENOUGH_NOTES.
    """
    repo = Repository(conn)
    cycle_id = "notes-cycle"
    _create_cycle(repo, cycle_id, "Notes Cycle")
    session_id = ensure_session(repo, cycle_id)
    _create_question(repo, cycle_id, "q_thin", indicator_id="IND-THIN")

    # 4 disputes: 2 are NOT_ENOUGH_NOTES, 1 is DIFFERENT_JUDGEMENT, 1 is ONE_BLOCKED
    for i in range(1, 5):
        portal_id = f"notes-unit-{i}"
        p = _create_portal_and_pass(repo, session_id, cycle_id, portal_id, ["q_thin"])
        if i in (1, 2):
            lbl = DisagreementLabel.NOT_ENOUGH_NOTES
        elif i == 3:
            lbl = DisagreementLabel.DIFFERENT_JUDGEMENT
        else:
            lbl = DisagreementLabel.ONE_BLOCKED
        _insert_label(repo, p.pass_id, session_id, portal_id, "q_thin", lbl)

    # Assert reportable via indicator_ambiguity and dedicated helper
    report = indicator_ambiguity(repo, cycle_id=cycle_id)
    assert report.insufficient_notes_share == pytest.approx(2 / 4)
    assert report.not_enough_notes_share == pytest.approx(0.5)
    assert insufficient_notes_proportion(repo, cycle_id=cycle_id) == pytest.approx(0.5)


async def test_thin_evidence_dispute_classification_with_fake(conn, settings, fake_label_provider):
    """T069: A dispute where neither assessor wrote notes and both cited same portal carries NOT_ENOUGH_NOTES."""
    repo = Repository(conn)
    cycle_id = "thin-class-cycle"
    _create_cycle(repo, cycle_id, "Thin Classification Cycle")
    session_id = ensure_session(repo, cycle_id)
    _create_question(repo, cycle_id, "q_empty", indicator_id="IND-EMPTY")

    portal_id = "portal-thin-run"
    repo.insert_portal(
        TargetPortal(
            portal_id=portal_id,
            cycle_id=cycle_id,
            country_id="THIN",
            unit_type="country",
            display_name="Thin Country",
        )
    )

    # Both assessors cite the exact same URL, with empty notes
    sub_a = HumanAssessorSubmission(
        submission_id="sub-thin-a",
        session_id=session_id,
        cycle_id=cycle_id,
        question_id="q_empty",
        portal_id=portal_id,
        role=AssessorRole.A,
        assessor_actor_id="actor-a",
        answer=True,
        evidence_url="https://portal.gov.example/page",
        ai_suggested_answer=None,
        ai_suggestion_accepted=False,
        notes="",
        submitted_at=utcnow(),
    )
    sub_b = HumanAssessorSubmission(
        submission_id="sub-thin-b",
        session_id=session_id,
        cycle_id=cycle_id,
        question_id="q_empty",
        portal_id=portal_id,
        role=AssessorRole.B,
        assessor_actor_id="actor-b",
        answer=False,
        evidence_url="https://portal.gov.example/page",
        ai_suggested_answer=None,
        ai_suggestion_accepted=False,
        notes="",
        submitted_at=utcnow(),
    )
    repo.insert_human_submission(sub_a)
    repo.insert_human_submission(sub_b)

    pass_ = LabellingPass(
        pass_id="pass-thin-run",
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=["q_empty"],
        compared_count=1,
        dispatched_by="portal",
    )
    repo.insert_labelling_pass(pass_)
    conn.commit()

    # Classifier fake returns not_enough_notes (which the prompt requires under empty notes)
    provider = fake_label_provider(
        canned_response={
            "label": "not_enough_notes",
            "reason": "Both cited same portal but neither assessor provided notes",
            "position_1_notes_contradict_answer": False,
            "position_2_notes_contradict_answer": False,
        }
    )

    class FakeRuntime:
        def __init__(self):
            self.provider = provider

    await run_labelling_pass(
        settings.database_path,
        settings,
        FakeRuntime(),
        pass_.pass_id,
    )

    labels = repo.list_labels_for_unit(session_id, portal_id)
    assert len(labels) == 1
    assert labels[0].label == DisagreementLabel.NOT_ENOUGH_NOTES
    assert labels[0].stated_reason == "Both cited same portal but neither assessor provided notes"


def test_admin_ambiguity_routes_render_and_write_nothing(client, conn, settings):
    """T066, T067, T068, T071: Admin routes render ambiguity tables, headline figure, and write nothing."""
    repo = Repository(conn)
    cycle_id = "route-cycle"
    _create_cycle(repo, cycle_id, "Route Test Cycle")
    session_id = ensure_session(repo, cycle_id)
    _create_question(repo, cycle_id, "q_route", indicator_id="IND-ROUTE")

    p = _create_portal_and_pass(repo, session_id, cycle_id, "p-route", ["q_route"])
    _insert_label(repo, p.pass_id, session_id, "p-route", "q_route", DisagreementLabel.NOT_ENOUGH_NOTES)

    # Count rows before GET requests
    c_passes = repo.conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0]
    c_labels = repo.conn.execute("SELECT COUNT(*) FROM disagreement_labels").fetchone()[0]
    c_attempts = repo.conn.execute("SELECT COUNT(*) FROM labelling_attempts").fetchone()[0]

    # 1. Project-specific route (Senior Reviewer view)
    resp_proj = client.get(f"/admin/projects/{cycle_id}/ambiguity")
    assert resp_proj.status_code == 200
    html_proj = resp_proj.text
    assert "Indicator Ambiguity: Route Test Cycle" in html_proj
    assert "Thin Evidence Measure" in html_proj
    assert "Disputes with Insufficient Notes" in html_proj
    assert "100.0%" in html_proj
    assert "IND-ROUTE" in html_proj

    # 2. Cross-project route (Administrator view)
    resp_cross = client.get("/admin/indicators/ambiguity")
    assert resp_cross.status_code == 200
    html_cross = resp_cross.text
    assert "Cross-Project Indicator Ambiguity" in html_cross
    assert "Thin Evidence Measure" in html_cross
    assert "IND-ROUTE" in html_cross

    # Assert pure reads: zero new rows created
    c_passes_after = repo.conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0]
    c_labels_after = repo.conn.execute("SELECT COUNT(*) FROM disagreement_labels").fetchone()[0]
    c_attempts_after = repo.conn.execute("SELECT COUNT(*) FROM labelling_attempts").fetchone()[0]
    assert c_passes == c_passes_after
    assert c_labels == c_labels_after
    assert c_attempts == c_attempts_after
