"""T033: Unit tests for level-of-government rule in assessor prompt rubric.

Replaces test_jurisdiction.py which tested the regex now deleted in T035.
"""

import pytest
from shared.prompts.profiles import build_prompt, render_rubric_section

pytestmark = pytest.mark.unit


def test_level_of_government_rule_in_rubric_section():
    rubric = render_rubric_section(
        title="Driving Licences",
        what="Online application for driving licence",
    )
    assert "Level of government:" in rubric
    assert "judge the level of government against the service, not the domain" in rubric.lower()
    assert "constitutionally delivered by states or municipalities" in rubric.lower()


def test_level_of_government_rule_in_built_prompt():
    prompt = build_prompt(
        question_text="Can citizens renew driving licences online?",
        answer_type="binary",
        evidence_locus="any_government_domain",
        page_text="State DMV portal",
        profile="literal",
        title="Driving Licences",
    )
    assert "Level of government:" in prompt
    assert "never answer no merely because the service is not run federally" in prompt.lower()
