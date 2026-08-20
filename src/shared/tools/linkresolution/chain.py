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
from urllib.parse import urlparse

import httpx

from shared.config.settings import Settings
from shared.ratelimit.token_bucket import RateLimiter
from shared.state.entities import LinkSource, ResolutionAttempt
from shared.tools.linkresolution.sources.msq import resolve_from_msq
from shared.tools.linkresolution.sources.prior_survey_kb import resolve_from_prior_survey_kb
from shared.tools.linkresolution.sources.search import (
    DDG_SEARCH_URL,
    is_government_domain,
    is_subdomain_of,
    search_for_link,
)
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
    exclude_sources: set[str] | None = None,
    limiter: RateLimiter | None = None,
    portal_url: str | None = None,
    provider: object | None = None,
    exclude_urls: set[str] | None = None,
    restrict_domain: str | None = None,
) -> ChainResolutionResult:
    """FR-003: consultation order follows settings.resolution_order, one of
    the three named modes. FR-002/FR-122: a later source runs only if every
    earlier enabled source yielded nothing usable.

    `exclude_sources` skips named sources entirely (e.g. re-invoking this
    chain after the source that originally supplied a link turned out, at
    live-fetch time, to be dead -- retrying the same source would just
    return the same dead URL again).

    `exclude_urls` (2026-08-20 goal) skips specific URLs already tried for
    this question within the SEARCH source, so a retry loop bounded to a
    few attempts surfaces a different candidate each time instead of
    re-resolving to the same rejected link.

    `portal_url` provides the target portal's registered base URL as an anchor/fallback
    when no specialized deep-link could be resolved.

    `restrict_domain` (2026-08-21 goal: strict-first-try / relaxed-retry
    resolution for any_government_domain questions -- national_portal_only
    questions stay portal-restricted at every round via the caller always
    passing it) requires every candidate, from every source, to resolve
    within that domain or a subdomain of it -- a candidate outside it is
    rejected here even if the source itself reported it usable, so a
    same-domain result further down that source's own list (or the next
    source in the chain) still gets a chance instead of the loop returning
    an off-domain link early.
    """
    history: list[ResolutionAttempt] = []
    order = 0
    excluded = exclude_sources or set()

    for source_name in settings.resolution_order:
        if source_name in excluded:
            continue
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
            if limiter is not None:
                await limiter.acquire(DDG_SEARCH_URL, "search")
            attempt = await search_for_link(
                http_client,
                search_query,
                order,
                country_id=country_id,
                provider=provider,
                model=getattr(settings, "validator_model", "gemini-2.5-flash"),
                portal_url=portal_url,
                exclude_urls=exclude_urls,
                firecrawl_api_key=getattr(settings, "firecrawl_api_key", None),
                restrict_domain=restrict_domain,
            )
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

        # Defense in depth for the non-search sources (msq, prior_survey_kb),
        # which return a single stored candidate with no domain check of
        # their own -- search's own candidates are already filtered inside
        # search_for_link via restrict_domain, so this is a no-op for it.
        if attempt.usable and restrict_domain and not is_subdomain_of(
            urlparse(attempt.returned).netloc.lower(), restrict_domain
        ):
            attempt = ResolutionAttempt(
                source=attempt.source, order=attempt.order, returned=attempt.returned,
                usable=False,
                rejection_reason=(
                    f"resolved outside the required domain ({restrict_domain}) for "
                    "this attempt"
                ),
            )

        history.append(attempt)

        if attempt.usable:
            return ChainResolutionResult(
                resolved_url=attempt.returned, supplying_source=attempt.source, history=history
            )

    # Fallback to portal base URL if registered and usable on a government domain
    if portal_url and is_government_domain(portal_url, country_id):
        usability = check_usable(portal_url)
        if usability.usable:
            order += 1
            fallback_attempt = ResolutionAttempt(
                source=LinkSource.PORTAL_DEFAULT,
                order=order,
                returned=portal_url,
                usable=True,
            )
            history.append(fallback_attempt)
            return ChainResolutionResult(
                resolved_url=portal_url,
                supplying_source=LinkSource.PORTAL_DEFAULT,
                history=history,
            )

    # FR-007: no source in the chain yielded a usable URL.
    return ChainResolutionResult(resolved_url=None, supplying_source=None, history=history)
