"""Centralized LangSmith distributed tracing instrumentation (FR-T-001–FR-T-010).

Provides async context managers for every pipeline stage. All functions are
zero-overhead no-ops when LANGCHAIN_TRACING_V2 is not "true" or LANGSMITH_API_KEY is missing.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from typing import Any

from dotenv import dotenv_values

logger = logging.getLogger(__name__)


def _auto_load_tracing_env() -> None:
    if os.path.exists(".env"):
        values = dotenv_values(".env")
        for key in (
            "LANGCHAIN_TRACING_V2",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
        ):
            val = values.get(key)
            if val is not None and key not in os.environ:
                os.environ[key] = val
        if "LANGCHAIN_TRACING_V2" in os.environ:
            v = os.environ["LANGCHAIN_TRACING_V2"].strip().lower()
            if v in ("true", "1", "yes", "on"):
                os.environ["LANGCHAIN_TRACING_V2"] = "true"


_auto_load_tracing_env()


def is_tracing_enabled() -> bool:
    """Check if LangSmith tracing is active via environment configuration."""
    tracing_v2 = os.getenv("LANGCHAIN_TRACING_V2", os.getenv("LANGSMITH_TRACING", "")).strip().lower()
    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    return tracing_v2 in ("true", "1", "yes", "on") and bool(api_key)


class NoOpRunHandle:
    """Dummy run handle returned when tracing is disabled."""

    def patch(self, metadata: dict | None = None, outputs: dict | None = None) -> None:
        pass

    def end(self, outputs: dict | None = None, metadata: dict | None = None, error: str | None = None) -> None:
        pass

    run_tree: Any = None


class SafeRunHandle:
    """Wrapper around LangSmith RunTree providing robust patch/end and attribute access."""

    def __init__(self, run: Any = None):
        self._run = run

    @property
    def run_tree(self) -> Any:
        """The underlying `RunTree`, for passing as `parent=` to a child span.

        Explicit parent-passing (rather than relying on ambient contextvar
        propagation across `asyncio.TaskGroup`/`gather` task boundaries) is
        what actually keeps one run's spans nested under a single trace.
        """
        return self._run

    def patch(self, metadata: dict | None = None, outputs: dict | None = None) -> None:
        if self._run is None:
            return
        if metadata:
            if hasattr(self._run, "add_metadata"):
                self._run.add_metadata(metadata)
            elif hasattr(self._run, "metadata") and isinstance(self._run.metadata, dict):
                self._run.metadata.update(metadata)
        if outputs:
            if hasattr(self._run, "add_outputs"):
                self._run.add_outputs(outputs)
            elif hasattr(self._run, "outputs") and isinstance(self._run.outputs, dict):
                self._run.outputs.update(outputs)
        try:
            if hasattr(self._run, "patch"):
                self._run.patch()
        except Exception as exc:
            logger.debug(f"LangSmith run patch failed: {exc}")

    def end(self, outputs: dict | None = None, metadata: dict | None = None, error: str | None = None) -> None:
        if self._run is None:
            return
        if metadata:
            if hasattr(self._run, "add_metadata"):
                self._run.add_metadata(metadata)
        if outputs:
            if hasattr(self._run, "add_outputs"):
                self._run.add_outputs(outputs)
        try:
            if hasattr(self._run, "end"):
                self._run.end(outputs=outputs, metadata=metadata, error=error)
        except Exception as exc:
            logger.debug(f"LangSmith run end failed: {exc}")

    def __getattr__(self, name: str) -> Any:
        if self._run is not None:
            return getattr(self._run, name)
        raise AttributeError(f"'SafeRunHandle' has no attribute '{name}'")


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

    # Normalize environment variables in case they were set with capitalized True
    tracing_val = os.getenv("LANGCHAIN_TRACING_V2", os.getenv("LANGSMITH_TRACING", ""))
    if tracing_val and tracing_val != "true" and tracing_val.strip().lower() in ("true", "1", "yes", "on"):
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_TRACING"] = "true"
        try:
            from langsmith.utils import get_env_var
            get_env_var.cache_clear()
        except Exception:
            pass

    api_key = os.getenv("LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", ""))
    if api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", api_key.strip())
        os.environ.setdefault("LANGCHAIN_API_KEY", api_key.strip())

    project = os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", ""))
    if project:
        os.environ.setdefault("LANGSMITH_PROJECT", project.strip())
        os.environ.setdefault("LANGCHAIN_PROJECT", project.strip())

    try:
        cm = langsmith.trace(
            name,
            run_type=run_type,
            inputs=inputs,
            metadata=metadata,
            tags=tags,
            parent=parent,
        )
        run = await cm.__aenter__()
    except Exception as exc:
        logger.warning(f"LangSmith trace upload failed: {exc}")
        yield NoOpRunHandle()
        return

    try:
        yield SafeRunHandle(run)
    except Exception:
        exc_type, exc_val, exc_tb = sys.exc_info()
        try:
            await cm.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as exit_exc:
            logger.warning(f"LangSmith trace upload failed: {exit_exc}")
        raise
    else:
        try:
            await cm.__aexit__(None, None, None)
        except Exception as exit_exc:
            logger.warning(f"LangSmith trace upload failed: {exit_exc}")


@contextlib.asynccontextmanager
async def batch_trace(
    session_id: str,
    portal_count: int,
    question_count: int,
    run_id: str | None = None,
    portal_ids: list[str] | None = None,
    question_ids: list[str] | None = None,
):
    """Root trace for a full assessment batch run across multiple units (FR-T-001)."""
    name = f"assessment_run[{session_id}]" if session_id else "assessment_run"
    inputs = {
        "session_id": session_id,
        "run_id": run_id or session_id,
        "portal_count": portal_count,
        "question_count": question_count,
        "portal_ids": portal_ids or [],
        "question_ids": question_ids or [],
    }
    metadata = {
        "session_id": session_id,
        "run_id": run_id or session_id,
        "portal_count": portal_count,
        "question_count": question_count,
    }
    async with safe_trace(
        name,
        run_type="chain",
        inputs=inputs,
        metadata=metadata,
        tags=[session_id] if session_id else [],
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def unit_trace(
    session_id: str,
    question_id: str,
    portal_id: str,
    question_text: str,
    portal_url: str,
    parent: Any = None,
):
    """Trace span for a single process_unit execution (FR-T-001, FR-T-008).

    `parent` should be the batch trace's `run_tree` so every unit in one
    batch run nests under that single trace instead of each becoming its
    own root (ambient contextvar propagation across `TaskGroup.create_task`
    is not reliable enough to depend on for this)."""
    name = f"process_unit[{question_id}@{portal_id}]" if (question_id and portal_id) else (f"process_unit[{question_id}]" if question_id else "process_unit")
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
        name,
        run_type="chain",
        inputs=inputs,
        metadata=metadata,
        tags=[session_id],
        parent=parent,
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def agent_trace(
    agent_index: int,
    round_number: int,
    model: str,
    temperature: float,
    profile: str,
    parent: Any = None,
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
        parent=parent,
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def confidence_gate_trace(
    retry_count: int,
    has_addendum: bool,
    addendum_kind: str | None = None,
    parent: Any = None,
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
        parent=parent,
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def validation_trace(
    retry_number: int,
    agent_index: int,
    round_number: int,
    parent: Any = None,
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
        parent=parent,
    ) as run:
        yield run


@contextlib.asynccontextmanager
async def adjudication_trace(
    round_number: int,
    is_retry: bool = False,
    parent: Any = None,
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
        parent=parent,
    ) as run:
        yield run
