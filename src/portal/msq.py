"""MSQ (Member State Questionnaire) ingestion (spec 005 Section 3.5).

Structural parse, not semantic: splits the questionnaire's own section
markers ("A. Institutional / Organizational Framework", "B. Crisis/Emergency
...") and its numbered question/answer rows, and pulls out every URL
mentioned. Confirmed against the real sample at
`understanding docs/Denmark - MS MSQ 2024.pdf`, which is a Microsoft Forms
export: each question label ends its line with "<label> * <N>." and the
answer follows as free text until the next such marker.

MSQ content never influences scoring (transcript Section 3) -- this is
purely reference context surfaced to assessors, so a noisy split (occasional
stray option lines like "Yes"/"No" folded into the wrong answer) is an
acceptable trade for staying inside the time budget; a human reads this, an
algorithm does not score it.
"""

from __future__ import annotations

import json
import re

from core.llm_factory import ModelProvider
from shared.state.entities import MSQDocument, MSQLinkCandidate, Question, new_id

_SECTION_RE = re.compile(r"^([A-G])\.\s+(.{3,120})$")
_QUESTION_RE = re.compile(r"^(.{3,300}?)\s*\*?\s*(\d{1,3})\.\s*$")
_URL_RE = re.compile(r"https?://[^\s\)\]\},;]+")
_NOISE_LINE_RE = re.compile(r"^\s*(Yes|No|Other|Anonymous.*|Time to complete.*|View results)\s*$", re.I)


def extract_pdf_text(pdf_path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_msq_text(raw_text: str) -> dict:
    """Returns {"sections": {title: [{"question": ..., "answer": ...}, ...]}, "urls": [...]}."""
    sections: dict[str, list[dict]] = {}
    current_section = "General"
    current_question: str | None = None
    current_answer_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_question, current_answer_lines
        if current_question is not None:
            answer = " ".join(line.strip() for line in current_answer_lines if line.strip())
            sections.setdefault(current_section, []).append(
                {
                    "question": current_question,
                    "answer": answer,
                    "urls": sorted(set(_URL_RE.findall(answer))),
                }
            )
        current_question = None
        current_answer_lines = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or "forms.office.com" in line.lower() or line.startswith("http") and "forms" in line.lower():
            continue
        if _NOISE_LINE_RE.match(line):
            continue

        section_match = _SECTION_RE.match(line)
        if section_match:
            _flush()
            current_section = f"{section_match.group(1)}. {section_match.group(2).strip()}"
            continue

        question_match = _QUESTION_RE.match(line)
        if question_match and len(question_match.group(1).strip()) > 5:
            _flush()
            current_question = question_match.group(1).strip().rstrip("*").strip()
            continue

        if current_question is not None:
            current_answer_lines.append(line)

    _flush()

    urls = sorted(set(_URL_RE.findall(raw_text)))
    return {"sections": sections, "urls": urls}


def ingest_msq_pdf(pdf_path: str, cycle_id: str, country_id: str, source_filename: str) -> MSQDocument:
    raw_text = extract_pdf_text(pdf_path)
    parsed = parse_msq_text(raw_text)
    return MSQDocument(
        msq_id=new_id("msq"),
        country_id=country_id,
        cycle_id=cycle_id,
        source_filename=source_filename,
        raw_text=raw_text,
        sections=parsed["sections"],
        extracted_urls=parsed["urls"],
    )


_MATCH_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "The exact question_id copied verbatim from the "
                        "bracketed [id] shown before each survey question below -- nothing "
                        "else, e.g. 'cycle-id:IF-010'. Never append the question's title or "
                        "text to it.",
                    },
                    "url": {
                        "type": "string",
                        "description": "One URL copied verbatim from the MSQ content above "
                        "that is directly relevant evidence for this question, or an empty "
                        "string if nothing above is relevant to it.",
                    },
                },
                "required": ["question_id", "url"],
            },
        },
    },
    "required": ["matches"],
}


async def match_msq_links(
    document: MSQDocument, questions: list[Question], provider: ModelProvider, model: str,
) -> list[MSQLinkCandidate]:
    """Structural MSQ parsing (see module docstring) never attributes a
    section/answer to a specific AIQ question_id -- this is the missing
    link. The full MSQ content (every question/answer entry that mentions at
    least one URL) is fed as context to the model alongside the full list of
    AIQ questions in a single call, and the model itself judges topical
    relevance -- no keyword-overlap heuristic. Best-effort, not authoritative.

    This is safe to be approximate because a wrong match is not a wrong
    answer: FR-124 still requires the resulting URL to be traversed live by
    the Assessor Agent, which only produces an answer from evidence it can
    actually quote off that live page -- a mismatched MSQ link just falls
    back to "no usable evidence here" like any other bad candidate would.
    """
    entries_with_urls = [
        entry
        for entries in document.sections.values()
        for entry in entries
        if entry.get("urls")
    ]
    if not entries_with_urls or not questions:
        return []

    all_urls = {url for entry in entries_with_urls for url in entry["urls"]}

    msq_context = "\n\n".join(
        f"Q: {entry['question']}\nA: {entry['answer']}\nURLs: {', '.join(entry['urls'])}"
        for entry in entries_with_urls
    )
    question_list = "\n".join(
        f"[{q.question_id}] {q.title or ''} — {q.text}" for q in questions
    )

    prompt = (
        "Below is the full content of a government's own submitted Member State "
        "Questionnaire (MSQ), limited to its question/answer entries that mention "
        "at least one URL:\n\n"
        f"{msq_context}\n\n"
        "Here is a list of survey questions we need evidence for. Each one starts "
        "with its id in square brackets, followed by its title and text:\n\n"
        f"{question_list}\n\n"
        "For each survey question, decide whether any single URL mentioned above is "
        "directly relevant, plausible evidence for that specific question -- judge by "
        "topic, not by shared words. Only include a match if you are reasonably "
        "confident the URL's topic matches the question's topic; otherwise omit that "
        "question or set url to an empty string. Never invent a URL that isn't printed "
        "above. For question_id, copy ONLY the bracketed id verbatim (e.g. 'cycle-id:"
        "IF-010') -- never append the question's title or text to it."
    )

    response = await provider.generate(
        model=model,
        system_instruction="Respond with valid JSON matching the required schema only.",
        prompt=prompt,
        temperature=0.0,
        response_schema=_MATCH_RESPONSE_SCHEMA,
    )

    try:
        parsed = json.loads(response.text)
    except json.JSONDecodeError:
        return []

    valid_question_ids = {q.question_id for q in questions}
    candidates: list[MSQLinkCandidate] = []
    for match in parsed.get("matches", []):
        question_id = match.get("question_id") or ""
        url = (match.get("url") or "").strip()
        if question_id not in valid_question_ids:
            # The model occasionally echoes back the id with the question's
            # title/text glued on after it (e.g. "cycle:IF-342: National ...").
            # Repair by taking the longest valid id that prefixes the string.
            prefix_matches = [qid for qid in valid_question_ids if question_id.startswith(qid)]
            if prefix_matches:
                question_id = max(prefix_matches, key=len)
        if not url or question_id not in valid_question_ids or url not in all_urls:
            continue
        candidates.append(
            MSQLinkCandidate(
                candidate_id=new_id("msqlink"),
                submission_id=document.msq_id,
                question_id=question_id,
                country_id=document.country_id,
                url=url,
            )
        )
    return candidates
