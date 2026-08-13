"""The Assessor Agent (FR-008–FR-013, FR-108).

One independent evaluation of one question against one target portal.
Each call is structurally isolated: a fresh ModelProvider.generate() call
(fresh genai.Client, research R2) with no state shared across agent
indices, and each agent independently fetches the page itself rather than
sharing a centrally-fetched copy -- matching the crawl-volume assumption
in research R6 (N agent fetches per unit, on top of which verification
roughly doubles the total).

Divergence (research R7) is bound here: model, temperature, and prompt
profile are selected per `agent_index` from settings, so identically-
isolated agents still produce genuinely different reads of an ambiguous
page.
"""

from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from core.base_agent import BaseAgent
from orchestration.routers.confidence_gate import ConfidenceGateOutcome, run_with_confidence_gate
from shared.prompts.profiles import build_prompt
from core.llm_factory import ModelProvider, estimate_cost
from shared.state.schemas import (
    AssessorAgentInput,
    AssessorAgentOutput,
    ElementReferenceOutput,
    EvidenceOutput,
    RetryAddendum,
)
from shared.config.settings import Settings
from shared.state.entities import AgentRunState, AssessorAgentRun, new_id, utcnow
from shared.tools.boundaries import check_authentication_boundary
from shared.tools.browser import BrowserSession
from shared.tools.capture import capture_region
from shared.tools.element_ref import build_reference, search_by_text
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.langsmith_tracing import agent_trace
from core.telemetry.stage_events import StageEventLog


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "boolean"},
        "confidence": {"type": "integer"},
        "justification": {"type": "string"},
        "evidence_quote": {
            "type": "string",
            "description": "The exact short text snippet from the page that is the evidence, "
            "or empty string if the answer is negative (feature not found).",
        },
    },
    "required": ["answer", "confidence", "justification", "evidence_quote"],
}


class AuthenticationBoundaryDetected(Exception):
    """Raised internally, caught by run_assessor_agent -- not a pipeline error."""


async def run_assessor_agent(
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
    addendum: RetryAddendum | None = None,
    portal_id: str | None = None,
) -> AssessorAgentRun:
    """Runs one full Assessor Agent attempt (including the confidence gate's
    internal retries) and returns a persisted-ready AssessorAgentRun.

    `portal_url` is the live page fetched for this attempt. `portal_id` is
    the stable TargetPortal identity persisted on the resulting run (falls
    back to `portal_url` when omitted, for callers -- e.g. existing tests --
    that only deal with a single URL and have no separate stable id)."""

    model = settings.agent_models[agent_index]
    temperature = (
        settings.agent_temperatures[agent_index]
        if agent_index < len(settings.agent_temperatures)
        else 0.3
    )
    profile = (
        settings.agent_prompt_profiles[agent_index]
        if agent_index < len(settings.agent_prompt_profiles)
        else "literal"
    )

    unit_ref = {"question_id": question["question_id"], "portal_id": portal_url}

    # LangSmith tracing (FR-T-002, FR-T-005): assessor_agent child span
    async with agent_trace(agent_index, round_number, model, temperature, profile) as agent_span:
        async def assess_once(current_addendum: RetryAddendum | None) -> AssessorAgentOutput:
            with stage_log.timed("assessor_run", unit_ref, agent_index=agent_index, round_number=round_number):
                page_result, page = await browser.fetch(portal_url, "assessor_agent", fetch_log)

                if not page_result.reachable or page is None:
                    return AssessorAgentOutput(
                        answer=None,
                        confidence=0,
                        justification=f"Portal unreachable: {page_result.reason}",
                        evidence=None,
                        model_identity=f"vertexai/{model}",
                    )

                try:
                    boundary = check_authentication_boundary(page_result.final_url, page_result.html)
                    if boundary.is_authentication_boundary:
                        return AssessorAgentOutput(
                            answer=None,
                            confidence=0,
                            justification=f"Authentication boundary detected ({boundary.signal}): "
                            f"{boundary.detail}",
                            evidence=None,
                            auth_boundary_observed=True,
                            auth_boundary_url=page_result.final_url,
                            model_identity=f"vertexai/{model}",
                        )

                    page_text = BeautifulSoup(page_result.html, "html.parser").get_text(" ", strip=True)


                    prompt = build_prompt(
                        question_text=question["text"],
                        answer_type=question["answer_type"],
                        evidence_locus=question["evidence_locus"],
                        page_text=page_text,
                        profile=profile,
                        addendum=current_addendum.model_dump() if current_addendum else None,
                    )

                    response = await provider.generate(
                        model=model,
                        system_instruction="Respond with valid JSON matching the required schema only.",
                        prompt=prompt,
                        temperature=temperature,
                        response_schema=_RESPONSE_SCHEMA,
                    )
                    cost_ledger.record(
                        stage="assessor_run",
                        model_identity=response.model_identity,
                        input_units=response.input_tokens,
                        output_units=response.output_tokens,
                        cost=estimate_cost(response.model_identity, response.input_tokens, response.output_tokens),
                        agent_index=agent_index,
                    )

                    parsed = _parse_model_json(response.text)

                    evidence = None
                    if parsed.get("evidence_quote"):
                        located = await search_by_text(page, parsed["evidence_quote"])
                        if located:
                            ref = build_reference(located["css_path"], located["text"])
                            capture_ref = await capture_region(page, located["css_path"], capture_dir)
                            evidence = EvidenceOutput(
                                resolved_url=page_result.final_url,
                                capture_ref=capture_ref,
                                element_reference=ElementReferenceOutput(**ref.__dict__),
                                element_text=located["text"],
                            )

                    return AssessorAgentOutput(
                        answer=bool(parsed.get("answer", False)) if question["answer_type"] == "binary" else parsed.get("answer"),
                        confidence=max(0, min(100, int(parsed.get("confidence", 0)))),
                        justification=str(parsed.get("justification", "")),
                        evidence=evidence,
                        model_identity=response.model_identity,
                    )
                finally:
                    await browser.close_page(page)

        outcome: ConfidenceGateOutcome = await run_with_confidence_gate(
            assess_once, settings.confidence_acceptance_threshold, settings.confidence_retry_limit
        )

        output = outcome.output
        evidence_artifact_id = None  # bound by the caller once persisted via persistence layer

        run = AssessorAgentRun(
            run_id=new_id("run"),
            session_id=session_id,
            question_id=question["question_id"],
            portal_id=portal_id or portal_url,
            agent_index=agent_index,
            round_number=round_number,
            answer=output.answer,
            confidence=output.confidence,
            justification=output.justification,
            evidence_artifact_id=evidence_artifact_id,
            confidence_retry_count=outcome.confidence_retry_count,
            state=AgentRunState.ASSESSED,
            auth_boundary_observed=output.auth_boundary_observed,
            auth_boundary_url=output.auth_boundary_url,
            model_identity=output.model_identity,
            below_acceptance_threshold=outcome.below_acceptance_threshold,
        )
        # Stash the raw evidence output for the caller (persistence needs a
        # standalone EvidenceArtifact record + artifact_id before it can be
        # attached to `run`); see orchestration/scheduler.py.
        run._pending_evidence = output.evidence  # type: ignore[attr-defined]
        agent_span.patch(outputs={
            "answer": run.answer,
            "confidence": run.confidence,
            "state": run.state.value,
            "auth_boundary_observed": run.auth_boundary_observed,
        })
        return run



def _parse_model_json(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"answer": False, "confidence": 0, "justification": "Model output was not valid JSON.", "evidence_quote": ""}


class AssessorAgent(BaseAgent[AssessorAgentInput, AssessorAgentRun]):
    """Assessor Agent implementation."""

    def __init__(self, provider: ModelProvider = None, browser: BrowserSession = None, name: str = "AssessorAgent", description: str = ""):
        super().__init__(name=name, description=description or "Evaluates questions against target portals.")
        self.provider = provider
        self.browser = browser

    async def run(self, input_data: AssessorAgentInput, **kwargs) -> AssessorAgentRun:
        """Executes the assessor agent logic."""
        settings = kwargs["settings"]
        fetch_log = kwargs["fetch_log"]
        stage_log = kwargs["stage_log"]
        cost_ledger = kwargs["cost_ledger"]
        capture_dir = kwargs["capture_dir"]

        return await run_assessor_agent(
            session_id=input_data.session_id,
            question=input_data.question.model_dump(),
            portal_url=input_data.portal.resolved_url,
            agent_index=input_data.agent_index,
            round_number=input_data.round_number,
            settings=settings,
            provider=self.provider,
            browser=self.browser,
            fetch_log=fetch_log,
            stage_log=stage_log,
            cost_ledger=cost_ledger,
            capture_dir=capture_dir,
            addendum=input_data.addendum,
            portal_id=input_data.portal.portal_id,
        )

