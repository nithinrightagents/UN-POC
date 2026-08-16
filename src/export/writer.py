"""NDJSON answer export and exclusion report writer (FR-101–FR-106, SC-023).

Produces newline-delimited JSON for delivered answers and an accompanying exclusion report JSON.
Enforces invariants and records export audit metadata.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from shared.state.entities import AnswerExport, SessionMode, UnitState, utcnow, new_id
from shared.state.reason_tags import is_blocked, reason_tag
from export.invariants import validate_export_record, validate_export_set
from shared.persistence.repositories import Repository


def export_cycle_answers(
    repo: Repository,
    cycle_id: str,
    output_dir: str | Path,
    actor_id: str = "system-exporter",
) -> tuple[Path, Path]:
    """Export delivered answers and exclusion report for a cycle (FR-101, FR-102, FR-104, FR-106).
    Returns (ndjson_path, exclusion_report_path).
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    questions = repo.list_questions(cycle_id)
    portals = repo.list_portals(cycle_id)
    portals_by_id = {p.portal_id: p for p in portals}

    # Find sessions for cycle (production only)
    sessions = repo.list_sessions_for_cycle(cycle_id) if hasattr(repo, "list_sessions_for_cycle") else []
    if not sessions:
        # Fallback: get all sessions
        rows = repo.conn.execute("SELECT data FROM assessment_sessions WHERE cycle_id = ?", (cycle_id,)).fetchall()
        from shared.state.entities import AssessmentSession
        from shared.persistence.serialization import from_json
        sessions = [from_json(r["data"], AssessmentSession) for r in rows]

    # Filter out benchmark sessions (E2)
    prod_sessions = [s for s in sessions if s.mode != SessionMode.BENCHMARK]
    prod_session_ids = {s.session_id for s in prod_sessions}

    delivered_records = []
    excluded_items = []
    record_ids = []

    total_expected = len(questions) * len(portals)

    for p in portals:
        for q in questions:
            unit = None
            sess_used = None
            for s in prod_sessions:
                st = repo.get_unit(s.session_id, q.question_id, p.portal_id)
                if st:
                    unit = st
                    sess_used = s
                    break

            # FR-BF-013/FR-BF-014, R3: a human decision recorded for a blocked
            # unit (ESCALATED/UNASSESSABLE) also makes it export-eligible as
            # delivered, without touching the unit's own terminal state.
            dec = (
                repo.latest_assessor_decision(sess_used.session_id, q.question_id, p.portal_id)
                if sess_used
                else None
            )
            unit_state = unit.get("state") if unit else None
            is_delivered = unit_state == UnitState.DELIVERED.value
            is_blocked_with_decision = bool(unit) and is_blocked(unit_state) and dec is not None

            if not (is_delivered or is_blocked_with_decision):
                # Determine exclusion reason
                reason = "awaiting_human_review"
                esc_reason_value = unit.get("escalation_reason") if unit else None
                if q.requires_authenticated_access:
                    reason = "requires_authenticated_access"
                elif unit and is_blocked(unit_state):
                    esc_reason = esc_reason_value or "unresolved_disagreement"
                    reason = esc_reason if isinstance(esc_reason, str) else esc_reason.value

                # FR-BF-015: the raw `reason` code is unchanged; `reason_tag`
                # carries the same human-readable text a reviewer would see.
                reason_tag_text = None
                if unit and esc_reason_value:
                    resolution_manner = None
                    if esc_reason_value == "language_declined":
                        language_decisions = repo.list_language_decisions(p.portal_id)
                        if language_decisions:
                            resolution_manner = language_decisions[-1].resolution_manner
                    reason_tag_text = reason_tag(
                        esc_reason_value, unit, resolution_manner=resolution_manner
                    ).text

                excluded_items.append({
                    "country_id": p.country_id,
                    "question_id": q.question_id,
                    "reason": reason,
                    "reason_tag": reason_tag_text,
                })
                continue

            # Delivered (or blocked-with-a-human-decision) unit
            consensus_answer = unit.get("consensus_answer")
            consensus_confidence = unit.get("consensus_confidence", 80)
            below_thresh = bool(unit.get("below_acceptance_threshold", False))

            provenance = "system_proposed"
            acting_actor = sess_used.session_id
            acted_time = sess_used.started_at.isoformat() if hasattr(sess_used.started_at, "isoformat") else str(sess_used.started_at)

            if dec:
                if dec.action.value == "edit":
                    provenance = "human_edited"
                elif dec.action.value == "reject_override":
                    provenance = "human_overridden"
                acting_actor = dec.actor_id
                acted_time = dec.decided_at.isoformat() if hasattr(dec.decided_at, "isoformat") else str(dec.decided_at)

            evidence_refs = []
            ev_id = unit.get("evidence_artifact_id")
            if ev_id:
                ev_art = repo.get_evidence_artifact(ev_id)
                if ev_art:
                    evidence_refs.append({
                        "artifact_id": ev_art.artifact_id,
                        "resolved_url": ev_art.resolved_url,
                        "capture_ref": ev_art.capture_ref,
                        "element_reference": {
                            "css_path": ev_art.element_reference.css_path,
                            "text_hash": ev_art.element_reference.text_hash,
                            "sibling_index": ev_art.element_reference.sibling_index,
                        },
                        "verified_at": ev_art.verified_at.isoformat() if ev_art.verified_at else None,
                        "verifiability_status": ev_art.verifiability_status,
                    })

            record = {
                "cycle_id": cycle_id,
                "country_id": p.country_id,
                "portal": {
                    "resolved_url": p.resolved_url or "",
                    "supplying_source": p.supplying_source.value if p.supplying_source else "msq",
                },
                "question": {
                    "question_id": q.question_id,
                    "is_custom": q.is_custom,
                },
                "delivered_answer": True,
                "consensus_confidence": consensus_confidence,
                "below_acceptance_threshold": below_thresh,
                "provenance": provenance,
                "actor_id": acting_actor,
                "acted_at": acted_time,
                "out_of_set_language_best_effort": bool(unit.get("out_of_set_language_best_effort", False)),
                "session_id": sess_used.session_id,
                "evidence_refs": evidence_refs,
            }

            validate_export_record(record, sess_used.mode.value)
            delivered_records.append(record)
            record_ids.append(f"{q.question_id}:{p.country_id}")

    exclusion_report = {
        "cycle_id": cycle_id,
        "excluded": excluded_items,
    }

    validate_export_set(delivered_records, excluded_items, total_expected)

    # Write NDJSON
    ndjson_path = out_dir / f"export_{cycle_id}.ndjson"
    with open(ndjson_path, "w", encoding="utf-8") as f:
        for r in delivered_records:
            f.write(json.dumps(r) + "\n")

    # Write Exclusion Report
    excl_path = out_dir / f"exclusion_report_{cycle_id}.json"
    with open(excl_path, "w", encoding="utf-8") as f:
        json.dump(exclusion_report, f, indent=2)

    # Audit export record (FR-106)
    exp_obj = AnswerExport(
        export_id=new_id("exp"),
        cycle_id=cycle_id,
        produced_at=utcnow(),
        produced_by_actor_id=actor_id,
        record_ids=record_ids,
        exclusion_report=excluded_items,
    )
    repo.insert_export(exp_obj)

    return ndjson_path, excl_path
