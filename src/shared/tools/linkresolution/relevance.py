"""LLM-assisted semantic relevance judge for candidate search links (FR-121, spec 010 US3).

Replaces hand-tuned lexical scoring with a single targeted model call evaluating
semantic meaning against the questionnaire indicator.
"""

from __future__ import annotations

import json
from typing import Any


async def choose_best(
    provider: Any,
    model: str,
    question: dict | Any,
    candidates: list[dict | Any],
) -> int | None:
    """Evaluates candidate search links semantically and returns the 0-based index of the
    best matching candidate, or None if no candidate is relevant.

    `question` provides `title` and `what` text.
    `candidates` provides a list of candidate items with `url`, `title`, and optional `snippet`.
    """
    if not provider or not candidates:
        return None

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
        "Return ONLY a JSON object: {\"index\": <number>} or {\"index\": null}."
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
        idx_val = parsed.get("index")
        if isinstance(idx_val, int) and 0 <= idx_val < len(candidates):
            return idx_val
        return None
    except Exception:
        return None
