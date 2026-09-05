"""Shared helpers for the assessment workflow web surfaces (admin/assessor/public)."""

from __future__ import annotations

import sqlite3

from shared.persistence.repositories import Repository
from shared.state.entities import (
    AssessmentSession,
    ConfigurationSnapshot,
    SessionMode,
    SessionStatus,
    new_id,
)


def session_id_for_cycle(cycle_id: str) -> str:
    """One long-lived assessment session per cycle -- every AI pre-fill run
    and every human A/B submission for a cycle accumulates into it.
    Single-cycle assessment pipelines create one session per cycle."""
    return f"{cycle_id}-workflow-session"


def ensure_session(repo: Repository, cycle_id: str) -> str:
    session_id = session_id_for_cycle(cycle_id)
    if repo.get_session(session_id) is None:
        snapshot = ConfigurationSnapshot(snapshot_id=new_id("cfg"), session_id=session_id, values={})
        repo.insert_config_snapshot(snapshot)
        repo.insert_session(
            AssessmentSession(
                session_id=session_id,
                cycle_id=cycle_id,
                mode=SessionMode.PRODUCTION,
                config_snapshot_id=snapshot.snapshot_id,
                status=SessionStatus.RUNNING,
            )
        )
    return session_id


def repo_factory(database_path: str):
    def _repo() -> Repository:
        conn = sqlite3.connect(database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return Repository(conn)

    return _repo
