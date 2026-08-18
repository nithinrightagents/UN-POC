"""Question identity helpers (spec 007 FR-API-011a)."""

from __future__ import annotations

from dataclasses import dataclass


def compose_question_id(cycle_id: str, indicator_id: str) -> str:
    """Canonical question_id composition: f'{cycle_id}:{indicator_id}'."""
    return f"{cycle_id}:{indicator_id}"


@dataclass
class QuestionIdentity:
    question_id: str
    indicator_id: str
