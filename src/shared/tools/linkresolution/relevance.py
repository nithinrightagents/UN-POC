"""LLM-assisted semantic relevance judge for candidate search links (FR-121, spec 010 US3).

Replaces hand-tuned lexical scoring with a single targeted model call evaluating
semantic meaning against the questionnaire indicator.
"""

from dataclasses import dataclass
import json
from typing import Any


@dataclass(frozen=True)
class RelevanceJudgeResult:
    index: int | None
    status: str  # "chose" | "abstained" | "unavailable"
    reason: str | None = None
    confidence: float | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, RelevanceJudgeResult):
            return (self.index, self.status, self.reason) == (other.index, other.status, other.reason)
        if other is None:
            return self.index is None
        if isinstance(other, int):
            return self.index == other
        return False


async def choose_best(
    provider: Any,
    model: str,
    question: dict | Any,
    candidates: list[dict | Any],
) -> RelevanceJudgeResult:
    """Evaluates candidate search links semantically and returns a typed RelevanceJudgeResult.

    Carries:
    - index: 0-based index of winning candidate, or None
    - status: 'chose' | 'abstained' | 'unavailable'
    - reason: explanation of the choice or failure cause

    `question` provides `title` and `what` text.
    `candidates` provides a list of candidate items with `url`, `title`, and optional `snippet`.
    """
    if not provider or not candidates:
        return RelevanceJudgeResult(
            index=None,
            status="unavailable",
            reason="no provider or candidates provided",
        )

    # Extract question title and what
    if isinstance(question, dict):
        q_title = question.get("title") or question.get("text") or ""
        q_what = question.get("what") or ""
    else:
        q_title = getattr(question, "title", None) or getattr(question, "text", "") or ""
        q_what = getattr(question, "what", "") or ""

    candidates_formatted = []
    for idx, c in enumerate(candidates):
        if isinstance(c, dict):
            c_url = c.get("url", "")
            c_title = c.get("title", "")
            c_snippet = c.get("snippet", "")
        else:
            c_url = getattr(c, "url", "")
            c_title = getattr(c, "title", "")
            c_snippet = getattr(c, "snippet", "")
        snippet_part = f" - Snippet: {c_snippet}" if c_snippet else ""
        candidates_formatted.append(f"[{idx}] URL: {c_url}\n    Title: {c_title}{snippet_part}")

    candidates_block = "\n".join(candidates_formatted)

    prompt = (
        f"Question Title: {q_title}\n"
        f"What this indicator looks for: {q_what}\n\n"
        f"Candidate Links:\n{candidates_block}\n\n"
        "Evaluate which candidate link best and most directly answers the question.\n"
        "If a candidate directly provides the official page or service requested, choose its index.\n"
        "If NO candidate is relevant or all are irrelevant/unrelated pages, choose null.\n"
        "Return ONLY a JSON object: {\"index\": <number or null>, \"confidence\": <score 0.0 to 1.0>, \"reason\": \"<brief reason>\"}."
    )

    try:
        resp = await provider.generate(
            model=model,
            system_instruction="You are a strict semantic relevance judge for public government services. Return JSON only.",
            prompt=prompt,
            temperature=0.0,
        )
        text = (resp.text or "").strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        parsed = json.loads(text)
        if not isinstance(parsed, dict) or "index" not in parsed:
            return RelevanceJudgeResult(
                index=None,
                status="unavailable",
                reason=f"response missing 'index' key: {text[:100]}",
                confidence=None,
            )

        idx_val = parsed.get("index")
        raw_conf = parsed.get("confidence")
        conf_val = None
        if isinstance(raw_conf, (int, float)):
            conf_val = max(0.0, min(1.0, float(raw_conf)))

        expl = parsed.get("reason")

        if idx_val is None:
            return RelevanceJudgeResult(
                index=None,
                status="abstained",
                reason=expl or "model explicitly abstained (index is null)",
                confidence=conf_val if conf_val is not None else 0.0,
            )

        if isinstance(idx_val, int) and 0 <= idx_val < len(candidates):
            return RelevanceJudgeResult(
                index=idx_val,
                status="chose",
                reason=expl or f"model chose candidate [{idx_val}]",
                confidence=conf_val if conf_val is not None else 1.0,
            )

        return RelevanceJudgeResult(
            index=None,
            status="unavailable",
            reason=f"invalid candidate index returned: {idx_val} (candidates length: {len(candidates)})",
            confidence=None,
        )
    except Exception as exc:
        return RelevanceJudgeResult(
            index=None,
            status="unavailable",
            reason=f"exception during relevance judge call: {exc}",
            confidence=None,
        )

