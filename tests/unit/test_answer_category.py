"""Unit tests for the reviewer-facing yes/maybe/no answer category (spec 011 Step 5 pivot).

There are exactly three reviewer-facing outcomes -- no fourth bucket. A unit that
never formed any answer (`suggested=False`) reads the same as a flagged one
(`NEEDS_HUMAN_REVIEW`): both fold into "maybe". Only a clean, unflagged answer
earns a hard "yes" or "no".
"""

from __future__ import annotations

import pytest

from shared.state.entities import Prefill, PrefillReason, new_id, prefill_answer_category

pytestmark = pytest.mark.unit


def _prefill(**overrides) -> Prefill:
    fields = dict(
        prefill_id=new_id("pf"),
        run_id="run-1",
        session_id="session-1",
        cycle_id="cycle-1",
        question_id="q-1",
        portal_id="portal-1",
        suggested=False,
        answer=None,
        reason=PrefillReason.NO_USABLE_EVIDENCE,
    )
    fields.update(overrides)
    return Prefill(**fields)


def test_withheld_prefill_is_maybe():
    prefill = _prefill(suggested=False, answer=None, reason=PrefillReason.NO_USABLE_EVIDENCE)
    assert prefill.answer_category() == "maybe"


def test_flagged_true_answer_is_maybe():
    prefill = _prefill(suggested=True, answer=True, reason=PrefillReason.NEEDS_HUMAN_REVIEW)
    assert prefill.answer_category() == "maybe"


def test_flagged_false_answer_is_maybe():
    prefill = _prefill(suggested=True, answer=False, reason=PrefillReason.NEEDS_HUMAN_REVIEW)
    assert prefill.answer_category() == "maybe"


def test_clean_true_answer_is_yes():
    prefill = _prefill(suggested=True, answer=True, reason=None)
    assert prefill.answer_category() == "yes"


def test_clean_false_answer_is_no():
    prefill = _prefill(suggested=True, answer=False, reason=None)
    assert prefill.answer_category() == "no"


@pytest.mark.parametrize(
    "suggested,answer,reason,expected",
    [
        (False, None, PrefillReason.NO_USABLE_EVIDENCE, "maybe"),
        (False, None, None, "maybe"),
        (True, True, PrefillReason.NEEDS_HUMAN_REVIEW, "maybe"),
        (True, False, PrefillReason.NEEDS_HUMAN_REVIEW, "maybe"),
        (True, True, PrefillReason.NEEDS_HUMAN_REVIEW.value, "maybe"),
        (True, True, None, "yes"),
        (True, False, None, "no"),
    ],
)
def test_prefill_answer_category_free_function(suggested, answer, reason, expected):
    assert prefill_answer_category(suggested, answer, reason) == expected
