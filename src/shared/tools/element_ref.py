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
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    const target = needle.trim().toLowerCase();
    let node;
    while ((node = walker.nextNode())) {
        const text = (node.innerText || node.textContent || '').trim().toLowerCase();
        if (text && text.includes(target) && text.length < target.length * 3) {
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
            return { cssPath: cssPath(node), text: node.innerText || node.textContent || '' };
        }
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
