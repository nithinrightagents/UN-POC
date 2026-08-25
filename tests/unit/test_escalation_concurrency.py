"""FR-049: exactly one delivered disposition per escalation item, even
under concurrent action -- the second caller is told the item is already
resolved rather than silently overwriting the first.
"""

from __future__ import annotations

import sqlite3

import pytest

from review.escalations import dispose_escalation, list_escalation_queue
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import EscalationQueueItem, EscalationReason, new_id

pytestmark = pytest.mark.unit


@pytest.fixture
def repo() -> Repository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return Repository(conn)


def _seed_item(repo: Repository) -> str:
    item = EscalationQueueItem(
        item_id=new_id("esc"),
        session_id="s1",
        reason=EscalationReason.UNRESOLVED_DISAGREEMENT,
        context={"summary": "agents disagreed"},
    )
    repo.insert_escalation(item)
    return item.item_id


def test_first_disposition_succeeds(repo):
    item_id = _seed_item(repo)
    assert dispose_escalation(repo, item_id, "resolved-yes", "reviewer-a") is True


def test_second_concurrent_disposition_is_rejected_not_overwritten(repo):
    item_id = _seed_item(repo)

    first = dispose_escalation(repo, item_id, "resolved-yes", "reviewer-a")
    second = dispose_escalation(repo, item_id, "resolved-no", "reviewer-b")

    assert first is True
    assert second is False  # told "already resolved", not silently overwritten

    # The recorded disposition is reviewer-a's -- reviewer-b's attempt left no trace.
    stored = repo.get_disposition(item_id)
    assert stored["resolved_by_actor_id"] == "reviewer-a"
    assert stored["resolution"] == "resolved-yes"


def test_queue_view_reflects_resolution_state(repo):
    item_id = _seed_item(repo)
    views = list_escalation_queue(repo, "s1")
    assert len(views) == 1
    assert views[0].already_resolved is False

    dispose_escalation(repo, item_id, "resolved-yes", "reviewer-a")

    views = list_escalation_queue(repo, "s1")
    assert views[0].already_resolved is True
    assert views[0].disposition["resolved_by_actor_id"] == "reviewer-a"
