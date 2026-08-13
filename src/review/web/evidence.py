"""Evidence viewer rendering (FR-023, FR-021, FR-119, FR-120, FR-051, FR-123).

Renders the capture, element reference, and element text inline so the
reviewer never leaves the surface. Evidence text is presented in the
portal's original language with any translation shown alongside it, never
in place of it (FR-120, FR-026).
Supports out-of-set language best effort badges (FR-051) and link provenance tags (FR-123).
WCAG 2.1 AA compliant markup with proper roles, contrast, and ARIA attributes (FR-119).
"""

from __future__ import annotations

from html import escape

from shared.state.entities import EvidenceArtifact


def render_evidence_html(
    evidence: EvidenceArtifact | None,
    evidence_missing: bool,
    out_of_set_language_best_effort: bool = False,
    supplying_source: str | None = None,
) -> str:
    if evidence is None or evidence_missing:
        return (
            '<div class="evidence evidence--missing" role="alert" aria-live="assertive">'
            "<strong>Evidence missing or unresolvable.</strong> "
            "This answer's confidence has been capped below the acceptance threshold "
            "because required evidence could not be captured or located."
            "</div>"
        )

    verified_badge = ""
    if evidence.verifiability_status == "verified":
        verified_badge = '<span class="badge badge--verified" role="status">Verified against live page</span>'
    elif evidence.verifiability_status == "no_longer_verifiable":
        verified_badge = (
            '<span class="badge badge--stale" role="status">No longer verifiable against current page '
            "(retained as a point-in-time record)</span>"
        )
    else:
        verified_badge = '<span class="badge badge--unverified" role="status">Unverified</span>'

    lang_badge = ""
    if out_of_set_language_best_effort:
        lang_badge = '<span class="badge badge--lang-best-effort" role="status">Out-of-set language best effort (confidence capped)</span>'

    source_badge = ""
    if supplying_source:
        source_badge = f'<span class="badge badge--source" role="status">Source: {escape(supplying_source.upper())}</span>'

    translation_html = ""
    if evidence.element_text_translation:
        translation_html = (
            f'<p class="evidence__translation"><em>Translation:</em> '
            f"{escape(evidence.element_text_translation)}</p>"
        )

    original_text = evidence.element_text_original_language or evidence.element_text

    capture_html = ""
    if evidence.capture_ref:
        capture_html = (
            f'<img class="evidence__capture" src="/captures/{escape(evidence.capture_ref)}" '
            f'alt="Region-scoped capture of the cited page element">'
        )

    return f"""
    <div class="evidence" role="region" aria-label="Evidence Artifact Viewer">
        <div class="evidence__meta">
            <a href="{escape(evidence.resolved_url)}" target="_blank" rel="noopener noreferrer" aria-label="Open source link in new tab">
                {escape(evidence.resolved_url)}
            </a>
            {source_badge}
            {verified_badge}
            {lang_badge}
        </div>
        {capture_html}
        <p class="evidence__element-text" lang="">{escape(original_text)}</p>
        {translation_html}
        <p class="evidence__selector"><code>{escape(evidence.element_reference.css_path)}</code></p>
        <p class="evidence__timestamp">Captured: {evidence.captured_at.isoformat() if evidence.captured_at else 'n/a'}</p>
    </div>
    """
