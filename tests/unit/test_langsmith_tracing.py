"""Unit tests for LangSmith distributed tracing helper module (FR-T-001–FR-T-010)."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from core.telemetry.langsmith_tracing import (
    NoOpRunHandle,
    adjudication_trace,
    agent_trace,
    batch_trace,
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


def test_is_tracing_enabled_case_insensitive(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "True")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test")
    assert is_tracing_enabled()


def test_safe_run_handle_patch_and_end():
    from unittest.mock import MagicMock
    from core.telemetry.langsmith_tracing import SafeRunHandle

    mock_run = MagicMock()
    handle = SafeRunHandle(mock_run)

    # Calling patch with outputs and metadata must not raise TypeError
    handle.patch(metadata={"key": "val"}, outputs={"answer": "yes"})
    mock_run.add_metadata.assert_called_once_with({"key": "val"})
    mock_run.add_outputs.assert_called_once_with({"answer": "yes"})
    mock_run.patch.assert_called_once()

    # Calling end
    handle.end(outputs={"final": 1}, metadata={"meta": 2})
    mock_run.end.assert_called_once()


@pytest.mark.asyncio
async def test_batch_trace_returns_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    async with batch_trace("sess_1", 1, 5, "run_1", ["P1"], ["Q1", "Q2"]) as handle:
        assert isinstance(handle, NoOpRunHandle)
        handle.patch(metadata={"done": True}, outputs={"total": 5})


