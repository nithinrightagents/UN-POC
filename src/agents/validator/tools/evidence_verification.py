"""Independent evidence verification (FR-086–FR-091).

The Validator re-fetches the resolved URL and attempts to locate the
referenced element using the durable reference the Assessor Agent
recorded -- it does not judge the captured artifact alone.

Outcome taxonomy (contracts/validator.md): `confirmed` / `element_absent` /
`text_mismatch` / `target_unreachable`. `target_unreachable` must never be
recorded as a quality failure (FR-088, SC-020); `element_absent` must never
be recorded as an unreachable target. Verification fetches route through
the SAME shared per-domain limiter as Assessor Agent fetches, tagged
caller_class="validator" (FR-089).
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.state.entities import ElementReference
from shared.tools.browser import BrowserSession
from shared.tools.element_ref import resolve_on_page, search_by_text, text_hash
from core.telemetry.fetch_log import FetchLog


@dataclass
class VerificationAttemptResult:
    outcome: str  # "confirmed" | "element_absent" | "text_mismatch" | "target_unreachable"
    resolved_css_path: str | None = None
    resolved_text: str | None = None
    detail: str | None = None


async def verify_evidence(
    browser: BrowserSession,
    resolved_url: str,
    reference: ElementReference,
    expected_text: str,
    fetch_log: FetchLog,
    timeout_ms: int = 45000,
) -> VerificationAttemptResult:
    """One verification attempt. Caller (validator.py) handles the
    attempt-bound retry loop for target_unreachable outcomes (FR-088)."""
    page_result, page = await browser.fetch(resolved_url, "validator", fetch_log, timeout_ms=timeout_ms)

    if not page_result.reachable or page is None:
        # FR-088: NOT a quality failure. Deferred/re-attempted by the caller.
        return VerificationAttemptResult(
            outcome="target_unreachable", detail=page_result.reason
        )

    try:
        # Try the recorded selector first.
        located = await resolve_on_page(page, reference)
        if located and located["outcome"] == "confirmed":
            return VerificationAttemptResult(
                outcome="confirmed",
                resolved_css_path=located["css_path"],
                resolved_text=located["text"],
            )
        if located and located["outcome"] == "text_mismatch":
            # Selector still resolves but text changed -- try a text-hash
            # fallback search across the document before concluding mismatch,
            # per research R5's fallback design (page reshuffled vs genuinely
            # changed).
            fallback = await search_by_text(page, expected_text)
            if fallback and text_hash(fallback["text"]) == reference.text_hash:
                return VerificationAttemptResult(
                    outcome="confirmed",
                    resolved_css_path=fallback["css_path"],
                    resolved_text=fallback["text"],
                )
            return VerificationAttemptResult(
                outcome="text_mismatch",
                resolved_css_path=located["css_path"],
                resolved_text=located["text"],
                detail=f"expected text hash {reference.text_hash}, "
                f"found different text at the same selector",
            )

        # Selector missed entirely -- fall back to text-hash search.
        fallback = await search_by_text(page, expected_text)
        if fallback:
            return VerificationAttemptResult(
                outcome="confirmed",
                resolved_css_path=fallback["css_path"],
                resolved_text=fallback["text"],
                detail="located via text-hash fallback; page structure reshuffled",
            )

        return VerificationAttemptResult(
            outcome="element_absent",
            detail=f"neither the recorded selector ({reference.css_path}) nor a "
            "text-hash search located the cited evidence",
        )
    finally:
        await browser.close_page(page)


async def verify_with_retry(
    browser: BrowserSession,
    resolved_url: str,
    reference: ElementReference,
    expected_text: str,
    fetch_log: FetchLog,
    verification_attempt_bound: int,
    timeout_ms: int = 45000,
) -> tuple[VerificationAttemptResult, int]:
    """Retries only on target_unreachable, up to the configured bound
    (FR-088). Returns (final_result, attempts_made)."""
    attempts = 0
    result = None
    while attempts < verification_attempt_bound:
        attempts += 1
        result = await verify_evidence(
            browser, resolved_url, reference, expected_text, fetch_log, timeout_ms=timeout_ms
        )
        if result.outcome != "target_unreachable":
            return result, attempts
    return result, attempts
