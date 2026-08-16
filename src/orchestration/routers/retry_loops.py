"""The three independently-tracked retry loops (FR-032, FR-084, FR-137).

Validation retries (this module, FR-080–FR-084): re-run ONE agent only,
with the specific gaps as an addendum, up to validation_retry_limit.
A validation retry never touches the adjudication counter (FR-084) and
never touches the confidence-retry counter (which lives entirely inside
confidence_gate.py and is already resolved before validation starts).

Adjudication retries (FR-030–FR-034): re-run every agent in the round with
an anonymised disagreement addendum, up to adjudication_retry_limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agents.adjudicator.agent import AdjudicationDecision, AdjudicatorAgent, build_adjudication_result
from agents.adjudicator.node import adjudicator_node
from core.llm_factory import ModelProvider
from shared.state.schemas import PortalInput, QuestionInput, RetryAddendum
from agents.validator.agent import ValidatorAgent
from agents.validator.node import validator_node
from shared.config.settings import Settings
from shared.state.entities import (
    AdjudicationResult,
    AgentRunState,
    AssessorAgentRun,
    ElementReference,
    EvidenceArtifact,
    ValidationResult,
    new_id,
    utcnow,
)
from shared.tools.browser import BrowserSession
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.langsmith_tracing import adjudication_trace, validation_trace
from core.telemetry.stage_events import StageEventLog



@dataclass
class ValidationLoopResult:
    final_run: AssessorAgentRun
    final_validation: ValidationResult
    final_evidence: EvidenceArtifact | None
    attempted_runs: list[AssessorAgentRun] = field(default_factory=list)
    attempted_validations: list[ValidationResult] = field(default_factory=list)


async def run_validation_retry_loop(
    *,
    session_id: str,
    question: dict,
    portal_url: str,
    agent_index: int,
    round_number: int,
    settings: Settings,
    provider: ModelProvider,
    browser: BrowserSession,
    fetch_log: FetchLog,
    stage_log: StageEventLog,
    cost_ledger: CostLedger,
    capture_dir: str,
    initial_run: AssessorAgentRun,
    initial_evidence: EvidenceArtifact | None,
    portal_id: str | None = None,
) -> ValidationLoopResult:
    """FR-081: the validation retry loop operates strictly per agent --
    retrying agent_index never touches any other agent's run."""
    # Deferred: agents.assessor.agent imports orchestration.routers.confidence_gate,
    # which would be a circular import if this were a top-level import here.
    from agents.assessor.agent import AssessorAgent
    from agents.assessor.node import assessor_node

    stable_portal_id = portal_id or portal_url

    assessor_agent = AssessorAgent(provider=provider, browser=browser)
    validator_agent = ValidatorAgent()

    current_run = initial_run
    current_evidence = initial_evidence
    attempted_runs = [current_run]
    attempted_validations: list[ValidationResult] = []
    retry_number = 0

    while True:
        element_ref = current_evidence.element_reference if current_evidence else None
        output = _run_output_from_agent_run(current_run, current_evidence)

        # LangSmith tracing (FR-T-002, FR-T-004): validation_attempt child span
        async with validation_trace(retry_number, agent_index, round_number) as val_span:
            with stage_log.timed(
                "validation", {"question_id": question["question_id"], "portal_id": stable_portal_id},
                agent_index=agent_index, round_number=round_number,
            ):
                validation = await validator_node(
                    {
                        "run_id": current_run.run_id,
                        "session_id": session_id,
                        "question_text": question["text"],
                        "output": output,
                        "element_reference": element_ref,
                        "retry_number": retry_number,
                    },
                    validator_agent,
                    settings=settings,
                    provider=provider,
                    browser=browser,
                    fetch_log=fetch_log,
                    cost_ledger=cost_ledger,
                )
            val_span.patch(outputs={
                "passed": validation.passed,
                "quality_score": validation.quality_score,
                "gaps_count": len(validation.gaps),
                "verification_outcome": validation.verification_outcome.value,
            })
        attempted_validations.append(validation)


        if validation.passed:
            current_run.state = AgentRunState.VALIDATED_PASS
            current_run.validation_retry_count = retry_number
            return ValidationLoopResult(
                final_run=current_run,
                final_validation=validation,
                final_evidence=current_evidence,
                attempted_runs=attempted_runs,
                attempted_validations=attempted_validations,
            )

        if retry_number >= settings.validation_retry_limit:
            # FR-082: not admitted to adjudication. Terminal.
            current_run.state = AgentRunState.VALIDATION_FAILED_TERMINAL
            current_run.validation_retry_count = retry_number
            return ValidationLoopResult(
                final_run=current_run,
                final_validation=validation,
                final_evidence=current_evidence,
                attempted_runs=attempted_runs,
                attempted_validations=attempted_validations,
            )

        # FR-080: re-run this agent only, with the gaps as an addendum.
        retry_number += 1
        addendum = RetryAddendum(kind="validation_gaps", items=validation.gaps)

        new_run = await assessor_node(
            {
                "session_id": session_id,
                "question": QuestionInput(**question),
                "portal": PortalInput(portal_id=stable_portal_id, resolved_url=portal_url),
                "addendum": addendum,
            },
            agent_index, round_number, assessor_agent,
            settings=settings, fetch_log=fetch_log, stage_log=stage_log,
            cost_ledger=cost_ledger, capture_dir=capture_dir,
        )
        new_run.validation_retry_count = retry_number
        current_run = new_run
        current_evidence = materialize_evidence_artifact(new_run)
        attempted_runs.append(current_run)


def materialize_evidence_artifact(run: AssessorAgentRun) -> EvidenceArtifact | None:
    """`run_assessor_agent` stashes the raw model-turn evidence as an
    EvidenceOutput (schemas.py) on `run._pending_evidence` -- a transient,
    not-yet-persisted shape. This converts it into a proper EvidenceArtifact
    domain entity with a fresh artifact_id, ready to insert and attach.
    Called both here (for retries) and by orchestration/scheduler.py (for
    the first attempt of every agent run)."""
    pending = getattr(run, "_pending_evidence", None)
    if pending is None:
        return None
    return EvidenceArtifact(
        artifact_id=new_id("ev"),
        resolved_url=pending.resolved_url,
        capture_ref=pending.capture_ref or "",
        element_reference=ElementReference(**pending.element_reference.model_dump())
        if pending.element_reference
        else ElementReference(css_path="", text_hash=""),
        element_text=pending.element_text,
        element_text_original_language=pending.element_text_original_language,
        element_text_translation=pending.element_text_translation,
        captured_at=utcnow(),
    )


def _run_output_from_agent_run(run: AssessorAgentRun, evidence: EvidenceArtifact | None):
    """Reconstruct an AssessorAgentOutput-shaped view for the Validator from
    a persisted-form AssessorAgentRun + its EvidenceArtifact."""
    from shared.state.schemas import AssessorAgentOutput, ElementReferenceOutput, EvidenceOutput

    evidence_output = None
    if evidence:
        evidence_output = EvidenceOutput(
            resolved_url=evidence.resolved_url,
            capture_ref=evidence.capture_ref,
            element_reference=ElementReferenceOutput(**evidence.element_reference.__dict__),
            element_text=evidence.element_text,
            element_text_original_language=evidence.element_text_original_language,
            element_text_translation=evidence.element_text_translation,
        )
    return AssessorAgentOutput(
        answer=run.answer,
        confidence=run.confidence or 0,
        justification=run.justification or "",
        evidence=evidence_output,
        auth_boundary_observed=run.auth_boundary_observed,
        auth_boundary_url=run.auth_boundary_url,
        model_identity=run.model_identity or "",
        detected_language=run.detected_language,
    )


# --- Adjudication retry loop (FR-030–FR-034) --------------------------------


@dataclass
class AdjudicationLoopResult:
    final_decision: AdjudicationDecision
    final_result: AdjudicationResult
    escalated: bool
    retry_count: int
    all_round_runs: list[list[AssessorAgentRun]] = field(default_factory=list)


async def run_adjudication_retry_loop(
    *,
    session_id: str,
    question: dict,
    portal_url: str,
    settings: Settings,
    stage_log: StageEventLog,
    validated_runs: list[AssessorAgentRun],
    starting_round: int,
    run_full_agent_and_validation_loop,
    portal_id: str | None = None,
) -> AdjudicationLoopResult:
    """FR-030: on a flagged discrepancy below the retry limit, re-run every
    agent in the round with an anonymised addendum. FR-033: still
    disagreeing at the limit -> escalate with every position from every
    round, no automatic consensus delivered.

    `run_full_agent_and_validation_loop(agent_index, round_number, addendum)`
    is injected by the caller (orchestration/scheduler.py), which closes
    over the provider/browser/fetch_log/cost_ledger/capture_dir this needs,
    since it must run BOTH the confidence gate and the validation retry
    loop per agent -- this module only owns the adjudication-level decision
    and retry count.
    """
    stable_portal_id = portal_id or portal_url
    current_runs = validated_runs
    round_number = starting_round
    retry_count = 0
    all_rounds = [current_runs]
    adjudicator_agent = AdjudicatorAgent()

    while True:
        # LangSmith tracing (FR-T-002, FR-T-004): adjudication child span
        async with adjudication_trace(round_number, is_retry=(retry_count > 0)) as adj_span:
            started = utcnow()
            decision = await adjudicator_node(
                {"validated_runs": current_runs}, adjudicator_agent,
                per_question_confidence_threshold=settings.per_question_confidence_threshold,
            )
            stage_log.record(
                "adjudication",
                {"question_id": question["question_id"], "portal_id": stable_portal_id},
                started_at=started,
                ended_at=utcnow(),
                round_number=round_number,
            )

            result = build_adjudication_result(
                session_id, question["question_id"], stable_portal_id, round_number,
                current_runs, decision, settings.confidence_acceptance_threshold,
            )
            adj_span.patch(outputs={
                "consensus_answer": decision.consensus_answer,
                "consensus_confidence": decision.consensus_confidence,
                "discrepancy_flagged": decision.discrepancy_flagged,
                "flag_reason": decision.flag_reason,
            })


        if not decision.discrepancy_flagged:
            return AdjudicationLoopResult(
                final_decision=decision, final_result=result, escalated=False,
                retry_count=retry_count, all_round_runs=all_rounds,
            )

        if retry_count >= settings.adjudication_retry_limit:
            # FR-033: escalate. No consensus answer delivered automatically.
            return AdjudicationLoopResult(
                final_decision=decision, final_result=result, escalated=True,
                retry_count=retry_count, all_round_runs=all_rounds,
            )

        # FR-030, FR-031: re-run every agent with an anonymised addendum.
        retry_count += 1
        round_number += 1
        disagreement_points = _describe_disagreement(current_runs)
        addendum = RetryAddendum(kind="disagreement_points", items=disagreement_points)

        new_runs = []
        for run in current_runs:
            new_run = await run_full_agent_and_validation_loop(run.agent_index, round_number, addendum)
            new_runs.append(new_run)

        current_runs = new_runs
        all_rounds.append(current_runs)


def _describe_disagreement(runs: list[AssessorAgentRun]) -> list[str]:
    """FR-031: describes WHAT differs, never WHO said what."""
    answers = sorted({str(r.answer) for r in runs})
    confidences = [r.confidence for r in runs if r.confidence is not None]
    points = []
    if len(answers) > 1:
        points.append(f"Independent assessments produced different answers: {', '.join(answers)}.")
    if confidences and (max(confidences) - min(confidences)) > 0:
        points.append(
            f"Confidence values ranged from {min(confidences)} to {max(confidences)}, "
            "suggesting the evidence strength was read differently."
        )
    return points or ["Independent assessments did not converge."]
