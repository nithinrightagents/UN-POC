"""Prior-survey knowledge base link source (FR-121, FR-127, FR-128).

Supplies a candidate LINK from a previous assessment run -- never an
answer (FR-124).
"""

from __future__ import annotations

from shared.state.entities import LinkSource, ResolutionAttempt
from shared.persistence.repositories import Repository


def resolve_from_prior_survey_kb(
    repo: Repository, question_id: str, country_id: str, order: int
) -> ResolutionAttempt:
    links = repo.find_prior_survey_links(question_id, country_id)
    if not links:
        return ResolutionAttempt(
            source=LinkSource.PRIOR_SURVEY_KB, order=order, returned=None, usable=False,
            rejection_reason="no prior-cycle link on record",
        )

    newest = links[0]  # find_prior_survey_links orders by created_at DESC
    return ResolutionAttempt(
        source=LinkSource.PRIOR_SURVEY_KB, order=order, returned=newest.url, usable=True,
    )
