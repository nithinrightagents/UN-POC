"""Unit tests for LangSmith distributed tracing helper module (FR-T-001–FR-T-010)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from core.telemetry.langsmith_tracing import (
    NoOpRunHandle,
    adjudication_trace,
    agent_trace,
    confidence_gate_trace,
    is_tracing_enabled,
    safe_trace,
    unit_trace,
    validation_trace,
)


def test_is_tracing_enabled_when_unset(monkeypatch):
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert not is_tracing_enabled()


def test_is_tracing_enabled_when_true_with_key(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_123456789")
    assert is_tracing_enabled()


def test_is_tracing_enabled_when_true_without_key(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert not is_tracing_enabled()


@pytest.mark.asyncio
async def test_safe_trace_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    async with safe_trace("test_span") as handle:
        assert isinstance(handle, NoOpRunHandle)
        # Verify no-op methods do not raise
        handle.patch(metadata={"foo": "bar"})
        handle.end()


@pytest.mark.asyncio
async def test_safe_trace_suppresses_exceptions(monkeypatch, caplog):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test")

    with patch("langsmith.trace", side_effect=RuntimeError("LangSmith network timeout")):
        async with safe_trace("test_span") as handle:
            assert isinstance(handle, NoOpRunHandle)

    assert "LangSmith trace upload failed: LangSmith network timeout" in caplog.text


@pytest.mark.asyncio
async def test_unit_trace_returns_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    async with unit_trace("sess_1", "q_1", "p_1", "Question text", "http://example.gov") as handle:
        assert isinstance(handle, NoOpRunHandle)


@pytest.mark.asyncio
async def test_agent_trace_returns_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    async with agent_trace(0, 1, "gemini-2.0-flash", 0.2, "literal") as handle:
        assert isinstance(handle, NoOpRunHandle)


@pytest.mark.asyncio
async def test_confidence_gate_trace_returns_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    async with confidence_gate_trace(0, False) as handle:
        assert isinstance(handle, NoOpRunHandle)


@pytest.mark.asyncio
async def test_validation_trace_returns_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    async with validation_trace(0, 0, 1) as handle:
        assert isinstance(handle, NoOpRunHandle)


@pytest.mark.asyncio
async def test_adjudication_trace_returns_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    async with adjudication_trace(1, is_retry=False) as handle:
        assert isinstance(handle, NoOpRunHandle)
