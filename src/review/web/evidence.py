"""Evidence viewer rendering (FR-023, FR-021, FR-119, FR-120, FR-051, FR-123).

Renders the capture, element reference, and element text inline so the
reviewer never leaves the surface. Evidence text is presented in the
portal's original language with any translation shown alongside it, never
in place of it (FR-120, FR-026).
Supports out-of-set language best effort badges (FR-051) and link provenance tags (FR-123).
WCAG 2.1 AA / 2.2 AA compliant markup with proper roles, contrast, and ARIA attributes (FR-119).
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
            "<strong>Evidence Missing or Unresolvable:</strong> "
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
            "(retained as point-in-time record)</span>"
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
            f'<div class="evidence__translation" style="margin-top: 0.5rem; padding: 0.5rem 0.75rem; background: rgba(255,255,255,0.7); border-radius: var(--radius-xs); border: 1px solid var(--color-border-subtle);">'
            f'<span class="muted" style="font-size: 0.75rem; text-transform: uppercase; font-weight: 700;">English Translation:</span>'
            f'<p style="margin-top: 0.25rem; font-style: normal; color: var(--color-text-primary);">{escape(evidence.element_text_translation)}</p>'
            f"</div>"
        )

    original_text = evidence.element_text_original_language or evidence.element_text

    capture_html = ""
    if evidence.capture_ref:
        capture_html = (
            f'<div style="margin: 0.75rem 0;">'
            f'<img class="evidence__capture" src="/captures/{escape(evidence.capture_ref)}" '
            f'alt="Region-scoped capture of the cited page element" style="max-width: 100%; border: 1px solid var(--color-border-default); border-radius: var(--radius-sm);">'
            f'</div>'
        )

    return f"""
    <div class="evidence" role="region" aria-label="Evidence Artifact Viewer" style="margin: 1.25rem 0;">
        <div class="evidence__meta" style="margin-bottom: 0.75rem;">
            <div style="font-weight: 600; font-size: 0.9rem; margin-bottom: 0.35rem;">
                <a href="{escape(evidence.resolved_url)}" target="_blank" rel="noopener noreferrer" aria-label="Open source link in new tab" style="word-break: break-all;">
                    {escape(evidence.resolved_url)}
                </a>
            </div>
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                {source_badge}
                {verified_badge}
                {lang_badge}
            </div>
        </div>
        {capture_html}
        <div style="background: rgba(255,255,255,0.8); padding: 0.75rem; border-radius: var(--radius-xs); border: 1px solid var(--color-border-subtle); margin: 0.5rem 0;">
            <span class="muted" style="font-size: 0.75rem; text-transform: uppercase; font-weight: 700;">Original Cited Text:</span>
            <p class="evidence__element-text" lang="" style="margin-top: 0.25rem; font-style: italic; color: var(--color-text-primary);">{escape(original_text)}</p>
        </div>
        {translation_html}
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem;">
            <p class="evidence__selector" style="margin: 0;"><code style="font-size: 0.8rem; background: rgba(0,0,0,0.06); padding: 0.2rem 0.4rem; border-radius: var(--radius-xs);">{escape(evidence.element_reference.css_path)}</code></p>
            <p class="evidence__timestamp muted" style="margin: 0; font-size: 0.8rem;">Captured: {evidence.captured_at.isoformat() if evidence.captured_at else 'n/a'}</p>
        </div>
    </div>
    """
