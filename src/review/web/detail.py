"""Per-agent breakdown rendering (FR-048).

Each individual Assessor Agent's position and the adjudication outcome,
shown behind a detail affordance -- <details>/<summary> so it is available
to assistive technology without JavaScript.
"""

from __future__ import annotations

from html import escape

from review.query import AgentPositionView


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
