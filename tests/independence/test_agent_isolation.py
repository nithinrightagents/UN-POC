"""Independence assertions (FR-010, FR-011, research R7).

The suite whose failure invalidates results rather than reporting a bug: a
run whose independence assertions fail has produced numbers that look
fine and mean nothing (spec Assumptions).

Uses fakes for the model provider and browser -- no network or credentials
required -- so this is exercisable in CI without live Vertex AI access.
"""

from __future__ import annotations

import json

import pytest

from agents.assessor.agent import run_assessor_agent
from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.stage_events import StageEventLog
from shared.config.settings import Settings
from shared.state.schemas import RetryAddendum

pytestmark = pytest.mark.independence


class FakeModelResponse:
    def __init__(self, text: str, model_identity: str):
        self.text = text
        self.model_identity = model_identity
        self.input_tokens = 100
        self.output_tokens = 50


class FakeProvider:
    """Records every call so the test can assert per-agent divergence and
    that no call's arguments reference another agent's identity."""

    def __init__(self, answer: bool, confidence: int):
        self.calls: list[dict] = []
        self._answer = answer
        self._confidence = confidence

    async def generate(self, *, model, system_instruction, prompt, temperature, response_schema=None):
        self.calls.append(
            {"model": model, "prompt": prompt, "temperature": temperature}
        )
        payload = json.dumps(
            {
                "answer": self._answer,
                "confidence": self._confidence,
                "justification": f"Formed independently by model {model} at temperature {temperature}.",
                "evidence_quote": "",
            }
        )
        return FakeModelResponse(payload, f"vertexai/{model}")


class FakePage:
    async def close(self):
        pass


class FakeContext:
    def __init__(self, page):
        self.page = page

    async def close(self):
        pass


class FakePageWithContext(FakePage):
    def __init__(self):
        self.context = FakeContext(self)
        self.url = "https://example.gov"


class FakeBrowserSession:
    """No real playwright browser -- returns a canned reachable page with
    no evidence quote match, so the agent path exercised is the
    no-evidence-located branch (sufficient for isolation testing)."""

    async def fetch(self, url, caller_class, fetch_log=None, timeout_ms=15000):
        from shared.tools.browser import PageResult

        result = PageResult(
            url=url, final_url=url, html="<html><body>Example government portal.</body></html>",
            status=200, reachable=True,
        )
        return result, FakePageWithContext()

    async def close_page(self, page):
        pass


def _settings() -> Settings:
    s = Settings()
    s.agent_models = ["model-a", "model-b"]
    s.agent_temperatures = [0.1, 0.9]
    s.agent_prompt_profiles = ["literal", "inferential"]
    s.confidence_acceptance_threshold = 75
    s.confidence_retry_limit = 1
    return s


@pytest.mark.asyncio
async def test_two_agents_use_distinct_model_and_temperature():
    """Structural half of R7: configuration divergence is actually bound
    per agent_index, not accidentally uniform."""
    settings = _settings()
    provider0, provider1 = FakeProvider(True, 90), FakeProvider(True, 85)
    browser = FakeBrowserSession()
    fetch_log = FetchLog.__new__(FetchLog)  # not touched by the fake browser
    stage_log = StageEventLog.__new__(StageEventLog)
    stage_log.timed = lambda *a, **k: _NullContext()
    cost_ledger = CostLedger.__new__(CostLedger)
    cost_ledger.record = lambda **k: None

    question = {
        "question_id": "q1", "text": "Does X exist?", "answer_type": "binary",
        "evidence_locus": "national_portal_only",
    }

    run0 = await run_assessor_agent(
        session_id="s1", question=question, portal_url="https://example.gov",
        agent_index=0, round_number=1, settings=settings, provider=provider0,
        browser=browser, fetch_log=fetch_log, stage_log=stage_log,
        cost_ledger=cost_ledger,
    )
    run1 = await run_assessor_agent(
        session_id="s1", question=question, portal_url="https://example.gov",
        agent_index=1, round_number=1, settings=settings, provider=provider1,
        browser=browser, fetch_log=fetch_log, stage_log=stage_log,
        cost_ledger=cost_ledger,
    )

    assert provider0.calls[0]["model"] == "model-a"
    assert provider1.calls[0]["model"] == "model-b"
    assert provider0.calls[0]["temperature"] == 0.1
    assert provider1.calls[0]["temperature"] == 0.9
    assert run0.model_identity != run1.model_identity


@pytest.mark.asyncio
async def test_agent_provider_calls_carry_no_reference_to_other_agent():
    """FR-010: nothing passed to a model call for one agent contains
    another agent's identity, model name, or output."""
    settings = _settings()
    provider0 = FakeProvider(True, 90)
    browser = FakeBrowserSession()
    stage_log = StageEventLog.__new__(StageEventLog)
    stage_log.timed = lambda *a, **k: _NullContext()
    cost_ledger = CostLedger.__new__(CostLedger)
    cost_ledger.record = lambda **k: None
    fetch_log = FetchLog.__new__(FetchLog)

    question = {
        "question_id": "q1", "text": "Does X exist?", "answer_type": "binary",
        "evidence_locus": "national_portal_only",
    }

    await run_assessor_agent(
        session_id="s1", question=question, portal_url="https://example.gov",
        agent_index=0, round_number=1, settings=settings, provider=provider0,
        browser=browser, fetch_log=fetch_log, stage_log=stage_log,
        cost_ledger=cost_ledger,
    )

    prompt = provider0.calls[0]["prompt"]
    assert "model-b" not in prompt  # the other agent's model identity
    assert "agent_index=1" not in prompt
    assert "Agent 1" not in prompt


@pytest.mark.asyncio
async def test_disagreement_addendum_never_attributes_a_position_to_an_agent():
    """FR-031: the retry addendum for adjudication disagreement must not say
    which agent held which position."""
    settings = _settings()
    provider = FakeProvider(True, 95)
    browser = FakeBrowserSession()
    stage_log = StageEventLog.__new__(StageEventLog)
    stage_log.timed = lambda *a, **k: _NullContext()
    cost_ledger = CostLedger.__new__(CostLedger)
    cost_ledger.record = lambda **k: None
    fetch_log = FetchLog.__new__(FetchLog)

    addendum = RetryAddendum(
        kind="disagreement_points",
        items=["The two positions differ on whether a mobile app is offered."],
    )
    question = {
        "question_id": "q1", "text": "Does X exist?", "answer_type": "binary",
        "evidence_locus": "national_portal_only",
    }

    await run_assessor_agent(
        session_id="s1", question=question, portal_url="https://example.gov",
        agent_index=0, round_number=2, settings=settings, provider=provider,
        browser=browser, fetch_log=fetch_log, stage_log=stage_log,
        cost_ledger=cost_ledger, addendum=addendum,
    )

    prompt = provider.calls[0]["prompt"]
    assert "Agent 0" not in prompt
    assert "Agent 1" not in prompt
    assert "agent_index" not in prompt.lower()


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
