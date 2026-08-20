"""The batch scheduler (spec 001, spec 008 prefill pipeline).

Ties link resolution, N independent Assessor Agents (each running its own
confidence gate and validation retry loop), agreement classification, and
the prefill writer into one per-unit headless pipeline.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from agents.adjudicator.agreement import classify_agreement
from agents.assessor.agent import AssessorAgent
from agents.assessor.node import assessor_node
from agents.resolver.agent import ResolverAgent
from agents.validator.agent import ValidatorAgent
from agents.validator.node import validator_node
from core.llm_factory import ModelProvider
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.langsmith_tracing import safe_trace, unit_trace
from core.telemetry.stage_events import StageEventLog
from orchestration.prefill_writer import write_prefill
from orchestration.routers.retry_loops import (
    _describe_disagreement,
    _run_output_from_agent_run,
    materialize_evidence_artifact,
    run_validation_retry_loop,
)
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state import unit_state
from shared.state.entities import (
    AgentRunState,
    AssessorAgentRun,
    LinkSource,
    PrefillReason,
    Question,
    TargetPortal,
    UnitState,
    new_id,
)
from shared.state.resume import remaining_work
from shared.state.schemas import PortalInput, QuestionInput, RetryAddendum
from shared.tools.browser import BrowserSession
from shared.tools.linkresolution.chain import resolve_link
from shared.tools.linkresolution.locus import evidence_permitted


@dataclass
class UnitOutcome:
    question_id: str
    portal_id: str
    final_state: UnitState
    detail: str = ""


@dataclass
class BatchRunSummary:
    outcomes: list[UnitOutcome] = field(default_factory=list)

    @property
    def delivered(self) -> int:
        return sum(1 for o in self.outcomes if o.final_state == UnitState.DELIVERED)

    @property
    def escalated(self) -> int:
        return sum(1 for o in self.outcomes if o.final_state == UnitState.ESCALATED)

    @property
    def no_suggestion(self) -> int:
        return sum(1 for o in self.outcomes if o.final_state == UnitState.NO_SUGGESTION)

    @property
    def unassessable(self) -> int:
        return sum(1 for o in self.outcomes if o.final_state == UnitState.UNASSESSABLE)

    @property
    def in_progress(self) -> int:
        return (
            len(self.outcomes)
            - self.delivered
            - self.escalated
            - self.no_suggestion
            - self.unassessable
        )


async def run_batch(
    *,
    repo: Repository,
    settings: Settings,
    session_id: str,
    provider: ModelProvider,
    browser: BrowserSession,
    http_client: httpx.AsyncClient | None,
    fetch_log: FetchLog,
    stage_log: StageEventLog,
    cost_ledger: CostLedger,
    capture_dir: str,
    questions: list[Question],
    portals: list[TargetPortal],
    adjudicate_results: bool = True,
    run_id: str | None = None,
) -> BatchRunSummary:
    summary = BatchRunSummary()
    semaphore = asyncio.Semaphore(max(1, settings.batch_size))
    units = [(q, p) for p in portals for q in questions]
    budget = getattr(cost_ledger, "budget", None)

    async def bounded(question: Question, portal: TargetPortal) -> None:
        if budget and budget.exhausted():
            # FR-PF-041b: budget reached before dispatch -> write budget_reached prefill without dispatching
            effective_run_id = run_id or session_id
            write_prefill(
                repo=repo,
                session_id=session_id,
                cycle_id=portal.cycle_id,
                portal_id=portal.portal_id,
                question_id=question.question_id,
                run_id=effective_run_id,
                suggested=False,
                reason=PrefillReason.BUDGET_REACHED,
                advance_state=True,
            )
            outcome = UnitOutcome(
                question.question_id,
                portal.portal_id,
                UnitState.NO_SUGGESTION,
                PrefillReason.BUDGET_REACHED.value,
            )
            summary.outcomes.append(outcome)
            return

        async with semaphore:
            if budget and budget.exhausted():
                effective_run_id = run_id or session_id
                write_prefill(
                    repo=repo,
                    session_id=session_id,
                    cycle_id=portal.cycle_id,
                    portal_id=portal.portal_id,
                    question_id=question.question_id,
                    run_id=effective_run_id,
                    suggested=False,
                    reason=PrefillReason.BUDGET_REACHED,
                    advance_state=True,
                )
                outcome = UnitOutcome(
                    question.question_id,
                    portal.portal_id,
                    UnitState.NO_SUGGESTION,
                    PrefillReason.BUDGET_REACHED.value,
                )
                summary.outcomes.append(outcome)
                return

            outcome = await process_unit(
                repo=repo,
                settings=settings,
                session_id=session_id,
                provider=provider,
                browser=browser,
                http_client=http_client,
                fetch_log=fetch_log,
                stage_log=stage_log,
                cost_ledger=cost_ledger,
                capture_dir=capture_dir,
                question=question,
                portal=portal,
                adjudicate_results=adjudicate_results,
                run_id=run_id,
            )
            summary.outcomes.append(outcome)

    async with asyncio.TaskGroup() as tg:
        for question, portal in units:
            tg.create_task(bounded(question, portal))

    return summary


async def process_unit(
    *,
    repo: Repository,
    settings: Settings,
    session_id: str,
    provider: ModelProvider,
    browser: BrowserSession,
    http_client: httpx.AsyncClient | None,
    fetch_log: FetchLog,
    stage_log: StageEventLog,
    cost_ledger: CostLedger,
    capture_dir: str,
    question: Question,
    portal: TargetPortal,
    adjudicate_results: bool = True,
    run_id: str | None = None,
) -> UnitOutcome:
    """Runs (or resumes) exactly one question x portal unit end to end into a prefill record."""
    portal_id = portal.portal_id
    effective_run_id = run_id or new_id("run")
    cycle_id = portal.cycle_id or getattr(question, "cycle_id", "default-cycle")

    how = question.how if isinstance(question.how, dict) else {}
    question_dict = {
        "question_id": question.question_id,
        "text": question.text,
        "answer_type": question.answer_type.value,
        "evidence_locus": question.evidence_locus.value,
        "title": question.title,
        "what": question.what,
        "why": question.why,
        "criteria_for_yes": how.get("criteria_for_yes"),
        "criteria_for_no": how.get("criteria_for_no"),
        "scoring_guidance": how.get("scoring_guidance"),
        "benchmark_case": question.benchmark_case,
    }

    existing = repo.get_unit(session_id, question.question_id, portal_id)
    unit_data: dict = existing or {}
    current_state = UnitState(existing["state"]) if existing else UnitState.PENDING

    if unit_state.is_terminal(current_state):
        return UnitOutcome(question.question_id, portal_id, current_state, "already terminal")

    def advance(to_state: UnitState, data: dict) -> None:
        if to_state != current_state_ref[0]:
            unit_state.transition(current_state_ref[0], to_state)
        repo.upsert_unit(session_id, question.question_id, portal_id, to_state.value, data)
        current_state_ref[0] = to_state

    current_state_ref = [current_state]

    async with unit_trace(
        session_id, question.question_id, portal_id, question.text, unit_data.get("resolved_url", "")
    ) as root_run:

        async def no_suggestion(
            reason: PrefillReason,
            context: dict,
            terminal_state: UnitState = UnitState.NO_SUGGESTION,
            position_run_ids: list[str] | None = None,
        ) -> UnitOutcome:
            advance(terminal_state, {**unit_data, "prefill_reason": reason.value, **context})
            write_prefill(
                repo=repo,
                session_id=session_id,
                cycle_id=cycle_id,
                portal_id=portal_id,
                question_id=question.question_id,
                run_id=effective_run_id,
                suggested=False,
                reason=reason,
                terminal_state=terminal_state,
                position_run_ids=position_run_ids or [],
                advance_state=False,
            )
            outcome = UnitOutcome(question.question_id, portal_id, terminal_state, reason.value)
            root_run.patch(
                metadata={"prefill_reason": reason.value},
                outputs={"outcome": outcome.final_state.value, "detail": outcome.detail},
            )
            return outcome

        try:
            # --- Link resolution (FR-001–FR-007) -----------------------------
            if current_state_ref[0] == UnitState.PENDING:
                advance(UnitState.RESOLVING_LINK, unit_data)

            if current_state_ref[0] == UnitState.RESOLVING_LINK and not unit_data.get("resolved_url"):
                async with safe_trace(
                    "url_resolution",
                    run_type="chain",
                    inputs={"question_id": question.question_id, "portal_id": portal_id},
                ) as url_span:
                    with stage_log.timed(
                        "url_resolution",
                        {"question_id": question.question_id, "portal_id": portal_id},
                    ):
                        # Strict-first-try / relaxed-retry domain restriction
                        # (2026-08-21): national_portal_only questions must
                        # always resolve on the portal's own domain -- no
                        # round ever relaxes that (FR-130). any_government_domain
                        # questions are only this strict on the FIRST
                        # resolution attempt (link_retry_count == 0); once a
                        # link retry has kicked in, later attempts may land
                        # on any recognized government domain, not just the
                        # national portal.
                        locus_value = question.evidence_locus.value
                        is_first_attempt = unit_data.get("link_retry_count", 0) == 0
                        restrict_to_portal = locus_value == "national_portal_only" or (
                            locus_value == "any_government_domain" and is_first_attempt
                        )
                        restrict_domain = (
                            urlparse(portal.resolved_url).netloc.lower()
                            if restrict_to_portal and portal.resolved_url
                            else None
                        )
                        # A search engine query built from the full question
                        # `text` (a paragraph-length description) measurably
                        # returns zero results on live DuckDuckGo where the
                        # same topic phrased as the short `title` succeeds --
                        # confirmed by direct comparison during diagnosis.
                        # `title` is concise and keyword-rich by construction;
                        # `text` is only a fallback for the rare question
                        # without one, truncated to stay query-length-safe.
                        search_topic = question.title or question.text[:120]
                        if restrict_domain:
                            # search_for_link already anchors this query to
                            # `restrict_domain` via a `site:` operator --
                            # wrapping the topic in portal-name/URL boilerplate
                            # on top of that (2026-08-21 debugging pass:
                            # reproduced live against Firecrawl) swamps
                            # ranking so badly that unrelated questions
                            # collapse onto the SAME generic top-level page
                            # (e.g. four different questions all resolving to
                            # usa.gov/about-the-us) instead of a topic-specific
                            # one -- keep the query lean when domain-restricted.
                            search_query = search_topic
                        elif portal.resolved_url:
                            search_query = (
                                f"{portal.display_name or portal.country_id} government "
                                f"portal ({portal.resolved_url}): {search_topic}"
                            )
                        else:
                            search_query = (
                                f"{portal.display_name or portal.country_id} government "
                                f"portal: {search_topic}"
                            )
                        result = await resolve_link(
                            repo,
                            http_client,
                            question.question_id,
                            portal.country_id,
                            search_query,
                            settings,
                            exclude_sources=set(unit_data.get("excluded_link_sources", [])),
                            limiter=browser.search_limiter if browser else None,
                            portal_url=portal.resolved_url,
                            provider=provider,
                            exclude_urls=set(unit_data.get("tried_urls", [])),
                            restrict_domain=restrict_domain,
                        )
                    url_span.patch(
                        outputs={
                            "resolved_url": result.resolved_url,
                            "supplying_source": result.supplying_source.value
                            if result.supplying_source
                            else None,
                            "usable": result.resolved_url is not None,
                        }
                    )
                unit_data["resolution_history"] = unit_data.get("resolution_history", []) + [
                    {
                        "source": a.source.value,
                        "order": a.order,
                        "returned": a.returned,
                        "usable": a.usable,
                        "rejection_reason": a.rejection_reason,
                    }
                    for a in result.history
                ]
                if result.resolved_url is None:
                    return await no_suggestion(
                        PrefillReason.NO_USABLE_EVIDENCE,
                        {"resolution_history": unit_data["resolution_history"]},
                        terminal_state=UnitState.UNASSESSABLE,
                    )
                unit_data["resolved_url"] = result.resolved_url
                unit_data["supplying_source"] = (
                    result.supplying_source.value if result.supplying_source else None
                )
                advance(UnitState.RESOLVED, unit_data)

            resolved_url = unit_data["resolved_url"]

            # FR-107 / Access boundary
            if current_state_ref[0] == UnitState.RESOLVED and question.requires_authenticated_access:
                return await no_suggestion(
                    PrefillReason.ACCESS_BOUNDARY,
                    {"reason": "question is flagged requires_authenticated_access (FR-107)"},
                )

            # --- Independent assessment (FR-008–FR-013, FR-076–FR-091) --------
            round_number = unit_data.get("round_number", 1)

            if current_state_ref[0] == UnitState.RESOLVED:
                # A fresh RESOLVED->ASSESSING transition starts a new round --
                # normally round 1, but the dead-link fallback below re-enters
                # here with round_number already at 1, so this must increment
                # rather than reset to keep the retry's agent runs from
                # colliding with (and being mistaken for) the first attempt's.
                round_number = unit_data.get("round_number", 0) + 1
                unit_data["round_number"] = round_number
                advance(UnitState.ASSESSING, unit_data)

            existing_runs = repo.list_agent_runs(
                session_id, question.question_id, portal_id, round_number=round_number
            )
            plan = remaining_work(UnitState.ASSESSING, existing_runs, settings.assessor_agent_count)
            dispatch_indices = plan.agents_to_dispatch
            retained_runs: list[AssessorAgentRun] = [
                r for r in existing_runs if r.run_id in plan.retained_run_ids
            ]

            assessor_agent = AssessorAgent(provider=provider, browser=browser)

            async def run_one_agent(
                agent_index: int, this_round: int, addendum: RetryAddendum | None
            ) -> AssessorAgentRun:
                assessor_state = {
                    "session_id": session_id,
                    "question": QuestionInput(**question_dict),
                    "portal": PortalInput(portal_id=portal_id, resolved_url=resolved_url),
                    "addendum": addendum,
                }
                initial_run = await assessor_node(
                    assessor_state,
                    agent_index,
                    this_round,
                    assessor_agent,
                    settings=settings,
                    fetch_log=fetch_log,
                    stage_log=stage_log,
                    cost_ledger=cost_ledger,
                    capture_dir=capture_dir,
                )
                initial_evidence = materialize_evidence_artifact(initial_run)
                if initial_evidence:
                    repo.insert_evidence(initial_evidence)
                    initial_run.evidence_artifact_id = initial_evidence.artifact_id
                repo.insert_agent_run(initial_run)

                loop_result = await run_validation_retry_loop(
                    session_id=session_id,
                    question=question_dict,
                    portal_url=resolved_url,
                    agent_index=agent_index,
                    round_number=this_round,
                    settings=settings,
                    provider=provider,
                    browser=browser,
                    fetch_log=fetch_log,
                    stage_log=stage_log,
                    cost_ledger=cost_ledger,
                    capture_dir=capture_dir,
                    initial_run=initial_run,
                    initial_evidence=initial_evidence,
                    portal_id=portal_id,
                )

                for i, run in enumerate(loop_result.attempted_runs):
                    if i == 0:
                        continue
                    evidence = materialize_evidence_artifact(run)
                    if evidence:
                        repo.insert_evidence(evidence)
                        run.evidence_artifact_id = evidence.artifact_id
                    repo.insert_agent_run(run)
                for validation in loop_result.attempted_validations:
                    repo.insert_validation_result(validation)

                repo.insert_agent_run(loop_result.final_run)
                return loop_result.final_run

            new_runs = (
                list(
                    await asyncio.gather(
                        *(run_one_agent(i, round_number, None) for i in dispatch_indices)
                    )
                )
                if dispatch_indices
                else []
            )
            all_runs = retained_runs + new_runs

            # --- Language support check (FR-015 replacement) -------------------
            reported_languages = [r.detected_language for r in all_runs if r.detected_language]
            if reported_languages:
                language_counts = Counter(reported_languages)
                majority_language, _ = language_counts.most_common(1)[0]
                if majority_language not in settings.supported_languages:
                    return await no_suggestion(
                        PrefillReason.UNSUPPORTED_LANGUAGE,
                        {
                            "detected_language": majority_language,
                            "reported_languages": dict(language_counts),
                            "supported_languages": settings.supported_languages,
                        },
                    )

            validated_runs = [r for r in all_runs if r.state == AgentRunState.VALIDATED_PASS]

            if len(validated_runs) < settings.assessor_agent_count:
                if all_runs and all(r.auth_boundary_observed for r in all_runs):
                    return await no_suggestion(
                        PrefillReason.ACCESS_BOUNDARY,
                        {"reason": "every independent agent observed an authentication boundary"},
                    )

                # Link-retry fallback (2026-08-20 goal): every dispatched agent
                # either found the resolved URL unreachable, OR read it fine
                # but flagged it as the WRONG page/link for this question
                # (link_likely_wrong) -- e.g. an MSQ-supplied link that turns
                # out to be a generic hub page. Re-resolves, excluding
                # non-search sources that already proved dead/wrong once
                # each (so a bad MSQ link falls through to web search), and
                # excluding specific URLs already tried within this unit so
                # search keeps surfacing new candidates -- bounded to
                # MAX_LINK_RETRIES so a persistently-wrong search result
                # can't retry forever.
                MAX_LINK_RETRIES = 3
                link_needs_retry = bool(all_runs) and all(
                    getattr(r, "portal_unreachable", False) or getattr(r, "link_likely_wrong", False)
                    for r in all_runs
                )
                retry_count = unit_data.get("link_retry_count", 0)
                if link_needs_retry and retry_count < MAX_LINK_RETRIES:
                    unit_data["link_retry_count"] = retry_count + 1
                    excluded = set(unit_data.get("excluded_link_sources", []))
                    dead_source = unit_data.get("supplying_source")
                    # "search" is never excluded -- it's the fallback meant to
                    # keep offering new candidates across retries; kb/msq
                    # each get excluded once, on their first miss.
                    if dead_source and dead_source != LinkSource.SEARCH.value:
                        excluded.add(dead_source)
                    unit_data["excluded_link_sources"] = list(excluded)
                    tried_urls = set(unit_data.get("tried_urls", []))
                    if unit_data.get("resolved_url"):
                        tried_urls.add(unit_data["resolved_url"])
                    unit_data["tried_urls"] = list(tried_urls)
                    unit_data["resolved_url"] = None
                    unit_data.pop("supplying_source", None)
                    advance(UnitState.RESOLVING_LINK, unit_data)
                    return await process_unit(
                        repo=repo,
                        settings=settings,
                        session_id=session_id,
                        provider=provider,
                        browser=browser,
                        http_client=http_client,
                        fetch_log=fetch_log,
                        stage_log=stage_log,
                        cost_ledger=cost_ledger,
                        capture_dir=capture_dir,
                        question=question,
                        portal=portal,
                        adjudicate_results=adjudicate_results,
                        run_id=run_id,
                    )

                return await no_suggestion(
                    PrefillReason.INSUFFICIENT_POSITIONS,
                    {"validated_run_count": len(validated_runs), "total_run_count": len(all_runs)},
                )

            if not adjudicate_results:
                outcome = UnitOutcome(
                    question.question_id,
                    portal_id,
                    UnitState.ASSESSING,
                    "assessed only (--no-adjudicate)",
                )
                root_run.patch(
                    outputs={"outcome": outcome.final_state.value, "detail": outcome.detail}
                )
                return outcome

            # --- Agreement Classification (FR-PF-023–027) ---------------------
            advance(UnitState.ADJUDICATING, unit_data)

            agreement = classify_agreement(
                validated_runs[:2],
                per_question_confidence_threshold=settings.per_question_confidence_threshold,
                gap_tolerance=settings.prefill_confidence_gap_tolerance,
            )

            if agreement.kind in ("uncontested", "agreed_with_gap"):
                selected_run = validated_runs[0]
                candidate_answer = agreement.answer
                candidate_confidence = agreement.confidence
                agreement_outcome_str = agreement.kind
                resolver_decision_dict = None
                unselected_pos_dict = None
            else:
                # Differing / Disputed -> Resolver Agent (FR-PF-026)
                resolver_agent = ResolverAgent(provider=provider)
                disagreement_points = _describe_disagreement(validated_runs[:2])
                resolver_decision = await resolver_agent.resolve(
                    question_text=question.text,
                    portal_url=resolved_url,
                    runs=validated_runs[:2],
                    disagreement_points=disagreement_points,
                    settings=settings,
                    provider=provider,
                    stage_log=stage_log,
                    cost_ledger=cost_ledger,
                )

                if resolver_decision.undetermined or resolver_decision.selected_run_id is None:
                    return await no_suggestion(
                        PrefillReason.UNRESOLVED_DISAGREEMENT,
                        {
                            "agreement_outcome": "unresolved_disagreement",
                            "confidence_gap": agreement.confidence_gap,
                            "resolver_decision": resolver_decision.__dict__,
                        },
                        position_run_ids=agreement.position_run_ids,
                    )

                selected_run = next(
                    (r for r in validated_runs[:2] if r.run_id == resolver_decision.selected_run_id),
                    validated_runs[0],
                )
                unselected_run = next(
                    (r for r in validated_runs[:2] if r.run_id != resolver_decision.selected_run_id),
                    None,
                )

                unselected_pos_dict = None
                if unselected_run:
                    unselected_art = (
                        repo.get_evidence(unselected_run.evidence_artifact_id)
                        if unselected_run.evidence_artifact_id
                        else None
                    )
                    unselected_pos_dict = {
                        "run_id": unselected_run.run_id,
                        "answer": unselected_run.answer,
                        "confidence": unselected_run.confidence,
                        "justification": unselected_run.justification,
                        "evidence_url": (
                            unselected_art.resolved_url
                            if unselected_art and unselected_art.resolved_url
                            else resolved_url
                        ),
                        "capture_ref": unselected_art.capture_ref if unselected_art else None,
                    }

                candidate_answer = selected_run.answer
                candidate_confidence = (
                    resolver_decision.confidence
                    if resolver_decision.confidence is not None
                    else selected_run.confidence
                )
                agreement_outcome_str = "resolved_dispute"
                resolver_decision_dict = resolver_decision.__dict__

            evidence_art = (
                repo.get_evidence(selected_run.evidence_artifact_id)
                if selected_run.evidence_artifact_id
                else None
            )
            evidence_url_val = (
                evidence_art.resolved_url
                if evidence_art and evidence_art.resolved_url
                else resolved_url
            )

            # --- Evidence Locus Enforcement (FR-129-FR-133) ------------------
            # Domain restriction so far only shaped WHERE link resolution
            # looked (see restrict_domain above); it never checked WHAT the
            # delivered evidence actually landed on -- a national_portal_only
            # question could still be delivered off-portal if evidence
            # surfaced there via one-hop navigation or a resolver pick.
            if portal.resolved_url:
                locus_permitted, locus_reason = evidence_permitted(
                    question.evidence_locus.value, evidence_url_val, portal.resolved_url
                )
                if not locus_permitted:
                    return await no_suggestion(
                        PrefillReason.NO_USABLE_EVIDENCE,
                        {
                            "candidate_run_id": selected_run.run_id,
                            "candidate_answer": candidate_answer,
                            "evidence_locus_violation": locus_reason,
                        },
                        position_run_ids=agreement.position_run_ids,
                    )

            # --- Final Validation Gate (FR-PF-030) ---------------------------
            # Every candidate position (whether from agreement or resolver) passes
            # through the single-pass final validation gate before prefill delivery.
            validator_agent = ValidatorAgent()
            candidate_output = _run_output_from_agent_run(selected_run, evidence_art)
            element_ref = evidence_art.element_reference if evidence_art else None

            final_validation_passed = True
            if provider and browser:
                try:
                    final_validation = await validator_node(
                        {
                            "run_id": selected_run.run_id,
                            "session_id": session_id,
                            "question_text": question.text,
                            "answer_type": question.answer_type.value,
                            "output": candidate_output,
                            "element_reference": element_ref,
                            "retry_number": 0,
                        },
                        validator_agent,
                        settings=settings,
                        provider=provider,
                        browser=browser,
                        fetch_log=fetch_log,
                        cost_ledger=cost_ledger,
                    )
                    repo.insert_validation_result(final_validation)
                    final_validation_passed = final_validation.passed
                except Exception:
                    final_validation_passed = False

            if not final_validation_passed:
                return await no_suggestion(
                    PrefillReason.FAILED_FINAL_VALIDATION,
                    {
                        "candidate_run_id": selected_run.run_id,
                        "candidate_answer": candidate_answer,
                    },
                    position_run_ids=agreement.position_run_ids,
                )

            write_prefill(
                repo=repo,
                session_id=session_id,
                cycle_id=cycle_id,
                portal_id=portal_id,
                question_id=question.question_id,
                run_id=effective_run_id,
                suggested=True,
                answer=bool(candidate_answer),
                confidence=candidate_confidence,
                justification=selected_run.justification,
                evidence_url=evidence_url_val,
                capture_ref=evidence_art.capture_ref if evidence_art else None,
                supplying_source=unit_data.get("supplying_source"),
                agreement_outcome=agreement_outcome_str,
                confidence_gap=agreement.confidence_gap,
                resolver_decision=resolver_decision_dict,
                unselected_position=unselected_pos_dict,
                position_run_ids=agreement.position_run_ids,
                advance_state=False,
            )
            unit_data["consensus_answer"] = candidate_answer
            unit_data["consensus_confidence"] = candidate_confidence
            advance(UnitState.DELIVERED, unit_data)
            outcome = UnitOutcome(
                question.question_id, portal_id, UnitState.DELIVERED, "delivered"
            )
            root_run.patch(
                outputs={"outcome": outcome.final_state.value, "detail": outcome.detail}
            )
            return outcome

        except Exception as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            try:
                return await no_suggestion(
                    PrefillReason.ASSESSMENT_FAILURE,
                    {"error": f"{type(exc).__name__}: {str(exc)}"},
                )
            except Exception:
                raise exc


def enqueue_custom_question(
    repo: Repository,
    session_id: str,
    question: Question,
    portals: list[TargetPortal],
) -> list[str]:
    """Enqueue a mid-run custom question against in-scope portals without re-assessing
    or invalidating completed work (T094, FR-056). Returns unit IDs enqueued."""
    enqueued = []
    for p in portals:
        existing = repo.get_unit(session_id, question.question_id, p.portal_id)
        if existing is None:
            repo.upsert_unit(session_id, question.question_id, p.portal_id, UnitState.PENDING.value, {})
            enqueued.append(f"{question.question_id}:{p.portal_id}")
    return enqueued
