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

import re

from shared.state.entities import MSQDocument, new_id

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
            answer = " ".join(l.strip() for l in current_answer_lines if l.strip())
            sections.setdefault(current_section, []).append(
                {"question": current_question, "answer": answer}
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
