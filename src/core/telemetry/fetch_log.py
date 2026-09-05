"""Per-domain fetch logging (FR-115).

Every outbound fetch is recorded with the domain, the caller class
(assessor_agent | validator), and the limiter wait time. This is the raw
data SC-012 and SC-019 are demonstrated from — not asserted, demonstrated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from shared.persistence.serialization import to_json
from shared.state.entities import new_id


@dataclass
class FetchRecord:
    fetch_id: str
    session_id: str
    domain: str
    caller_class: str  # "assessor_agent" | "validator"
    requested_at: datetime
    granted_at: datetime
    wait_seconds: float
    status: str  # "ok" | "timeout" | "interstitial" | "error"


class FetchLog:
    def __init__(self, conn: sqlite3.Connection, session_id: str):
        self.conn = conn
        self.session_id = session_id

    def record(self, domain: str, caller_class: str, wait_seconds: float, status: str = "ok") -> None:
        now = datetime.now(UTC)
        record = FetchRecord(
            fetch_id=new_id("fetch"),
            session_id=self.session_id,
            domain=domain,
            caller_class=caller_class,
            requested_at=now,
            granted_at=now,
            wait_seconds=wait_seconds,
            status=status,
        )
        self.conn.execute(
            "INSERT INTO fetch_records (fetch_id, session_id, domain, caller_class, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (record.fetch_id, self.session_id, domain, caller_class, to_json(record)),
        )
        self.conn.commit()

    def summary_by_caller(self) -> dict[str, dict[str, int]]:
        """Per-domain fetch counts split by caller_class -- the data behind
        SC-019's shared-budget demonstration."""
        rows = self.conn.execute(
            "SELECT domain, caller_class, COUNT(*) as n FROM fetch_records "
            "WHERE session_id = ? GROUP BY domain, caller_class",
            (self.session_id,),
        ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            out.setdefault(r["domain"], {})[r["caller_class"]] = r["n"]
        return out
