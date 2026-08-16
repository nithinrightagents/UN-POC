"""The batch scheduler (FR-064–FR-070, research R6).

Ties link resolution, N independent Assessor Agents (each running its own
confidence gate and validation retry loop, and each reporting the language
it observed on the page as part of its normal structured response), and
adjudication into one per-unit pipeline, run across many units with
concurrency bounded PER UNIT (`settings.batch_size`), not per fetch --
every fetch inside a unit still passes through the single shared
per-domain rate limiter (FR-089), so raising batch_size increases how many
units are in flight, never how fast any one domain is hit.

Resume (FR-064–FR-067b) uses `domain/resume.py`'s `remaining_work()` at
whatever round is on record: terminal agent runs for that round are
retained, non-terminal ones discarded and re-dispatched. `round_number` is
persisted once, when a unit enters ASSESSING -- it is not updated again as
`run_adjudication_retry_loop` privately advances through retry rounds. A
crash mid-adjudication-retry (round > 1) therefore resumes by re-deriving
round 1 from its retained, already-validated agent runs and re-running
adjudication fresh from there, rather than picking the exact retry round
back up. Any partially-written round-2+ agent runs from the interrupted
attempt are simply orphaned, append-only rows -- never re-read, never
double-counted. This still satisfies SC-006 (zero duplicated, zero lost
units); it is only not maximally efficient in that one interrupted case.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field

import httpx

from agents.adjudicator.agent import AdjudicatorAgent, build_adjudication_result
from agents.adjudicator.node import adjudicator_node
from agents.assessor.agent import AssessorAgent
from agents.assessor.node import assessor_node
from core.llm_factory import ModelProvider
from shared.state.schemas import PortalInput, QuestionInput, RetryAddendum
from shared.config.settings import Settings
from shared.state import unit_state
from shared.state.entities import (
    AgentRunState,
    AssessorAgentRun,
    DiscrepancyCase,
    EscalationQueueItem,
    EscalationReason,
    Question,
    TargetPortal,
    UnitState,
    new_id,
)
from shared.state.resume import remaining_work
from shared.tools.linkresolution.chain import resolve_link
from orchestration.routers.retry_loops import (
    _describe_disagreement,
    materialize_evidence_artifact,
    run_adjudication_retry_loop,
    run_validation_retry_loop,
)
from shared.persistence.repositories import Repository
from shared.tools.browser import BrowserSession
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.langsmith_tracing import safe_trace, unit_trace
from core.telemetry.stage_events import StageEventLog



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
    def unassessable(self) -> int:
        return sum(1 for o in self.outcomes if o.final_state == UnitState.UNASSESSABLE)

    @property
    def in_progress(self) -> int:
        return len(self.outcomes) - self.delivered - self.escalated - self.unassessable


async def run_batch(
    *,
    repo: Repository,
    settings: Settings,
    session_id: str,
    provider: ModelProvider,
    browser: BrowserSession,
    http_client: httpx.AsyncClient,
    fetch_log: FetchLog,
    stage_log: StageEventLog,
    cost_ledger: CostLedger,
    capture_dir: str,
    questions: list[Question],
    portals: list[TargetPortal],
    adjudicate_results: bool = True,
) -> BatchRunSummary:
    summary = BatchRunSummary()
    semaphore = asyncio.Semaphore(max(1, settings.batch_size))
    units = [(q, p) for p in portals for q in questions]

    async def bounded(question: Question, portal: TargetPortal) -> None:
        async with semaphore:
            outcome = await process_unit(
                repo=repo, settings=settings, session_id=session_id, provider=provider,
                browser=browser, http_client=http_client, fetch_log=fetch_log,
                stage_log=stage_log, cost_ledger=cost_ledger, capture_dir=capture_dir,
                question=question, portal=portal, adjudicate_results=adjudicate_results,
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
    http_client: httpx.AsyncClient,
    fetch_log: FetchLog,
    stage_log: StageEventLog,
    cost_ledger: CostLedger,
    capture_dir: str,
    question: Question,
    portal: TargetPortal,
    adjudicate_results: bool = True,
) -> UnitOutcome:
    """Runs (or resumes) exactly one question x portal unit end to end."""
    portal_id = portal.portal_id
    question_dict = {
        "question_id": question.question_id,
        "text": question.text,
        "answer_type": question.answer_type.value,
        "evidence_locus": question.evidence_locus.value,
    }

    existing = repo.get_unit(session_id, question.question_id, portal_id)
    unit_data: dict = existing or {}
    current_state = UnitState(existing["state"]) if existing else UnitState.PENDING

    if unit_state.is_terminal(current_state):
        return UnitOutcome(question.question_id, portal_id, current_state, "already terminal")

    def advance(to_state: UnitState, data: dict) -> None:
        """Persists `data` under `to_state`. Validates the transition only
        when it actually changes state -- re-persisting updated `data` under
        the SAME state (e.g. recording `language_checked` while remaining
        RESOLVED) is not itself a state transition and must not be checked
        as one, since `unit_state._ALLOWED` never lists a state as its own
        successor."""
        if to_state != current_state_ref[0]:
            unit_state.transition(current_state_ref[0], to_state)
        repo.upsert_unit(session_id, question.question_id, portal_id, to_state.value, data)
        current_state_ref[0] = to_state

    # Mutable box so the `advance` closure can track the in-flight state
    # across this function without every call site re-threading it.
    current_state_ref = [current_state]

    # LangSmith tracing (FR-T-001, FR-T-008): root trace for process_unit
    async with unit_trace(session_id, question.question_id, portal_id, question.text, unit_data.get("resolved_url", "")) as root_run:
        async def escalate(reason: EscalationReason, context: dict, to_state: UnitState = UnitState.ESCALATED) -> UnitOutcome:
            advance(to_state, {**unit_data, "escalation_reason": reason.value, **context})
            repo.insert_escalation(
                EscalationQueueItem(
                    item_id=new_id("esc"), session_id=session_id, reason=reason, context=context,
                    question_id=question.question_id, portal_id=portal_id,
                )
            )
            outcome = UnitOutcome(question.question_id, portal_id, to_state, reason.value)
            root_run.patch(metadata={"escalation_reason": reason.value}, outputs={"outcome": outcome.final_state.value, "detail": outcome.detail})
            return outcome

        # --- Link resolution (FR-001–FR-007) ---------------------------------
        if current_state_ref[0] == UnitState.PENDING:
            advance(UnitState.RESOLVING_LINK, unit_data)

        if current_state_ref[0] == UnitState.RESOLVING_LINK and not unit_data.get("resolved_url"):
            # LangSmith tracing (FR-T-002): url_resolution child span
            async with safe_trace("url_resolution", run_type="chain", inputs={"question_id": question.question_id, "portal_id": portal_id}) as url_span:
                with stage_log.timed("url_resolution", {"question_id": question.question_id, "portal_id": portal_id}):
                    result = await resolve_link(
                        repo, http_client, question.question_id, portal.country_id,
                        f"{portal.country_id} government portal: {question.text}", settings,
                    )
                url_span.patch(outputs={
                    "resolved_url": result.resolved_url,
                    "supplying_source": result.supplying_source.value if result.supplying_source else None,
                    "usable": result.resolved_url is not None,
                })
            unit_data["resolution_history"] = [
                {
                    "source": a.source.value, "order": a.order, "returned": a.returned,
                    "usable": a.usable, "rejection_reason": a.rejection_reason,
                }
                for a in result.history
            ]
            if result.resolved_url is None:
                return await escalate(
                    EscalationReason.NO_USABLE_URL,
                    {"resolution_history": unit_data["resolution_history"]},
                    to_state=UnitState.UNASSESSABLE,
                )
            unit_data["resolved_url"] = result.resolved_url
            unit_data["supplying_source"] = result.supplying_source.value if result.supplying_source else None
            advance(UnitState.RESOLVED, unit_data)

        resolved_url = unit_data["resolved_url"]

        # FR-107: flagged questions never reach an agent at all.
        if current_state_ref[0] == UnitState.RESOLVED and question.requires_authenticated_access:
            return await escalate(
                EscalationReason.REQUIRES_AUTHENTICATED_ACCESS,
                {"reason": "question is flagged requires_authenticated_access (FR-107)"},
            )

    # --- Independent assessment (FR-008–FR-013, FR-076–FR-091) ------------
    round_number = unit_data.get("round_number", 1)

    if current_state_ref[0] == UnitState.RESOLVED:
        round_number = 1
        unit_data["round_number"] = round_number
        advance(UnitState.ASSESSING, unit_data)

    # Whether resuming mid-ASSESSING (round 1) or mid-ADJUDICATING (see
    # module docstring re: round bookkeeping), the recovery is identical:
    # re-derive what's missing for `round_number` from recorded agent runs.
    existing_runs = repo.list_agent_runs(session_id, question.question_id, portal_id, round_number=round_number)
    plan = remaining_work(UnitState.ASSESSING, existing_runs, settings.assessor_agent_count)
    dispatch_indices = plan.agents_to_dispatch
    retained_runs: list[AssessorAgentRun] = [r for r in existing_runs if r.run_id in plan.retained_run_ids]

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
            assessor_state, agent_index, this_round, assessor_agent,
            settings=settings, fetch_log=fetch_log, stage_log=stage_log,
            cost_ledger=cost_ledger, capture_dir=capture_dir,
        )
        initial_evidence = materialize_evidence_artifact(initial_run)
        if initial_evidence:
            repo.insert_evidence(initial_evidence)
            initial_run.evidence_artifact_id = initial_evidence.artifact_id
        repo.insert_agent_run(initial_run)

        loop_result = await run_validation_retry_loop(
            session_id=session_id, question=question_dict, portal_url=resolved_url,
            agent_index=agent_index, round_number=this_round, settings=settings,
            provider=provider, browser=browser, fetch_log=fetch_log, stage_log=stage_log,
            cost_ledger=cost_ledger, capture_dir=capture_dir, initial_run=initial_run,
            initial_evidence=initial_evidence, portal_id=portal_id,
        )

        for i, run in enumerate(loop_result.attempted_runs):
            if i == 0:
                continue  # already persisted above
            evidence = materialize_evidence_artifact(run)
            if evidence:
                repo.insert_evidence(evidence)
                run.evidence_artifact_id = evidence.artifact_id
            repo.insert_agent_run(run)
        for validation in loop_result.attempted_validations:
            repo.insert_validation_result(validation)

        repo.insert_agent_run(loop_result.final_run)  # persist final state (upsert on run_id)
        return loop_result.final_run

    new_runs = list(
        await asyncio.gather(*(run_one_agent(i, round_number, None) for i in dispatch_indices))
    ) if dispatch_indices else []
    all_runs = retained_runs + new_runs

    # --- Language support check (FR-015 replacement) -----------------------
    # Each assessor already reads the page to answer the question, so it
    # reports the language it observed as part of that same structured
    # response (no separate detection call, no python language-ID package).
    # The LLM reports the truth; this comparison against the configured
    # allow-list is the only place policy is applied. Independent agents
    # occasionally disagree on a marginal read, so the majority reported
    # language decides -- one outlier agent cannot flip the unit's outcome.
    reported_languages = [r.detected_language for r in all_runs if r.detected_language]
    if reported_languages:
        language_counts = Counter(reported_languages)
        majority_language, _ = language_counts.most_common(1)[0]
        if majority_language not in settings.supported_languages:
            return await escalate(
                EscalationReason.LANGUAGE_NOT_SUPPORTED,
                {
                    "detected_language": majority_language,
                    "reported_languages": dict(language_counts),
                    "supported_languages": settings.supported_languages,
                },
            )

    validated_runs = [r for r in all_runs if r.state == AgentRunState.VALIDATED_PASS]

    if len(validated_runs) < 2:
        if all_runs and all(r.auth_boundary_observed for r in all_runs):
            return await escalate(
                EscalationReason.REQUIRES_AUTHENTICATED_ACCESS,
                {"reason": "every independent agent observed an authentication boundary"},
            )
        return await escalate(
            EscalationReason.UNVERIFIABLE_TARGET,
            {"validated_run_count": len(validated_runs), "total_run_count": len(all_runs)},
        )

    if not adjudicate_results:
        outcome = UnitOutcome(question.question_id, portal_id, UnitState.ASSESSING, "assessed only (--no-adjudicate)")
        root_run.patch(outputs={"outcome": outcome.final_state.value, "detail": outcome.detail})
        return outcome

    # --- Adjudication (FR-027–FR-034) --------------------------------------
    advance(UnitState.ADJUDICATING, unit_data)

    loop_result = await run_adjudication_retry_loop(
        session_id=session_id, question=question_dict, portal_url=resolved_url, settings=settings,
        stage_log=stage_log, validated_runs=validated_runs, starting_round=round_number,
        run_full_agent_and_validation_loop=run_one_agent, portal_id=portal_id,
    )

    # Persist the full audit trail across every round attempted (FR-061),
    # not just the final one -- the retry loop itself only returns the last.
    adjudicator_agent = AdjudicatorAgent()
    for i, round_runs in enumerate(loop_result.all_round_runs):
        decision = await adjudicator_node(
            {"validated_runs": round_runs}, adjudicator_agent,
            per_question_confidence_threshold=settings.per_question_confidence_threshold,
        )
        result = build_adjudication_result(
            session_id, question.question_id, portal_id, round_number + i,
            round_runs, decision, settings.confidence_acceptance_threshold,
        )
        repo.insert_adjudication_result(result)

    if loop_result.escalated:
        repo.insert_discrepancy_case(
            DiscrepancyCase(
                case_id=new_id("disc"), scope="question", session_id=session_id,
                question_id=question.question_id, portal_id=portal_id,
                points_of_disagreement=_describe_disagreement(loop_result.all_round_runs[-1]),
                retry_count=loop_result.retry_count,
                thresholds_in_force={
                    "per_question_confidence_threshold": settings.per_question_confidence_threshold,
                    "adjudication_retry_limit": settings.adjudication_retry_limit,
                },
                outcome="escalated",
            )
        )
        return await escalate(
            EscalationReason.UNRESOLVED_DISAGREEMENT,
            {
                "flag_reason": loop_result.final_decision.flag_reason,
                "max_pairwise_confidence_delta": loop_result.final_decision.max_pairwise_confidence_delta,
                "retry_count": loop_result.retry_count,
            },
        )

    unit_data["consensus_answer"] = loop_result.final_decision.consensus_answer
    unit_data["consensus_confidence"] = loop_result.final_decision.consensus_confidence
    advance(UnitState.DELIVERED, unit_data)
    outcome = UnitOutcome(question.question_id, portal_id, UnitState.DELIVERED, "delivered")
    root_run.patch(outputs={"outcome": outcome.final_state.value, "detail": outcome.detail})
    return outcome



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


