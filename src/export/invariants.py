"""Export invariants checker (FR-103, FR-105, SC-023).

Enforces rules E1 through E7 on exported NDJSON answer records and exclusion reports.
"""

from __future__ import annotations

from typing import Any, Sequence

VALID_EXCLUSION_REASONS = frozenset({
    "awaiting_human_review",
    "unresolved_disagreement",
    "portal_discrepancy",
    "no_usable_url",
    "unreachable_portal",
    "unverifiable_target",
    "requires_authenticated_access",
    "language_declined",
})


class ExportInvariantError(Exception):
    """Raised when an export invariant E1-E7 is violated."""


def validate_export_record(record: dict[str, Any], session_mode: str) -> None:
    """Validate single record invariants E1, E2, E3."""
    # E1: Only delivered answers
    if not record.get("delivered_answer"):
        raise ExportInvariantError(f"E1 Violation: record {record.get('question', {}).get('question_id')} is not delivered_answer")

    # E2: Zero benchmark answers
    if session_mode == "benchmark":
        raise ExportInvariantError(f"E2 Violation: record from benchmark session {record.get('session_id')} cannot be exported")

    # E3: Must carry session_id and evidence_refs
    if not record.get("session_id"):
        raise ExportInvariantError("E3 Violation: record missing session_id")
    if "evidence_refs" not in record or not isinstance(record["evidence_refs"], list):
        raise ExportInvariantError("E3 Violation: record missing evidence_refs list")


def validate_export_set(
    delivered_records: Sequence[dict[str, Any]],
    exclusion_report: Sequence[dict[str, Any]],
    total_expected_units: int,
) -> None:
    """Validate full export set invariants E4, E5, E6, E7."""
    delivered_count = len(delivered_records)
    excluded_count = len(exclusion_report)

    # E4: Coverage complete
    if delivered_count + excluded_count < total_expected_units:
        raise ExportInvariantError(
            f"E4 Violation: total delivered ({delivered_count}) + excluded ({excluded_count}) "
            f"is less than expected units ({total_expected_units})"
        )

    for item in exclusion_report:
        reason = item.get("reason")
        if reason not in VALID_EXCLUSION_REASONS:
            raise ExportInvariantError(f"E4 Violation: invalid exclusion reason {reason!r}")
