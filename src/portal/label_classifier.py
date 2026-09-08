"""Model boundary for disagreement labelling.

This is the sole model boundary for disagreement labelling. It takes a model provider
as an explicit parameter rather than constructing one.

CONSTITUTIONAL CONSTRAINT:
This module DOES NOT import `Prefill` and must never be made to.
The classifier evaluates assessor-vs-assessor discrepancies without awareness of
or comparison against any prior AI prefill ground truth (D3, FR-DL-037).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from shared.state.entities import (
    CLASSIFIER_LABELS,
    DisagreementLabel,
    HumanAssessorSubmission,
)

LABEL_PROMPT_VERSION = "dl-1"

# Contractual instruction properties (contracts/classifier-contract.md §5):
# 1. Never asks which answer is correct.
# 2. Defines the three substantive labels by their decision procedure in order:
#    - one_blocked: was one side prevented from reaching or accessing the source?
#    - different_content: did both access the source but saw/described different content?
#    - different_judgement: did both see the same content and judge it differently?
# 3. Makes not_enough_notes the REQUIRED answer under uncertainty.
# 4. Never refers to Assessor A or B, roles, or AI suggestions.
SYSTEM_INSTRUCTION = """You are an impartial analyst characterizing why two independent evaluators arrived at differing evaluations for an e-government indicator.

Your task is to classify the nature of the disagreement between Position 1 and Position 2.
You MUST NOT decide or express an opinion on which evaluator is correct or which answer is right.
Do not evaluate truth or quality. Characterize ONLY the relationship between the two positions.

Analyze the evidence URL and notes provided by both positions in the following order of decision procedure:

1. 'one_blocked': One evaluator was prevented from reaching or inspecting the source due to access barriers (such as a login wall, authentication prompt, geo-blocking, paywall, broken link, or technical obstacle), while the other evaluator accessed it.
2. 'different_content': Both evaluators reached the source, but they describe different content (e.g. content was updated between assessments, seasonal availability, dynamic elements, or they inspected different sections/pages of the same domain).
3. 'different_judgement': Both evaluators accessed and described the same content or evidence, but interpreted or judged it differently according to the indicator definition.
4. 'not_enough_notes': REQUIRED when notes are missing, brief, ambiguous, or too thin to establish with confidence whether one was blocked, saw different content, or judged differently. You MUST NOT guess among the other labels if the evidence is insufficient.

In addition, determine for each position whether the evaluator's own written notes directly contradict their chosen answer:
- position_1_notes_contradict_answer: true if Position 1's notes describe the opposite of their boolean answer.
- position_2_notes_contradict_answer: true if Position 2's notes describe the opposite of their boolean answer.

Provide a short, factual 1-sentence reason for your classification in 'reason'.
"""

CLASSIFIER_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": [
                "one_blocked",
                "different_content",
                "different_judgement",
                "not_enough_notes",
            ],
        },
        "reason": {"type": "string"},
        "position_1_notes_contradict_answer": {"type": "boolean"},
        "position_2_notes_contradict_answer": {"type": "boolean"},
    },
    "required": [
        "label",
        "reason",
        "position_1_notes_contradict_answer",
        "position_2_notes_contradict_answer",
    ],
}


@dataclass(frozen=True)
class PositionView:
    answer: bool
    evidence_url: str | None
    notes: str | None
    accepted_ai_suggestion: bool | None = None


@dataclass(frozen=True)
class ClassifierInput:
    indicator_text: str
    positions: tuple[PositionView, PositionView]  # content-ordered, role-free
    interval_seconds: int | None = None


@dataclass(frozen=True)
class ClassifierResult:
    label: DisagreementLabel
    stated_reason: str
    notes_contradict: tuple[bool, bool]  # (pos_1, pos_2)
    model_identity: str
    input_digest: str
    input_tokens: int
    output_tokens: int


def build_position_view(submission: HumanAssessorSubmission) -> PositionView:
    """Builds a PositionView from a HumanAssessorSubmission and NOTHING else.

    Does not read ai_suggested_answer, does not query Prefill.
    """
    ans = bool(submission.answer) if isinstance(submission.answer, (bool, int)) else submission.answer
    return PositionView(
        answer=ans,
        evidence_url=submission.evidence_url,
        notes=submission.notes if submission.notes is not None else "",
        accepted_ai_suggestion=submission.ai_suggestion_accepted,
    )


def order_positions(
    sub_a: HumanAssessorSubmission,
    sub_b: HumanAssessorSubmission,
) -> tuple[tuple[PositionView, PositionView], tuple[str, str]]:
    """Orders positions by (evidence_url or '', notes or '') ascending.

    Role never participates in ordering (FR-DL-038).
    Returns (positions_tuple, order_map) where order_map records ('A', 'B') or ('B', 'A').
    """
    pos_a = build_position_view(sub_a)
    pos_b = build_position_view(sub_b)

    key_a = (pos_a.evidence_url or "", pos_a.notes or "")
    key_b = (pos_b.evidence_url or "", pos_b.notes or "")

    if key_a <= key_b:
        return (pos_a, pos_b), ("A", "B")
    return (pos_b, pos_a), ("B", "A")


def compute_input_digest(payload_dict: dict[str, Any]) -> str:
    """Computes SHA-256 digest over canonical JSON with sorted keys and no whitespace."""
    canonical_json = json.dumps(
        payload_dict,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def render_classifier_payload(payload: ClassifierInput) -> dict[str, Any]:
    """Renders the canonical payload dictionary for the model and digest."""
    return {
        "prompt_version": LABEL_PROMPT_VERSION,
        "indicator_text": payload.indicator_text,
        "positions": [
            {
                "answer": p.answer,
                "evidence_url": p.evidence_url,
                "notes": p.notes,
                "accepted_ai_suggestion": p.accepted_ai_suggestion,
            }
            for p in payload.positions
        ],
        "interval_seconds": payload.interval_seconds,
    }



class ClassifierError(Exception):
    """Base exception for classifier errors."""
    pass


class SchemaRejectedError(ClassifierError):
    """Raised when the model returns a label outside CLASSIFIER_LABELS or invalid enum."""
    pass


class InvalidResponseError(ClassifierError):
    """Raised when the model response is malformed JSON or missing required keys."""
    pass


async def classify(
    provider: Any,
    settings: Any,
    payload: ClassifierInput,
) -> ClassifierResult:
    """Invokes the model provider to classify the discrepancy.

    Raises on provider failure or invalid response.
    Caller turns failures into labelling_attempts rows.
    """
    rendered = render_classifier_payload(payload)
    digest = compute_input_digest(rendered)
    prompt_text = json.dumps(rendered, indent=2, ensure_ascii=False)

    model = getattr(settings, "disagreement_label_model", "gemini-2.5-flash-lite")
    temperature = getattr(settings, "disagreement_label_temperature", 0.0)

    response = await provider.generate(
        prompt=prompt_text,
        model=model,
        system_instruction=SYSTEM_INSTRUCTION,
        response_schema=CLASSIFIER_RESPONSE_SCHEMA,
        temperature=temperature,
    )

    try:
        parsed = json.loads(response.text)
    except Exception as exc:
        raise InvalidResponseError(f"Unparseable response JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise InvalidResponseError(f"Response is not a JSON object: {parsed!r}")

    if "label" not in parsed:
        raise InvalidResponseError("Missing 'label' in classifier response")

    raw_label = parsed.get("label")
    try:
        label_enum = DisagreementLabel(raw_label)
    except Exception as exc:
        raise SchemaRejectedError(f"Label {raw_label!r} is not a valid DisagreementLabel: {exc}") from exc

    if label_enum not in CLASSIFIER_LABELS:
        raise SchemaRejectedError(f"Label {label_enum.value} is not in CLASSIFIER_LABELS")

    reason = str(parsed.get("reason", "")).strip()
    if not reason:
        raise InvalidResponseError("Missing or empty reason in classifier response")

    p1_contra = bool(parsed.get("position_1_notes_contradict_answer", False))
    p2_contra = bool(parsed.get("position_2_notes_contradict_answer", False))

    return ClassifierResult(
        label=label_enum,
        stated_reason=reason,
        notes_contradict=(p1_contra, p2_contra),
        model_identity=response.model_identity,
        input_digest=digest,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )
