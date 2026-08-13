"""Telemetry reporting (FR-112, SC-025).

Generates summary, timings, fetch counts (assessor vs validator), and model cost reports for a session.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def get_telemetry_summary(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Get overall session telemetry summary (FR-112)."""
    rows = conn.execute(
        "SELECT state, COUNT(*) as cnt FROM units WHERE session_id = ? GROUP BY state",
        (session_id,),
    ).fetchall()
    unit_states = {r["state"]: r["cnt"] for r in rows}

    rows = conn.execute(
        "SELECT data FROM escalation_queue_items WHERE session_id = ?", (session_id,)
    ).fetchall()
    esc_counts = {}
    for r in rows:
        d = json.loads(r["data"])
        reason = d.get("reason", "unknown")
        esc_counts[reason] = esc_counts.get(reason, 0) + 1

    timings = get_timings_report(conn, session_id)
    fetches = get_fetches_report(conn, session_id)
    cost = get_cost_report(conn, session_id)

    return {
        "session_id": session_id,
        "unit_states": unit_states,
        "escalations_by_reason": esc_counts,
        "timings": timings,
        "fetches": fetches,
        "cost": cost,
    }


def get_timings_report(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Get per-stage and total execution timings (FR-113, FR-114)."""
    rows = conn.execute(
        "SELECT data FROM stage_events WHERE session_id = ? ORDER BY created_at",
        (session_id,),
    ).fetchall()

    stages = []
    total_duration_ms = 0
    for r in rows:
        d = json.loads(r["data"])
        dur = d.get("duration_ms", 0)
        total_duration_ms += dur
        stages.append({
            "stage": d.get("stage"),
            "started_at": d.get("started_at"),
            "ended_at": d.get("ended_at"),
            "duration_ms": dur,
        })

    return {
        "stages": stages,
        "total_duration_ms": total_duration_ms,
    }


def get_fetches_report(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Get fetch counts per domain split by caller_class (assessor vs validator) (FR-115)."""
    rows = conn.execute(
        "SELECT data FROM fetch_records WHERE session_id = ?", (session_id,)
    ).fetchall()

    per_domain: dict[str, dict[str, int]] = {}
    total_assessor_fetches = 0
    total_validator_fetches = 0

    for r in rows:
        d = json.loads(r["data"])
        dom = d.get("domain", "unknown")
        caller = d.get("caller_class", "unknown")
        if dom not in per_domain:
            per_domain[dom] = {"assessor_agent": 0, "validator": 0, "other": 0}
        if "validator" in caller.lower():
            per_domain[dom]["validator"] = per_domain[dom].get("validator", 0) + 1
            total_validator_fetches += 1
        elif "assessor" in caller.lower():
            per_domain[dom]["assessor_agent"] = per_domain[dom].get("assessor_agent", 0) + 1
            total_assessor_fetches += 1
        else:
            per_domain[dom]["other"] = per_domain[dom].get("other", 0) + 1

    return {
        "per_domain": per_domain,
        "total_assessor_fetches": total_assessor_fetches,
        "total_validator_fetches": total_validator_fetches,
        "total_fetches": total_assessor_fetches + total_validator_fetches,
    }


def get_cost_report(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Get model invocation cost attributable to stage and agent index (FR-116)."""
    rows = conn.execute(
        "SELECT data FROM cost_ledger_entries WHERE session_id = ?", (session_id,)
    ).fetchall()

    entries = []
    total_cost_usd = 0.0

    for r in rows:
        d = json.loads(r["data"])
        cost = d.get("cost", 0.0)
        total_cost_usd += cost
        entries.append({
            "stage": d.get("stage"),
            "agent_index": d.get("agent_index"),
            "model_identity": d.get("model_identity"),
            "input_units": d.get("input_units"),
            "output_units": d.get("output_units"),
            "cost": round(cost, 6),
        })

    return {
        "entries": entries,
        "total_cost_usd": round(total_cost_usd, 6),
    }
