"""General-purpose PDF ingestion for admin-uploaded custom indicators.

Generalizes the regex-based What/Why/How extraction originally used to
manually build the UN OSI/LOSI master questionnaires (see
src/data/extract_modules.py -- a one-off script hardcoded against known
slide indices and titles for those specific files) into a reusable parser
for any admin-uploaded PDF that follows the same slide layout, with no
prior knowledge of the document's contents required.

Nothing here writes a live Question. Every extracted candidate is staged
as a PendingIndicator for an admin to review, edit, and explicitly approve
or reject -- see admin.py's /indicators/upload and /indicators/review
routes, which are the only callers.
"""

from __future__ import annotations

import io
import re

import pypdf

_LIGATURES = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
}


def clean_text(text: str) -> str:
    """Normalize whitespace, ligatures, and typographic quotes/dashes."""
    if not text:
        return ""
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text).strip()
    return text


_WHAT_RE = re.compile(r"What\s+(.*?)(?=Why|How\?|Case Examples|Check out|Submit your case|$)", re.DOTALL)
_WHY_RE = re.compile(r"Why\s+(.*?)(?=How\?|Case Examples|Check out|Submit your case|$)", re.DOTALL)
_HOW_RE = re.compile(
    r"How\?\s*(?:Indicative [sS]teps:?)?\s*(.*?)(?=Case Examples|Check out|Submit your case|$)", re.DOTALL,
)
_CASES_RE = re.compile(r"Case Examples\s+(.*?)(?=Check out|Submit your case|$)", re.DOTALL)
_CHECK_OUT_RE = re.compile(r"Check out\s+(.*?)(?=Case Examples|Submit your case|$)", re.DOTALL)
_CODE_RE = re.compile(r"#\s*(\d+[a-z]?)")


def _derive_title(text: str, fallback: str) -> str:
    """Best-effort title: whatever precedes the "What" section, with leading
    numbering and indicator codes stripped. Falls back to a generic label
    when a page doesn't carry a clean title line (rare, but the layout is
    hand-authored slide-to-slide across source decks)."""
    head_m = re.match(r"^\s*(.*?)(?=\bWhat\b)", text, re.DOTALL)
    head = head_m.group(1).strip() if head_m else ""
    head = re.sub(r"^\d+\.\s*", "", head)
    head = re.sub(r"#\s*\d+[a-z]?", "", head).strip(" -–—:")
    return head or fallback


def extract_candidate_indicators(
    pdf_bytes: bytes, module_name: str, prefix: str, evidence_locus: str,
) -> list[dict]:
    """Parse every page in an uploaded PDF that follows the What/Why/How
    (/Case Examples/Check out) indicator-slide layout, returning one
    candidate dict per matching page. Pages that don't match (cover slides,
    section dividers, an "Indicator Description" key page) are silently
    skipped -- the same tolerance the original manual extraction used.

    Raises ValueError if the file isn't a readable PDF; returns an empty
    list (not an error) if it's readable but no page matches the layout,
    since that's a legitimate "wrong document" signal for the caller to
    surface to the admin rather than a crash."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    except Exception as exc:
        raise ValueError(f"Could not read PDF: {exc}") from exc

    candidates: list[dict] = []
    slide_idx = 0

    for page in reader.pages:
        raw_text = page.extract_text() or ""
        text = clean_text(raw_text)
        if "Indicator Description" in text or ("Indicator" in text[:60] and "Description" in text[:60]):
            continue
        if "What" not in text or "Why" not in text:
            continue

        slide_idx += 1
        what_m = _WHAT_RE.search(text)
        why_m = _WHY_RE.search(text)
        how_m = _HOW_RE.search(text)
        cases_m = _CASES_RE.search(text)
        check_out_m = _CHECK_OUT_RE.search(text)

        what_text = clean_text(what_m.group(1)) if what_m else ""
        why_text = clean_text(why_m.group(1)) if why_m else ""
        how_text = clean_text(how_m.group(1)) if how_m else ""
        case_text = clean_text(cases_m.group(1)) if cases_m else ""
        ref_text = clean_text(check_out_m.group(1)) if check_out_m else ""

        # This becomes the URL-path-safe suffix of question_id (via
        # compose_question_id) once approved -- deliberately never "#050"
        # (a literal "#" here would truncate every admin route built from
        # question_id at the browser, since it reads as a URL fragment).
        codes = _CODE_RE.findall(text)
        indicator_id = f"{prefix}-{codes[0]}" if codes else f"{prefix}-{slide_idx:03d}"
        title = _derive_title(text, f"{module_name} Indicator {slide_idx}")

        candidates.append({
            "module": module_name,
            "indicator_id": indicator_id,
            "title": title,
            "what": what_text,
            "why": why_text,
            "how_scoring_guidance": how_text,
            "benchmark_case": case_text,
            "reference_links": [ref_text] if ref_text else [],
            "evidence_locus": evidence_locus,
            "source_page": slide_idx,
        })

    return candidates
