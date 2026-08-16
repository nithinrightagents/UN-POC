"""Ordered link resolution chain (FR-001–FR-007, FR-121–FR-128).

A later source is consulted only when every earlier ENABLED source yielded
no usable candidate (FR-002, FR-122). Every candidate -- used or rejected
-- is recorded with its source, order, and rejection reason (FR-006,
FR-084). The resolved link is never treated as an answer source itself:
FR-124 requires it to be traversed live before any answer is produced,
which the orchestration scheduler enforces by always fetching the
resolved_url through the Assessor Agent regardless of which source
supplied it.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from shared.config.settings import Settings
from shared.state.entities import LinkSource, ResolutionAttempt
from shared.tools.linkresolution.sources.msq import resolve_from_msq
from shared.tools.linkresolution.sources.prior_survey_kb import resolve_from_prior_survey_kb
from shared.tools.linkresolution.sources.search import search_for_link
from shared.tools.linkresolution.usability import check_usable
from shared.persistence.repositories import Repository


@dataclass
class ChainResolutionResult:
    resolved_url: str | None
    supplying_source: LinkSource | None
    history: list[ResolutionAttempt]


async def resolve_link(
    repo: Repository,
    http_client: httpx.AsyncClient,
    question_id: str,
    country_id: str,
    search_query: str,
    settings: Settings,
) -> ChainResolutionResult:
    """FR-003: consultation order follows settings.resolution_order, one of
    the three named modes. FR-002/FR-122: a later source runs only if every
    earlier enabled source yielded nothing usable."""
    history: list[ResolutionAttempt] = []
    order = 0

    for source_name in settings.resolution_order:
        if source_name == "prior_survey_kb":
            if not settings.kb_link_source_enabled:
                continue
            order += 1
            attempt = resolve_from_prior_survey_kb(repo, question_id, country_id, order)
        elif source_name == "msq":
            if not settings.msq_link_source_enabled:
                continue
            order += 1
            attempt = resolve_from_msq(repo, question_id, country_id, order)
        elif source_name == "search":
            order += 1
            attempt = await search_for_link(http_client, search_query, order)
        else:
            continue

        # FR-005: an explicit usability test is applied to whatever the
        # source returned, in addition to the source's own usable flag.
        usability = check_usable(attempt.returned)
        if attempt.usable and not usability.usable:
            attempt = ResolutionAttempt(
                source=attempt.source, order=attempt.order, returned=attempt.returned,
                usable=False, rejection_reason=usability.reason,
            )

        history.append(attempt)

        if attempt.usable:
            return ChainResolutionResult(
                resolved_url=attempt.returned, supplying_source=attempt.source, history=history
            )

    # FR-007: no source in the chain yielded a usable URL.
    return ChainResolutionResult(resolved_url=None, supplying_source=None, history=history)
