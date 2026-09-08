"""Append-only schema for all entities and telemetry records (FR-062).

Every table is insert-only: no UPDATE or DELETE statement exists anywhere
in this codebase against these tables. Corrections are new rows. Complex
fields are stored as JSON for PoC simplicity; indexed columns cover every
query pattern the audit trail (FR-061) and the review surface need.
"""

from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS survey_cycles (
    cycle_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assessment_sessions (
    session_id TEXT PRIMARY KEY,
    cycle_id TEXT,
    mode TEXT NOT NULL,
    config_snapshot_id TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS questions (
    question_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    is_custom INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only. The default questionnaire (is_custom=0) is immutable once
-- created; a custom question (is_custom=1) may be edited any number of
-- times, and each edit snapshots the pre-edit state here before overwriting
-- questions.data, so the edit history is never lost.
CREATE TABLE IF NOT EXISTS question_revisions (
    revision_id  TEXT PRIMARY KEY,
    question_id  TEXT NOT NULL,
    cycle_id     TEXT NOT NULL,
    data         TEXT NOT NULL,   -- the Question snapshot as it was BEFORE this edit
    revised_by   TEXT,
    revised_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_question_revisions_lookup
    ON question_revisions(question_id, revised_at DESC);

CREATE TABLE IF NOT EXISTS target_portals (
    portal_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    country_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(cycle_id, country_id)
);

CREATE TABLE IF NOT EXISTS units (
    unit_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    portal_id TEXT NOT NULL,
    state TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, question_id, portal_id)
);

CREATE TABLE IF NOT EXISTS language_decisions (
    decision_id TEXT PRIMARY KEY,
    portal_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evidence_artifacts (
    artifact_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assessor_agent_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    portal_id TEXT NOT NULL,
    agent_index INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    state TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS validation_results (
    validation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    passed INTEGER NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS adjudication_results (
    adjudication_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    portal_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS discrepancy_cases (
    case_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    session_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS escalation_queue_items (
    item_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Dispositions are appended separately so "exactly one delivered disposition"
-- (FR-049) is enforced by a unique index, not by an UPDATE.
CREATE TABLE IF NOT EXISTS escalation_dispositions (
    disposition_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assessor_decisions (
    decision_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    portal_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS configuration_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS prior_survey_links (
    link_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    country_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS msq_link_candidates (
    candidate_id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    country_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS answer_exports (
    export_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Telemetry: stage events, fetch log, cost ledger (FR-112-FR-118).
CREATE TABLE IF NOT EXISTS stage_events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fetch_records (
    fetch_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    caller_class TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cost_ledger_entries (
    entry_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    agent_index INTEGER,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Benchmark tables. Isolated deliberately: no other module's repository
-- reads or writes these; only persistence/benchmark_repo.py touches them,
-- and agents/ has no import path to that module (FR-094).
CREATE TABLE IF NOT EXISTS benchmark_sets (
    set_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ground_truth_answers (
    truth_id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    country_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(set_id, question_id, country_id)
);

CREATE TABLE IF NOT EXISTS answer_exports (
    export_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmark_run_results (
    result_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);



-- Assessment & Workflow Engine tables (spec 005): human blind assessors, MSQ ingestion, publication.
CREATE TABLE IF NOT EXISTS human_assessor_submissions (
    submission_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    question_id TEXT NOT NULL,
    portal_id TEXT NOT NULL,
    role TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS msq_documents (
    msq_id TEXT PRIMARY KEY,
    country_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only: a republish is a new row. "Currently published" is always
-- the latest row per (cycle_id, portal_id), read via ORDER BY created_at DESC.
CREATE TABLE IF NOT EXISTS publication_records (
    publication_id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    portal_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only. A re-run writes a fresh row per indicator; the "current"
-- prefill is the newest row belonging to the newest COMPLETED run
-- (FR-PF-039). Never updated, never deleted.
CREATE TABLE IF NOT EXISTS prefills (
    prefill_id   TEXT PRIMARY KEY,
    run_id       TEXT NOT NULL,        -- assessment_jobs.job_id
    session_id   TEXT NOT NULL,
    cycle_id     TEXT NOT NULL,
    question_id  TEXT NOT NULL,
    portal_id    TEXT NOT NULL,
    suggested    INTEGER NOT NULL,     -- 1 = carries a suggestion, 0 = no suggestion
    data         TEXT NOT NULL,        -- the payload below
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Append-only. One row per explicit completion declaration. Completeness is
-- NOT read from this table alone -- see "Derived completeness" below.
CREATE TABLE IF NOT EXISTS assessor_completions (
    completion_id                   TEXT PRIMARY KEY,
    session_id                      TEXT NOT NULL,
    cycle_id                        TEXT NOT NULL,
    portal_id                       TEXT NOT NULL,
    role                            TEXT NOT NULL,   -- 'A' | 'B'
    actor_id                        TEXT NOT NULL,
    indicator_count_at_declaration  INTEGER NOT NULL,
    declared_at                     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_prefills_lookup
    ON prefills(session_id, portal_id, question_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_prefills_run ON prefills(run_id);
CREATE INDEX IF NOT EXISTS idx_completions_lookup
    ON assessor_completions(session_id, portal_id, role, declared_at DESC);

CREATE INDEX IF NOT EXISTS idx_human_submissions_lookup
    ON human_assessor_submissions(session_id, portal_id, question_id, role);
CREATE INDEX IF NOT EXISTS idx_msq_documents_country ON msq_documents(cycle_id, country_id);
CREATE INDEX IF NOT EXISTS idx_publications_portal ON publication_records(cycle_id, portal_id);

CREATE INDEX IF NOT EXISTS idx_units_session ON units(session_id);
CREATE INDEX IF NOT EXISTS idx_units_state ON units(session_id, state);
CREATE INDEX IF NOT EXISTS idx_runs_session ON assessor_agent_runs(session_id, question_id, portal_id);
CREATE INDEX IF NOT EXISTS idx_validations_run ON validation_results(run_id);
CREATE INDEX IF NOT EXISTS idx_stage_events_session ON stage_events(session_id);
CREATE INDEX IF NOT EXISTS idx_fetch_records_session ON fetch_records(session_id, domain);
CREATE INDEX IF NOT EXISTS idx_cost_ledger_session ON cost_ledger_entries(session_id);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON assessor_decisions(session_id);

-- Assessment Jobs (spec 007): tracks live background assessment run state.
-- Deliberately mutable for live run state (same documented exception as units).
CREATE TABLE IF NOT EXISTS assessment_jobs (
    job_id           TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    cycle_id         TEXT NOT NULL,
    portal_id        TEXT NOT NULL,
    state            TEXT NOT NULL,            -- 'running' | 'done' | 'failed'
    questions_total  INTEGER NOT NULL,         -- snapshot at trigger time (R7)
    failure_cause    TEXT,                     -- NULL unless state='failed'
    triggered_by     TEXT NOT NULL,            -- 'api' | 'portal'
    data             TEXT NOT NULL,            -- JSON: terminal outcome counts, actor
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- At most one running job per unit: makes FR-API-014 a storage invariant, so
-- two simultaneous triggers resolve atomically rather than by a memory check.
CREATE UNIQUE INDEX IF NOT EXISTS idx_assessment_jobs_one_running
    ON assessment_jobs(portal_id) WHERE state = 'running';

CREATE INDEX IF NOT EXISTS idx_assessment_jobs_unit
    ON assessment_jobs(cycle_id, portal_id, created_at);
CREATE INDEX IF NOT EXISTS idx_assessment_jobs_state
    ON assessment_jobs(state);

-- Reconciliation Rounds (spec 012): tracks human A/B reconciliation lifecycle.
-- Lifecycle table (mutable state, following assessment_jobs precedent).
CREATE TABLE IF NOT EXISTS reconciliation_rounds (
    round_id        TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    portal_id       TEXT NOT NULL,
    cycle_id        TEXT NOT NULL,
    round_number    INTEGER NOT NULL,      -- 1-based, per unit
    opened_by       TEXT NOT NULL,         -- 'automatic' | 'senior_reviewer'
    opened_by_actor_id TEXT,               -- NULL when opened_by = 'automatic'
    opened_reason   TEXT,                  -- required when opened_by = 'senior_reviewer'
    state           TEXT NOT NULL,         -- 'open' | 'resolved' | 'exhausted' | 'not_required'
    data            TEXT NOT NULL,         -- disputed_question_ids, rate_at_open, tolerance_at_open
    opened_at       TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT
);

-- Concurrency guarantee: partial unique index ensures at most one open round per unit.
CREATE UNIQUE INDEX IF NOT EXISTS idx_reconciliation_one_open
    ON reconciliation_rounds(session_id, portal_id) WHERE state = 'open';

CREATE INDEX IF NOT EXISTS idx_reconciliation_unit
    ON reconciliation_rounds(session_id, portal_id, round_number);

-- Joint Answers (spec 012): append-only record of agreed answers during reconciliation.
CREATE TABLE IF NOT EXISTS joint_answers (
    joint_answer_id TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    portal_id       TEXT NOT NULL,
    question_id     TEXT NOT NULL,
    round_id        TEXT NOT NULL,
    data            TEXT NOT NULL,   -- answer, justification, submitted_by_role, submitted_by_actor_id
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Concurrency guarantee: at most one joint answer per indicator per round.
CREATE UNIQUE INDEX IF NOT EXISTS idx_joint_answers_once
    ON joint_answers(round_id, question_id);

CREATE INDEX IF NOT EXISTS idx_joint_answers_lookup
    ON joint_answers(session_id, portal_id, question_id);

-- Tolerance Changes (spec 012): append-only audit trail of per-project tolerance edits.
CREATE TABLE IF NOT EXISTS tolerance_changes (
    change_id       TEXT PRIMARY KEY,
    cycle_id        TEXT NOT NULL,
    previous_value  REAL,            -- NULL when the project was previously inheriting
    new_value       REAL NOT NULL,
    changed_by_actor_id TEXT NOT NULL,
    changed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tolerance_changes_cycle
    ON tolerance_changes(cycle_id, changed_at);

-- Pending Indicators: candidates parsed from an admin-uploaded PDF, staged
-- here for review before admin approval turns one into a real question row.
-- A reject is a straight DELETE (never scoring-relevant, nothing to audit).
CREATE TABLE IF NOT EXISTS pending_indicators (
    pending_id TEXT PRIMARY KEY,
    cycle_id   TEXT NOT NULL,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_pending_indicators_cycle
    ON pending_indicators(cycle_id, created_at);

-- Assessors (spec 014): ingested roster of candidate assessors. Source replica; survives project deletion.
CREATE TABLE IF NOT EXISTS assessors (
    assessor_id TEXT PRIMARY KEY,
    email       TEXT NOT NULL,
    data        TEXT NOT NULL,   -- display_name, organisation, languages, notes
    ingested_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_assessors_email ON assessors(email);

-- Unit Assessor Mapping (spec 014): the source database's statement of which
-- assessors cover which units. Source replica; survives project deletion.
CREATE TABLE IF NOT EXISTS unit_assessor_mapping (
    unit_type   TEXT NOT NULL,   -- 'country' | 'city'
    unit_code   TEXT NOT NULL,   -- ISO country code, as carried on TargetPortal.country_id
    data        TEXT NOT NULL,   -- assessor_a_id, assessor_b_id (either may be null)
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (unit_type, unit_code)
);

-- Unit Assessor Assignments (spec 014): lifecycle table (mutable) on the
-- reconciliation_rounds precedent. Who works this unit of this project.
CREATE TABLE IF NOT EXISTS unit_assessor_assignments (
    assignment_id TEXT PRIMARY KEY,
    cycle_id      TEXT NOT NULL,
    portal_id     TEXT NOT NULL,
    data          TEXT NOT NULL,   -- role_a, role_b (each RoleAssignment | null), ingest_defect
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One assignment record per unit: makes distinctness a single-row invariant (R2).
-- idx_unit_assignment_one_per_unit is a correctness guarantee, not an optimisation.
CREATE UNIQUE INDEX IF NOT EXISTS idx_unit_assignment_one_per_unit
    ON unit_assessor_assignments(cycle_id, portal_id);

CREATE INDEX IF NOT EXISTS idx_unit_assignment_cycle
    ON unit_assessor_assignments(cycle_id);

-- Assignment Changes (spec 014): append-only audit trail on the tolerance_changes
-- precedent. One row per role write.
CREATE TABLE IF NOT EXISTS assignment_changes (
    change_id            TEXT PRIMARY KEY,
    cycle_id             TEXT NOT NULL,
    portal_id            TEXT NOT NULL,
    role                 TEXT NOT NULL,   -- 'A' | 'B'
    previous_assessor_id TEXT,            -- NULL when the role was previously unstaffed
    new_assessor_id      TEXT,            -- NULL when the role was cleared
    source               TEXT NOT NULL,   -- 'mapping' | 'administrator' | 'migration'
    changed_by_actor_id  TEXT,            -- NULL when source = 'mapping'
    changed_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_assignment_changes_unit
    ON assignment_changes(cycle_id, portal_id, changed_at);

-- Labelling Passes (spec 017): append-only, one row per unit once both completions are declared.
-- idx_labelling_pass_once is a load-bearing once-only guarantee rather than an optimisation.
CREATE TABLE IF NOT EXISTS labelling_passes (
    pass_id     TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    portal_id   TEXT NOT NULL,
    cycle_id    TEXT NOT NULL,
    data        TEXT NOT NULL,   -- disputed_question_ids, compared_count, dispatched_by, model_configured
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_labelling_pass_once
    ON labelling_passes(session_id, portal_id);

CREATE INDEX IF NOT EXISTS idx_labelling_pass_cycle
    ON labelling_passes(cycle_id, created_at);

-- Disagreement Labels (spec 017): append-only audit record per dispute.
-- idx_disagreement_label_once is a load-bearing once-only guarantee rather than an optimisation.
-- label is a real column, not a JSON field, because every aggregate in the feature groups by it.
CREATE TABLE IF NOT EXISTS disagreement_labels (
    label_id     TEXT PRIMARY KEY,
    pass_id      TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    portal_id    TEXT NOT NULL,
    question_id  TEXT NOT NULL,
    label        TEXT NOT NULL,   -- DisagreementLabel enum value
    data         TEXT NOT NULL,   -- provenance + per-side observations
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_disagreement_label_once
    ON disagreement_labels(pass_id, question_id);

CREATE INDEX IF NOT EXISTS idx_disagreement_label_unit
    ON disagreement_labels(session_id, portal_id);

CREATE INDEX IF NOT EXISTS idx_disagreement_label_question
    ON disagreement_labels(question_id, label);

-- Labelling Attempts (spec 017): append-only, one row per failure.
CREATE TABLE IF NOT EXISTS labelling_attempts (
    attempt_id   TEXT PRIMARY KEY,
    pass_id      TEXT NOT NULL,
    question_id  TEXT NOT NULL,
    failure      TEXT NOT NULL,   -- 'provider_error' | 'invalid_response' | 'schema_rejected'
    data         TEXT NOT NULL,   -- error class, truncated detail; never the raw prompt
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_labelling_attempt_dispute
    ON labelling_attempts(pass_id, question_id);
"""



def connect(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(database_path: str) -> None:
    import pathlib

    pathlib.Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(database_path)
    try:
        conn.executescript(DDL)
        conn.commit()
    finally:
        conn.close()
