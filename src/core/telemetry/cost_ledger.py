"""Per-session model invocation and cost accounting (FR-116).

Attributed to pipeline stage and to the individual Assessor Agent or
Validator that made the call. This is what lets a divergence choice (e.g.
mixing model tiers per research R7) be evaluated against what it costs.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from shared.state.entities import new_id
from shared.persistence.serialization import to_json


@dataclass
class CostLedgerEntry:
    entry_id: str
    session_id: str
    stage: str
    agent_index: int | None
    model_identity: str
    input_units: int
    output_units: int
    cost: float


class CostLedger:
    def __init__(self, conn: sqlite3.Connection, session_id: str, budget: Any | None = None):
        self.conn = conn
        self.session_id = session_id
        self.budget = budget

    def record(
        self,
        stage: str,
        model_identity: str,
        input_units: int,
        output_units: int,
        cost: float,
        agent_index: int | None = None,
    ) -> None:
        if self.budget is not None:
            self.budget.record(cost)
        entry = CostLedgerEntry(
            entry_id=new_id("cost"),
            session_id=self.session_id,
            stage=stage,
            agent_index=agent_index,
            model_identity=model_identity,
            input_units=input_units,
            output_units=output_units,
            cost=cost,
        )
        self.conn.execute(
            "INSERT INTO cost_ledger_entries (entry_id, session_id, stage, "
            "agent_index, data) VALUES (?, ?, ?, ?, ?)",
            (entry.entry_id, self.session_id, stage, agent_index, to_json(entry)),
        )
        self.conn.commit()

    def total_cost(self) -> float:
        row = self.conn.execute(
            "SELECT data FROM cost_ledger_entries WHERE session_id = ?", (self.session_id,)
        ).fetchall()
        import json

        return sum(json.loads(r["data"])["cost"] for r in row)

    def by_stage_and_agent(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT data FROM cost_ledger_entries WHERE session_id = ?", (self.session_id,)
        ).fetchall()
        import json

        return [json.loads(r["data"]) for r in rows]
