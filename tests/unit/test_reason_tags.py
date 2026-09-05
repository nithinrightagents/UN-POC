"""Reason Tag lookup tests (FR-BF-005, FR-BF-006). See
specs/004-blank-field-fallback/contracts/reason-tags.md and quickstart.md Scenario 3.
"""

from __future__ import annotations

import pytest

from shared.state.entities import EscalationReason, PrefillReason
from shared.state.reason_tags import prefill_reason_tag, reason_tag

pytestmark = pytest.mark.unit

_FIXTURE_CONTEXT = {
    "detected_language": "fr",
    "attempts": 3,
}


@pytest.mark.parametrize(
    "reason", [r for r in EscalationReason if r is not EscalationReason.PORTAL_DISCREPANCY]
)
def test_every_escalation_reason_has_a_template(reason):
    tag = reason_tag(reason.value, _FIXTURE_CONTEXT)
    assert tag.text.startswith("Left blank: ")
    assert tag.condition is reason


def test_language_declined_sub_cases_differ():
    explicit = reason_tag(
        EscalationReason.LANGUAGE_DECLINED.value, _FIXTURE_CONTEXT, resolution_manner="explicit"
    )
    expired = reason_tag(
        EscalationReason.LANGUAGE_DECLINED.value, _FIXTURE_CONTEXT, resolution_manner="window_expired"
    )
    assert explicit.text != expired.text
    assert explicit.text
    assert expired.text


def test_determinism():
    first = reason_tag(EscalationReason.UNREACHABLE_PORTAL.value, _FIXTURE_CONTEXT)
    second = reason_tag(EscalationReason.UNREACHABLE_PORTAL.value, _FIXTURE_CONTEXT)
    assert first.text == second.text


def test_unrecognized_reason_raises_keyerror():
    with pytest.raises(KeyError):
        reason_tag("not_a_real_reason", {})


def test_portal_discrepancy_has_no_template():
    with pytest.raises(KeyError):
        reason_tag(EscalationReason.PORTAL_DISCREPANCY.value, {})


@pytest.mark.parametrize(
    "reason", [r for r in PrefillReason if r is not PrefillReason.NEEDS_HUMAN_REVIEW]
)
def test_every_prefill_reason_has_a_template(reason):
    tag = prefill_reason_tag(reason.value, _FIXTURE_CONTEXT)
    assert tag.text.startswith("No suggestion: ")
    assert tag.condition is reason


def test_needs_human_review_is_delivered_not_a_no_suggestion():
    # Unlike every other PrefillReason, this one accompanies a delivered
    # (suggested=True) prefill -- "No suggestion: ..." would misdescribe it.
    tag = prefill_reason_tag(PrefillReason.NEEDS_HUMAN_REVIEW.value, _FIXTURE_CONTEXT)
    assert tag.text.startswith("Needs review: ")
    assert tag.condition is PrefillReason.NEEDS_HUMAN_REVIEW


def test_unrecognized_prefill_reason_raises_keyerror():
    with pytest.raises(KeyError):
        prefill_reason_tag("not_a_real_prefill_reason", {})

