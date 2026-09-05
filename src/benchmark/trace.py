"""Unit resolution trace extractor (FR-LD-007, FR-LD-022 - FR-LD-028).

Lifts all link resolution evidence, stage attempts, rejection reasons,
escalation status, evidence locus gate verdicts, assessor rationale,
and truncation markers from units and agent runs into a frozen trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.persistence.repositories import Repository


@dataclass(frozen=True)
class UnitResolutionTrace:
    question_id: str
    portal_id: str
    resolved_url: str | None
    supplying_source: str | None
    link_escalated_off_portal: bool
    evidence_locus_violation: Any | None
    prefill_reason: str | None
    terminal_state: str
    resolution_history: tuple[dict, ...]
    fill_gap_reason: str | None = None
    link_likely_wrong: bool = False
    raw_evidence_quote: str | None = None
    page_text_truncated: bool = False
    page_text_excess_chars: int = 0
    assessor_answer: Any | None = None
    assessor_justification: str | None = None
    portal_unreachable: bool = False
    auth_boundary_observed: bool = False
    unit_data: dict = field(default_factory=dict)


def read_unit_traces(
    repo: Repository, session_id: str
) -> dict[tuple[str, str], UnitResolutionTrace]:
    """Read all units for a session and lift resolution traces.

    Returns mapping of (question_id, portal_id) -> UnitResolutionTrace.
    """
    units = repo.list_units(session_id)
    agent_runs = repo.list_all_agent_runs_for_session(session_id)
    adjudications = repo.list_all_adjudication_results_for_session(session_id)

    # Group runs and adjudications by (question_id, portal_id)
    runs_by_key: dict[tuple[str, str], list] = {}
    for run in agent_runs:
        key = (run.question_id, run.portal_id)
        runs_by_key.setdefault(key, []).append(run)

    adj_by_key: dict[tuple[str, str], Any] = {}
    for adj in adjudications:
        key = (adj.question_id, adj.portal_id)
        adj_by_key[key] = adj

    traces: dict[tuple[str, str], UnitResolutionTrace] = {}

    for u in units:
        if isinstance(u, dict):
            qid = u.get("question_id", "")
            pid = u.get("portal_id", "")
            udata = u
            terminal_state = str(u.get("state", "unassessable"))
        else:
            qid = getattr(u, "question_id", "")
            pid = getattr(u, "portal_id", "")
            udata = dict(u.data) if hasattr(u, "data") and isinstance(u.data, dict) else {}
            terminal_state = u.state.value if hasattr(u.state, "value") else str(u.state)

        key = (qid, pid)
        runs = runs_by_key.get(key, [])
        adj = adj_by_key.get(key)

        res_history = tuple(udata.get("resolution_history") or [])
        resolved_url = udata.get("resolved_url")
        supplying_source = udata.get("supplying_source")
        escalated = bool(udata.get("link_escalated_off_portal", False))
        locus_violation = udata.get("evidence_locus_violation")
        prefill_reason = udata.get("prefill_reason")

        fill_gap_reason = udata.get("fill_gap_reason")
        link_likely_wrong = False
        portal_unreachable = False
        auth_boundary_observed = False
        page_text_truncated = False
        page_text_excess_chars = 0
        raw_quote = udata.get("raw_evidence_quote")
        assessor_answer = None
        assessor_justification = None

        if adj is not None:
            assessor_answer = adj.consensus_answer
        elif udata.get("consensus_answer") is not None:
            assessor_answer = udata.get("consensus_answer")
        elif "prefill_answer" in udata:
            assessor_answer = udata["prefill_answer"]

        for run in runs:
            if getattr(run, "fill_gap_reason", None):
                fill_gap_reason = run.fill_gap_reason
            if getattr(run, "link_likely_wrong", False):
                link_likely_wrong = True
            if getattr(run, "portal_unreachable", False):
                portal_unreachable = True
            if getattr(run, "auth_boundary_observed", False):
                auth_boundary_observed = True
            if getattr(run, "raw_evidence_quote", None):
                raw_quote = run.raw_evidence_quote
            if getattr(run, "page_text_truncated", False):
                page_text_truncated = True
            excess = getattr(run, "page_text_excess_chars", 0)
            if excess > page_text_excess_chars:
                page_text_excess_chars = excess

        validated_runs = [
            r for r in runs
            if getattr(r, "state", None) == "validated_pass"
            or getattr(getattr(r, "state", None), "value", None) == "validated_pass"
        ]
        target_run = validated_runs[-1] if validated_runs else (runs[-1] if runs else None)
        if assessor_answer is None and target_run and getattr(target_run, "answer", None) is not None:
            assessor_answer = target_run.answer
        if assessor_justification is None and target_run and getattr(target_run, "justification", None):
            assessor_justification = target_run.justification

        if assessor_justification is None:
            assessor_justification = udata.get("justification") or udata.get("prefill_justification")

        traces[key] = UnitResolutionTrace(
            question_id=qid,
            portal_id=pid,
            resolved_url=resolved_url,
            supplying_source=supplying_source,
            link_escalated_off_portal=escalated,
            evidence_locus_violation=locus_violation,
            prefill_reason=prefill_reason,
            terminal_state=terminal_state,
            resolution_history=res_history,
            fill_gap_reason=fill_gap_reason,
            link_likely_wrong=link_likely_wrong,
            raw_evidence_quote=raw_quote,
            page_text_truncated=page_text_truncated,
            page_text_excess_chars=page_text_excess_chars,
            assessor_answer=assessor_answer,
            assessor_justification=assessor_justification,
            portal_unreachable=portal_unreachable,
            auth_boundary_observed=auth_boundary_observed,
            unit_data=udata,
        )

    return traces
