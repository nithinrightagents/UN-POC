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
        '<p class="detail__flag" role="status">Discrepancy flagged during adjudication.</p>'
        if discrepancy_flagged
        else '<p class="detail__flag detail__flag--agreed" role="status">Agents agreed; no discrepancy flagged.</p>'
    )

    rows = []
    for pos in positions:
        validation = (
            '<span class="badge badge--pass">validation passed</span>'
            if pos.validation_passed
            else '<span class="badge badge--fail">validation failed</span>'
            if pos.validation_passed is False
            else '<span class="badge">validation pending</span>'
        )
        gaps_html = ""
        if pos.validation_gaps:
            items = "".join(f"<li>{escape(g)}</li>" for g in pos.validation_gaps)
            gaps_html = f'<ul class="detail__gaps">{items}</ul>'

        rows.append(
            f"""
            <tr>
                <td>Agent {pos.agent_index}</td>
                <td>{escape(str(pos.answer))}</td>
                <td>{pos.confidence}%</td>
                <td>{escape(pos.model_identity or '')}</td>
                <td>{validation}{gaps_html}</td>
            </tr>
            """
        )

    return f"""
    <details class="detail">
        <summary>Show each agent's position and the adjudication outcome</summary>
        {flag_html}
        <table class="detail__table">
            <thead>
                <tr><th>Agent</th><th>Answer</th><th>Confidence</th><th>Model</th><th>Validation</th></tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
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
            f"<li>{escape(str(a.get('source', '')))}: "
            f"{'usable' if a.get('usable') else 'not usable'}"
            f"{' — ' + escape(a['rejection_reason']) if a.get('rejection_reason') else ''}"
            f"{' (' + escape(a['returned']) + ')' if a.get('returned') else ''}</li>"
            for a in history.resolution_attempts
        )
        resolution_html = f'<ul class="detail__resolution-attempts">{items}</ul>'

    counts_html = ""
    if history.reachability_attempts is not None:
        counts_html += f"<p>Reachability attempts: {history.reachability_attempts}</p>"
    if history.verification_attempts is not None:
        counts_html += f"<p>Verification attempts: {history.verification_attempts}</p>"

    retry_html = ""
    if history.retry_counts:
        items = "".join(
            f"<li>Agent {r.get('agent_index')}: "
            f"{r.get('confidence_retry_count', 0)} confidence retries, "
            f"{r.get('validation_retry_count', 0)} validation retries</li>"
            for r in history.retry_counts
        )
        retry_html = f'<ul class="detail__retry-counts">{items}</ul>'

    disagreement_html = ""
    if history.points_of_disagreement:
        items = "".join(f"<li>{escape(p)}</li>" for p in history.points_of_disagreement)
        disagreement_html = f'<ul class="detail__disagreement">{items}</ul>'

    evidence_note = (
        ""
        if history.has_any_evidence
        else '<p class="detail__no-evidence" role="status">No evidence was captured before this question was blocked.</p>'
    )

    return f"""
    <details class="detail">
        <summary>Show attempt history</summary>
        {resolution_html}
        {counts_html}
        {retry_html}
        {disagreement_html}
        {evidence_note}
    </details>
    """
