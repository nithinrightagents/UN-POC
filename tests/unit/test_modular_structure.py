"""Unit test verifying the modular folder structure pivot."""

import pytest
from unittest.mock import MagicMock

from core.base_agent import BaseAgent
from core.llm_factory import ModelProvider, ModelResponse, estimate_cost
from core.telemetry import CostLedger, FetchLog, StageEventLog
from shared.state import AssessorAgentInput, AssessorAgentOutput, QuestionInput, PortalInput
from shared.tools import BrowserSession
from shared.prompts import build_prompt, PROFILE_VERSION
from agents.assessor import AssessorAgent, assessor_node
from agents.validator import ValidatorAgent, validator_node
from agents.adjudicator import AdjudicatorAgent, adjudicator_node
from agents.portal_adjudicator import PortalAdjudicatorAgent, portal_adjudicator_node
from orchestration.routers import language_requires_decision
from orchestration.workflow import BatchRunSummary, UnitOutcome, run_batch, process_unit


@pytest.mark.unit
def test_core_imports():
    assert issubclass(BaseAgent, object)
    assert ModelProvider is not None
    assert estimate_cost("vertexai/gemini-1.5-flash", 1000, 1000) > 0


@pytest.mark.unit
def test_shared_state_imports():
    q = QuestionInput(
        question_id="q1",
        text="Is there an e-portal?",
        answer_type="binary",
        evidence_locus="national_portal_only",
    )
    p = PortalInput(portal_id="p1", resolved_url="https://example.gov")
    inp = AssessorAgentInput(
        session_id="s1",
        agent_index=0,
        round_number=1,
        question=q,
        portal=p,
    )
    assert inp.session_id == "s1"


@pytest.mark.unit
def test_agent_instantiations():
    provider = ModelProvider(project="test-proj", location="us-central1")
    limiter = MagicMock()
    browser = BrowserSession(user_agent="EKAP-AIQ-Bot/1.0", limiter=limiter)
    
    assessor = AssessorAgent(provider=provider, browser=browser)
    validator = ValidatorAgent()
    adjudicator = AdjudicatorAgent()
    portal_adjudicator = PortalAdjudicatorAgent()

    assert assessor.name == "AssessorAgent"
    assert validator.name == "ValidatorAgent"
    assert adjudicator.name == "AdjudicatorAgent"
    assert portal_adjudicator.name == "PortalAdjudicatorAgent"


@pytest.mark.unit
def test_orchestration_router():
    assert language_requires_decision("fr", ["en"]) is True
    assert language_requires_decision("en", ["en"]) is False


@pytest.mark.unit
def test_orchestration_workflow_exports():
    summary = BatchRunSummary()
    assert summary.delivered == 0
