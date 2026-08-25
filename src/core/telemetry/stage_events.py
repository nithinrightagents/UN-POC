"""Structured stage-transition events (FR-113, FR-114).

Every pipeline stage transition -- URL resolution, language detection, each
Assessor Agent Run, each validation and verification, each adjudication,
each retry, each escalation, each human action -- is recorded with a start
and end timestamp, keyed on the session identifier. This is what makes
per-stage duration and end-to-end unit duration derivable without
inference, and is the raw data behind SC-011.
"""

from __future__ import annotations

import contextlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from shared.persistence.serialization import to_json
from shared.state.entities import new_id

STAGES = (
    "url_resolution",
    "language_detection",
    "assessor_run",
    "confidence_gate",
    "validation",
    "verification",
    "adjudication",
    "portal_adjudication",
    "retry",
    "escalation",
    "human_action",
)


@dataclass
class StageEvent:
    event_id: str
    session_id: str
    unit_ref: dict
    stage: str
    agent_index: int | None
    round_number: int | None
    started_at: datetime
    ended_at: datetime
    outcome: str  # "success" | "failure" | "deferred" | "escalated"


class StageEventLog:
    def __init__(self, conn: sqlite3.Connection, session_id: str):
        self.conn = conn
        self.session_id = session_id

    def record(
        self,
        stage: str,
        unit_ref: dict,
        started_at: datetime,
        ended_at: datetime,
        outcome: str = "success",
        agent_index: int | None = None,
        round_number: int | None = None,
    ) -> None:
        event = StageEvent(
            event_id=new_id("evt"),
            session_id=self.session_id,
            unit_ref=unit_ref,
            stage=stage,
            agent_index=agent_index,
            round_number=round_number,
            started_at=started_at,
            ended_at=ended_at,
            outcome=outcome,
        )
        self.conn.execute(
            "INSERT INTO stage_events (event_id, session_id, stage, data) VALUES (?, ?, ?, ?)",
            (event.event_id, self.session_id, stage, to_json(event)),
        )
        self.conn.commit()

    @contextlib.contextmanager
    def timed(self, stage: str, unit_ref: dict, **kwargs):
        """Context manager: records a stage event covering the wrapped block.
        Usage: `with log.timed("assessor_run", {...}, agent_index=0): ...`"""
        started = datetime.now(UTC)
        outcome = "success"
        try:
            yield
        except Exception:
            outcome = "failure"
            raise
        finally:
            ended = datetime.now(UTC)
            self.record(stage, unit_ref, started, ended, outcome=outcome, **kwargs)

    def durations_by_stage(self) -> dict[str, list[float]]:
        import json

        rows = self.conn.execute(
            "SELECT data FROM stage_events WHERE session_id = ?", (self.session_id,)
        ).fetchall()
        out: dict[str, list[float]] = {}
        for r in rows:
            d = json.loads(r["data"])
            start = datetime.fromisoformat(d["started_at"])
            end = datetime.fromisoformat(d["ended_at"])
            out.setdefault(d["stage"], []).append((end - start).total_seconds())
        return out

    def end_to_end_duration(self) -> float | None:
        import json

        rows = self.conn.execute(
            "SELECT data FROM stage_events WHERE session_id = ?", (self.session_id,)
        ).fetchall()
        if not rows:
            return None
        starts, ends = [], []
        for r in rows:
            d = json.loads(r["data"])
            starts.append(datetime.fromisoformat(d["started_at"]))
            ends.append(datetime.fromisoformat(d["ended_at"]))
        return (max(ends) - min(starts)).total_seconds()
