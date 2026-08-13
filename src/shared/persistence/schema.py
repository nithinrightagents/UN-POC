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



CREATE INDEX IF NOT EXISTS idx_units_session ON units(session_id);
CREATE INDEX IF NOT EXISTS idx_units_state ON units(session_id, state);
CREATE INDEX IF NOT EXISTS idx_runs_session ON assessor_agent_runs(session_id, question_id, portal_id);
CREATE INDEX IF NOT EXISTS idx_validations_run ON validation_results(run_id);
CREATE INDEX IF NOT EXISTS idx_stage_events_session ON stage_events(session_id);
CREATE INDEX IF NOT EXISTS idx_fetch_records_session ON fetch_records(session_id, domain);
CREATE INDEX IF NOT EXISTS idx_cost_ledger_session ON cost_ledger_entries(session_id);
CREATE INDEX IF NOT EXISTS idx_decisions_session ON assessor_decisions(session_id);
"""


def connect(database_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(database_path)
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
