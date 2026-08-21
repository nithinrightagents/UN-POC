"""LLM-inline language support check (replaces the FR-015-FR-020 human
decision gate and the py3langid-based pre-fetch detector).

Each Assessor Agent already reads the page to answer its question, so it
reports the language it observed as part of that same structured response
(agents/assessor/agent.py::_RESPONSE_SCHEMA). No separate detection call,
no python language-ID package. orchestration/scheduler.py::process_unit
compares the majority reported language against `settings.supported_languages`
after assessment and, if unsupported, raises a hard error via the existing
escalate()/EscalationReason mechanism -- never a silent default, never a
pending human decision.
"""

from __future__ import annotations

import sqlite3

import pytest

from agents.assessor.agent import _RESPONSE_SCHEMA
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from orchestration.scheduler import process_unit
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.prompts.profiles import build_prompt
from shared.state.entities import (
    AnswerType,
    EscalationReason,
    EvidenceLocus,
    PrefillReason,
    Question,
    TargetPortal,
    UnitState,
)
from shared.tools.browser import PageResult

pytestmark = pytest.mark.unit


# --- Schema / prompt contract -----------------------------------------------


def test_response_schema_requires_detected_language():
    assert "detected_language" in _RESPONSE_SCHEMA["properties"]
    assert "detected_language" in _RESPONSE_SCHEMA["required"]


def test_build_prompt_instructs_language_identification():
    prompt = build_prompt(
        question_text="Does X exist?", answer_type="binary",
        evidence_locus="national_portal_only", page_text="hello world",
        profile="literal",
    )
    assert "detected_language" in prompt


# --- process_unit escalation behaviour --------------------------------------


class FakeModelResponse:
    def __init__(self, text: str, model_identity: str):
        self.text = text
        self.model_identity = model_identity
        self.input_tokens = 10
        self.output_tokens = 10


class FakeProvider:
    """Returns a fixed answer/confidence and a per-model detected_language,
    so different agent_index values (each bound to a distinct model name via
    Settings.agent_models) can report different observed languages."""

    def __init__(self, languages_by_model: dict[str, str]):
        self._languages_by_model = languages_by_model

    async def generate(self, *, model, system_instruction, prompt, temperature, response_schema=None):
        import json

        language = self._languages_by_model.get(model, "en")
        payload = json.dumps(
            {
                "answer": True,
                "confidence": 90,
                "justification": "Found on the page.",
                "evidence_quote": "",  # no evidence -> validation short-circuits, no extra calls
                "detected_language": language,
            }
        )
        return FakeModelResponse(payload, f"vertexai/{model}")


class FakePage:
    async def close(self):
        pass


class FakeBrowserSession:
    async def fetch(self, url, caller_class, fetch_log=None, timeout_ms=15000):
        result = PageResult(
            url=url, final_url=url, html="<html><body>Some content.</body></html>",
            status=200, reachable=True,
        )
        return result, FakePage()

    async def close_page(self, page):
        pass


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _repo() -> Repository:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    return Repository(conn)


def _settings(agent_count: int, supported_languages: list[str]) -> Settings:
    models = [f"model-{i}" for i in range(agent_count)]
    return Settings(
        assessor_agent_count=agent_count,
        agent_models=models,
        agent_temperatures=[0.2] * agent_count,
        agent_prompt_profiles=["literal"] * agent_count,
        confidence_acceptance_threshold=75,
        confidence_retry_limit=0,
        validation_retry_limit=0,  # fail validation once, terminal -- no extra fetch/LLM calls
        supported_languages=supported_languages,
    )


def _seed_resolved_unit(repo: Repository, session_id: str, question_id: str, portal_id: str, url: str) -> None:
    repo.upsert_unit(session_id, question_id, portal_id, UnitState.RESOLVED.value, {"resolved_url": url})


def _question() -> Question:
    return Question(
        question_id="q1", cycle_id="c1", text="Does X exist?",
        answer_type=AnswerType.BINARY, evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )


def _portal() -> TargetPortal:
    return TargetPortal(portal_id="p1", cycle_id="c1", country_id="XX")


async def _run(repo, settings, provider) -> "UnitOutcome":
    stage_log = StageEventLog.__new__(StageEventLog)
    stage_log.timed = lambda *a, **k: _NullContext()
    cost_ledger = CostLedger.__new__(CostLedger)
    cost_ledger.record = lambda **k: None
    fetch_log = FetchLog.__new__(FetchLog)

    return await process_unit(
        repo=repo, settings=settings, session_id="s1", provider=provider,
        browser=FakeBrowserSession(), http_client=None, fetch_log=fetch_log,
        stage_log=stage_log, cost_ledger=cost_ledger,
        question=_question(), portal=_portal(), adjudicate_results=True,
    )


@pytest.mark.asyncio
async def test_majority_unsupported_language_produces_no_suggestion():
    repo = _repo()
    _seed_resolved_unit(repo, "s1", "q1", "p1", "https://example.gov/page")
    settings = _settings(agent_count=2, supported_languages=["en"])
    provider = FakeProvider({"model-0": "fr", "model-1": "fr"})

    outcome = await _run(repo, settings, provider)

    assert outcome.final_state == UnitState.NO_SUGGESTION
    assert outcome.detail == PrefillReason.UNSUPPORTED_LANGUAGE.value

    # Zero escalation items written
    escalations = repo.list_escalations("s1")
    assert len(escalations) == 0

    # Prefill written with suggested=False and reason=unsupported_language
    prefill = repo.latest_prefill("s1", "q1", "p1")
    assert prefill is not None
    assert prefill.suggested is False
    assert prefill.reason == PrefillReason.UNSUPPORTED_LANGUAGE.value or prefill.reason == PrefillReason.UNSUPPORTED_LANGUAGE


@pytest.mark.asyncio
async def test_supported_language_does_not_trigger_language_escalation():
    repo = _repo()
    _seed_resolved_unit(repo, "s1", "q1", "p1", "https://example.gov/page")
    settings = _settings(agent_count=2, supported_languages=["en"])
    provider = FakeProvider({"model-0": "en", "model-1": "en"})

    outcome = await _run(repo, settings, provider)

    assert outcome.detail != PrefillReason.UNSUPPORTED_LANGUAGE.value
    prefill = repo.latest_prefill("s1", "q1", "p1")
    assert prefill is not None
    assert prefill.reason != PrefillReason.UNSUPPORTED_LANGUAGE.value and prefill.reason != PrefillReason.UNSUPPORTED_LANGUAGE


@pytest.mark.asyncio
async def test_majority_vote_ignores_minority_outlier_language():
    """One agent misreading the page's language must not flip the unit's
    outcome -- only a majority does."""
    repo = _repo()
    _seed_resolved_unit(repo, "s1", "q1", "p1", "https://example.gov/page")
    settings = _settings(agent_count=3, supported_languages=["en"])
    provider = FakeProvider({"model-0": "en", "model-1": "en", "model-2": "fr"})

    outcome = await _run(repo, settings, provider)

    assert outcome.detail != PrefillReason.UNSUPPORTED_LANGUAGE.value
    prefill = repo.latest_prefill("s1", "q1", "p1")
    assert prefill is not None
    assert prefill.reason != PrefillReason.UNSUPPORTED_LANGUAGE.value and prefill.reason != PrefillReason.UNSUPPORTED_LANGUAGE
