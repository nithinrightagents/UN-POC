"""Unit tests for labelling pass dispatch preconditions and once-only guarantee (T027, Scenario 1).

Covers FR-DL-001 to FR-DL-008, FR-DL-041, FR-DL-042.
"""

from __future__ import annotations

import datetime
from datetime import timezone
import pytest

from portal.disagreement_labels import (
    dispatch_labelling_pass,
    unit_labelling_state,
)
from shared.persistence.repositories import Repository
from shared.state.entities import (
    AnswerType,
    EvidenceLocus,
    Question,
    new_id,
)

pytestmark = pytest.mark.unit


def _create_question(repo: Repository, qid: str = "q1", cycle_id: str = "c1"):
    repo.insert_question(
        Question(
            question_id=qid,
            cycle_id=cycle_id,
            text=f"Indicator {qid}",
            answer_type=AnswerType.BINARY,
            evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        )
    )


def test_submissions_alone_create_no_pass(conn, settings, disputed_unit):
    """Submissions alone (without both completions) create no pass."""
    repo = Repository(conn)
    _create_question(repo, "q1", "c1")

    # Both assessors submitted, but declare_both=False so no completion records exist
    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={"q1": (True, "https://gov.example", "Notes A", False, "https://gov.example", "Notes B")},
        declare_both=False,
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
    assert pass_ is None
    assert repo.get_labelling_pass("s1", "p1") is None


def test_single_completion_creates_no_pass(conn, settings, disputed_unit):
    """A single completion (Assessor A only) creates no pass."""
    repo = Repository(conn)
    _create_question(repo, "q1", "c1")

    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={"q1": (True, "https://gov.example", "Notes A", False, "https://gov.example", "Notes B")},
        declare_both=False,
    )

    # Insert only Assessor A completion
    now = datetime.datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO assessor_completions (
            completion_id, session_id, cycle_id, portal_id, role, actor_id, indicator_count_at_declaration, declared_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id("comp"), "s1", "c1", "p1", "A", "actor-a", 1, now),
    )
    conn.commit()

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
    assert pass_ is None
    assert repo.get_labelling_pass("s1", "p1") is None


def test_both_completions_creates_exactly_one_pass_and_recomputing_is_idempotent(conn, settings, disputed_unit):
    """Both completions create exactly one pass; 10 subsequent recomputes write no further rows."""
    repo = Repository(conn)
    _create_question(repo, "q1", "c1")

    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={"q1": (True, "https://gov.example", "Notes A", False, "https://gov.example", "Notes B")},
        declare_both=True,
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
    assert pass_.disputed_question_ids == ["q1"]
    assert pass_.dispatched_by == "portal"

    # Recomputing 10 times, changing tolerance, etc.
    for i in range(10):
        subsequent_pass = dispatch_labelling_pass(
            repo=repo,
            settings=settings,
            session_id="s1",
            cycle_id="c1",
            portal_id="p1",
            question_ids=["q1"],
            threshold=0.5 if i % 2 == 0 else 0.1,
            dispatched_by="portal",
            provider_available=True,
        )
        assert subsequent_pass is None

    # Verify exactly one row in database
    cursor = conn.execute("SELECT COUNT(*) FROM labelling_passes WHERE session_id = ? AND portal_id = ?", ("s1", "p1"))
    count = cursor.fetchone()[0]
    assert count == 1


def test_unit_with_no_disagreements_produces_no_pass(conn, settings, disputed_unit):
    """A unit with agreeing answers produces no disagreements and no pass row."""
    repo = Repository(conn)
    _create_question(repo, "q1", "c1")

    # Both assessors agree (True, True)
    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={"q1": (True, "https://gov.example", "Notes A", True, "https://gov.example", "Notes B")},
        declare_both=True,
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
    assert pass_ is None
    assert repo.get_labelling_pass("s1", "p1") is None


def test_provider_unavailable_produces_no_pass_and_never_labelled_state(conn, settings, disputed_unit):
    """With provider_available=False, no pass or attempt row is written; state is never_labelled."""
    repo = Repository(conn)
    _create_question(repo, "q1", "c1")

    disputed_unit(
        session_id="s1",
        cycle_id="c1",
        portal_id="p1",
        dispute_map={"q1": (True, "https://gov.example", "Notes A", False, "https://gov.example", "Notes B")},
        declare_both=True,
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
        provider_available=False,  # e.g. ai_runtime is None
    )
    assert pass_ is None
    assert repo.get_labelling_pass("s1", "p1") is None

    cursor = conn.execute("SELECT COUNT(*) FROM labelling_attempts")
    assert cursor.fetchone()[0] == 0

    state_map = unit_labelling_state(repo, "s1", "p1")
    assert "q1" in state_map
    assert state_map["q1"].state == "never_labelled"
    assert state_map["q1"].badge == "Not labelled"
