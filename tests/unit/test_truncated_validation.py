"""Regression tests for the truncated-page validation short-circuit (T024).

A page the assessor's own output flagged as truncated (page_text_truncated=True)
should never be scored as a mechanical quality failure when the cited element
cannot be relocated -- the quote may simply sit past the 15,000-char cutoff.
This must be caught BEFORE the Validator's judgment model call, and it must
not look like an ordinary element_absent failure to the retry loop (T025).
"""

from __future__ import annotations

import pytest

import agents.validator.agent as validator_agent_module
from agents.validator.agent import validate_agent_output
from agents.validator.tools.evidence_verification import VerificationAttemptResult
from shared.state.entities import ElementReference, VerificationOutcome
from shared.state.schemas import AssessorAgentOutput, ElementReferenceOutput, EvidenceOutput

pytestmark = pytest.mark.unit


class _ExplodingProvider:
    """Any call to .generate() means the judgment step ran -- it must not,
    for a truncated/unlocatable page."""

    async def generate(self, *args, **kwargs):
        raise AssertionError("judgment model should not be called for a truncated page")


class _FakeBrowser:
    pass


class _FakeFetchLog:
    def record(self, *args, **kwargs):
        pass


class _FakeCostLedger:
    def record(self, *args, **kwargs):
        pass


def _make_output(*, page_text_truncated: bool, page_text_excess_chars: int = 0) -> AssessorAgentOutput:
    return AssessorAgentOutput(
        answer=True,
        confidence=70,
        justification="The page lists this benefit under a heading.",
        evidence=EvidenceOutput(
            resolved_url="https://example.gov/benefits",
            element_reference=ElementReferenceOutput(css_path="main > h2", text_hash="abc123"),
            element_text="Unemployment Benefits",
        ),
        page_text_truncated=page_text_truncated,
        page_text_excess_chars=page_text_excess_chars,
    )


async def _run_validation(monkeypatch, output: AssessorAgentOutput, outcome: str):
    async def _fake_verify_with_retry(browser, resolved_url, reference, expected_text, fetch_log, attempt_bound, timeout_ms=None):
        return VerificationAttemptResult(outcome=outcome, detail="not found in re-fetched DOM"), 1

    monkeypatch.setattr(validator_agent_module, "verify_with_retry", _fake_verify_with_retry)

    class _FakeSettings:
        verification_attempt_bound = 2
        page_navigation_timeout_ms = 45000
        validator_model = "test-model"

    return await validate_agent_output(
        run_id="run-truncated",
        session_id="s-truncated",
        question_text="Does the portal describe unemployment benefits?",
        output=output,
        element_reference=ElementReference(css_path="main > h2", text_hash="abc123"),
        settings=_FakeSettings(),
        provider=_ExplodingProvider(),
        browser=_FakeBrowser(),
        fetch_log=_FakeFetchLog(),
        cost_ledger=_FakeCostLedger(),
        retry_number=0,
    )


@pytest.mark.asyncio
async def test_element_absent_on_truncated_page_short_circuits(monkeypatch):
    output = _make_output(page_text_truncated=True, page_text_excess_chars=4200)
    result = await _run_validation(monkeypatch, output, outcome="element_absent")

    assert result.verification_outcome == VerificationOutcome.TRUNCATED_UNVERIFIABLE
    assert result.passed is False
    assert result.quality_score == 0.0
    assert "4200" in result.gaps[0]


@pytest.mark.asyncio
async def test_element_absent_on_a_non_truncated_page_is_unchanged(monkeypatch):
    output = _make_output(page_text_truncated=False)
    result = await _run_validation(monkeypatch, output, outcome="element_absent")

    assert result.verification_outcome == VerificationOutcome.ELEMENT_ABSENT
    assert result.quality_score == 0.2


@pytest.mark.asyncio
async def test_text_mismatch_on_truncated_page_is_not_special_cased(monkeypatch):
    # Only element_absent is ambiguous under truncation -- a text_mismatch
    # means the element WAS found, just with different text, which
    # truncation cannot explain.
    output = _make_output(page_text_truncated=True, page_text_excess_chars=500)
    result = await _run_validation(monkeypatch, output, outcome="text_mismatch")

    assert result.verification_outcome == VerificationOutcome.TEXT_MISMATCH
