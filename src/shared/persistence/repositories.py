"""Append-only repositories. Insert and read only — FR-062.

No repository in this module exposes an UPDATE or DELETE path against any
audit-relevant table. A "correction" is always a new row (e.g. a new
AssessorAgentRun, a new AssessorDecision), never a mutation of an old one.
"""

from __future__ import annotations

import sqlite3

from shared.state.entities import (
    AdjudicationResult,
    AnswerExport,
    AssessmentSession,
    AssessorAgentRun,
    AssessorDecision,
    ConfigurationSnapshot,
    DiscrepancyCase,
    EscalationQueueItem,
    EvidenceArtifact,
    LanguageDecision,
    MSQLinkCandidate,
    PriorSurveyLink,
    Question,
    SurveyCycle,
    TargetPortal,
    ValidationResult,
)

from .serialization import from_json, to_json


class Repository:
    """Thin wrapper over one sqlite3 connection. All writes are INSERT."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Survey Cycle -------------------------------------------------

    def insert_cycle(self, cycle: SurveyCycle) -> None:
        self.conn.execute(
            "INSERT INTO survey_cycles (cycle_id, data) VALUES (?, ?)",
            (cycle.cycle_id, to_json(cycle)),
        )
        self.conn.commit()

    def get_cycle(self, cycle_id: str) -> SurveyCycle | None:
        row = self.conn.execute(
            "SELECT data FROM survey_cycles WHERE cycle_id = ?", (cycle_id,)
        ).fetchone()
        return from_json(row["data"], SurveyCycle) if row else None

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

    # --- Question --------------------------------------------------------

    def insert_question(self, question: Question) -> None:
        self.conn.execute(
            "INSERT INTO questions (question_id, cycle_id, is_custom, data) "
            "VALUES (?, ?, ?, ?)",
            (
                question.question_id,
                question.cycle_id,
                int(question.is_custom),
                to_json(question),
            ),
        )
        self.conn.commit()

    def get_question(self, question_id: str) -> Question | None:
        row = self.conn.execute(
            "SELECT data FROM questions WHERE question_id = ?", (question_id,)
        ).fetchone()
        return from_json(row["data"], Question) if row else None

    def list_questions(self, cycle_id: str, include_custom: bool = True) -> list[Question]:
        sql = "SELECT data FROM questions WHERE cycle_id = ?"
        params: list = [cycle_id]
        if not include_custom:
            sql += " AND is_custom = 0"
        rows = self.conn.execute(sql, params).fetchall()
        return [from_json(r["data"], Question) for r in rows]

    # --- Target Portal -----------------------------------------------------

    def insert_portal(self, portal: TargetPortal) -> None:
        self.conn.execute(
            "INSERT INTO target_portals (portal_id, cycle_id, country_id, data) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(cycle_id, country_id) DO NOTHING",
            (portal.portal_id, portal.cycle_id, portal.country_id, to_json(portal)),
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

    def list_units(self, session_id: str, state: str | None = None) -> list[dict]:
        import json

        if state:
            rows = self.conn.execute(
                "SELECT state, data FROM units WHERE session_id = ? AND state = ?",
                (session_id, state),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT state, data FROM units WHERE session_id = ?", (session_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
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

    def insert_export(self, export_obj: AnswerExport) -> None:
        self.conn.execute(
            "INSERT INTO answer_exports (export_id, cycle_id, data) VALUES (?, ?, ?)",
            (export_obj.export_id, export_obj.cycle_id, to_json(export_obj)),
        )
        self.conn.commit()

    def get_export(self, export_id: str) -> AnswerExport | None:
        row = self.conn.execute(
            "SELECT data FROM answer_exports WHERE export_id = ?", (export_id,)
        ).fetchone()
        return from_json(row["data"], AnswerExport) if row else None


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
        rows = self.conn.execute(
            "SELECT e.item_id, e.data FROM escalation_queue_items e WHERE e.session_id = ?",
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
            "SELECT data FROM prior_survey_links WHERE question_id = ? AND country_id = ? "
            "ORDER BY created_at DESC",
            (question_id, country_id),
        ).fetchall()
        return [from_json(r["data"], PriorSurveyLink) for r in rows]

    def insert_msq_link_candidate(self, candidate: MSQLinkCandidate) -> None:
        self.conn.execute(
            "INSERT INTO msq_link_candidates (candidate_id, question_id, country_id, data) "
            "VALUES (?, ?, ?, ?)",
            (candidate.candidate_id, candidate.question_id, candidate.country_id, to_json(candidate)),
        )
        self.conn.commit()

    def find_msq_link_candidates(self, question_id: str, country_id: str) -> list[MSQLinkCandidate]:
        rows = self.conn.execute(
            "SELECT data FROM msq_link_candidates WHERE question_id = ? AND country_id = ? "
            "ORDER BY created_at DESC",
            (question_id, country_id),
        ).fetchall()
        return [from_json(r["data"], MSQLinkCandidate) for r in rows]

    # --- Answer Export --------------------------------------------------

    def insert_export(self, export: AnswerExport) -> None:
        self.conn.execute(
            "INSERT INTO answer_exports (export_id, cycle_id, data) VALUES (?, ?, ?)",
            (export.export_id, export.cycle_id, to_json(export)),
        )
        self.conn.commit()

    def list_exports(self, cycle_id: str) -> list[AnswerExport]:
        rows = self.conn.execute(
            "SELECT data FROM answer_exports WHERE cycle_id = ? ORDER BY created_at",
            (cycle_id,),
        ).fetchall()
        return [from_json(r["data"], AnswerExport) for r in rows]
