"""Telemetry and tracing package for EKAP AIQ."""

from __future__ import annotations

from core.telemetry.cost_ledger import CostLedger, CostLedgerEntry
from core.telemetry.fetch_log import FetchLog
from core.telemetry.hygiene import scan_for_credentials, scan_for_ground_truth
from core.telemetry.langsmith_tracing import (
    adjudication_trace,
    agent_trace,
    batch_trace,
    confidence_gate_trace,
    is_tracing_enabled,
    safe_trace,
    unit_trace,
    validation_trace,
)
from core.telemetry.reports import get_telemetry_summary
from core.telemetry.stage_events import StageEvent, StageEventLog

__all__ = [
    "CostLedger",
    "CostLedgerEntry",
    "FetchLog",
    "StageEventLog",
    "StageEvent",
    "scan_for_credentials",
    "scan_for_ground_truth",
    "get_telemetry_summary",
    "is_tracing_enabled",
    "safe_trace",
    "batch_trace",
    "unit_trace",
    "agent_trace",
    "confidence_gate_trace",
    "validation_trace",
    "adjudication_trace",
]
