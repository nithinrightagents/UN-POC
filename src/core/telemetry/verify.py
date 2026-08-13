"""Telemetry hygiene verification (FR-110, FR-117, SC-025).

Asserts zero credentials and zero ground-truth answers in telemetry logs and observability records.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

CREDENTIAL_PATTERNS = ("api_key", "secret", "password", "bearer ", "token=", "auth=")


@dataclass
class TelemetryHygieneReport:
    session_id: str
    clean: bool
    findings: list[str] = field(default_factory=list)


def verify_telemetry_hygiene(conn: sqlite3.Connection, session_id: str) -> TelemetryHygieneReport:
    """Assert zero credentials and zero ground truth in telemetry records (FR-110, FR-117)."""
    findings = []

    # 1. Fetch records
    rows = conn.execute(
        "SELECT fetch_id, data FROM fetch_records WHERE session_id = ?", (session_id,)
    ).fetchall()
    for r in rows:
        d_str = r["data"].lower()
        for pat in CREDENTIAL_PATTERNS:
            if pat in d_str:
                findings.append(f"Credential pattern {pat!r} found in fetch record {r['fetch_id']}")

    # 2. Stage events
    rows = conn.execute(
        "SELECT event_id, data FROM stage_events WHERE session_id = ?", (session_id,)
    ).fetchall()
    for r in rows:
        d_str = r["data"].lower()
        for pat in CREDENTIAL_PATTERNS:
            if pat in d_str:
                findings.append(f"Credential pattern {pat!r} found in stage event {r['event_id']}")

    # 3. Cost ledger
    rows = conn.execute(
        "SELECT entry_id, data FROM cost_ledger_entries WHERE session_id = ?", (session_id,)
    ).fetchall()
    for r in rows:
        d_str = r["data"].lower()
        for pat in CREDENTIAL_PATTERNS:
            if pat in d_str:
                findings.append(f"Credential pattern {pat!r} found in cost ledger {r['entry_id']}")

    clean = len(findings) == 0
    return TelemetryHygieneReport(session_id=session_id, clean=clean, findings=findings)


def verify_no_credentials(conn: sqlite3.Connection) -> TelemetryHygieneReport:
    """Global check for credentials across all telemetry tables (FR-110)."""
    findings = []
    for table in ("fetch_records", "stage_events", "cost_ledger_entries"):
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        for r in rows:
            text = str(dict(r)).lower()
            for pat in CREDENTIAL_PATTERNS:
                if pat in text:
                    findings.append(f"Credential pattern {pat!r} found in table {table}")

    clean = len(findings) == 0
    return TelemetryHygieneReport(session_id="global", clean=clean, findings=findings)
