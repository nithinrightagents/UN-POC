"""Unit tests for disagreement label provenance and append-only guarantees (T048, T049).

Covers Scenario 6, SC-004, FR-DL-051, FR-DL-053, FR-DL-054, FR-DL-056.
"""

from __future__ import annotations

import datetime
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from portal.assignment import set_role_assignment
from portal.common import ensure_session
from portal.disagreement_labels import (
    dispatch_labelling_pass,
    run_labelling_pass,
)
from portal.discrepancy import recompute_portal_discrepancy
from portal.label_classifier import (
    LABEL_PROMPT_VERSION,
    ClassifierInput,
    PositionView,
    compute_input_digest,
    render_classifier_payload,
)
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    Assessor,
    AssessorRole,
    DisagreementLabel,
    EvidenceLocus,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
)

pytestmark = pytest.mark.unit


class MockRuntime:
    def __init__(self, provider):
        self.provider = provider


def _setup_cycle_and_unit(repo: Repository, cycle_id: str = "prov-cycle", portal_id: str = "portal-prov"):
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Provenance Test Cycle",
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
    repo.insert_question(
        Question(
            question_id="q2",
            cycle_id=cycle_id,
            text="Indicator 2 Text",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
            indicator_id="IND-02",
        )
    )
    repo.upsert_assessor(Assessor(assessor_id="actor-a", display_name="Assessor A", email="a@test.gov"))
    repo.upsert_assessor(Assessor(assessor_id="actor-b", display_name="Assessor B", email="b@test.gov"))
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.A, "actor-a", "admin")
    set_role_assignment(repo, cycle_id, portal_id, AssessorRole.B, "actor-b", "admin")


@pytest.mark.asyncio
async def test_scenario_6_label_provenance_and_digest_versioning(
    conn, settings, disputed_unit, fake_label_provider
):
    """T048: Labels carry complete provenance. Classifier labels carry model and prompt_version, deterministic labels name no model, and changing prompt_version changes digest."""
    repo = Repository(conn)
    cycle_id = "prov-cycle"
    portal_id = "portal-prov"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    # q1 is classifier-bound dispute; q2 is deterministic dispute (one has no evidence URL -> ONE_FOUND_NOTHING)
    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example/page", "Found policy", False, "https://gov.example/page", "Not found policy"),
            "q2": (True, "https://gov.example/page2", "Found evidence", False, None, "Could not find"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1", "q2"], 0.0, cycle_id=cycle_id)

    provider = fake_label_provider({
        "label": "different_judgement",
        "reason": "Different judgement on policy",
        "position_1_notes_contradict_answer": False,
        "position_2_notes_contradict_answer": False,
    })
    runtime = MockRuntime(provider)

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_ids=["q1", "q2"],
        threshold=0.0,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    res = await run_labelling_pass(settings.database_path, settings, runtime, pass_.pass_id)
    assert res.total_disputes == 2
    assert res.labelled_deterministic == 1
    assert res.labelled_classifier == 1

    labels = repo.list_labels_for_unit(session_id, portal_id)
    assert len(labels) == 2
    labels_by_qid = {l.question_id: l for l in labels}

    # Deterministic label (q2)
    l_det = labels_by_qid["q2"]
    assert l_det.established_by == "deterministic"
    assert l_det.label == DisagreementLabel.ONE_FOUND_NOTHING
    assert l_det.model_identity is None  # FR-DL-051: names no model
    assert l_det.prompt_version is None
    assert l_det.input_digest is not None
    assert len(l_det.input_digest) == 64
    assert l_det.stated_reason is not None
    assert l_det.created_at is not None

    # Classifier label (q1)
    l_clf = labels_by_qid["q1"]
    assert l_clf.established_by == "classifier"
    assert l_clf.label == DisagreementLabel.DIFFERENT_JUDGEMENT
    assert l_clf.model_identity == "fake-provider/test-model"
    assert l_clf.prompt_version == LABEL_PROMPT_VERSION
    assert l_clf.input_digest is not None
    assert len(l_clf.input_digest) == 64
    assert l_clf.stated_reason == "Different judgement on policy"
    assert l_clf.created_at is not None

    # Verify that changing LABEL_PROMPT_VERSION produces a different input_digest for identical submissions (FR-DL-056)
    pos_a = PositionView(answer=True, evidence_url="https://gov.example/page", notes="Found policy")
    pos_b = PositionView(answer=False, evidence_url="https://gov.example/page", notes="Not found policy")
    clf_in = ClassifierInput(indicator_text="Indicator 1 Text", positions=[pos_a, pos_b])
    
    payload_v1 = render_classifier_payload(clf_in)
    digest_v1 = compute_input_digest(payload_v1)

    with patch("portal.label_classifier.LABEL_PROMPT_VERSION", "dl-2"):
        payload_v2 = render_classifier_payload(clf_in)
        digest_v2 = compute_input_digest(payload_v2)

    assert digest_v1 != digest_v2


@pytest.mark.asyncio
async def test_sc004_model_call_cap_and_append_only_across_lifecycle(
    conn, settings, disputed_unit, fake_label_provider
):
    """T049: Model calls never exceed dispute count across lifecycle, and tables are strictly append-only (SC-004, FR-DL-054)."""
    repo = Repository(conn)
    cycle_id = "cap-cycle"
    portal_id = "portal-cap"
    _setup_cycle_and_unit(repo, cycle_id, portal_id)
    session_id = ensure_session(repo, cycle_id)

    disputed_unit(
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        dispute_map={
            "q1": (True, "https://gov.example/1", "Notes 1", False, "https://gov.example/1", "Notes 1"),
            "q2": (True, "https://gov.example/2", "Notes 2", False, "https://gov.example/2", "Notes 2"),
        },
        declare_both=True,
        actor_a="actor-a",
        actor_b="actor-b",
    )

    recompute_portal_discrepancy(repo, session_id, portal_id, ["q1", "q2"], 0.0, cycle_id=cycle_id)

    provider = fake_label_provider()
    runtime = MockRuntime(provider)

    pass_ = dispatch_labelling_pass(
        repo=repo,
        settings=settings,
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        question_ids=["q1", "q2"],
        threshold=0.0,
        dispatched_by="portal",
        provider_available=True,
    )
    assert pass_ is not None

    await run_labelling_pass(settings.database_path, settings, runtime, pass_.pass_id)

    # Initial call count should be exactly the 2 classifier-bound disputes
    assert len(provider.calls) == 2

    # Track row counts across lifecycle
    def _counts():
        p = conn.execute("SELECT COUNT(*) FROM labelling_passes").fetchone()[0]
        l = conn.execute("SELECT COUNT(*) FROM disagreement_labels").fetchone()[0]
        a = conn.execute("SELECT COUNT(*) FROM labelling_attempts").fetchone()[0]
        return p, l, a

    p0, l0, a0 = _counts()
    assert p0 == 1
    assert l0 == 2

    # 1. Recompute discrepancy 5 times
    for _ in range(5):
        recompute_portal_discrepancy(repo, session_id, portal_id, ["q1", "q2"], 0.0, cycle_id=cycle_id)
    p1, l1, a1 = _counts()
    assert (p1, l1, a1) >= (p0, l0, a0)
    assert len(provider.calls) == 2

    # 2. Run labelling pass again (idempotent skip)
    await run_labelling_pass(settings.database_path, settings, runtime, pass_.pass_id)
    p2, l2, a2 = _counts()
    assert (p2, l2, a2) >= (p1, l1, a1)
    assert len(provider.calls) == 2  # No additional model calls made

    # 3. Assert append-only property via source inspection (no UPDATE or DELETE queries)
    root = Path(__file__).resolve().parent.parent.parent
    src_portal = (root / "src" / "portal" / "disagreement_labels.py").read_text(encoding="utf-8")
    src_repo = (root / "src" / "shared" / "persistence" / "repositories.py").read_text(encoding="utf-8")

    forbidden_patterns = [
        "UPDATE disagreement_labels",
        "DELETE FROM disagreement_labels",
        "UPDATE labelling_passes",
        "DELETE FROM labelling_passes",
        "UPDATE labelling_attempts",
        "DELETE FROM labelling_attempts",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in src_portal, f"Found {pattern} in disagreement_labels.py"
        assert pattern not in src_repo, f"Found {pattern} in repositories.py"
