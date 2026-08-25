"""Shared fixtures for unit tests."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from portal.webapp import build_app
from shared.config.settings import Settings
from shared.persistence.schema import connect, init_db


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "test_aiq.db")
    init_db(path)
    return path


@pytest.fixture
def conn(db_path):
    connection = connect(db_path)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def settings(db_path) -> Settings:
    return Settings(
        api_key="test-secret",
        max_concurrent_assessment_runs=2,
        google_cloud_project="test-proj",
        google_cloud_location="us-central1",
        database_path=db_path,
    )


@pytest.fixture
def auth() -> dict[str, str]:
    return {"X-API-Key": "test-secret"}


@pytest.fixture
def fake_runner():
    async def _fake_run(*args, **kwargs):
        return None

    try:
        with patch("api.jobs.run_assessment_job", new_callable=AsyncMock) as mock_jobs_run, \
             patch("api.runner.run_assessment_job", new_callable=AsyncMock):
            yield mock_jobs_run
    except (ImportError, AttributeError):
        yield AsyncMock()


@pytest.fixture
def app(db_path, settings):
    return build_app(db_path, settings)


@pytest.fixture
def client(app, fake_runner):
    with TestClient(app) as test_client:
        yield test_client


class StubModelResponse:
    def __init__(self, text: str, model_identity: str = "stub-model"):
        self.text = text
        self.model_identity = model_identity
        self.input_tokens = 10
        self.output_tokens = 10


class StubProvider:
    def __init__(self, responses: list[dict | str] | None = None, default_payload: dict | None = None):
        self.calls: list[dict] = []
        self._responses = list(responses or [])
        self._default = default_payload or {
            "answer": True,
            "confidence": 90,
            "justification": "Stub justification",
            "evidence_quote": "evidence",
        }

    async def generate(self, *, model="test", system_instruction="", prompt="", temperature=0.0, response_schema=None):
        self.calls.append({"model": model, "prompt": prompt, "temperature": temperature, "schema": response_schema})
        if self._responses:
            item = self._responses.pop(0)
            if isinstance(item, dict):
                text = json.dumps(item)
            else:
                text = str(item)
        else:
            text = json.dumps(self._default)
        return StubModelResponse(text, f"stub/{model}")


@pytest.fixture
def stub_provider():
    def _factory(responses=None, default_payload=None):
        return StubProvider(responses, default_payload)
    return _factory


@pytest.fixture
def seeded_prefills(conn):
    def _seed(rows: list[dict]):
        cursor = conn.cursor()
        for r in rows:
            prefill_id = r.get("prefill_id", f"pref-{uuid.uuid4().hex[:10]}")
            run_id = r.get("run_id", "job-test")
            session_id = r.get("session_id", "session-test")
            cycle_id = r.get("cycle_id", "c-2024")
            question_id = r.get("question_id", "c-2024:2.1.1")
            portal_id = r.get("portal_id", "portal-test")
            suggested = 1 if r.get("suggested", True) else 0
            data_dict = dict(r.get("data", {}))
            for k in ("answer", "confidence", "justification", "evidence_url", "supplying_source", "reason", "terminal_state", "agreement_outcome", "confidence_gap", "resolver_decision", "unselected_position", "position_run_ids"):
                if k not in data_dict and k in r:
                    data_dict[k] = r[k]
            created_at = r.get("created_at", datetime.now(UTC).isoformat())
            cursor.execute(
                """
                INSERT INTO prefills (prefill_id, run_id, session_id, cycle_id, question_id, portal_id, suggested, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (prefill_id, run_id, session_id, cycle_id, question_id, portal_id, suggested, json.dumps(data_dict), created_at),
            )
        conn.commit()
    return _seed


@pytest.fixture
def completed_unit(conn):
    def _complete(session_id: str, cycle_id: str, portal_id: str, questions: list[str], *, roles=("A", "B"), answers=None):
        cursor = conn.cursor()
        answers = answers or {}
        now = datetime.now(UTC).isoformat()
        for role in roles:
            for qid in questions:
                ans = answers.get(qid, True)
                sub_id = f"sub-{uuid.uuid4().hex[:10]}"
                ans_val = 1 if ans is True else (0 if ans is False else None)
                cursor.execute(
                    """
                    INSERT INTO human_assessor_submissions (
                        submission_id, session_id, cycle_id, question_id, portal_id, role,
                        actor_id, answer, confidence, evidence_url, justification,
                        ai_suggested_answer, ai_suggestion_accepted, notes, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sub_id, session_id, cycle_id, qid, portal_id, role, f"actor-{role}", ans_val, 95, "https://example.com", "Justification", None, None, "", now),
                )
            comp_id = f"comp-{uuid.uuid4().hex[:10]}"
            cursor.execute(
                """
                INSERT INTO assessor_completions (
                    completion_id, session_id, cycle_id, portal_id, role, actor_id, indicator_count_at_declaration, declared_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (comp_id, session_id, cycle_id, portal_id, role, f"actor-{role}", len(questions), now),
            )
        conn.commit()
    return _complete


@pytest.fixture
def two_assessor_unit(conn):
    """Constructs a unit with given questions and (a_answer, b_answer) pairs.
    pair_map is dict[str, tuple[bool | object, bool | object]].
    """
    def _create(
        session_id: str,
        cycle_id: str,
        portal_id: str,
        pair_map: dict[str, tuple[object, object]],
        *,
        declare_a: bool = False,
        declare_b: bool = False,
        actor_a: str = "actor-A",
        actor_b: str = "actor-B",
    ):
        cursor = conn.cursor()
        now = datetime.now(UTC).isoformat()
        for qid, (a_ans, b_ans) in pair_map.items():
            if a_ans is not None:
                sub_id_a = f"sub-{uuid.uuid4().hex[:10]}"
                ans_a_val = 1 if a_ans is True else (0 if a_ans is False else a_ans)
                cursor.execute(
                    """
                    INSERT INTO human_assessor_submissions (
                        submission_id, session_id, cycle_id, question_id, portal_id, role,
                        actor_id, answer, confidence, evidence_url, justification,
                        ai_suggested_answer, ai_suggestion_accepted, notes, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sub_id_a, session_id, cycle_id, qid, portal_id, "A", actor_a, ans_a_val, 95, "https://example.com", "Justification", None, None, "", now),
                )
            if b_ans is not None:
                sub_id_b = f"sub-{uuid.uuid4().hex[:10]}"
                ans_b_val = 1 if b_ans is True else (0 if b_ans is False else b_ans)
                cursor.execute(
                    """
                    INSERT INTO human_assessor_submissions (
                        submission_id, session_id, cycle_id, question_id, portal_id, role,
                        actor_id, answer, confidence, evidence_url, justification,
                        ai_suggested_answer, ai_suggestion_accepted, notes, submitted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sub_id_b, session_id, cycle_id, qid, portal_id, "B", actor_b, ans_b_val, 95, "https://example.com", "Justification", None, None, "", now),
                )
        if declare_a:
            cursor.execute(
                """
                INSERT INTO assessor_completions (
                    completion_id, session_id, cycle_id, portal_id, role, actor_id, indicator_count_at_declaration, declared_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (f"comp-{uuid.uuid4().hex[:10]}", session_id, cycle_id, portal_id, "A", actor_a, len(pair_map), now),
            )
        if declare_b:
            cursor.execute(
                """
                INSERT INTO assessor_completions (
                    completion_id, session_id, cycle_id, portal_id, role, actor_id, indicator_count_at_declaration, declared_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (f"comp-{uuid.uuid4().hex[:10]}", session_id, cycle_id, portal_id, "B", actor_b, len(pair_map), now),
            )
        conn.commit()
    return _create


@pytest.fixture
def open_round(conn):
    """Directly creates an open reconciliation_rounds row for a unit."""
    def _create(
        session_id: str,
        cycle_id: str,
        portal_id: str,
        disputed_question_ids: list[str],
        *,
        round_number: int = 1,
        opened_by: str = "automatic",
        opened_by_actor_id: str | None = None,
        opened_reason: str | None = None,
        rate_at_open: float = 0.1,
        tolerance_at_open: float = 0.05,
    ) -> str:
        round_id = f"rnd-{uuid.uuid4().hex[:10]}"
        now = datetime.now(UTC).isoformat()
        data = {
            "disputed_question_ids": disputed_question_ids,
            "rate_at_open": rate_at_open,
            "tolerance_at_open": tolerance_at_open,
        }
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO reconciliation_rounds (
                round_id, session_id, portal_id, cycle_id, round_number,
                opened_by, opened_by_actor_id, opened_reason, state, data, opened_at, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                round_id,
                session_id,
                portal_id,
                cycle_id,
                round_number,
                opened_by,
                opened_by_actor_id,
                opened_reason,
                "open",
                json.dumps(data),
                now,
                None,
            ),
        )
        conn.commit()
        return round_id
    return _create


@pytest.fixture
def both_declared(conn):
    """Writes assessor_completions rows for both roles A and B."""
    def _declare(
        session_id: str,
        cycle_id: str,
        portal_id: str,
        count: int = 140,
        *,
        actor_a: str = "actor-A",
        actor_b: str = "actor-B",
    ):
        cursor = conn.cursor()
        now = datetime.now(UTC).isoformat()
        cursor.execute(
            """
            INSERT INTO assessor_completions (
                completion_id, session_id, cycle_id, portal_id, role, actor_id, indicator_count_at_declaration, declared_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"comp-{uuid.uuid4().hex[:10]}", session_id, cycle_id, portal_id, "A", actor_a, count, now),
        )
        cursor.execute(
            """
            INSERT INTO assessor_completions (
                completion_id, session_id, cycle_id, portal_id, role, actor_id, indicator_count_at_declaration, declared_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (f"comp-{uuid.uuid4().hex[:10]}", session_id, cycle_id, portal_id, "B", actor_b, count, now),
        )
        conn.commit()
    return _declare

