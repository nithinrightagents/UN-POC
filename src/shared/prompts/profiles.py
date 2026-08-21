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
{rubric_section}
The page content follows. Locate the evidence, form your answer, and respond in the
required structured format including a numeric confidence (0-100) that reflects
ONLY the quality and authority of the evidence you found on THIS page -- not your
general belief about the country.

Calibrate confidence to how MUCH of the page actually supports the answer, not just
whether you found something quotable. Reserve 90-100 for substantial, specific,
unambiguous evidence (a dedicated section, a named feature, a working link you can
see leads exactly where the question asks). A single short heading, a page title
alone, a generic topic/hub page that merely seems adjacent to the question, or a
one-line snippet with no surrounding detail should score in the 30-65 range even
when your answer is otherwise confident -- the confidence measures the EVIDENCE's
weight, not your certainty in your own reasoning. Do not default to 100 out of
habit; a reviewer will independently judge whether the cited quote alone justifies
the score, and a high score resting on a thin quote will be rejected.

`evidence_quote` will be used to relocate your evidence on the live page, so it must
be copied VERBATIM (same words, same order, same casing where practical) from a
SINGLE contiguous run of text as it appears in PAGE CONTENT below -- do not combine,
paraphrase, or summarize text that came from two different parts of the page (e.g. a
heading plus a paragraph that does not immediately follow it) into one quote. Keep
quotes focused: roughly 40 words or fewer is enough in most cases, though a heading
immediately followed by its first sentence may be taken as a single span when you
need both to make the meaning clear. Your fuller reasoning belongs in `justification`,
not in the quote.

`justification` will be checked for consistency against `evidence_quote` alone -- an
independent reviewer sees ONLY the quote, not the rest of the page. Do not write
justifications that lean on page-wide context the quote doesn't contain (e.g. "the
page title and content show...", "mentioned multiple times", "other sections
confirm..."). If a fact matters to your reasoning, either fold it into the quote
(if it is a single contiguous span) or leave it out of the justification -- state
only what the quoted text itself establishes.

Avoid quoting numbers or values that look like they update live -- dataset/result
counters, visitor counts, "last updated" timestamps, dates, or anything else likely
to change between now and when this evidence is re-checked moments later. If a
stable label sits next to the volatile number (e.g. a heading like "Datasets" next
to a live count), quote the label alone rather than the label-plus-number -- the
label is what proves the feature exists, and re-verification will otherwise fail
through no fault of your reasoning simply because the number ticked over. This
still applies even when the label and number run together with no space or
punctuation between them (e.g. "Datasets1,234") -- quote only the leading
alphabetic portion ("Datasets") as your evidence_quote; a substring is enough
to relocate the element, you do not need the trailing digits.

`evidence_quote` is REQUIRED even when your answer is negative (feature not found).
Every answer, positive or negative, must be anchored to a specific point on the
page you actually examined -- never leave it empty. For a negative answer, quote
the most relevant heading, section title, or short passage on the page that is
closest to where this feature would appear if it existed (e.g. the section heading
under which you looked, or the page's main title if nothing more specific applies).
This proves you examined a real, locatable part of the page rather than reporting
absence with nothing to check it against.

You must also report `detected_language`: the ISO 639-1 two-letter code of the
language the PAGE CONTENT below is actually written in (not the language of this
question or these instructions). Report exactly what you observe on the page --
do not guess toward any particular language, and do not let it affect your answer
or confidence. Use "unknown" only if the page content is too sparse, garbled, or
non-linguistic (e.g. an error page) to identify a language at all.

{addendum_section}

{links_section}

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


def render_links_section(available_links: list[dict] | None) -> str:
    """One-hop navigation (2026-08-20 debugging pass, phase 1): several
    negatives turned out to be the model correctly reading a category/hub
    page ("Skole og uddannelse") one click above the specific service the
    question actually needed -- confirmed live across 7 of 25 questions in
    one run, all resolved via search to a plausible topic page rather than a
    wrong domain. `link_likely_wrong` was built to catch this and never
    fired once in 50 questions: asking the model to self-report "this page
    is wrong" gave it nothing concrete to act on. Handing it the same-domain
    links actually present on the page, and asking it to name ONE if the
    page is insufficient, gives it a concrete next step instead."""
    if not available_links:
        return (
            "No links were found on this page to follow. Always report "
            "`follow_link_index` as -1."
        )
    lines = [
        "AVAILABLE LINKS on this page (same domain). If the page content below "
        "does NOT contain enough information to answer this question "
        "confidently, and one of these links plausibly leads directly to the "
        "specific content the question needs (e.g. this page is a category or "
        "topic hub, and one link below leads to the specific service), report "
        "its number as `follow_link_index`. Otherwise report -1 -- including "
        "whenever you already found clear evidence for a Yes, or a confident, "
        "well-evidenced No, on THIS page. Never pick a link just because none "
        "seem perfect; -1 is always the safe default.",
        "",
    ]
    for i, link in enumerate(available_links):
        lines.append(f'{i}. "{link["text"]}" -> {link["href"]}')
    return "\n".join(lines)


_SIX_SECTORS = ("Health", "Education", "Employment", "Social Protection", "Environment", "Justice")


def _extract_target_sector(title: str | None) -> str | None:
    """Titles for 6-sector indicator variants end "<indicator> — <Sector>"
    (e.g. "Online services provision for six main sectors — Employment").
    Surfacing that sector as its own rubric line is redundant insurance
    alongside the sector-localized `what` text (extract_modules.py), not a
    substitute for it -- catches any question where sector-specific wording
    didn't make it into `what`."""
    if not title or "—" not in title:
        return None
    tail = title.rsplit("—", 1)[-1].strip()
    return tail if tail in _SIX_SECTORS else None


def render_rubric_section(
    title: str | None = None,
    what: str | None = None,
    why: str | None = None,
    criteria_for_yes: str | None = None,
    criteria_for_no: str | None = None,
    scoring_guidance: str | None = None,
    benchmark_case: str | None = None,
) -> str:
    """Renders the questionnaire's own scoring rubric (What/Why/How,
    acceptance criteria, a worked example) into the prompt. Without this,
    the model judged evidence against acceptance criteria it never saw --
    Question.text alone (a single truncated sentence) is not the rubric,
    it is a label for one."""
    lines: list[str] = []

    target_sector = _extract_target_sector(title)
    if target_sector:
        lines.append(
            f"TARGET SECTOR: {target_sector}. This question covers ONLY the "
            f"{target_sector} sector -- do not require or look for evidence "
            "covering any other sector, and do not answer No merely because "
            "other sectors are missing or a full six-sector list isn't present."
        )

    if what:
        lines.append(f"What this indicator looks for: {what}")
    if why:
        lines.append(f"Why it matters: {why}")
    if criteria_for_yes:
        lines.append(f"Criteria for a Yes answer: {criteria_for_yes}")
    if criteria_for_no:
        lines.append(f"Criteria for a No answer: {criteria_for_no}")
    if scoring_guidance:
        lines.append(f"Scoring guidance (indicative, not a strict checklist): {scoring_guidance}")
    if benchmark_case:
        lines.append(f"Reference example of qualifying evidence (from a different country): {benchmark_case}")

    # T034: Level-of-government rubric rule
    lines.append(
        "Level of government: Judge the level of government against the service, not the domain; "
        "a nationally-delivered service should be evidenced on a national government site; "
        "a service constitutionally delivered by states or municipalities (driving licences, "
        "vehicle registration, water and electricity billing, local property records) is "
        "correctly evidenced by a state or municipal portal, or by the national portal's page "
        "directing citizens to it; never answer No merely because the service is not run federally."
    )

    if not lines:
        return ""
    return "\n" + "\n".join(lines) + "\n"


def build_prompt(
    question_text: str,
    answer_type: str,
    evidence_locus: str,
    page_text: str,
    profile: str,
    addendum: dict | None = None,
    available_links: list[dict] | None = None,
    title: str | None = None,
    what: str | None = None,
    why: str | None = None,
    criteria_for_yes: str | None = None,
    criteria_for_no: str | None = None,
    scoring_guidance: str | None = None,
    benchmark_case: str | None = None,
) -> str:
    stance = PROMPT_PROFILES.get(profile, PROMPT_PROFILES["literal"])
    addendum_section = render_addendum(addendum)
    rubric_section = render_rubric_section(
        title, what, why, criteria_for_yes, criteria_for_no, scoring_guidance, benchmark_case
    )
    return _BASE_TEMPLATE.format(
        stance=stance,
        question_text=question_text,
        answer_type=answer_type,
        evidence_locus_note=evidence_locus_note(evidence_locus),
        rubric_section=rubric_section,
        addendum_section=addendum_section,
        links_section=render_links_section(available_links),
        page_text=page_text[:15000],  # bound prompt size
    )


def check_truncation(page_text: str, limit: int = 15000) -> tuple[bool, int]:
    """Check if page_text exceeds prompt length bound and return (is_truncated, excess_chars)."""
    if len(page_text) > limit:
        return True, len(page_text) - limit
    return False, 0
