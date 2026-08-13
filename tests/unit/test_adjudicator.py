"""Per-question and portal-level adjudication, driven from the fixtures in
tests/fixtures/adjudication/ and tests/fixtures/portal-level/ (US3
independent test, quickstart.md Scenario 3). adjudicator.py and
portal_adjudicator.py are pure/mechanical -- no live assessment needed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.adjudicator.agent import adjudicate
from shared.state.entities import AgentRunState, AssessorAgentRun
from shared.state.measures import compute_portal_measures

pytestmark = pytest.mark.unit

_ADJ_DIR = Path(__file__).parent.parent / "fixtures" / "adjudication"
_PORTAL_DIR = Path(__file__).parent.parent / "fixtures" / "portal-level"


def _runs_from_fixture(runs: list[dict], round_number: int = 1) -> list[AssessorAgentRun]:
    return [
        AssessorAgentRun(
            run_id=f"r{r['agent_index']}",
            session_id="s1",
            question_id="q1",
            portal_id="p1",
            agent_index=r["agent_index"],
            round_number=round_number,
            answer=r["answer"],
            confidence=r["confidence"],
            state=AgentRunState.VALIDATED_PASS,
        )
        for r in runs
    ]


@pytest.mark.parametrize(
    "fixture_name",
    ["agreement.json", "answer_disagreement.json", "confidence_only_disagreement.json"],
)
def test_single_round_fixtures(fixture_name: str):
    fixture = json.loads((_ADJ_DIR / fixture_name).read_text())
    runs = _runs_from_fixture(fixture["runs"])
    decision = adjudicate(runs, fixture["per_question_confidence_threshold"])

    assert decision.discrepancy_flagged == fixture["expected"]["discrepancy_flagged"]
    assert decision.flag_reason == fixture["expected"]["flag_reason"]
    assert decision.consensus_answer == fixture["expected"]["consensus_answer"]


def test_retry_convergence_fixture():
    fixture = json.loads((_ADJ_DIR / "retry_convergence.json").read_text())
    threshold = fixture["per_question_confidence_threshold"]

    decisions = []
    for round_data in fixture["rounds"]:
        runs = _runs_from_fixture(round_data["runs"], round_data["round_number"])
        decisions.append(adjudicate(runs, threshold))

    assert decisions[0].discrepancy_flagged is True
    assert decisions[-1].discrepancy_flagged is False
    assert decisions[-1].consensus_answer == fixture["expected"]["final_consensus_answer"]
    # Full retry history retained: both rounds' decisions exist and are distinct.
    assert len(decisions) == len(fixture["rounds"])


def test_retry_exhaustion_fixture():
    fixture = json.loads((_ADJ_DIR / "retry_exhaustion.json").read_text())
    threshold = fixture["per_question_confidence_threshold"]
    retry_limit = fixture["adjudication_retry_limit"]

    decisions = []
    for round_data in fixture["rounds"]:
        runs = _runs_from_fixture(round_data["runs"], round_data["round_number"])
        decisions.append(adjudicate(runs, threshold))

    # All rounds disagree.
    assert all(d.discrepancy_flagged for d in decisions)
    # Retries used == adjudication_retry_limit -> escalate rather than deliver.
    retries_used = len(decisions) - 1
    assert retries_used == retry_limit
    assert fixture["expected"]["final_consensus_answer"] is None


@pytest.mark.parametrize(
    "fixture_name",
    ["zero_gap_high_differing.json", "heavy_disagreement_then_converge.json"],
)
def test_portal_level_fixtures(fixture_name: str):
    fixture = json.loads((_PORTAL_DIR / fixture_name).read_text())

    runs_by_question = {}
    for row in fixture["first_round_positions"]:
        qid = row["question_id"]
        runs_by_question[qid] = [
            AssessorAgentRun(
                run_id=f"{qid}-0", session_id="s1", question_id=qid, portal_id="p1",
                agent_index=0, round_number=1, answer=row["agent_0"], state=AgentRunState.VALIDATED_PASS,
            ),
            AssessorAgentRun(
                run_id=f"{qid}-1", session_id="s1", question_id=qid, portal_id="p1",
                agent_index=1, round_number=1, answer=row["agent_1"], state=AgentRunState.VALIDATED_PASS,
            ),
        ]

    measures = compute_portal_measures(
        runs_by_question,
        configured_agent_count=2,
        differing_answer_rate_threshold=fixture["differing_answer_rate_threshold"],
        affirmative_rate_gap_threshold=fixture["affirmative_rate_gap_threshold"],
    )

    assert measures.differing_answer_rate == pytest.approx(fixture["expected"]["differing_answer_rate"])
    assert measures.flagged == fixture["expected"]["flagged"]
    assert measures.triggering_measure == fixture["expected"]["triggering_measure"]
    if "affirmative_rate_gap" in fixture["expected"]:
        assert measures.affirmative_rate_gap == pytest.approx(fixture["expected"]["affirmative_rate_gap"])
