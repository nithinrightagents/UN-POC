"""Append-only repositories. Insert and read only — FR-062.

No repository in this module exposes an UPDATE or DELETE path against any
audit-relevant table. A "correction" is always a new row (e.g. a new
AssessorAgentRun, a new AssessorDecision), never a mutation of an old one.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime

from shared.state.entities import (
    AdjudicationResult,
    AnswerExport,
    AssessmentSession,
    Assessor,
    AssessorAgentRun,
    AssessorCompletion,
    AssessorDecision,
    AssessorRole,
    AssignmentChange,
    ConfigurationSnapshot,
    DiscrepancyCase,
    EscalationQueueItem,
    EvidenceArtifact,
    HumanAssessorSubmission,
    JointAnswer,
    LanguageDecision,
    MSQDocument,
    MSQLinkCandidate,
    PendingIndicator,
    Prefill,
    PriorSurveyLink,
    PublicationRecord,
    Question,
    ReconciliationRound,
    SessionStatus,
    SurveyCycle,
    TargetPortal,
    ToleranceChange,
    UnitAssessorAssignment,
    UnitAssessorMappingEntry,
    ValidationResult,
    new_id,
)

from .serialization import from_json, to_json


class Repository:
    """Thin wrapper over one sqlite3 connection. All writes are INSERT."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Survey Cycle -------------------------------------------------

    def insert_cycle(self, cycle: SurveyCycle) -> None:
        self.conn.execute(
            "INSERT INTO survey_cycles (cycle_id, data) VALUES (?, ?) "
            "ON CONFLICT(cycle_id) DO UPDATE SET data = excluded.data, created_at = datetime('now')",
            (cycle.cycle_id, to_json(cycle)),
        )
        self.conn.commit()

    def get_cycle(self, cycle_id: str) -> SurveyCycle | None:
        row = self.conn.execute(
            "SELECT data FROM survey_cycles WHERE cycle_id = ? ORDER BY created_at DESC, rowid DESC", (cycle_id,)
        ).fetchone()
        return from_json(row["data"], SurveyCycle) if row else None

    def list_cycles(self) -> list[SurveyCycle]:
        rows = self.conn.execute(
            "SELECT data FROM survey_cycles ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
        seen: set[str] = set()
        out: list[SurveyCycle] = []
        for r in rows:
            c = from_json(r["data"], SurveyCycle)
            if c.cycle_id not in seen:
                seen.add(c.cycle_id)
                out.append(c)
        return out

    def delete_cycle(self, cycle_id: str) -> None:
        session_rows = self.conn.execute(
            "SELECT session_id FROM assessment_sessions WHERE cycle_id = ?", (cycle_id,)
        ).fetchall()
        session_ids = [r["session_id"] for r in session_rows]

        portal_rows = self.conn.execute(
            "SELECT portal_id FROM target_portals WHERE cycle_id = ?", (cycle_id,)
        ).fetchall()
        portal_ids = [r["portal_id"] for r in portal_rows]

        for s_id in session_ids:
            items = self.conn.execute(
                "SELECT item_id FROM escalation_queue_items WHERE session_id = ?", (s_id,)
            ).fetchall()
            for it in items:
                self.conn.execute(
                    "DELETE FROM escalation_dispositions WHERE item_id = ?", (it["item_id"],)
                )
            self.conn.execute("DELETE FROM units WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM language_decisions WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM assessor_agent_runs WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM validation_results WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM adjudication_results WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM discrepancy_cases WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM escalation_queue_items WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM assessor_decisions WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM configuration_snapshots WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM stage_events WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM fetch_records WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM cost_ledger_entries WHERE session_id = ?", (s_id,))
            self.conn.execute("DELETE FROM joint_answers WHERE session_id = ?", (s_id,))

        for p_id in portal_ids:
            self.conn.execute("DELETE FROM language_decisions WHERE portal_id = ?", (p_id,))
            self.conn.execute("DELETE FROM joint_answers WHERE portal_id = ?", (p_id,))

        self.conn.execute("DELETE FROM human_assessor_submissions WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM msq_documents WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM publication_records WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM prefills WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM assessor_completions WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM assessment_jobs WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM reconciliation_rounds WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM tolerance_changes WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM unit_assessor_assignments WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM assignment_changes WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM question_revisions WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM questions WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM pending_indicators WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM target_portals WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM assessment_sessions WHERE cycle_id = ?", (cycle_id,))
        self.conn.execute("DELETE FROM survey_cycles WHERE cycle_id = ?", (cycle_id,))
        self.conn.commit()

    def delete_portal(self, cycle_id: str, portal_id: str) -> None:
        """Remove a single target unit from a project -- the counterpart to
        delete_cycle() at unit granularity. Projects now default to tagging
        every country (or, for LOSI, every country's most-populous city) at
        creation, so admins prune this down to the units they actually want
        from Manage Workspace rather than hand-picking at creation time.

        Mirrors delete_cycle()'s per-table cleanup, scoped to just this
        portal_id -- and, for the country-keyed msq_documents table, this
        portal's country within this cycle. A no-op if the portal doesn't
        belong to this cycle (or doesn't exist)."""
        portal = self.get_portal(portal_id)
        if portal is None or portal.cycle_id != cycle_id:
            return

        self.conn.execute("DELETE FROM units WHERE portal_id = ?", (portal_id,))
        self.conn.execute("DELETE FROM language_decisions WHERE portal_id = ?", (portal_id,))
        self.conn.execute("DELETE FROM assessor_agent_runs WHERE portal_id = ?", (portal_id,))
        self.conn.execute("DELETE FROM adjudication_results WHERE portal_id = ?", (portal_id,))
        self.conn.execute("DELETE FROM assessor_decisions WHERE portal_id = ?", (portal_id,))
        self.conn.execute("DELETE FROM joint_answers WHERE portal_id = ?", (portal_id,))
        self.conn.execute(
            "DELETE FROM human_assessor_submissions WHERE cycle_id = ? AND portal_id = ?",
            (cycle_id, portal_id),
        )
        self.conn.execute(
            "DELETE FROM msq_documents WHERE cycle_id = ? AND country_id = ?",
            (cycle_id, portal.country_id),
        )
        self.conn.execute(
            "DELETE FROM publication_records WHERE cycle_id = ? AND portal_id = ?",
            (cycle_id, portal_id),
        )
        self.conn.execute(
            "DELETE FROM prefills WHERE cycle_id = ? AND portal_id = ?", (cycle_id, portal_id)
        )
        self.conn.execute(
            "DELETE FROM assessor_completions WHERE cycle_id = ? AND portal_id = ?",
            (cycle_id, portal_id),
        )
        self.conn.execute(
            "DELETE FROM assessment_jobs WHERE cycle_id = ? AND portal_id = ?", (cycle_id, portal_id)
        )
        self.conn.execute(
            "DELETE FROM reconciliation_rounds WHERE cycle_id = ? AND portal_id = ?",
            (cycle_id, portal_id),
        )
        self.conn.execute(
            "DELETE FROM unit_assessor_assignments WHERE cycle_id = ? AND portal_id = ?",
            (cycle_id, portal_id),
        )
        self.conn.execute(
            "DELETE FROM assignment_changes WHERE cycle_id = ? AND portal_id = ?",
            (cycle_id, portal_id),
        )
        self.conn.execute("DELETE FROM target_portals WHERE portal_id = ?", (portal_id,))
        self.conn.commit()

    # --- Assessment Session --------------------------------------------

    def insert_session(self, session: AssessmentSession) -> None:
        self.conn.execute(
            "INSERT INTO assessment_sessions (session_id, cycle_id, mode, "
            "config_snapshot_id, data) VALUES (?, ?, ?, ?, ?)",
            (
                session.session_id,
                session.cycle_id,
                session.mode.value,
                session.config_snapshot_id,
                to_json(session),
            ),
        )
        self.conn.commit()

    def get_session(self, session_id: str) -> AssessmentSession | None:
        row = self.conn.execute(
            "SELECT data FROM assessment_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return from_json(row["data"], AssessmentSession) if row else None

    def update_session_status(self, session_id: str, status: SessionStatus) -> None:
        session = self.get_session(session_id)
        if session:
            session.status = status
            self.conn.execute(
                "UPDATE assessment_sessions SET data = ? WHERE session_id = ?",
                (to_json(session), session_id),
            )
            self.conn.commit()

    # --- Question --------------------------------------------------------

    def insert_question(self, question: Question) -> None:
        self.conn.execute(
            "INSERT INTO questions (question_id, cycle_id, is_custom, data) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(question_id) DO UPDATE SET data = excluded.data, is_custom = excluded.is_custom, created_at = datetime('now')",
            (
                question.question_id,
                question.cycle_id,
                1 if question.is_custom else 0,
                to_json(question),
            ),
        )
        self.conn.commit()

    def insert_questions(self, questions: list[Question]) -> None:
        if not questions:
            return
        params = [
            (
                q.question_id,
                q.cycle_id,
                1 if q.is_custom else 0,
                to_json(q),
            )
            for q in questions
        ]
        self.conn.executemany(
            "INSERT INTO questions (question_id, cycle_id, is_custom, data) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(question_id) DO UPDATE SET data = excluded.data, is_custom = excluded.is_custom, created_at = datetime('now')",
            params,
        )
        self.conn.commit()

    def get_question(self, question_id: str) -> Question | None:
        row = self.conn.execute(
            "SELECT data FROM questions WHERE question_id = ?", (question_id,)
        ).fetchone()
        return from_json(row["data"], Question) if row else None

    def update_question(self, question: Question, revised_by: str | None = None) -> Question:
        """Edit an existing custom question. The default questionnaire
        (is_custom=0) is immutable once created -- admin edits only ever
        produce a new custom question via insert_question, never a mutation
        of a default one. A custom question may be edited any number of
        times; each call snapshots the pre-edit row into question_revisions
        (append-only) before overwriting it."""
        existing = self.get_question(question.question_id)
        if existing is None:
            raise ValueError(f"Question '{question.question_id}' does not exist; use insert_question to create it.")
        if not existing.is_custom:
            raise ValueError(
                f"Question '{question.question_id}' is part of the default questionnaire and cannot be edited. "
                "Add a new custom question instead."
            )
        if not question.is_custom:
            raise ValueError("A custom question cannot be converted into a default one via edit.")

        self.conn.execute(
            "INSERT INTO question_revisions (revision_id, question_id, cycle_id, data, revised_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_id("qrev"), existing.question_id, existing.cycle_id, to_json(existing), revised_by),
        )
        self.conn.execute(
            "UPDATE questions SET data = ?, is_custom = 1 WHERE question_id = ?",
            (to_json(question), question.question_id),
        )
        self.conn.commit()
        return question

    def set_question_status(
        self, question_id: str, status: str, revised_by: str | None = None
    ) -> Question:
        """Retire or reactivate a question for this cycle. Unlike
        update_question(), this is allowed on BOTH default and custom
        questions: retiring doesn't alter scoring-relevant text, it just
        stops the indicator from counting toward live progress/discrepancy/
        publication going forward (see list_questions' include_retired),
        while past submissions against it are left untouched for audit."""
        if status not in ("active", "retired"):
            raise ValueError(f"Invalid question status '{status}'; must be 'active' or 'retired'.")
        existing = self.get_question(question_id)
        if existing is None:
            raise ValueError(f"Question '{question_id}' does not exist.")
        self.conn.execute(
            "INSERT INTO question_revisions (revision_id, question_id, cycle_id, data, revised_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (new_id("qrev"), existing.question_id, existing.cycle_id, to_json(existing), revised_by),
        )
        existing.status = status
        self.conn.execute(
            "UPDATE questions SET data = ? WHERE question_id = ?",
            (to_json(existing), question_id),
        )
        self.conn.commit()
        return existing

    def count_question_revisions(self, question_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM question_revisions WHERE question_id = ?", (question_id,)
        ).fetchone()
        return int(row["n"]) if row else 0

    def list_question_revisions(self, question_id: str) -> list[Question]:
        """Oldest first: the sequence of pre-edit snapshots for a custom question."""
        # revised_at has only second resolution (datetime('now')), so ties
        # from same-second edits need rowid (insertion order) as a tiebreaker.
        rows = self.conn.execute(
            "SELECT data FROM question_revisions WHERE question_id = ? "
            "ORDER BY revised_at ASC, rowid ASC",
            (question_id,),
        ).fetchall()
        return [from_json(r["data"], Question) for r in rows]

    def list_questions(
        self, cycle_id: str, include_custom: bool = True, include_retired: bool = False
    ) -> list[Question]:
        sql = "SELECT question_id, cycle_id, is_custom, data FROM questions WHERE cycle_id = ?"
        params: list = [cycle_id]
        if not include_custom:
            sql += " AND is_custom = 0"
        rows = self.conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
            if "cycle_id" not in d:
                d["cycle_id"] = r["cycle_id"]
            if "question_id" not in d:
                d["question_id"] = r["question_id"]
            if not include_retired and d.get("status", "active") == "retired":
                continue
            out.append(from_json(json.dumps(d), Question))
        return out

    # --- Pending Indicator (PDF ingestion review queue) -------------------

    def insert_pending_indicators(self, items: list[PendingIndicator]) -> None:
        if not items:
            return
        params = [(i.pending_id, i.cycle_id, to_json(i)) for i in items]
        self.conn.executemany(
            "INSERT INTO pending_indicators (pending_id, cycle_id, data) VALUES (?, ?, ?)",
            params,
        )
        self.conn.commit()

    def list_pending_indicators(self, cycle_id: str) -> list[PendingIndicator]:
        rows = self.conn.execute(
            "SELECT data FROM pending_indicators WHERE cycle_id = ? ORDER BY created_at ASC, rowid ASC",
            (cycle_id,),
        ).fetchall()
        return [from_json(r["data"], PendingIndicator) for r in rows]

    def get_pending_indicator(self, pending_id: str) -> PendingIndicator | None:
        row = self.conn.execute(
            "SELECT data FROM pending_indicators WHERE pending_id = ?", (pending_id,)
        ).fetchone()
        return from_json(row["data"], PendingIndicator) if row else None

    def delete_pending_indicator(self, pending_id: str) -> None:
        self.conn.execute("DELETE FROM pending_indicators WHERE pending_id = ?", (pending_id,))
        self.conn.commit()

    def delete_pending_indicators_for_cycle(self, cycle_id: str) -> None:
        """Bulk-reject: clear every pending indicator awaiting review for a project."""
        self.conn.execute("DELETE FROM pending_indicators WHERE cycle_id = ?", (cycle_id,))
        self.conn.commit()

    # --- Target Portal -----------------------------------------------------

    def insert_portal(self, portal: TargetPortal) -> None:
        self.conn.execute(
            "INSERT INTO target_portals (portal_id, cycle_id, country_id, data) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(cycle_id, country_id) DO NOTHING",
            (portal.portal_id, portal.cycle_id, portal.country_id, to_json(portal)),
        )
        self.conn.commit()

    def insert_portals(self, portals: list[TargetPortal]) -> None:
        if not portals:
            return
        params = [
            (p.portal_id, p.cycle_id, p.country_id, to_json(p))
            for p in portals
        ]
        self.conn.executemany(
            "INSERT INTO target_portals (portal_id, cycle_id, country_id, data) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(cycle_id, country_id) DO NOTHING",
            params,
        )
        self.conn.commit()

    def update_portal_resolution(self, portal: TargetPortal) -> None:
        """Portal resolution state genuinely mutates as the chain runs (URL
        found, language detected) -- it is not audit history itself, unlike
        the resolution_history list it carries, which only ever grows."""
        self.conn.execute(
            "UPDATE target_portals SET data = ? WHERE portal_id = ?",
            (to_json(portal), portal.portal_id),
        )
        self.conn.commit()

    def get_portal(self, portal_id: str) -> TargetPortal | None:
        row = self.conn.execute(
            "SELECT data FROM target_portals WHERE portal_id = ?", (portal_id,)
        ).fetchone()
        return from_json(row["data"], TargetPortal) if row else None

    def get_portal_by_country(self, cycle_id: str, country_id: str) -> TargetPortal | None:
        row = self.conn.execute(
            "SELECT data FROM target_portals WHERE cycle_id = ? AND country_id = ?",
            (cycle_id, country_id),
        ).fetchone()
        return from_json(row["data"], TargetPortal) if row else None

    def list_portals(self, cycle_id: str) -> list[TargetPortal]:
        rows = self.conn.execute(
            "SELECT data FROM target_portals WHERE cycle_id = ?", (cycle_id,)
        ).fetchall()
        return [from_json(r["data"], TargetPortal) for r in rows]

    # --- Units (state machine records) ----------------------------------

    def upsert_unit(
        self, session_id: str, question_id: str, portal_id: str, state: str, data: dict
    ) -> None:
        """Units track live pipeline progress, not audit history -- FR-065
        requires a single current state per unit for resume to read. Every
        state *transition* is separately recorded as a stage event
        (telemetry/stage_events.py), which is append-only."""
        self.conn.execute(
            "INSERT INTO units (unit_id, session_id, question_id, portal_id, state, data) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, question_id, portal_id) "
            "DO UPDATE SET state = excluded.state, data = excluded.data, "
            "updated_at = datetime('now')",
            (
                f"{session_id}:{question_id}:{portal_id}",
                session_id,
                question_id,
                portal_id,
                state,
                to_json(data),
            ),
        )
        self.conn.commit()

    def get_unit(self, session_id: str, question_id: str, portal_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT state, data FROM units WHERE session_id = ? AND question_id = ? "
            "AND portal_id = ?",
            (session_id, question_id, portal_id),
        ).fetchone()
        if not row:
            return None
        import json

        data = json.loads(row["data"])
        data["state"] = row["state"]
        return data

    def list_units_for_portal(self, session_id: str, portal_id: str) -> list[dict]:
        """Per-portal progress view (admin "Run AI Assessment" status) --
        list_units() only selects `state`/`data`, not the question_id/portal_id
        columns needed to group by unit here."""
        import json

        rows = self.conn.execute(
            "SELECT question_id, state, data FROM units WHERE session_id = ? AND portal_id = ?",
            (session_id, portal_id),
        ).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
            d["question_id"] = r["question_id"]
            d["state"] = r["state"]
            out.append(d)
        return out

    def list_units(self, session_id: str, state: str | None = None) -> list[dict]:
        import json

        if state:
            rows = self.conn.execute(
                "SELECT question_id, portal_id, state, data FROM units WHERE session_id = ? AND state = ?",
                (session_id, state),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT question_id, portal_id, state, data FROM units WHERE session_id = ?", (session_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
            d["question_id"] = r["question_id"]
            d["portal_id"] = r["portal_id"]
            d["state"] = r["state"]
            out.append(d)
        return out

    # --- Language Decision ------------------------------------------------

    def insert_language_decision(self, decision: LanguageDecision) -> None:
        self.conn.execute(
            "INSERT INTO language_decisions (decision_id, portal_id, session_id, data) "
            "VALUES (?, ?, ?, ?)",
            (decision.decision_id, decision.portal_id, decision.session_id, to_json(decision)),
        )
        self.conn.commit()

    def list_language_decisions(self, portal_id: str) -> list[LanguageDecision]:
        rows = self.conn.execute(
            "SELECT data FROM language_decisions WHERE portal_id = ? ORDER BY created_at",
            (portal_id,),
        ).fetchall()
        return [from_json(r["data"], LanguageDecision) for r in rows]

    # --- Evidence Artifact --------------------------------------------------

    def insert_evidence(self, artifact: EvidenceArtifact) -> None:
        self.conn.execute(
            "INSERT INTO evidence_artifacts (artifact_id, data) VALUES (?, ?)",
            (artifact.artifact_id, to_json(artifact)),
        )
        self.conn.commit()

    def get_evidence(self, artifact_id: str) -> EvidenceArtifact | None:
        row = self.conn.execute(
            "SELECT data FROM evidence_artifacts WHERE artifact_id = ?", (artifact_id,)
        ).fetchone()
        return from_json(row["data"], EvidenceArtifact) if row else None


    # --- Assessor Agent Run --------------------------------------------------

    def insert_agent_run(self, run: AssessorAgentRun) -> None:
        """Every state change to a run is a NEW row with a new run_id in the
        general case, EXCEPT that within one run's lifecycle (pending ->
        assessing -> assessed -> validating -> ...) we track it as a single
        evolving record keyed on run_id, since it is one continuous attempt
        by one agent. A *retry* creates a brand new run_id (see
        orchestration/retry_loops.py) -- that is what makes retries visible
        as separate append-only records in the audit trail (FR-061)."""
        self.conn.execute(
            "INSERT INTO assessor_agent_runs "
            "(run_id, session_id, question_id, portal_id, agent_index, round_number, "
            "state, data) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET state = excluded.state, data = excluded.data",
            (
                run.run_id,
                run.session_id,
                run.question_id,
                run.portal_id,
                run.agent_index,
                run.round_number,
                run.state.value,
                to_json(run),
            ),
        )
        self.conn.commit()

    def get_agent_run(self, run_id: str) -> AssessorAgentRun | None:
        row = self.conn.execute(
            "SELECT data FROM assessor_agent_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return from_json(row["data"], AssessorAgentRun) if row else None

    def list_agent_runs(
        self, session_id: str, question_id: str, portal_id: str, round_number: int | None = None
    ) -> list[AssessorAgentRun]:
        sql = (
            "SELECT data FROM assessor_agent_runs WHERE session_id = ? "
            "AND question_id = ? AND portal_id = ?"
        )
        params: list = [session_id, question_id, portal_id]
        if round_number is not None:
            sql += " AND round_number = ?"
            params.append(round_number)
        rows = self.conn.execute(sql, params).fetchall()
        return [from_json(r["data"], AssessorAgentRun) for r in rows]

    def list_all_agent_runs_for_session(self, session_id: str) -> list[AssessorAgentRun]:
        rows = self.conn.execute(
            "SELECT data FROM assessor_agent_runs WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [from_json(r["data"], AssessorAgentRun) for r in rows]

    # --- Validation Result --------------------------------------------------

    def insert_validation_result(self, result: ValidationResult) -> None:
        self.conn.execute(
            "INSERT INTO validation_results (validation_id, run_id, session_id, "
            "passed, data) VALUES (?, ?, ?, ?, ?)",
            (
                result.validation_id,
                result.run_id,
                result.session_id,
                int(result.passed),
                to_json(result),
            ),
        )
        self.conn.commit()

    def list_validation_results(self, run_id: str) -> list[ValidationResult]:
        rows = self.conn.execute(
            "SELECT data FROM validation_results WHERE run_id = ? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        return [from_json(r["data"], ValidationResult) for r in rows]

    # --- Adjudication Result --------------------------------------------------

    def insert_adjudication_result(self, result: AdjudicationResult) -> None:
        self.conn.execute(
            "INSERT INTO adjudication_results (adjudication_id, session_id, "
            "question_id, portal_id, round_number, data) VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.adjudication_id,
                result.session_id,
                result.question_id,
                result.portal_id,
                result.round_number,
                to_json(result),
            ),
        )
        self.conn.commit()

    def list_adjudication_results(
        self, session_id: str, question_id: str, portal_id: str
    ) -> list[AdjudicationResult]:
        rows = self.conn.execute(
            "SELECT data FROM adjudication_results WHERE session_id = ? "
            "AND question_id = ? AND portal_id = ? ORDER BY round_number",
            (session_id, question_id, portal_id),
        ).fetchall()
        return [from_json(r["data"], AdjudicationResult) for r in rows]

    def list_all_adjudication_results_for_session(self, session_id: str) -> list[AdjudicationResult]:
        rows = self.conn.execute(
            "SELECT data FROM adjudication_results WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [from_json(r["data"], AdjudicationResult) for r in rows]


    # --- Discrepancy Case --------------------------------------------------

    def insert_discrepancy_case(self, case: DiscrepancyCase) -> None:
        self.conn.execute(
            "INSERT INTO discrepancy_cases (case_id, scope, session_id, data) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(case_id) DO UPDATE SET data = excluded.data",
            (case.case_id, case.scope, case.session_id, to_json(case)),
        )
        self.conn.commit()

    def list_discrepancy_cases(self, session_id: str, scope: str | None = None) -> list[DiscrepancyCase]:
        if scope:
            rows = self.conn.execute(
                "SELECT data FROM discrepancy_cases WHERE session_id = ? AND scope = ?",
                (session_id, scope),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM discrepancy_cases WHERE session_id = ?", (session_id,)
            ).fetchall()
        return [from_json(r["data"], DiscrepancyCase) for r in rows]

    # --- Escalation Queue --------------------------------------------------

    def insert_escalation(self, item: EscalationQueueItem) -> None:
        self.conn.execute(
            "INSERT INTO escalation_queue_items (item_id, session_id, reason, data) "
            "VALUES (?, ?, ?, ?)",
            (item.item_id, item.session_id, item.reason.value, to_json(item)),
        )
        self.conn.commit()

    def get_escalation(self, item_id: str) -> EscalationQueueItem | None:
        row = self.conn.execute(
            "SELECT data FROM escalation_queue_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        return from_json(row["data"], EscalationQueueItem) if row else None

    def list_escalations(self, session_id: str, unresolved_only: bool = False) -> list[EscalationQueueItem]:
        # Newest first: find_resolved_answer (portal/discrepancy.py) relies on
        # this ordering to prefer a fresh, still-open disagreement over a
        # stale already-arbitrated item that happens to cover the same
        # question_id (e.g. after a resubmission re-opens a settled dispute).
        rows = self.conn.execute(
            "SELECT e.item_id, e.data FROM escalation_queue_items e WHERE e.session_id = ? "
            "ORDER BY e.rowid DESC",
            (session_id,),
        ).fetchall()
        items = [from_json(r["data"], EscalationQueueItem) for r in rows]
        if unresolved_only:
            resolved_ids = {
                r["item_id"]
                for r in self.conn.execute("SELECT item_id FROM escalation_dispositions").fetchall()
            }
            items = [i for i in items if i.item_id not in resolved_ids]
        return items

    def record_disposition(self, item_id: str, disposition: dict) -> bool:
        """FR-049: exactly one delivered disposition, even under concurrent
        action. The UNIQUE constraint on item_id is the enforcement -- a
        second attempt fails with IntegrityError rather than overwriting."""
        from shared.state.entities import new_id

        try:
            self.conn.execute(
                "INSERT INTO escalation_dispositions (disposition_id, item_id, data) "
                "VALUES (?, ?, ?)",
                (new_id("disp"), item_id, to_json(disposition)),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_disposition(self, item_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT data FROM escalation_dispositions WHERE item_id = ?", (item_id,)
        ).fetchone()
        if not row:
            return None
        import json

        return json.loads(row["data"])

    # --- Assessor Decision --------------------------------------------------

    def insert_assessor_decision(self, decision: AssessorDecision) -> None:
        self.conn.execute(
            "INSERT INTO assessor_decisions (decision_id, session_id, question_id, "
            "portal_id, action, actor_id, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                decision.decision_id,
                decision.session_id,
                decision.question_id,
                decision.portal_id,
                decision.action.value,
                decision.actor_id,
                to_json(decision),
            ),
        )
        self.conn.commit()

    def list_assessor_decisions(
        self, session_id: str, question_id: str, portal_id: str
    ) -> list[AssessorDecision]:
        rows = self.conn.execute(
            "SELECT data FROM assessor_decisions WHERE session_id = ? "
            "AND question_id = ? AND portal_id = ? ORDER BY created_at",
            (session_id, question_id, portal_id),
        ).fetchall()
        return [from_json(r["data"], AssessorDecision) for r in rows]

    def latest_assessor_decision(
        self, session_id: str, question_id: str, portal_id: str
    ) -> AssessorDecision | None:
        decisions = self.list_assessor_decisions(session_id, question_id, portal_id)
        return decisions[-1] if decisions else None

    # --- Configuration Snapshot ---------------------------------------------

    def insert_config_snapshot(self, snapshot: ConfigurationSnapshot) -> None:
        self.conn.execute(
            "INSERT INTO configuration_snapshots (snapshot_id, session_id, data) "
            "VALUES (?, ?, ?)",
            (snapshot.snapshot_id, snapshot.session_id, to_json(snapshot)),
        )
        self.conn.commit()

    def get_config_snapshot(self, snapshot_id: str) -> ConfigurationSnapshot | None:
        row = self.conn.execute(
            "SELECT data FROM configuration_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return from_json(row["data"], ConfigurationSnapshot) if row else None

    # --- Prior-Survey Link / MSQ Link Candidate -----------------------------

    def insert_prior_survey_link(self, link: PriorSurveyLink) -> None:
        self.conn.execute(
            "INSERT INTO prior_survey_links (link_id, question_id, country_id, data) "
            "VALUES (?, ?, ?, ?)",
            (link.link_id, link.question_id, link.country_id, to_json(link)),
        )
        self.conn.commit()

    def find_prior_survey_links(self, question_id: str, country_id: str) -> list[PriorSurveyLink]:
        rows = self.conn.execute(
            "SELECT data FROM prior_survey_links WHERE country_id = ? "
            "ORDER BY created_at DESC",
            (country_id,),
        ).fetchall()
        indicator_code = question_id.split(":")[-1]
        all_links = [from_json(r["data"], PriorSurveyLink) for r in rows]
        exact = [link for link in all_links if link.question_id == question_id]
        if exact:
            return exact
        return [link for link in all_links if link.question_id.split(":")[-1] == indicator_code]

    def insert_msq_link_candidate(self, candidate: MSQLinkCandidate) -> None:
        self.conn.execute(
            "INSERT INTO msq_link_candidates (candidate_id, question_id, country_id, data) "
            "VALUES (?, ?, ?, ?)",
            (candidate.candidate_id, candidate.question_id, candidate.country_id, to_json(candidate)),
        )
        self.conn.commit()

    def find_msq_link_candidates(self, question_id: str, country_id: str) -> list[MSQLinkCandidate]:
        rows = self.conn.execute(
            "SELECT data FROM msq_link_candidates WHERE country_id = ? "
            "ORDER BY created_at DESC",
            (country_id,),
        ).fetchall()
        indicator_code = question_id.split(":")[-1]
        all_candidates = [from_json(r["data"], MSQLinkCandidate) for r in rows]
        exact = [c for c in all_candidates if c.question_id == question_id]
        if exact:
            return exact
        return [c for c in all_candidates if c.question_id.split(":")[-1] == indicator_code]

    # --- Answer Export --------------------------------------------------

    def insert_export(self, export: AnswerExport) -> None:
        self.conn.execute(
            "INSERT INTO answer_exports (export_id, cycle_id, data) VALUES (?, ?, ?)",
            (export.export_id, export.cycle_id, to_json(export)),
        )
        self.conn.commit()

    def get_export(self, export_id: str) -> AnswerExport | None:
        row = self.conn.execute(
            "SELECT data FROM answer_exports WHERE export_id = ?", (export_id,)
        ).fetchone()
        return from_json(row["data"], AnswerExport) if row else None

    def list_exports(self, cycle_id: str) -> list[AnswerExport]:
        rows = self.conn.execute(
            "SELECT data FROM answer_exports WHERE cycle_id = ? ORDER BY created_at",
            (cycle_id,),
        ).fetchall()
        return [from_json(r["data"], AnswerExport) for r in rows]

    # --- Human Assessor Submission (spec 005) -------------------------------

    def insert_human_submission(self, submission: HumanAssessorSubmission) -> None:
        self.conn.execute(
            "INSERT INTO human_assessor_submissions "
            "(submission_id, session_id, cycle_id, question_id, portal_id, role, data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                submission.submission_id,
                submission.session_id,
                submission.cycle_id,
                submission.question_id,
                submission.portal_id,
                submission.role.value,
                to_json(submission),
            ),
        )
        self.conn.commit()

    def list_human_submissions(
        self,
        session_id: str,
        portal_id: str,
        question_id: str | None = None,
        role: AssessorRole | None = None,
    ) -> list[HumanAssessorSubmission]:
        sql = "SELECT data FROM human_assessor_submissions WHERE session_id = ? AND portal_id = ?"
        params: list = [session_id, portal_id]
        if question_id:
            sql += " AND question_id = ?"
            params.append(question_id)
        if role:
            sql += " AND role = ?"
            params.append(role.value)
        # created_at has only second-level resolution (SQLite datetime('now')),
        # so two submissions in the same second need rowid as a tiebreaker to
        # preserve true insertion order -- this is what "latest" relies on.
        sql += " ORDER BY created_at, rowid"
        rows = self.conn.execute(sql, params).fetchall()
        return [from_json(r["data"], HumanAssessorSubmission) for r in rows]

    def latest_human_submission(
        self, session_id: str, question_id: str, portal_id: str, role: AssessorRole
    ) -> HumanAssessorSubmission | None:
        subs = self.list_human_submissions(session_id, portal_id, question_id, role)
        return subs[-1] if subs else None

    # --- MSQ Document (spec 005) --------------------------------------------

    def insert_msq_document(self, doc: MSQDocument) -> None:
        self.conn.execute(
            "INSERT INTO msq_documents (msq_id, country_id, cycle_id, data) VALUES (?, ?, ?, ?)",
            (doc.msq_id, doc.country_id, doc.cycle_id, to_json(doc)),
        )
        self.conn.commit()

    def get_msq_document(self, msq_id: str) -> MSQDocument | None:
        row = self.conn.execute(
            "SELECT data FROM msq_documents WHERE msq_id = ?", (msq_id,)
        ).fetchone()
        return from_json(row["data"], MSQDocument) if row else None

    def find_msq_document(self, cycle_id: str, country_id: str) -> MSQDocument | None:
        row = self.conn.execute(
            "SELECT data FROM msq_documents WHERE cycle_id = ? AND country_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cycle_id, country_id),
        ).fetchone()
        return from_json(row["data"], MSQDocument) if row else None

    # --- Publication Record (spec 005) --------------------------------------

    def insert_publication(self, record: PublicationRecord) -> None:
        self.conn.execute(
            "INSERT INTO publication_records (publication_id, cycle_id, portal_id, data) "
            "VALUES (?, ?, ?, ?)",
            (record.publication_id, record.cycle_id, record.portal_id, to_json(record)),
        )
        self.conn.commit()

    def latest_publication(self, cycle_id: str, portal_id: str) -> PublicationRecord | None:
        row = self.conn.execute(
            "SELECT data FROM publication_records WHERE cycle_id = ? AND portal_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cycle_id, portal_id),
        ).fetchone()
        return from_json(row["data"], PublicationRecord) if row else None

    def list_published_portals(self, cycle_id: str) -> list[PublicationRecord]:
        """Latest publication record per portal within the cycle, published only."""
        rows = self.conn.execute(
            "SELECT data FROM publication_records WHERE cycle_id = ? ORDER BY created_at, rowid",
            (cycle_id,),
        ).fetchall()
        latest_by_portal: dict[str, PublicationRecord] = {}
        for r in rows:
            record = from_json(r["data"], PublicationRecord)
            latest_by_portal[record.portal_id] = record
        return list(latest_by_portal.values())

    def list_all_published_cycles(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT cycle_id FROM publication_records"
        ).fetchall()
        return [r["cycle_id"] for r in rows]

    # --- Transactions -------------------------------------------------------

    @contextmanager
    def begin_immediate(self):
        """Acquires a write lock immediately (BEGIN IMMEDIATE).
        Restores previous isolation_level on exit."""
        prev_isolation = self.conn.isolation_level
        self.conn.isolation_level = None
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            yield
            if getattr(self.conn, "in_transaction", False):
                self.conn.execute("COMMIT")
        except Exception:
            if getattr(self.conn, "in_transaction", False):
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
            raise
        finally:
            self.conn.isolation_level = prev_isolation

    # --- Assessment Jobs (spec 007) -----------------------------------------

    def insert_assessment_job(self, job) -> None:
        data_str = json.dumps(job.data) if isinstance(job.data, dict) else to_json(job.data)
        if getattr(job, "created_at", None) and getattr(job, "updated_at", None):
            self.conn.execute(
                "INSERT INTO assessment_jobs (job_id, session_id, cycle_id, portal_id, state, "
                "questions_total, failure_cause, triggered_by, data, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.session_id,
                    job.cycle_id,
                    job.portal_id,
                    job.state,
                    job.questions_total,
                    job.failure_cause,
                    job.triggered_by,
                    data_str,
                    job.created_at,
                    job.updated_at,
                ),
            )
        else:
            self.conn.execute(
                "INSERT INTO assessment_jobs (job_id, session_id, cycle_id, portal_id, state, "
                "questions_total, failure_cause, triggered_by, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    job.job_id,
                    job.session_id,
                    job.cycle_id,
                    job.portal_id,
                    job.state,
                    job.questions_total,
                    job.failure_cause,
                    job.triggered_by,
                    data_str,
                ),
            )
        self.conn.commit()

    def get_assessment_job(self, job_id: str):
        row = self.conn.execute(
            "SELECT * FROM assessment_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return _row_to_job(row) if row else None

    def latest_assessment_job(self, cycle_id: str, portal_id: str):
        row = self.conn.execute(
            "SELECT * FROM assessment_jobs WHERE cycle_id = ? AND portal_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (cycle_id, portal_id),
        ).fetchone()
        return _row_to_job(row) if row else None

    def running_assessment_job(self, portal_id: str):
        row = self.conn.execute(
            "SELECT * FROM assessment_jobs WHERE portal_id = ? AND state = 'running' LIMIT 1",
            (portal_id,),
        ).fetchone()
        return _row_to_job(row) if row else None

    def count_running_assessment_jobs(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS cnt FROM assessment_jobs WHERE state = 'running'"
        ).fetchone()
        return row["cnt"] if row else 0

    def update_assessment_job_state(
        self,
        job_id: str,
        state: str,
        failure_cause: str | None = None,
        data: dict | None = None,
    ) -> None:
        if data is not None:
            data_str = json.dumps(data)
            self.conn.execute(
                "UPDATE assessment_jobs SET state = ?, failure_cause = ?, data = ?, updated_at = datetime('now') "
                "WHERE job_id = ?",
                (state, failure_cause, data_str, job_id),
            )
        else:
            self.conn.execute(
                "UPDATE assessment_jobs SET state = ?, failure_cause = ?, updated_at = datetime('now') "
                "WHERE job_id = ?",
                (state, failure_cause, job_id),
            )
        self.conn.commit()

    def sweep_running_assessment_jobs(self) -> int:
        cursor = self.conn.execute(
            "UPDATE assessment_jobs SET state = 'failed', failure_cause = 'service_stopped_mid_run', "
            "updated_at = datetime('now') WHERE state = 'running'"
        )
        self.conn.commit()
        return cursor.rowcount

    # --- Prefills & Assessor Completions (spec 008) -----------------------

    def insert_prefill(self, prefill: Prefill) -> None:
        data = {
            "answer": prefill.answer,
            "confidence": prefill.confidence,
            "justification": prefill.justification,
            "evidence_url": prefill.evidence_url,
            "supplying_source": prefill.supplying_source,
            "agreement_outcome": prefill.agreement_outcome,
            "confidence_gap": prefill.confidence_gap,
            "resolver_decision": prefill.resolver_decision if isinstance(prefill.resolver_decision, dict) or prefill.resolver_decision is None else dict(prefill.resolver_decision.__dict__),
            "unselected_position": prefill.unselected_position,
            "position_run_ids": prefill.position_run_ids,
            "reason": prefill.reason.value if hasattr(prefill.reason, "value") else prefill.reason,
            "terminal_state": prefill.terminal_state.value if hasattr(prefill.terminal_state, "value") else prefill.terminal_state,
        }
        self.conn.execute(
            """
            INSERT INTO prefills (prefill_id, run_id, session_id, cycle_id, question_id, portal_id, suggested, data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prefill.prefill_id,
                prefill.run_id,
                prefill.session_id,
                prefill.cycle_id,
                prefill.question_id,
                prefill.portal_id,
                1 if prefill.suggested else 0,
                json.dumps(data),
                prefill.created_at.isoformat() if hasattr(prefill.created_at, "isoformat") else str(prefill.created_at),
            ),
        )
        self.conn.commit()

    def latest_prefill(
        self, session_id: str, question_id: str, portal_id: str
    ) -> Prefill | None:
        row = self.conn.execute(
            """
            SELECT * FROM prefills
            WHERE portal_id = ? AND question_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (portal_id, question_id),
        ).fetchone()
        if row:
            return _row_to_prefill(row)
        return None

    def list_prefills_for_run(self, run_id: str) -> list[Prefill]:
        rows = self.conn.execute(
            "SELECT * FROM prefills WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
        return [_row_to_prefill(r) for r in rows]

    def insert_assessor_completion(self, completion: AssessorCompletion) -> None:
        self.conn.execute(
            """
            INSERT INTO assessor_completions (
                completion_id, session_id, cycle_id, portal_id, role, actor_id,
                indicator_count_at_declaration, declared_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                completion.completion_id,
                completion.session_id,
                completion.cycle_id,
                completion.portal_id,
                completion.role,
                completion.actor_id,
                completion.indicator_count_at_declaration,
                completion.declared_at.isoformat() if hasattr(completion.declared_at, "isoformat") else str(completion.declared_at),
            ),
        )
        self.conn.commit()

    def latest_assessor_completion(
        self, session_id: str, portal_id: str, role: str
    ) -> AssessorCompletion | None:
        row = self.conn.execute(
            """
            SELECT * FROM assessor_completions
            WHERE session_id = ? AND portal_id = ? AND role = ?
            ORDER BY declared_at DESC LIMIT 1
            """,
            (session_id, portal_id, role),
        ).fetchone()
        if not row:
            return None
        return AssessorCompletion(
            completion_id=row["completion_id"],
            session_id=row["session_id"],
            cycle_id=row["cycle_id"],
            portal_id=row["portal_id"],
            role=row["role"],
            actor_id=row["actor_id"],
            indicator_count_at_declaration=row["indicator_count_at_declaration"],
            declared_at=row["declared_at"],
        )

    # --- Reconciliation Rounds, Joint Answers, Tolerance Changes (spec 012) ---

    def insert_reconciliation_round(self, round_obj: ReconciliationRound) -> bool:
        """Inserts a reconciliation round.
        Returns False on IntegrityError (e.g. concurrent open under partial unique index).
        """
        opened_at_str = (
            round_obj.opened_at.isoformat()
            if hasattr(round_obj.opened_at, "isoformat")
            else str(round_obj.opened_at)
        )
        closed_at_str = (
            round_obj.closed_at.isoformat()
            if round_obj.closed_at and hasattr(round_obj.closed_at, "isoformat")
            else (str(round_obj.closed_at) if round_obj.closed_at else None)
        )
        data_str = (
            json.dumps(round_obj.data)
            if isinstance(round_obj.data, dict)
            else to_json(round_obj.data)
        )
        try:
            self.conn.execute(
                """
                INSERT INTO reconciliation_rounds (
                    round_id, session_id, portal_id, cycle_id, round_number,
                    opened_by, opened_by_actor_id, opened_reason, state, data,
                    opened_at, closed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    round_obj.round_id,
                    round_obj.session_id,
                    round_obj.portal_id,
                    round_obj.cycle_id,
                    round_obj.round_number,
                    round_obj.opened_by,
                    round_obj.opened_by_actor_id,
                    round_obj.opened_reason,
                    round_obj.state,
                    data_str,
                    opened_at_str,
                    closed_at_str,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def open_round_for_unit(self, session_id: str, portal_id: str) -> ReconciliationRound | None:
        row = self.conn.execute(
            """
            SELECT * FROM reconciliation_rounds
            WHERE session_id = ? AND portal_id = ? AND state = 'open'
            LIMIT 1
            """,
            (session_id, portal_id),
        ).fetchone()
        return _row_to_reconciliation_round(row) if row else None

    def list_rounds_for_unit(self, session_id: str, portal_id: str) -> list[ReconciliationRound]:
        rows = self.conn.execute(
            """
            SELECT * FROM reconciliation_rounds
            WHERE session_id = ? AND portal_id = ?
            ORDER BY round_number ASC
            """,
            (session_id, portal_id),
        ).fetchall()
        return [_row_to_reconciliation_round(r) for r in rows]

    def close_round(self, round_id: str, state: str, closed_at: datetime | str | None = None) -> bool:
        if state not in ("resolved", "exhausted", "not_required"):
            raise ValueError(f"Invalid terminal state for reconciliation round: {state}")
        if closed_at is None:
            closed_at_val = datetime.now(UTC).isoformat()
        elif hasattr(closed_at, "isoformat"):
            closed_at_val = closed_at.isoformat()
        else:
            closed_at_val = str(closed_at)

        cursor = self.conn.execute(
            """
            UPDATE reconciliation_rounds
            SET state = ?, closed_at = ?
            WHERE round_id = ?
            """,
            (state, closed_at_val, round_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def insert_joint_answer(self, joint_answer: JointAnswer) -> bool:
        created_at_str = (
            joint_answer.created_at.isoformat()
            if hasattr(joint_answer.created_at, "isoformat")
            else str(joint_answer.created_at)
        )
        data_str = (
            json.dumps(joint_answer.data)
            if isinstance(joint_answer.data, dict)
            else to_json(joint_answer.data)
        )
        try:
            self.conn.execute(
                """
                INSERT INTO joint_answers (
                    joint_answer_id, session_id, portal_id, question_id, round_id, data, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    joint_answer.joint_answer_id,
                    joint_answer.session_id,
                    joint_answer.portal_id,
                    joint_answer.question_id,
                    joint_answer.round_id,
                    data_str,
                    created_at_str,
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def latest_joint_answer(self, session_id: str, portal_id: str, question_id: str) -> JointAnswer | None:
        row = self.conn.execute(
            """
            SELECT * FROM joint_answers
            WHERE session_id = ? AND portal_id = ? AND question_id = ?
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (session_id, portal_id, question_id),
        ).fetchone()
        return _row_to_joint_answer(row) if row else None

    def list_joint_answers_for_round(self, round_id: str) -> list[JointAnswer]:
        rows = self.conn.execute(
            """
            SELECT * FROM joint_answers
            WHERE round_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (round_id,),
        ).fetchall()
        return [_row_to_joint_answer(r) for r in rows]

    def insert_tolerance_change(self, change: ToleranceChange) -> None:
        changed_at_str = (
            change.changed_at.isoformat()
            if hasattr(change.changed_at, "isoformat")
            else str(change.changed_at)
        )
        self.conn.execute(
            """
            INSERT INTO tolerance_changes (
                change_id, cycle_id, previous_value, new_value, changed_by_actor_id, changed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                change.change_id,
                change.cycle_id,
                change.previous_value,
                change.new_value,
                change.changed_by_actor_id,
                changed_at_str,
            ),
        )
        self.conn.commit()

    def list_tolerance_changes(self, cycle_id: str) -> list[ToleranceChange]:
        rows = self.conn.execute(
            """
            SELECT * FROM tolerance_changes
            WHERE cycle_id = ?
            ORDER BY changed_at ASC, rowid ASC
            """,
            (cycle_id,),
        ).fetchall()
        return [_row_to_tolerance_change(r) for r in rows]

    # --- Assessors and Unit Assignment (spec 014) -----------------------

    def upsert_assessor(self, assessor: Assessor) -> None:
        payload = {
            "display_name": assessor.display_name,
            "organisation": assessor.organisation,
            "languages": assessor.languages,
            "notes": assessor.notes,
        }
        self.conn.execute(
            """
            INSERT INTO assessors (assessor_id, email, data, ingested_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(assessor_id) DO UPDATE SET
                email = excluded.email,
                data = excluded.data,
                ingested_at = excluded.ingested_at
            """,
            (assessor.assessor_id, assessor.email, json.dumps(payload)),
        )
        self.conn.commit()

    def get_assessor(self, assessor_id: str) -> Assessor | None:
        row = self.conn.execute(
            "SELECT assessor_id, email, data FROM assessors WHERE assessor_id = ?",
            (assessor_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_assessor(row)

    def list_assessors(self) -> list[Assessor]:
        rows = self.conn.execute(
            "SELECT assessor_id, email, data FROM assessors ORDER BY assessor_id ASC"
        ).fetchall()
        return [_row_to_assessor(r) for r in rows]

    def load_assessor_index(self) -> dict[str, Assessor]:
        return {a.assessor_id: a for a in self.list_assessors()}

    def upsert_mapping_entry(self, entry: UnitAssessorMappingEntry) -> None:
        payload = {
            "assessor_a_id": entry.assessor_a_id,
            "assessor_b_id": entry.assessor_b_id,
        }
        self.conn.execute(
            """
            INSERT INTO unit_assessor_mapping (unit_type, unit_code, data, ingested_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(unit_type, unit_code) DO UPDATE SET
                data = excluded.data,
                ingested_at = excluded.ingested_at
            """,
            (entry.unit_type, entry.unit_code, json.dumps(payload)),
        )
        self.conn.commit()

    def load_mapping_index(self) -> dict[tuple[str, str], UnitAssessorMappingEntry]:
        rows = self.conn.execute(
            "SELECT unit_type, unit_code, data FROM unit_assessor_mapping"
        ).fetchall()
        out: dict[tuple[str, str], UnitAssessorMappingEntry] = {}
        for r in rows:
            data = json.loads(r["data"]) if isinstance(r["data"], str) else (r["data"] or {})
            entry = UnitAssessorMappingEntry(
                unit_type=r["unit_type"],
                unit_code=r["unit_code"],
                assessor_a_id=data.get("assessor_a_id"),
                assessor_b_id=data.get("assessor_b_id"),
            )
            out[(entry.unit_type, entry.unit_code)] = entry
        return out

    def get_unit_assignment(self, cycle_id: str, portal_id: str) -> UnitAssessorAssignment | None:
        row = self.conn.execute(
            """
            SELECT assignment_id, cycle_id, portal_id, data, updated_at
            FROM unit_assessor_assignments
            WHERE cycle_id = ? AND portal_id = ?
            """,
            (cycle_id, portal_id),
        ).fetchone()
        if row is None:
            return None
        return _row_to_unit_assignment(row)

    def list_unit_assignments(self, cycle_id: str) -> dict[str, UnitAssessorAssignment]:
        rows = self.conn.execute(
            """
            SELECT assignment_id, cycle_id, portal_id, data, updated_at
            FROM unit_assessor_assignments
            WHERE cycle_id = ?
            """,
            (cycle_id,),
        ).fetchall()
        return {r["portal_id"]: _row_to_unit_assignment(r) for r in rows}

    def list_all_unit_assignments(self) -> list[UnitAssessorAssignment]:
        rows = self.conn.execute(
            """
            SELECT assignment_id, cycle_id, portal_id, data, updated_at
            FROM unit_assessor_assignments
            """
        ).fetchall()
        return [_row_to_unit_assignment(r) for r in rows]

    def upsert_unit_assignment(self, assignment: UnitAssessorAssignment) -> None:
        self.conn.execute(
            """
            INSERT INTO unit_assessor_assignments (assignment_id, cycle_id, portal_id, data, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(cycle_id, portal_id) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (
                assignment.assignment_id,
                assignment.cycle_id,
                assignment.portal_id,
                to_json(assignment),
            ),
        )
        self.conn.commit()

    def insert_assignment_change(self, change: AssignmentChange) -> None:
        changed_at = (
            change.changed_at.isoformat()
            if isinstance(change.changed_at, datetime)
            else str(change.changed_at)
        )
        self.conn.execute(
            """
            INSERT INTO assignment_changes (
                change_id, cycle_id, portal_id, role,
                previous_assessor_id, new_assessor_id, source, changed_by_actor_id, changed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                change.change_id,
                change.cycle_id,
                change.portal_id,
                change.role,
                change.previous_assessor_id,
                change.new_assessor_id,
                change.source,
                change.changed_by_actor_id,
                changed_at,
            ),
        )
        self.conn.commit()

    def list_assignment_changes(self, cycle_id: str, portal_id: str) -> list[AssignmentChange]:
        rows = self.conn.execute(
            """
            SELECT change_id, cycle_id, portal_id, role, previous_assessor_id,
                   new_assessor_id, source, changed_by_actor_id, changed_at
            FROM assignment_changes
            WHERE cycle_id = ? AND portal_id = ?
            ORDER BY changed_at ASC, rowid ASC
            """,
            (cycle_id, portal_id),
        ).fetchall()
        return [_row_to_assignment_change(r) for r in rows]

    def has_any_human_activity(self, session_id: str) -> bool:
        """True once any assessor has submitted or declared completion in this session."""
        row = self.conn.execute(
            "SELECT 1 FROM human_assessor_submissions WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is not None:
            return True
        row = self.conn.execute(
            "SELECT 1 FROM assessor_completions WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        return row is not None


def _row_to_reconciliation_round(row: sqlite3.Row) -> ReconciliationRound:
    from datetime import datetime
    data_val = row["data"]
    parsed_data = json.loads(data_val) if isinstance(data_val, str) else (data_val or {})
    opened_at = row["opened_at"]
    if isinstance(opened_at, str):
        try:
            opened_at = datetime.fromisoformat(opened_at)
        except Exception:
            pass
    closed_at = row["closed_at"]
    if isinstance(closed_at, str):
        try:
            closed_at = datetime.fromisoformat(closed_at)
        except Exception:
            pass
    return ReconciliationRound(
        round_id=row["round_id"],
        session_id=row["session_id"],
        portal_id=row["portal_id"],
        cycle_id=row["cycle_id"],
        round_number=row["round_number"],
        opened_by=row["opened_by"],
        opened_by_actor_id=row["opened_by_actor_id"],
        opened_reason=row["opened_reason"],
        state=row["state"],
        data=parsed_data,
        opened_at=opened_at,
        closed_at=closed_at,
    )


def _row_to_joint_answer(row: sqlite3.Row) -> JointAnswer:
    from datetime import datetime
    data_val = row["data"]
    parsed_data = json.loads(data_val) if isinstance(data_val, str) else (data_val or {})
    created_at = row["created_at"]
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except Exception:
            pass
    return JointAnswer(
        joint_answer_id=row["joint_answer_id"],
        session_id=row["session_id"],
        portal_id=row["portal_id"],
        question_id=row["question_id"],
        round_id=row["round_id"],
        data=parsed_data,
        created_at=created_at,
    )


def _row_to_tolerance_change(row: sqlite3.Row) -> ToleranceChange:
    from datetime import datetime
    changed_at = row["changed_at"]
    if isinstance(changed_at, str):
        try:
            changed_at = datetime.fromisoformat(changed_at)
        except Exception:
            pass
    return ToleranceChange(
        change_id=row["change_id"],
        cycle_id=row["cycle_id"],
        previous_value=row["previous_value"],
        new_value=row["new_value"],
        changed_by_actor_id=row["changed_by_actor_id"],
        changed_at=changed_at,
    )


def _row_to_prefill(row: sqlite3.Row) -> Prefill:
    data = json.loads(row["data"]) if isinstance(row["data"], str) else (row["data"] or {})
    return Prefill(
        prefill_id=row["prefill_id"],
        run_id=row["run_id"],
        session_id=row["session_id"],
        cycle_id=row["cycle_id"],
        question_id=row["question_id"],
        portal_id=row["portal_id"],
        suggested=bool(row["suggested"]),
        answer=data.get("answer"),
        confidence=data.get("confidence"),
        justification=data.get("justification"),
        evidence_url=data.get("evidence_url"),
        supplying_source=data.get("supplying_source"),
        agreement_outcome=data.get("agreement_outcome"),
        confidence_gap=data.get("confidence_gap"),
        resolver_decision=data.get("resolver_decision"),
        unselected_position=data.get("unselected_position"),
        position_run_ids=data.get("position_run_ids", []),
        reason=data.get("reason"),
        terminal_state=data.get("terminal_state", "delivered"),
        created_at=row["created_at"],
    )


def _row_to_job(row: sqlite3.Row):
    from api.jobs import AssessmentJob

    data_val = row["data"]
    parsed_data = json.loads(data_val) if isinstance(data_val, str) else (data_val or {})
    return AssessmentJob(
        job_id=row["job_id"],
        session_id=row["session_id"],
        cycle_id=row["cycle_id"],
        portal_id=row["portal_id"],
        state=row["state"],
        questions_total=row["questions_total"],
        failure_cause=row["failure_cause"],
        triggered_by=row["triggered_by"],
        data=parsed_data,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_assessor(row: sqlite3.Row) -> Assessor:
    data = json.loads(row["data"]) if isinstance(row["data"], str) else (row["data"] or {})
    return Assessor(
        assessor_id=row["assessor_id"],
        display_name=data.get("display_name", ""),
        email=row["email"],
        organisation=data.get("organisation", ""),
        languages=data.get("languages", []),
        notes=data.get("notes", ""),
    )


def _row_to_unit_assignment(row: sqlite3.Row) -> UnitAssessorAssignment:
    assignment = from_json(row["data"], UnitAssessorAssignment)
    assignment.assignment_id = row["assignment_id"]
    assignment.cycle_id = row["cycle_id"]
    assignment.portal_id = row["portal_id"]
    return assignment


def _row_to_assignment_change(row: sqlite3.Row) -> AssignmentChange:
    changed_at = row["changed_at"]
    if isinstance(changed_at, str):
        try:
            changed_at = datetime.fromisoformat(changed_at)
        except Exception:
            pass
    return AssignmentChange(
        change_id=row["change_id"],
        cycle_id=row["cycle_id"],
        portal_id=row["portal_id"],
        role=row["role"],
        previous_assessor_id=row["previous_assessor_id"],
        new_assessor_id=row["new_assessor_id"],
        source=row["source"],
        changed_by_actor_id=row["changed_by_actor_id"],
        changed_at=changed_at,
    )


