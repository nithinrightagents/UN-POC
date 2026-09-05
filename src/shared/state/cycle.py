"""Questionnaire assembly and survey cycle domain logic.

FR-057: Prior-cycle custom questions are excluded from new cycle questionnaire assembly.
"""

from __future__ import annotations

from collections.abc import Sequence

from .entities import Question


def assemble_questionnaire(
    current_cycle_id: str,
    all_questions: Sequence[Question],
) -> list[Question]:
    """Assemble the active questionnaire for a cycle.

    Includes standard questions (is_custom=False) and custom questions created
    specifically for current_cycle_id (is_custom=True and cycle_id == current_cycle_id).
    Excludes custom questions from prior/other cycles (FR-057).
    """
    assembled: list[Question] = []
    for q in all_questions:
        if not q.is_custom:
            assembled.append(q)
        elif q.cycle_id == current_cycle_id:
            assembled.append(q)
    return assembled
