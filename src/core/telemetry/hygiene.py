"""Telemetry hygiene enforcement (FR-117, FR-118).

Telemetry records must never contain portal credentials (there are none in
this system — FR-110) or benchmark ground truth, and telemetry must never
be an input to an assessment decision.

`ekap_aiq/telemetry/*.py` must never import `ekap_aiq.agents` — that is the
structural half of FR-118's enforcement (telemetry cannot feed an
assessment decision if it has no path to reach one). This module holds the
runtime half: scanning stored records for suspicious content.
"""

from __future__ import annotations

import json
import re
import sqlite3

_CREDENTIAL_PATTERNS = [
    re.compile(r"password", re.I),
    re.compile(r"api[_-]?key", re.I),
    re.compile(r"secret", re.I),
    re.compile(r"bearer\s+[a-z0-9._-]+", re.I),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

_TELEMETRY_TABLES = ("stage_events", "fetch_records", "cost_ledger_entries")


def scan_for_credentials(conn: sqlite3.Connection, session_id: str) -> list[str]:
    """Returns a list of violation descriptions; empty means clean."""
    violations: list[str] = []
    for table in _TELEMETRY_TABLES:
        rows = conn.execute(
            f"SELECT data FROM {table} WHERE session_id = ?", (session_id,)
        ).fetchall()
        for row in rows:
            blob = row["data"]
            for pattern in _CREDENTIAL_PATTERNS:
                if pattern.search(blob):
                    violations.append(f"{table}: matched {pattern.pattern!r}")
    return violations


def scan_for_ground_truth(conn: sqlite3.Connection, session_id: str, known_truth_values: list[str]) -> list[str]:
    """Cross-checks telemetry payloads against known ground-truth answer
    strings for a benchmark session. Used by `aiq verify telemetry-hygiene`."""
    violations: list[str] = []
    if not known_truth_values:
        return violations
    for table in _TELEMETRY_TABLES:
        rows = conn.execute(
            f"SELECT data FROM {table} WHERE session_id = ?", (session_id,)
        ).fetchall()
        for row in rows:
            data = json.loads(row["data"])
            blob = json.dumps(data)
            for truth in known_truth_values:
                if truth and str(truth) in blob:
                    violations.append(f"{table}: contains ground-truth value {truth!r}")
    return violations
