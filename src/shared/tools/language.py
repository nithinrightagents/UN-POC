"""Primary language detection (FR-015).

A lightweight heuristic detector sufficient for the PoC's supported-language
gate (FR-016/FR-017). Checks the declared `<html lang>` attribute first,
falling back to a simple stopword-frequency heuristic over visible text.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

_STOPWORDS = {
    "en": {"the", "and", "of", "to", "in", "is", "for", "on", "that", "with"},
    "fr": {"le", "la", "de", "et", "les", "des", "en", "un", "une", "pour"},
    "es": {"el", "la", "de", "y", "los", "las", "en", "un", "una", "para"},
    "pt": {"o", "a", "de", "e", "os", "as", "em", "um", "uma", "para"},
    "zh": set(),  # detected separately via CJK character ratio
}


def detect_language(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    html_tag = soup.find("html")
    if html_tag and html_tag.get("lang"):
        lang = html_tag["lang"].split("-")[0].lower()
        if lang:
            return lang

    text = soup.get_text(" ", strip=True)

    cjk = len(re.findall(r"[一-鿿]", text))
    if cjk > 50:
        return "zh"

    words = re.findall(r"[a-zA-Z]+", text.lower())
    if not words:
        return "unknown"

    scores = {}
    wordset = set(words[:2000])
    for lang, stops in _STOPWORDS.items():
        if not stops:
            continue
        scores[lang] = len(wordset & stops)

    if not scores or max(scores.values()) == 0:
        return "en"  # default assumption for Latin-script pages with no stopword signal

    return max(scores, key=scores.get)
