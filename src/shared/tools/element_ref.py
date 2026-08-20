"""Composite durable element reference (research R5).

A bare XPath is brittle against DOM reshuffles and would inflate FR-087
quality failures with false positives. The composite reference -- CSS
path, normalized text hash, sibling index -- lets verification (FR-086)
distinguish "page reshuffled, evidence intact" from "element genuinely
absent", which the spec requires as separately-attributed outcomes.
"""

from __future__ import annotations

import hashlib
import re

from shared.state.entities import ElementReference


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:16]


def build_reference(css_path: str, element_text: str, sibling_index: int = 0) -> ElementReference:
    return ElementReference(
        css_path=css_path,
        text_hash=text_hash(element_text),
        sibling_index=sibling_index,
    )


# JS injected into the page to build a stable CSS path for an element and
# return {cssPath, text} for the first element matching a selector or
# containing given text.
_LOCATE_BY_SELECTOR_JS = """
(selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    function cssPath(e) {
        const parts = [];
        while (e && e.nodeType === 1 && e !== document.body) {
            let sel = e.tagName.toLowerCase();
            if (e.id) { sel += '#' + e.id; parts.unshift(sel); break; }
            let sib = e, nth = 1;
            while ((sib = sib.previousElementSibling)) {
                if (sib.tagName === e.tagName) nth++;
            }
            sel += `:nth-of-type(${nth})`;
            parts.unshift(sel);
            e = e.parentElement;
        }
        return parts.join(' > ');
    }
    return { cssPath: cssPath(el), text: el.innerText || el.textContent || '' };
}
"""

_SEARCH_BY_TEXT_JS = """
(needle) => {
    // The quote being searched for was read off a version of the page text
    // that was flattened by joining all text nodes with plain spaces (see
    // element_ref.normalize_text / the BeautifulSoup extraction the model's
    // prompt is built from). A live element's innerText instead renders
    // block-boundary line breaks as literal newlines (and uses non-breaking
    // spaces verbatim), so a raw substring check against unnormalized
    // innerText spuriously misses quotes that are visibly present but happen
    // to cross a block boundary. Collapsing all whitespace runs to a single
    // space before comparing -- matching normalize_text()'s \\s+ collapse on
    // the Python side -- makes the two representations comparable again.
    // A TreeWalker visits ancestors before their descendants (pre-order), so
    // returning the first node satisfying the substring+6x bound biases
    // toward the outermost qualifying wrapper -- often several nested divs
    // whose innerText is identical because each has only one child, plus
    // whichever ancestor first becomes "small enough" once the needle is
    // long. That ancestor choice depends on the needle's own length: a short
    // evidence_quote and the full captured element_text of the SAME element
    // can satisfy the bound at different tree depths, so searching by one
    // vs. the other can silently resolve to two different elements on an
    // otherwise-unchanged page (observed concretely on a real government
    // homepage: a short quote matched a precise 134-char div, while the
    // full captured text of that exact div, used as the needle again,
    // matched a 463-char outer wrapper instead -- a spurious text_mismatch
    // with nothing on the page actually having changed). Scanning every
    // candidate and keeping the SHORTEST match makes the result depend only
    // on what is actually the tightest element containing the text, not on
    // traversal order or needle length.
    //
    // The bound carries a flat +60-char allowance on top of the 6x multiple
    // (2026-08-20 debugging pass): a pure multiple punishes SHORT quotes
    // hardest, and short quotes are exactly what a negative answer's
    // fill_gap_reason guidance asks for (quote "the most relevant heading"
    // -- typically 2-4 words). A real heading is rarely alone in its
    // tightest wrapping element -- a nav label, skip-link, or breadcrumb
    // sharing that ancestor commonly pushes a 10-20 char quote's true
    // container to 80-150 combined chars with nothing wrong with the match.
    // Confirmed as the dominant cause of "required evidence component
    // missing" validator rejections in that pass's live run: evidence was
    // dropped entirely whenever this search returned null, even when the
    // model's quote was correct and genuinely on the page.
    const normalize = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    const target = normalize(needle);
    let node;
    let best = null;
    let bestText = null;
    while ((node = walker.nextNode())) {
        const text = normalize(node.innerText || node.textContent || '');
        if (text && text.includes(target) && text.length < target.length * 6 + 60) {
            if (best === null || text.length < bestText.length) {
                best = node;
                bestText = text;
            }
        }
    }
    if (best) {
        function cssPath(e) {
            const parts = [];
            while (e && e.nodeType === 1 && e !== document.body) {
                let sel = e.tagName.toLowerCase();
                if (e.id) { sel += '#' + e.id; parts.unshift(sel); break; }
                let sib = e, nth = 1;
                while ((sib = sib.previousElementSibling)) {
                    if (sib.tagName === e.tagName) nth++;
                }
                sel += `:nth-of-type(${nth})`;
                parts.unshift(sel);
                e = e.parentElement;
            }
            return parts.join(' > ');
        }
        return { cssPath: cssPath(best), text: best.innerText || best.textContent || '' };
    }
    return null;
}
"""


async def resolve_on_page(page, reference: ElementReference) -> dict | None:
    """Attempt to locate `reference` on a live Playwright Page. Resolution
    falls back from selector match to text-hash search across the document,
    per research R5's fallback design:

    - selector hit + text match -> confirmed
    - selector miss + text-hash match elsewhere -> confirmed, reshuffled
    - selector hit + text mismatch -> text_mismatch
    - both miss -> element_absent

    Returns {"outcome": ..., "css_path": ..., "text": ...} or None on total miss.
    """
    try:
        result = await page.evaluate(_LOCATE_BY_SELECTOR_JS, reference.css_path)
    except Exception:  # noqa: BLE001
        result = None

    if result:
        found_hash = text_hash(result["text"])
        if found_hash == reference.text_hash:
            return {"outcome": "confirmed", "css_path": result["cssPath"], "text": result["text"]}
        return {"outcome": "text_mismatch", "css_path": result["cssPath"], "text": result["text"]}

    # Selector missed entirely -- fall back to searching by the recorded text.
    # We don't have the original text (only its hash) once persisted, so the
    # caller must supply the expected text for this fallback; see verification.py.
    return None


async def search_by_text(page, expected_text: str) -> dict | None:
    try:
        result = await page.evaluate(_SEARCH_BY_TEXT_JS, expected_text)
    except Exception:  # noqa: BLE001
        result = None
    if result:
        return {"outcome": "confirmed", "css_path": result["cssPath"], "text": result["text"]}
    return None
