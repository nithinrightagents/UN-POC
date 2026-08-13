"""Centralized LangSmith distributed tracing instrumentation (FR-T-001–FR-T-010).

Provides async context managers for every pipeline stage. All functions are
zero-overhead no-ops when LANGCHAIN_TRACING_V2 is not "true" or LANGSMITH_API_KEY is missing.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is active via environment configuration."""
    tracing_v2 = os.getenv("LANGCHAIN_TRACING_V2", "").strip().lower()
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    return tracing_v2 in ("true", "1") and bool(api_key)


class NoOpRunHandle:
    """Dummy run handle returned when tracing is disabled."""

    def patch(self, metadata: dict | None = None, outputs: dict | None = None) -> None:
        pass

    def end(self, outputs: dict | None = None) -> None:
        pass


@contextlib.asynccontextmanager
async def safe_trace(
    name: str,
    run_type: str = "chain",
    inputs: dict | None = None,
    metadata: dict | None = None,
    tags: list[str] | None = None,
    parent: Any = None,
):
    """Async context manager wrapping langsmith.trace with non-fatal error handling (FR-T-007)."""
    if not is_tracing_enabled():
        yield NoOpRunHandle()
        return

    try:
        import langsmith
    except ImportError:
        yield NoOpRunHandle()
        return

    try:
        async with langsmith.trace(
            name,
            run_type=run_type,
            inputs=inputs,
            metadata=metadata,
            tags=tags,
            parent=parent,
        ) as run:
            yield run
    except Exception as exc:
        logger.warning(f"LangSmith trace upload failed: {exc}")
        yield NoOpRunHandle()


@contextlib.asynccontextmanager
async def unit_trace(
    session_id: str,
    question_id: str,
    portal_id: str,
    question_text: str,
    portal_url: str,
):
    """Root trace for a single process_unit execution (FR-T-001, FR-T-008)."""
    inputs = {
        "session_id": session_id,
        "question_id": question_id,
        "portal_id": portal_id,
        "question_text": question_text,
        "portal_url": portal_url,
    }
    metadata = {
        "session_id": session_id,
        "question_id": question_id,
        "portal_id": portal_id,
    }
    async with safe_trace(
        "process_unit",
        run_type="chain",
        inputs=inputs,
        metadata=metadata,
        tags=[session_id],
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def agent_trace(
    agent_index: int,
    round_number: int,
    model: str,
    temperature: float,
    profile: str,
):
    """Child span for an assessor_agent execution (FR-T-002, FR-T-005)."""
    name = f"assessor_agent[{agent_index}]"
    inputs = {
        "agent_index": agent_index,
        "round_number": round_number,
        "model": model,
        "temperature": temperature,
        "profile": profile,
    }
    metadata = {
        "agent_index": agent_index,
        "round_number": round_number,
    }
    async with safe_trace(
        name,
        run_type="chain",
        inputs=inputs,
        metadata=metadata,
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def confidence_gate_trace(
    retry_count: int,
    has_addendum: bool,
    addendum_kind: str | None = None,
):
    """Child span for a confidence gate attempt (FR-T-002, FR-T-004)."""
    name = f"confidence_gate_attempt[{retry_count}]"
    inputs = {
        "retry_count": retry_count,
        "has_addendum": has_addendum,
        "addendum_kind": addendum_kind,
    }
    metadata = {
        "retry_type": "confidence_retry",
        "retry_number": retry_count,
    }
    async with safe_trace(
        name,
        run_type="chain",
        inputs=inputs,
        metadata=metadata,
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def validation_trace(
    retry_number: int,
    agent_index: int,
    round_number: int,
):
    """Child span for a validation attempt (FR-T-002, FR-T-004)."""
    name = f"validation_attempt[{retry_number}]"
    inputs = {
        "retry_number": retry_number,
        "agent_index": agent_index,
        "round_number": round_number,
    }
    metadata = {
        "retry_type": "validation_retry",
        "retry_number": retry_number,
        "agent_index": agent_index,
        "round_number": round_number,
    }
    async with safe_trace(
        name,
        run_type="chain",
        inputs=inputs,
        metadata=metadata,
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def adjudication_trace(
    round_number: int,
    is_retry: bool = False,
):
    """Child span for an adjudication evaluation (FR-T-002, FR-T-004)."""
    name = f"adjudication[round={round_number}]"
    inputs = {
        "round_number": round_number,
        "is_retry": is_retry,
    }
    metadata = (
        {"retry_type": "adjudication_retry", "round_number": round_number}
        if is_retry
        else {"round_number": round_number}
    )
    async with safe_trace(
        name,
        run_type="chain",
        inputs=inputs,
        metadata=metadata,
    ) as run:
        yield run
