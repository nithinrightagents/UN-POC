"""Unit tests for Phase 10 telemetry reports and hygiene (T110, T111)."""

import sqlite3
from datetime import UTC

from core.telemetry.cost_ledger import CostLedger
from core.telemetry.fetch_log import FetchLog
from core.telemetry.reports import (
    get_cost_report,
    get_fetches_report,
    get_telemetry_summary,
    get_timings_report,
)
from core.telemetry.stage_events import StageEventLog
from core.telemetry.verify import verify_no_credentials, verify_telemetry_hygiene
from shared.persistence.schema import DDL


def test_telemetry_reports_and_hygiene():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)

    session_id = "sess-tel-1"

    from datetime import datetime
    now = datetime.now(UTC)

    # 1. Log telemetry data
    fetch_log = FetchLog(conn, session_id)
    fetch_log.record("eesti.ee", "assessor_agent", 0.015)
    fetch_log.record("eesti.ee", "validator", 0.010)

    stage_log = StageEventLog(conn, session_id)
    stage_log.record("assessor_run", {"question_id": "Q1", "portal_id": "portal-EE"}, now, now, "success")

    cost_ledger = CostLedger(conn, session_id)
    cost_ledger.record("assessor_run", "gemini-2.0-flash", 100, 50, 0.00015, agent_index=0)

    # 2. Test reports
    fetches = get_fetches_report(conn, session_id)
    assert fetches["total_assessor_fetches"] == 1
    assert fetches["total_validator_fetches"] == 1

    timings = get_timings_report(conn, session_id)
    assert len(timings["stages"]) == 1

    cost = get_cost_report(conn, session_id)
    assert cost["total_cost_usd"] > 0

    summary = get_telemetry_summary(conn, session_id)
    assert summary["session_id"] == session_id

    # 3. Test hygiene verification
    hygiene = verify_telemetry_hygiene(conn, session_id)
    assert hygiene.clean is True

    no_creds = verify_no_credentials(conn)
    assert no_creds.clean is True
