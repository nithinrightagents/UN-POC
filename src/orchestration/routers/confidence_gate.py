"""Confidence acceptance gate orchestration (FR-134–FR-139).

Applied after the agent completes and BEFORE validation -- a doomed
low-confidence output does not consume a Validator fetch against the
shared per-domain budget (FR-089) before the gate has had a chance to
improve it.

Wraps an `assess_once(addendum) -> AssessorAgentOutput` callback so this
module has no dependency on the model provider or the browser; it owns
only the retry decision, the addendum content, and the retry counter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from shared.state.schemas import AssessorAgentOutput, RetryAddendum
from shared.state.confidence import evaluate_confidence_gate
from core.telemetry.langsmith_tracing import confidence_gate_trace


AssessOnce = Callable[[RetryAddendum | None], Awaitable[AssessorAgentOutput]]


@dataclass
class ConfidenceGateOutcome:
    output: AssessorAgentOutput
    confidence_retry_count: int
    below_acceptance_threshold: bool


async def run_with_confidence_gate(
    assess_once: AssessOnce,
    threshold: int,
    retry_limit: int,
) -> ConfidenceGateOutcome:
    """FR-134: >= threshold -> proceed unchanged.
    FR-135/FR-137: < threshold, retries remain -> re-run with a
        seek-better-evidence addendum (never a demand for a higher number).
    FR-138: still below after the limit -> admit unchanged, marked low
        confidence. Never escalate on this basis alone.
    """
    addendum: RetryAddendum | None = None
    retry_count = 0

    while True:
        # LangSmith tracing (FR-T-002, FR-T-004): confidence_gate_attempt child span
        async with confidence_gate_trace(
            retry_count,
            has_addendum=addendum is not None,
            addendum_kind=addendum.kind if addendum else None,
        ) as gate_span:
            output = await assess_once(addendum)
            gate_span.patch(outputs={"confidence": output.confidence, "auth_boundary_observed": output.auth_boundary_observed})

        # An authentication boundary means no answer was formed at all (A5) --
        # the confidence gate has nothing to evaluate; pass it straight through.
        # Likewise a portal_unreachable fetch failure -- retrying assess_once
        # re-fetches the same dead URL and will not change the outcome; the
        # scheduler's link-resolution fallback is the mechanism that can help.
        if output.auth_boundary_observed or output.portal_unreachable:
            return ConfidenceGateOutcome(
                output=output, confidence_retry_count=retry_count, below_acceptance_threshold=False
            )

        # Evidence-location failure: the agent quoted text it believed was on
        # the page, but the live re-search of the page (search_by_text)
        # couldn't find it verbatim, so `evidence` came back None even though
        # answer/confidence/justification were populated normally. Delivering
        # this as-is guarantees a Validator Check-1 rejection ("required
        # evidence component missing") without the Validator's judgment call
        # ever running -- silently burning a full validation retry on
        # something catchable right here. Retry with a targeted addendum
        # instead, while retries remain; on exhaustion fall through unchanged
        # (identical to today's behavior) rather than looping forever.
        if (
            output.evidence is None
            and output.raw_evidence_quote
            and output.evidence_located is False
            and retry_count < retry_limit
        ):
            addendum = RetryAddendum(
                kind="validation_gaps",
                items=[
                    f'Your quoted evidence ("{output.raw_evidence_quote}") could not be '
                    "located verbatim on the page. Copy the exact text, in the same words "
                    "and order, from a SINGLE contiguous span in PAGE CONTENT -- do not "
                    "paraphrase, summarize, or combine text from two different parts of "
                    "the page."
                ],
            )
            retry_count += 1
            continue

        # A calibrated negative (No) answer is hard-capped at confidence <= 60
        # by the agent's own negative-anchor calibration (agent.py), which
        # sits below any reasonable acceptance threshold by construction --
        # gating it the same way as a positive answer forced every single No
        # through a retry it could never pass, doubling fetch/model cost on
        # what is typically the majority answer across a real questionnaire.
        if output.answer is False:
            return ConfidenceGateOutcome(
                output=output,
                confidence_retry_count=retry_count,
                below_acceptance_threshold=output.confidence < threshold,
            )

        gate = evaluate_confidence_gate(output.confidence, threshold, retry_count, retry_limit)

        if gate.accepted:
            below = output.confidence < threshold
            return ConfidenceGateOutcome(
                output=output, confidence_retry_count=retry_count, below_acceptance_threshold=below
            )

        # should_retry
        addendum = build_confidence_retry_addendum(output.confidence, threshold)
        retry_count += 1



def build_confidence_retry_addendum(confidence: int, threshold: int) -> RetryAddendum:
    """FR-136: directs the agent to seek better evidence. Never requests or
    suggests a specific higher confidence value."""
    return RetryAddendum(
        kind="seek_better_evidence",
        items=[
            f"Your reported confidence was {confidence}, below the {threshold} "
            "acceptance threshold. Look for more specific or more authoritative "
            "evidence on this page. Do not simply report a higher number -- your "
            "confidence must continue to reflect only what the evidence supports."
        ],
    )
