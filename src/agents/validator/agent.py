"""The Validator (FR-076–FR-091).

Evaluates exactly one Assessor Agent output at a time (FR-079) -- never
compares agents to each other, and never forms its own answer to the
question (FR-090, invariant V2). Judges the agent's work, not the question.

Combines two kinds of check:
  - Mechanical: is evidence present at all (FR-021), and is it
    independently locatable and text-matching on a live re-fetch (FR-086,
    via verification.py).
  - Judgment: does the evidence support the answer, is the justification
    consistent, is the stated confidence proportionate -- assessed by the
    Validator's own model call, which never sees another agent's output.
"""

from __future__ import annotations

import json
import re

from agents.validator.tools.evidence_verification import verify_with_retry
from core.base_agent import BaseAgent
from core.llm_factory import ModelProvider, estimate_cost
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from shared.config.settings import Settings
from shared.state.entities import (
    ElementReference,
    ValidationResult,
    VerificationOutcome,
    new_id,
)
from shared.state.schemas import AssessorAgentOutput
from shared.tools.browser import BrowserSession

_JUDGMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence_supports_answer": {"type": "boolean"},
        "justification_consistent": {"type": "boolean"},
        "confidence_proportionate": {"type": "boolean"},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["evidence_supports_answer", "justification_consistent", "confidence_proportionate", "gaps"],
}

_JUDGMENT_PROMPT = """You are a quality-assurance reviewer for an AI government-portal
assessment. You are NOT answering the question yourself -- you are checking whether
THIS agent's answer, justification, and cited evidence hang together coherently.

Question: {question_text}
Answer type: {answer_type} -- the system enforces this format; a correctly-typed
answer (e.g. a plain true/false for a "binary" answer type) is NEVER itself a gap,
even if the question's wording sounds like it asks to "identify" or "list"
something. Judge only whether the evidence and justification support THIS answer
value, not whether a different response shape would have been more descriptive.
Agent's answer: {answer}
Agent's stated confidence: {confidence}/100
Agent's justification: {justification}
Cited evidence text: {evidence_text}

Evaluation Rules:
- For Positive answers (answer = true): The cited evidence must be concrete text/content that proves the feature exists.
- For Negative answers (answer = false): Absence cannot be directly quoted; the assessor is required to cite the nearest relevant section heading or page title as an anchor showing where the search was conducted. For negative answers, evaluate whether this anchor location and the justification coherently support the negative finding on this page. A confidence score between 30 and 65 for an anchored negative finding is proportionate and expected.
- Heading sufficiency (T023): A section heading, navigation label, page title, or link text that directly names the feature IS sufficient evidence that the feature exists. Do NOT fail `evidence_supports_answer` or `confidence_proportionate` solely because the quote is a heading without surrounding body text. A heading such as "File Your Taxes Online" or "Apply for Benefits" unambiguously names the service; brevity is not a gap.

Assess:
1. Does the cited evidence (or anchor location for negative findings) support the stated answer?
2. Is the justification consistent with both the answer and the evidence?
3. Is the stated confidence proportionate to how strong this evidence actually is?

List any specific gaps you find (empty list if none). Do not state what the correct
answer to the question "should" be -- only judge the internal coherence of this
agent's own work.
"""


async def validate_agent_output(
    *,
    run_id: str,
    session_id: str,
    question_text: str,
    answer_type: str = "binary",
    output: AssessorAgentOutput,
    element_reference: ElementReference | None,
    settings: Settings,
    provider: ModelProvider,
    browser: BrowserSession,
    fetch_log: FetchLog,
    cost_ledger: CostLedger,
    retry_number: int,
) -> ValidationResult:
    gaps: list[str] = []

    # Check 1 (FR-021): every required evidence component present.
    if output.evidence is None or element_reference is None:
        gaps.append("required evidence component missing (element reference or text)")
        return ValidationResult(
            validation_id=new_id("val"),
            run_id=run_id,
            session_id=session_id,
            quality_score=0.0,
            gaps=gaps,
            passed=False,
            retry_number=retry_number,
            verification_outcome=VerificationOutcome.ELEMENT_ABSENT,
            verification_attempts=0,
        )

    # Check 2 (FR-086): independent live re-traversal and element location.
    verification_result, attempts = await verify_with_retry(
        browser,
        output.evidence.resolved_url,
        element_reference,
        output.evidence.element_text,
        fetch_log,
        settings.verification_attempt_bound,
        timeout_ms=settings.page_navigation_timeout_ms,
    )

    if verification_result.outcome == "target_unreachable":
        # FR-088: NOT a quality failure. Caller escalates as unverifiable target.
        return ValidationResult(
            validation_id=new_id("val"),
            run_id=run_id,
            session_id=session_id,
            quality_score=0.0,
            gaps=[],
            passed=False,
            retry_number=retry_number,
            verification_outcome=VerificationOutcome.TARGET_UNREACHABLE,
            verification_attempts=attempts,
        )

    if verification_result.outcome == "element_absent" and output.page_text_truncated:
        # The assessor's own page fetch exceeded the 15,000-char cutoff
        # (FR-LD-027) before this quote could have been read in full -- the
        # quote may simply sit past the truncation point, not have been
        # fabricated. Scoring this as a quality failure and burning retries
        # on a deterministically-truncated page cannot improve the outcome;
        # the caller treats this the same as target_unreachable above --
        # not a quality failure -- and stops retrying immediately.
        gaps.append(
            f"verification element_absent on truncated page ({output.page_text_excess_chars} chars past cutoff): "
            f"{verification_result.detail}"
        )
        return ValidationResult(
            validation_id=new_id("val"),
            run_id=run_id,
            session_id=session_id,
            quality_score=0.0,
            gaps=gaps,
            passed=False,
            retry_number=retry_number,
            verification_outcome=VerificationOutcome.TRUNCATED_UNVERIFIABLE,
            verification_attempts=attempts,
        )

    if verification_result.outcome in ("element_absent", "text_mismatch"):
        gaps.append(f"verification {verification_result.outcome}: {verification_result.detail}")
        return ValidationResult(
            validation_id=new_id("val"),
            run_id=run_id,
            session_id=session_id,
            quality_score=0.2,
            gaps=gaps,
            passed=False,
            retry_number=retry_number,
            verification_outcome=VerificationOutcome(verification_result.outcome),
            verification_attempts=attempts,
        )

    # Checks 3-5: judgment, via the Validator's own model. It sees only this
    # one agent's output (FR-079) and never forms its own answer (FR-090).
    prompt = _JUDGMENT_PROMPT.format(
        question_text=question_text,
        answer_type=answer_type,
        answer=output.answer,
        confidence=output.confidence,
        justification=output.justification,
        evidence_text=output.evidence.element_text,
    )
    response = await provider.generate(
        model=settings.validator_model,
        system_instruction="Respond with valid JSON matching the required schema only.",
        prompt=prompt,
        temperature=0.0,
        response_schema=_JUDGMENT_SCHEMA,
    )
    cost_ledger.record(
        stage="validation",
        model_identity=response.model_identity,
        input_units=response.input_tokens,
        output_units=response.output_tokens,
        cost=estimate_cost(response.model_identity, response.input_tokens, response.output_tokens),
    )

    judgment = _parse_judgment(response.text)
    gaps.extend(judgment.get("gaps", []))

    checks_passed = sum(
        [
            judgment.get("evidence_supports_answer", False),
            judgment.get("justification_consistent", False),
            judgment.get("confidence_proportionate", False),
        ]
    )
    quality_score = checks_passed / 3.0
    # quality_score is checks_passed/3: 1/3=0.333, 2/3=0.667, 3/3=1.0.
    # threshold=0.60 means two-of-three must pass; threshold=0.70 would require all three.
    passed = quality_score >= settings.validation_quality_threshold

    if not judgment.get("evidence_supports_answer", False):
        gaps.append("cited evidence does not clearly support the stated answer")
    if not judgment.get("justification_consistent", False):
        gaps.append("justification is not consistent with the answer and evidence")
    if not judgment.get("confidence_proportionate", False):
        gaps.append("stated confidence is not proportionate to the observed evidence quality")

    return ValidationResult(
        validation_id=new_id("val"),
        run_id=run_id,
        session_id=session_id,
        quality_score=quality_score,
        gaps=gaps,
        passed=passed,
        retry_number=retry_number,
        verification_outcome=VerificationOutcome.CONFIRMED,
        verification_attempts=attempts,
    )


def _parse_judgment(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {
            "evidence_supports_answer": False,
            "justification_consistent": False,
            "confidence_proportionate": False,
            "gaps": ["Validator model output was not valid JSON."],
        }


class ValidatorAgent(BaseAgent):
    """Validator Agent implementation."""

    def __init__(self, name: str = "ValidatorAgent", description: str = ""):
        super().__init__(name=name, description=description or "Validates Assessor Agent outputs.")

    async def run(self, input_data: dict, **kwargs) -> ValidationResult:
        """`input_data` carries the per-call state (what is being validated);
        `kwargs` carries the shared services (settings/provider/browser/
        fetch_log/cost_ledger), mirroring AssessorAgent.run's split."""
        return await validate_agent_output(
            run_id=input_data["run_id"],
            session_id=input_data["session_id"],
            question_text=input_data["question_text"],
            answer_type=input_data.get("answer_type", "binary"),
            output=input_data["output"],
            element_reference=input_data.get("element_reference"),
            retry_number=input_data.get("retry_number", 0),
            **kwargs,
        )

