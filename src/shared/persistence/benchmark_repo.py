"""Isolated benchmark repository (FR-094, SC-021).

This module has NO import from `ekap_aiq.agents`, and nothing in
`ekap_aiq.agents` imports this module. That is the enforcement mechanism:
ground-truth leakage into an Assessor Agent, the Validator, or the
Adjudicator becomes an import error caught at development time, rather
than a contamination discovered after a benchmark run has already
completed.

`ekap_aiq/agents/*.py` must never import `ekap_aiq.persistence.benchmark_repo`.
`tests/independence/test_benchmark_isolation.py` asserts this via AST inspection.
"""

from __future__ import annotations

import sqlite3

from shared.state.entities import BenchmarkRunResult, BenchmarkSet, GroundTruthAnswer

from .serialization import from_json, to_json


class BenchmarkRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_set(self, benchmark_set: BenchmarkSet) -> None:
        self.conn.execute(
            "INSERT INTO benchmark_sets (set_id, data) VALUES (?, ?)",
            (benchmark_set.set_id, to_json(benchmark_set)),
        )
        self.conn.commit()

    def get_set(self, set_id: str) -> BenchmarkSet | None:
        row = self.conn.execute(
            "SELECT data FROM benchmark_sets WHERE set_id = ?", (set_id,)
        ).fetchone()
        return from_json(row["data"], BenchmarkSet) if row else None

    def insert_ground_truth(self, truth: GroundTruthAnswer) -> None:
        self.conn.execute(
            "INSERT INTO ground_truth_answers (truth_id, set_id, question_id, "
            "country_id, data) VALUES (?, ?, ?, ?, ?)",
            (truth.truth_id, truth.set_id, truth.question_id, truth.country_id, to_json(truth)),
        )
        self.conn.commit()

    def get_ground_truth(
        self, set_id: str, question_id: str, country_id: str
    ) -> GroundTruthAnswer | None:
        row = self.conn.execute(
            "SELECT data FROM ground_truth_answers WHERE set_id = ? AND question_id = ? "
            "AND country_id = ?",
            (set_id, question_id, country_id),
        ).fetchone()
        return from_json(row["data"], GroundTruthAnswer) if row else None

    def list_ground_truth(self, set_id: str) -> list[GroundTruthAnswer]:
        rows = self.conn.execute(
            "SELECT data FROM ground_truth_answers WHERE set_id = ?", (set_id,)
        ).fetchall()
        return [from_json(r["data"], GroundTruthAnswer) for r in rows]

    def insert_run_result(self, result: BenchmarkRunResult) -> None:
        self.conn.execute(
            "INSERT INTO benchmark_run_results (result_id, session_id, data) "
            "VALUES (?, ?, ?)",
            (result.result_id, result.session_id, to_json(result)),
        )
        self.conn.commit()

    def get_run_result(self, session_id: str) -> BenchmarkRunResult | None:
        row = self.conn.execute(
            "SELECT data FROM benchmark_run_results WHERE session_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return from_json(row["data"], BenchmarkRunResult) if row else None

    def list_all_run_results(self) -> list[BenchmarkRunResult]:
        rows = self.conn.execute(
            "SELECT data FROM benchmark_run_results ORDER BY created_at"
        ).fetchall()
        return [from_json(r["data"], BenchmarkRunResult) for r in rows]
