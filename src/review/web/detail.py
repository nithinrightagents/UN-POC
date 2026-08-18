"""Per-agent breakdown rendering (FR-048).

Each individual Assessor Agent's position and the adjudication outcome,
shown behind a detail affordance -- <details>/<summary> so it is available
to assistive technology without JavaScript.
"""

from __future__ import annotations

from html import escape

from review.query import AgentPositionView, AttemptHistoryView


def render_agent_detail_html(
    positions: list[AgentPositionView], discrepancy_flagged: bool
) -> str:
    if not positions:
        return ""

    flag_html = (
        '<div class="alert-box danger" role="status" style="margin: 0.75rem 0; padding: 0.5rem 0.75rem; font-size: 0.85rem;">'
        "<strong>Discrepancy Flagged:</strong> Divergent agent answers required adjudication."
        "</div>"
        if discrepancy_flagged
        else '<div class="alert-box success" role="status" style="margin: 0.75rem 0; padding: 0.5rem 0.75rem; font-size: 0.85rem;">'
        "<strong>Agents in Full Agreement:</strong> Independent runs converged on the same determination."
        "</div>"
    )

    rows = []
    for pos in positions:
        validation = (
            '<span class="badge badge--pass">Passed</span>'
            if pos.validation_passed
            else '<span class="badge badge--fail">Failed</span>'
            if pos.validation_passed is False
            else '<span class="badge">Pending</span>'
        )
        gaps_html = ""
        if pos.validation_gaps:
            items = "".join(f"<li>{escape(g)}</li>" for g in pos.validation_gaps)
            gaps_html = f'<ul class="detail__gaps" style="margin-top: 0.25rem; font-size: 0.8rem; color: var(--color-danger-text); padding-left: 1rem;">{items}</ul>'

        rows.append(
            f"""
            <tr>
                <td><strong>Agent {pos.agent_index}</strong></td>
                <td><span class="badge badge--neutral">{escape(str(pos.answer))}</span></td>
                <td><span class="confidence">{pos.confidence}%</span></td>
                <td><code style="font-size: 0.8rem;">{escape(pos.model_identity or '')}</code></td>
                <td>{validation}{gaps_html}</td>
            </tr>
            """
        )

    return f"""
    <details class="detail" style="margin-top: 1rem;">
        <summary>Show per-agent positions and adjudication breakdown ({len(positions)} agents)</summary>
        {flag_html}
        <div class="table-responsive" style="margin-top: 0.5rem; margin-bottom: 0;">
            <table class="detail__table">
                <thead>
                    <tr><th scope="col">Agent</th><th scope="col">Proposed Answer</th><th scope="col">Confidence</th><th scope="col">Model Identity</th><th scope="col">Evidence Validation</th></tr>
                </thead>
                <tbody>
                    {''.join(rows)}
                </tbody>
            </table>
        </div>
    </details>
    """


def render_attempt_history_html(history: AttemptHistoryView | None) -> str:
    """Attempt history for a blocked question (FR-BF-008, FR-BF-009): resolution
    attempts, reachability/verification counts, retry counts, and points of
    disagreement -- everything the pipeline gathered before it blocked."""
    if history is None:
        return ""

    resolution_html = ""
    if history.resolution_attempts:
        items = "".join(
            f"<li><strong>{escape(str(a.get('source', '')))}:</strong> "
            f"{'Usable' if a.get('usable') else 'Unusable'}"
            f"{' — ' + escape(a['rejection_reason']) if a.get('rejection_reason') else ''}"
            f"{' (' + escape(a['returned']) + ')' if a.get('returned') else ''}</li>"
            for a in history.resolution_attempts
        )
        resolution_html = f'<ul class="detail__resolution-attempts" style="margin: 0.5rem 0 0.5rem 1.25rem; font-size: 0.85rem;">{items}</ul>'

    counts_html = ""
    if history.reachability_attempts is not None:
        counts_html += f"<p style='font-size: 0.85rem;'>Reachability attempts: <strong>{history.reachability_attempts}</strong></p>"
    if history.verification_attempts is not None:
        counts_html += f"<p style='font-size: 0.85rem;'>Verification attempts: <strong>{history.verification_attempts}</strong></p>"

    retry_html = ""
    if history.retry_counts:
        items = "".join(
            f"<li>Agent {r.get('agent_index')}: "
            f"{r.get('confidence_retry_count', 0)} confidence retries, "
            f"{r.get('validation_retry_count', 0)} validation retries</li>"
            for r in history.retry_counts
        )
        retry_html = f'<ul class="detail__retry-counts" style="margin: 0.5rem 0 0.5rem 1.25rem; font-size: 0.85rem;">{items}</ul>'

    disagreement_html = ""
    if history.points_of_disagreement:
        items = "".join(f"<li>{escape(p)}</li>" for p in history.points_of_disagreement)
        disagreement_html = f'<ul class="detail__disagreement" style="margin: 0.5rem 0 0.5rem 1.25rem; font-size: 0.85rem; color: var(--color-danger-text);">{items}</ul>'

    evidence_note = (
        ""
        if history.has_any_evidence
        else '<div class="alert-box warning" role="status" style="margin-top: 0.5rem; font-size: 0.85rem;">No evidence was captured before this question was blocked.</div>'
    )

    return f"""
    <details class="detail" style="margin-top: 0.75rem;">
        <summary>Show resolution attempt history &amp; retry diagnostics</summary>
        <div style="padding-top: 0.5rem;">
            {resolution_html}
            {counts_html}
            {retry_html}
            {disagreement_html}
            {evidence_note}
        </div>
    </details>
    """
