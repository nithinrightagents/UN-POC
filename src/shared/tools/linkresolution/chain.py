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
from shared.persistence.repositories import Repository
from shared.ratelimit.token_bucket import RateLimiter
from shared.state.entities import (
    CandidateObservation,
    LinkSource,
    ResolutionAttempt,
    ResolutionNextAction,
    ResolutionObservation,
    ResolutionStatus,
)
from shared.tools.linkresolution.admissibility import check_admissible
from shared.tools.linkresolution.staleness import check_url_staleness
from shared.tools.linkresolution.relevance import choose_best
from shared.tools.linkresolution.sources.msq import resolve_from_msq
from shared.tools.linkresolution.sources.prior_survey_kb import resolve_from_prior_survey_kb
from shared.tools.linkresolution.sources.search import (
    DDG_SEARCH_URL,
    is_government_domain,
    is_subdomain_of,
    search_for_link,
)
from shared.tools.linkresolution.sources.sitemap import resolve_from_sitemap


@dataclass
class ChainResolutionResult:
    resolved_url: str | None
    supplying_source: LinkSource | None
    history: list[ResolutionAttempt]
    observation: ResolutionObservation | None = None


def build_resolution_observation(
    resolved_url: str | None,
    supplying_source: LinkSource | None,
    history: list[ResolutionAttempt],
    attempt_count: int = 1,
    confidence: float | None = None,
) -> ResolutionObservation:
    candidates: list[CandidateObservation] = []
    winner: CandidateObservation | None = None

    for a in history:
        cand = CandidateObservation(
            url=a.returned or "",
            title=a.title or "",
            snippet=a.snippet or "",
            source=a.source.value if hasattr(a.source, "value") else str(a.source),
            usable=a.usable,
            rejection_reason=a.rejection_reason,
            rejection_code=a.rejection_code,
            confidence=a.confidence,
            position=a.position or 0,
        )
        if a.returned:
            candidates.append(cand)
        if a.usable and a.returned == resolved_url and not winner:
            winner = cand

    if supplying_source == LinkSource.PORTAL_DEFAULT:
        status: ResolutionStatus = "homepage_fallback"
        summary = f"Fell back to portal homepage ({resolved_url}); no deep link could be resolved."
        next_actions: list[ResolutionNextAction] = ["widen_query", "needs_manual_link"]
    elif resolved_url is not None:
        if confidence is not None and confidence < 0.60:
            status = "resolved_low_confidence"
            summary = f"Resolved to {resolved_url} via {supplying_source.value if supplying_source else 'unknown'} with low confidence ({confidence:.2f})."
            next_actions = ["retry_other_candidate", "needs_manual_link"]
        else:
            status = "resolved"
            conf_str = f" ({confidence:.2f})" if confidence is not None else ""
            summary = f"Resolved to {resolved_url} via {supplying_source.value if supplying_source else 'unknown'}{conf_str}."
            next_actions = []
    else:
        status = "unresolved"
        summary = "No usable evidence URL resolved across configured sources."
        next_actions = ["widen_query", "relax_domain", "needs_manual_link"]

    return ResolutionObservation(
        status=status,
        summary=summary,
        winner=winner,
        candidates=candidates,
        next_actions=next_actions,
        attempt_count=attempt_count,
    )


def _make_result(
    resolved_url: str | None,
    supplying_source: LinkSource | None,
    history: list[ResolutionAttempt],
    attempt_count: int = 1,
    confidence: float | None = None,
) -> ChainResolutionResult:
    obs = build_resolution_observation(
        resolved_url, supplying_source, history, attempt_count=attempt_count, confidence=confidence
    )
    return ChainResolutionResult(
        resolved_url=resolved_url,
        supplying_source=supplying_source,
        history=history,
        observation=obs,
    )


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
    model: str | None = None,
    exclude_urls: set[str] | None = None,
    restrict_domain: str | None = None,
    relevance_text: str | None = None,
    relevance_detail: str | None = None,
    widened_query: str | None = None,
    blocked_domains: set[str] | None = None,
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

    `restrict_domain` scopes link candidate filtering when explicitly provided.
    In the standard chain, the sitemap source runs portal-scoped while search
    runs unrestricted across official government domains; choose_best()
    then adjudicates between both candidate winners with portal as tie-break.

    `widened_query` is the phrasing to use once the search leaves the
    portal behind; it falls back to `search_query`.

    `relevance_detail` is the question's longer explanation, ranked at a
    discount -- it expands the title's acronyms but is phrased in
    boilerplate shared across indicators.

    `relevance_text` is the question's own wording, used to rank candidates
    by how well they match what is being asked.
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
            if attempt.usable and attempt.returned:
                adm = check_admissible(attempt.returned)
                if not adm.admissible:
                    attempt = ResolutionAttempt(
                        source=attempt.source,
                        order=attempt.order,
                        returned=attempt.returned,
                        usable=False,
                        rejection_reason=adm.reason,
                    )
                else:
                    is_stale = False
                    if http_client is not None:
                        is_stale = await check_url_staleness(attempt.returned, http_client)
                    if is_stale:
                        attempt = ResolutionAttempt(
                            source=attempt.source,
                            order=attempt.order,
                            returned=attempt.returned,
                            usable=False,
                            rejection_reason=f"stale or unreachable prior URL ({attempt.returned})",
                        )
                    elif provider is not None:
                        judge_res = await choose_best(
                            provider=provider,
                            model=model or getattr(settings, "validator_model", "gemini-2.5-flash"),
                            question={"title": relevance_text or search_query, "what": relevance_detail or ""},
                            candidates=[{"url": attempt.returned, "title": attempt.title or relevance_text or search_query, "snippet": ""}],
                        )
                        if judge_res.status == "abstained":
                            attempt = ResolutionAttempt(
                                source=attempt.source,
                                order=attempt.order,
                                returned=attempt.returned,
                                usable=False,
                                rejection_reason="no candidate judged relevant by semantic judge",
                            )
                        elif judge_res.status == "chose":
                            attempt.confidence = judge_res.confidence
        elif source_name == "msq":
            if not settings.msq_link_source_enabled:
                continue
            order += 1
            attempt = resolve_from_msq(repo, question_id, country_id, order)
            if attempt.usable and attempt.returned:
                adm = check_admissible(attempt.returned)
                if not adm.admissible:
                    attempt = ResolutionAttempt(
                        source=attempt.source,
                        order=attempt.order,
                        returned=attempt.returned,
                        usable=False,
                        rejection_reason=adm.reason,
                    )
                else:
                    is_stale = False
                    if http_client is not None:
                        is_stale = await check_url_staleness(attempt.returned, http_client)
                    if is_stale:
                        attempt = ResolutionAttempt(
                            source=attempt.source,
                            order=attempt.order,
                            returned=attempt.returned,
                            usable=False,
                            rejection_reason=f"stale or unreachable MSQ URL ({attempt.returned})",
                        )
                    elif provider is not None:
                        judge_res = await choose_best(
                            provider=provider,
                            model=model or getattr(settings, "validator_model", "gemini-2.5-flash"),
                            question={"title": relevance_text or search_query, "what": relevance_detail or ""},
                            candidates=[{"url": attempt.returned, "title": attempt.title or relevance_text or search_query, "snippet": ""}],
                        )
                        if judge_res.status == "abstained":
                            attempt = ResolutionAttempt(
                                source=attempt.source,
                                order=attempt.order,
                                returned=attempt.returned,
                                usable=False,
                                rejection_reason="no candidate judged relevant by semantic judge",
                            )
                        elif judge_res.status == "chose":
                            attempt.confidence = judge_res.confidence
        elif source_name == "search":
            # T005 / T006 / T007: Run sitemap (portal-scoped) and search (unrestricted),
            # then adjudicate between the two winners using choose_best() with portal as tie-break.
            sitemap_attempt: ResolutionAttempt | None = None
            if portal_url:
                order += 1
                sitemap_attempt = await resolve_from_sitemap(
                    http_client,
                    portal_url,
                    order,
                    relevance_text or search_query,
                    relevance_detail=relevance_detail,
                    exclude_urls=exclude_urls,
                )
                if sitemap_attempt.usable:
                    adm = check_admissible(sitemap_attempt.returned)
                    if not adm.admissible:
                        sitemap_attempt = ResolutionAttempt(
                            source=sitemap_attempt.source,
                            order=sitemap_attempt.order,
                            returned=sitemap_attempt.returned,
                            usable=False,
                            rejection_reason=adm.reason,
                        )
                history.append(sitemap_attempt)

            order += 1
            if limiter is not None:
                await limiter.acquire(DDG_SEARCH_URL, "search")

            search_query_effective = widened_query or search_query
            search_attempt = await search_for_link(
                http_client,
                search_query_effective,
                order,
                country_id=country_id,
                provider=provider,
                model=model or getattr(settings, "validator_model", "gemini-2.5-flash"),
                portal_url=portal_url,
                exclude_urls=exclude_urls,
                firecrawl_api_key=getattr(settings, "firecrawl_api_key", None),
                serper_api_key=getattr(settings, "serper_api_key", None),
                restrict_domain=None,  # T007: search runs unrestricted
                relevance_text=relevance_text,
                relevance_detail=relevance_detail,
                blocked_domains=blocked_domains,
            )
            if search_attempt.usable:
                adm = check_admissible(search_attempt.returned)
                if not adm.admissible:
                    search_attempt = ResolutionAttempt(
                        source=search_attempt.source,
                        order=search_attempt.order,
                        returned=search_attempt.returned,
                        usable=False,
                        rejection_reason=adm.reason,
                    )
            history.append(search_attempt)

            # Adjudicate winners (T006)
            sitemap_ok = sitemap_attempt is not None and sitemap_attempt.usable
            search_ok = search_attempt.usable

            if sitemap_ok and search_ok:
                if sitemap_attempt.returned == search_attempt.returned:
                    return _make_result(
                        resolved_url=sitemap_attempt.returned,
                        supplying_source=sitemap_attempt.source,
                        history=history,
                    )

                candidates = [
                    {
                        "url": sitemap_attempt.returned,
                        "title": sitemap_attempt.title or (relevance_text or search_query),
                        "snippet": sitemap_attempt.snippet or "",
                    },
                    {
                        "url": search_attempt.returned,
                        "title": search_attempt.title or (relevance_text or search_query),
                        "snippet": search_attempt.snippet or "",
                    },
                ]
                chosen_idx = None
                judge_confidence = None
                if provider is not None:
                    judge_res = await choose_best(
                        provider=provider,
                        model=model or getattr(settings, "validator_model", "gemini-2.5-flash"),
                        question={"title": relevance_text or search_query, "what": relevance_detail or ""},
                        candidates=candidates,
                    )
                    chosen_idx = judge_res.index if hasattr(judge_res, "index") else judge_res
                    judge_confidence = getattr(judge_res, "confidence", None)

                # Tie-break: portal/sitemap wins unless judge explicitly chose search (index 1)
                if chosen_idx == 1:
                    winning_attempt = search_attempt
                else:
                    winning_attempt = sitemap_attempt

                return _make_result(
                    resolved_url=winning_attempt.returned,
                    supplying_source=winning_attempt.source,
                    history=history,
                    confidence=judge_confidence or winning_attempt.confidence,
                )

            elif sitemap_ok:
                return _make_result(
                    resolved_url=sitemap_attempt.returned,
                    supplying_source=sitemap_attempt.source,
                    history=history,
                    confidence=sitemap_attempt.confidence,
                )

            elif search_ok:
                return _make_result(
                    resolved_url=search_attempt.returned,
                    supplying_source=search_attempt.source,
                    history=history,
                    confidence=search_attempt.confidence,
                )

            continue
        else:
            continue

        # FR-005: an explicit usability test is applied to whatever the
        # source returned, in addition to the source's own usable flag.
        admissibility = check_admissible(attempt.returned)
        if attempt.usable and not admissibility.admissible:
            attempt = ResolutionAttempt(
                source=attempt.source, order=attempt.order, returned=attempt.returned,
                usable=False, rejection_reason=admissibility.reason,
                rejection_code=admissibility.code or "inadmissible",
            )

        # Defense in depth for non-search sources (msq, prior_survey_kb)
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
                rejection_code="outside_domain",
            )

        history.append(attempt)

        if attempt.usable:
            return _make_result(
                resolved_url=attempt.returned,
                supplying_source=attempt.source,
                history=history,
                confidence=attempt.confidence,
            )

    # Fallback to portal base URL if registered and usable on a government domain
    if portal_url and is_government_domain(portal_url, country_id):
        usability = check_admissible(portal_url)
        if usability.admissible:
            order += 1
            fallback_attempt = ResolutionAttempt(
                source=LinkSource.PORTAL_DEFAULT,
                order=order,
                returned=portal_url,
                usable=True,
            )
            history.append(fallback_attempt)
            return _make_result(
                resolved_url=portal_url,
                supplying_source=LinkSource.PORTAL_DEFAULT,
                history=history,
            )

    # FR-007: no source in the chain yielded a usable URL.
    return _make_result(resolved_url=None, supplying_source=None, history=history)
