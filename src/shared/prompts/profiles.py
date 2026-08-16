"""Versioned prompt profiles (research R7).

Two defensible evaluative stances, not two phrasings of one. Together with
model-tier and temperature divergence, these supply the variance
independence depends on (FR-011) -- structural session isolation alone is
necessary but not sufficient, since identically-configured isolated agents
still produce correlated output.
"""

from __future__ import annotations

PROFILE_VERSION = "v1"

_LITERAL = """You are an evidence-based government portal assessor. You answer ONLY
based on what is explicitly and unambiguously present on the page. If a feature or
piece of information is not directly visible or linked from the page you were given,
answer that it is absent -- do not infer its likely presence from context, general
knowledge about the country, or partial signals. Cite the specific page element that
supports your answer. Prefer stating "not found" over speculation."""

_INFERENTIAL = """You are a government portal assessor with domain expertise in
digital government practice. You may draw reasonable inferences from indirect
evidence -- for example, a link labelled with a ministry's name pointing to what is
clearly that ministry's domain counts as evidence of that ministry's presence, even
if the exact wording of the indicator is not repeated verbatim. Weigh the overall
context of the page, not just literal keyword matches. Still cite the specific
element your inference rests on, and lower your confidence in proportion to how much
inference the answer required."""

PROMPT_PROFILES: dict[str, str] = {
    "literal": _LITERAL,
    "inferential": _INFERENTIAL,
}

_BASE_TEMPLATE = """{stance}

You are evaluating this question against ONE specific government portal page.
Question: {question_text}
Answer type: {answer_type}
Evidence locus rule: {evidence_locus_note}

The page content follows. Locate the evidence, form your answer, and respond in the
required structured format including a numeric confidence (0-100) that reflects
ONLY the quality and authority of the evidence you found on THIS page -- not your
general belief about the country.

You must also report `detected_language`: the ISO 639-1 two-letter code of the
language the PAGE CONTENT below is actually written in (not the language of this
question or these instructions). Report exactly what you observe on the page --
do not guess toward any particular language, and do not let it affect your answer
or confidence. Use "unknown" only if the page content is too sparse, garbled, or
non-linguistic (e.g. an error page) to identify a language at all.

{addendum_section}

PAGE CONTENT:
{page_text}
"""


def evidence_locus_note(locus: str) -> str:
    if locus == "national_portal_only":
        return (
            "The evidence MUST be on this exact portal or its subdomains. If the "
            "feature exists elsewhere on the government web but not here, answer "
            "that it is absent from the portal."
        )
    return (
        "The evidence may be on this page, OR you may note that it would need to be "
        "found on another government domain -- but you were given this specific page "
        "to evaluate."
    )


def render_addendum(addendum: dict | None) -> str:
    if not addendum:
        return ""
    kind = addendum.get("kind")
    items = addendum.get("items", [])
    if not items:
        return ""
    bullets = "\n".join(f"- {i}" for i in items)

    if kind == "validation_gaps":
        return (
            "A previous attempt's evidence had these specific gaps -- address them "
            f"directly this time:\n{bullets}"
        )
    if kind == "disagreement_points":
        # FR-031: never attribute a position to an identified agent.
        return (
            "Other independent assessments of this same question disagreed on these "
            f"specific points. Re-examine the page carefully:\n{bullets}"
        )
    if kind == "seek_better_evidence":
        return (
            "Your previous confidence was low. Look for more specific or more "
            f"authoritative evidence on this page (never report a higher confidence "
            f"than what the evidence actually supports):\n{bullets}"
        )
    return ""


def build_prompt(
    question_text: str,
    answer_type: str,
    evidence_locus: str,
    page_text: str,
    profile: str,
    addendum: dict | None = None,
) -> str:
    stance = PROMPT_PROFILES.get(profile, PROMPT_PROFILES["literal"])
    addendum_section = render_addendum(addendum)
    return _BASE_TEMPLATE.format(
        stance=stance,
        question_text=question_text,
        answer_type=answer_type,
        evidence_locus_note=evidence_locus_note(evidence_locus),
        addendum_section=addendum_section,
        page_text=page_text[:15000],  # bound prompt size
    )
