"""MSQ link source (FR-121, FR-126).

Reads government MSQ submissions for a LINK only. FR-126 is the load-
bearing rule here: no function in this module, or anywhere else, returns
an MSQ-reported *value* as an answer. This module has no return type
capable of carrying one -- it only ever returns a ResolutionAttempt (a
link candidate), never a question answer -- so AIQ and MSQ stay two
independent readings for EKAP's cross-source comparison (contracts/
ekap-integration.md).
"""

from __future__ import annotations

from shared.persistence.repositories import Repository
from shared.state.entities import LinkSource, ResolutionAttempt


def resolve_from_msq(
    repo: Repository, question_id: str, country_id: str, order: int
) -> ResolutionAttempt:
    candidates = repo.find_msq_link_candidates(question_id, country_id)
    if not candidates:
        return ResolutionAttempt(
            source=LinkSource.MSQ, order=order, returned=None, usable=False,
            rejection_reason="no MSQ submission contained a link for this question",
        )

    newest = candidates[0]
    return ResolutionAttempt(source=LinkSource.MSQ, order=order, returned=newest.url, usable=True)
