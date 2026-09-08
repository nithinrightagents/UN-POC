"""Unit tests for deterministic pre-pass and label definitions (Scenario 2)."""

from types import SimpleNamespace
import pytest

from portal.disagreement_labels import (
    classify_deterministically,
    normalise_host,
    same_source,
)
from shared.state.entities import (
    CLASSIFIER_LABELS,
    DETERMINISTIC_LABELS,
    DisagreementLabel,
)

pytestmark = pytest.mark.unit


def test_disagreement_label_sets_disjoint_and_exhaustive():
    """T011: Assert DETERMINISTIC_LABELS and CLASSIFIER_LABELS are disjoint and cover all labels."""
    assert DETERMINISTIC_LABELS.isdisjoint(CLASSIFIER_LABELS)
    assert DETERMINISTIC_LABELS | CLASSIFIER_LABELS == set(DisagreementLabel)


@pytest.mark.parametrize(
    "url_a,url_b,expected_label",
    [
        # Row 1: same domain with/without www -> same source -> classifier reached (None)
        ("https://www.gov.br/x", "https://gov.br/y", None),
        # Row 2: gov.sg vs subdomain e-services.gov.sg -> same source -> classifier reached (None)
        ("https://gov.sg", "https://e-services.gov.sg/a", None),
        # Row 3: dvla.gov.uk vs hmrc.gov.uk -> DIFFERENT_SOURCES
        ("https://dvla.gov.uk", "https://hmrc.gov.uk", DisagreementLabel.DIFFERENT_SOURCES),
        # Row 4: mof.gov.ke vs None -> ONE_FOUND_NOTHING
        ("https://mof.gov.ke", None, DisagreementLabel.ONE_FOUND_NOTHING),
        # Row 5: None vs None -> classifier reached (None)
        (None, None, None),
        # Row 6: "not a url" vs None -> classifier reached (None, unparseable is treated as no evidence)
        ("not a url", None, None),
    ],
)
def test_deterministic_prepass_table(url_a, url_b, expected_label):
    """T020: Scenario 2 table of cases for classify_deterministically."""
    sub_a = SimpleNamespace(evidence_url=url_a)
    sub_b = SimpleNamespace(evidence_url=url_b)

    label = classify_deterministically(sub_a, sub_b)
    assert label == expected_label

    # Also test symmetry: swapping A and B produces the identical deterministic label
    label_swapped = classify_deterministically(sub_b, sub_a)
    assert label_swapped == expected_label


def test_normalise_host_cases():
    assert normalise_host("https://www.example.gov/path?q=1#frag") == "example.gov"
    assert normalise_host("http://user:pass@sub.domain.org:8080/") == "sub.domain.org"
    assert normalise_host("https://gov.sg/") == "gov.sg"
    assert normalise_host("not a url") == ""
    assert normalise_host("") == ""
    assert normalise_host(None) == ""


def test_same_source_cases():
    assert same_source("https://www.gov.br/x", "https://gov.br/y") is True
    assert same_source("https://gov.sg", "https://e-services.gov.sg/a") is True
    assert same_source("https://e-services.gov.sg/a", "https://gov.sg") is True
    assert same_source("https://dvla.gov.uk", "https://hmrc.gov.uk") is False
    assert same_source("https://mof.gov.ke", None) is False
    assert same_source(None, None) is False


def test_side_observations_extraction():
    from portal.disagreement_labels import compute_side_observations
    from shared.state.entities import SideObservation

    # Position A: notes provided, ai_suggestion_accepted=True
    sub_a = SimpleNamespace(notes="Checked the page carefully.", ai_suggestion_accepted=True)
    # Position B: whitespace notes, ai_suggestion_accepted=False
    sub_b = SimpleNamespace(notes="   ", ai_suggestion_accepted=False)

    obs = compute_side_observations(sub_a, sub_b)
    assert obs["A"] == [SideObservation.ACCEPTED_AI_UNCHANGED]
    assert obs["B"] == [SideObservation.NO_NOTES]


def test_repository_labelling_methods_and_once_guards(conn):
    from portal.disagreement_labels import labelling_counts, unit_labelling_state
    from shared.persistence.repositories import Repository
    from shared.state.entities import (
        DisagreementLabel,
        DisagreementLabelRecord,
        LabellingAttempt,
        LabellingPass,
        SideObservation,
        new_id,
        utcnow,
    )

    repo = Repository(conn)
    session_id = "sess-test-p2"
    portal_id = "port-test-p2"
    cycle_id = "cycle-test-p2"

    # 1. State before pass: empty or never_labelled
    state_before = unit_labelling_state(repo, session_id, portal_id)
    assert state_before == {}

    # 2. Insert pass
    pass_ = LabellingPass(
        pass_id=new_id("pass"),
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=["q1", "q2"],
        compared_count=2,
        dispatched_by="portal",
        created_at=utcnow(),
    )
    assert repo.insert_labelling_pass(pass_) is True
    # Once-guard: second insert for same (session_id, portal_id) must return False
    assert repo.insert_labelling_pass(pass_) is False

    # Check state after pass: both q1 and q2 are awaiting (0 attempts)
    state_awaiting = unit_labelling_state(repo, session_id, portal_id)
    assert state_awaiting["q1"].state == "awaiting"
    assert state_awaiting["q1"].badge == "Labelling not yet complete"
    assert state_awaiting["q2"].state == "awaiting"

    # 3. Insert deterministic label for q1
    rec = DisagreementLabelRecord(
        label_id=new_id("lbl"),
        pass_id=pass_.pass_id,
        session_id=session_id,
        portal_id=portal_id,
        question_id="q1",
        label=DisagreementLabel.DIFFERENT_SOURCES,
        established_by="deterministic",
        input_digest="dig1",
        stated_reason="Different hosts cited",
        observations={"A": [SideObservation.NO_NOTES], "B": []},
        submission_ids={"A": "sub1", "B": "sub2"},
        interval_seconds=10,
        model_identity=None,
        prompt_version=None,
        created_at=utcnow(),
    )
    assert repo.insert_disagreement_label(rec) is True
    # Once-guard: second insert for same (pass_id, question_id) must return False
    assert repo.insert_disagreement_label(rec) is False

    # 4. Insert 3 attempts for q2 -> exhausted
    for i in range(3):
        repo.insert_labelling_attempt(
            LabellingAttempt(
                attempt_id=new_id("att"),
                pass_id=pass_.pass_id,
                question_id="q2",
                failure="provider_error",
                detail=f"fail {i}",
                created_at=utcnow(),
            )
        )
    assert repo.count_attempts(pass_.pass_id, "q2") == 3

    # Check state now: q1 established, q2 exhausted
    state_final = unit_labelling_state(repo, session_id, portal_id)
    assert state_final["q1"].state == "established"
    assert state_final["q1"].label == DisagreementLabel.DIFFERENT_SOURCES
    assert state_final["q1"].badge == "Used different sources"
    assert state_final["q2"].state == "exhausted"
    assert state_final["q2"].badge == "Labelling was attempted and could not be completed"

    # Check labelling_counts
    counts = labelling_counts(repo, cycle_id)
    assert counts.established_deterministic == 1
    assert counts.established_by_classifier == 0
    assert counts.awaiting == 0
    assert counts.exhausted == 1

    # Check count_labels_by_kind and count_labels_by_question on repo
    kind_counts = repo.count_labels_by_kind(cycle_id)
    assert kind_counts["established_deterministic"] == 1
    assert kind_counts["total_passes"] == 1
    assert kind_counts["total_labels"] == 1
    assert kind_counts["total_attempts"] == 3

    q_counts = repo.count_labels_by_question(cycle_id)
    assert len(q_counts) == 1
    assert q_counts[0]["question_id"] == "q1"
    assert q_counts[0]["label"] == "different_sources"
    assert q_counts[0]["count"] == 1

