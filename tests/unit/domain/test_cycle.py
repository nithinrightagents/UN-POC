"""Unit tests for questionnaire assembly and cycle rules (FR-057)."""

from shared.state.cycle import assemble_questionnaire
from shared.state.entities import AnswerType, EvidenceLocus, Question


def test_assemble_questionnaire_excludes_prior_cycle_custom_questions():
    q1 = Question("OSQ-1.01", "2026-cycle", "Standard Q1", AnswerType.BINARY, EvidenceLocus.NATIONAL_PORTAL_ONLY, is_custom=False)
    q2 = Question("OSQ-1.02", "2026-cycle", "Standard Q2", AnswerType.BINARY, EvidenceLocus.NATIONAL_PORTAL_ONLY, is_custom=False)
    q_custom_prior = Question("OSQ-C-99", "2024-cycle", "Old Custom Q", AnswerType.BINARY, EvidenceLocus.NATIONAL_PORTAL_ONLY, is_custom=True)
    q_custom_current = Question("OSQ-C-01", "2026-cycle", "New Custom Q", AnswerType.BINARY, EvidenceLocus.NATIONAL_PORTAL_ONLY, is_custom=True)

    all_qs = [q1, q2, q_custom_prior, q_custom_current]

    assembled = assemble_questionnaire("2026-cycle", all_qs)

    assembled_ids = [q.question_id for q in assembled]
    assert "OSQ-1.01" in assembled_ids
    assert "OSQ-1.02" in assembled_ids
    assert "OSQ-C-01" in assembled_ids
    assert "OSQ-C-99" not in assembled_ids, "Prior cycle custom question must be excluded (FR-057)"
