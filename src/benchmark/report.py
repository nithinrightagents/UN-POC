"""Link resolution diagnostic report renderer.

Implements FR-LD-002, FR-LD-014, FR-LD-015, FR-LD-027, FR-LD-029, FR-LD-030,
FR-LD-031, FR-LD-037, SC-004.
"""

from __future__ import annotations

from benchmark.diagnostics import DiagnosticRunResult, IndicatorVerdict


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed seconds into a readable string."""
    if seconds < 60:
        return f"{seconds:.2f}s"
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins}m {secs:.1f}s"


def render_diagnostic_report(result: DiagnosticRunResult) -> str:
    """Render a comprehensive plaintext diagnostic report."""
    lines: list[str] = []

    # 1. Header
    lines.append("=" * 80)
    lines.append("LINK RESOLUTION DIAGNOSTIC REPORT")
    lines.append("=" * 80)
    lines.append(f"Session ID:         {result.session_id}")
    lines.append(f"Benchmark Set ID:   {result.benchmark_set_id}")
    lines.append(f"Config Snapshot ID: {result.config_snapshot_id or 'N/A'}")
    lines.append(f"Execution Mode:     {'Resolution-Only' if result.resolve_only else 'End-to-End'}")
    lines.append(f"Status:             {result.status.upper()}")
    lines.append(f"Elapsed Time:       {format_elapsed_time(result.elapsed_seconds)}")
    lines.append("-" * 80)

    if result.status == "interrupted":
        lines.append("⚠️  WARNING: THIS RUN WAS INTERRUPTED. RESULTS DO NOT COVER THE FULL SET.")
        lines.append("-" * 80)

    # 2. Per-Indicator Section
    lines.append("PER-INDICATOR VERDICTS")
    lines.append("-" * 80)

    for v in result.verdicts:
        conf_marker = "[AUTH]" if v.confidence == "authoritative" else "[PROV]"
        verdict_str = v.link_verdict.upper()

        lines.append(f"• {conf_marker} Indicator {v.indicator_id} ({v.question_id}):")
        ref_display = v.reference_url or ("(No valid link required)" if v.no_valid_link else "(None)")
        lines.append(f"    Reference:        {ref_display}")
        if v.verified_on or v.origin:
            prov_info = []
            if v.verified_on:
                prov_info.append(f"verified {v.verified_on}")
            if v.origin:
                prov_info.append(f"origin: {v.origin}")
            lines.append(f"    Provenance:       {', '.join(prov_info)}")
        if v.note:
            lines.append(f"    Note:             {v.note}")

        lines.append(f"    Resolved Link:    {v.resolved_url or '(None)'}")
        lines.append(f"    Link Verdict:     {verdict_str}")

        if not result.resolve_only:
            ans_exp = str(v.expected_answer) if v.expected_answer is not None else "N/A"
            ans_pip = str(v.pipeline_answer) if v.pipeline_answer is not None else "N/A"
            lines.append(f"    Answer:           Pipeline={ans_pip} | Expected={ans_exp} ({v.answer_verdict.upper()})")

        if v.attributed_stage:
            stage_str = f"[{v.attributed_stage}]"
            lines.append(f"    Attributed Stage: {stage_str} {v.stage_reason or ''}")

        if v.refused_url:
            lines.append(f"    Refused URL:      {v.refused_url}")
        if v.escalation_status and v.escalation_status != "not_applicable":
            lines.append(f"    Escalation:       {v.escalation_status}")
        if v.page_truncated:
            lines.append(f"    Truncation:       Page exceeded 15k limit by {v.excess_chars} chars")

        lines.append("")

    # 3. Divergent Plausible Review Section (FR-LD-037)
    divergent_list = [v for v in result.verdicts if v.link_verdict == "divergent_plausible"]
    if divergent_list:
        lines.append("-" * 80)
        lines.append("DIVERGENT PLAUSIBLE CANDIDATES (Listed for Review, Excluded from Headline Pass Rate)")
        lines.append("-" * 80)
        for d in divergent_list:
            lines.append(f"• Indicator {d.indicator_id}: resolved {d.resolved_url}")
            lines.append(f"    Reference was: {d.reference_url}")
            lines.append(f"    Action: Review whether this URL should be added to accepted_alternatives.")
        lines.append("")

    # 4. Summary Totals (FR-LD-030, FR-LD-031)
    lines.append("=" * 80)
    lines.append("SUMMARY TOTALS")
    lines.append("=" * 80)
    lines.append(f"Total Indicators Evaluated:       {result.total_indicators}")
    lines.append("")

    auth_total = result.authoritative_matches + result.authoritative_misses + result.authoritative_divergent_plausible
    auth_rate = (result.authoritative_matches / auth_total * 100.0) if auth_total > 0 else 0.0

    lines.append(f"AUTHORITATIVE REFERENCES ({auth_total} total):")
    lines.append(f"  Matches:                        {result.authoritative_matches}")
    lines.append(f"  Divergent Plausible:            {result.authoritative_divergent_plausible}")
    lines.append(f"  Misses / Divergences:           {result.authoritative_misses}")
    lines.append(f"  HEADLINE PASS RATE:             {auth_rate:.1f}% ({result.authoritative_matches}/{auth_total})")
    lines.append("")

    prov_total = result.provisional_matches + result.provisional_misses
    lines.append(f"PROVISIONAL REFERENCES ({prov_total} total):")
    lines.append(f"  Matches:                        {result.provisional_matches}")
    lines.append(f"  Misses:                         {result.provisional_misses}")
    lines.append("")

    lines.append("FAILURE BREAKDOWN:")
    lines.append(f"  Resolution Failures (Link):     {result.resolution_failures}")
    if not result.resolve_only:
        lines.append(f"  Assessment Failures (Answer):   {result.assessment_failures}")
    lines.append(f"  Environmental Failures:         {result.environmental_failures}")
    if result.stale_references_count > 0:
        lines.append(f"  Stale Reference Links:          {result.stale_references_count}")

    lines.append("=" * 80)
    return "\n".join(lines)
