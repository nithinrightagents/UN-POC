from benchmark.attribution import PipelineStage, attribute
from benchmark.trace import UnitResolutionTrace
from shared.state.entities import GroundTruthAnswer, new_id


def test_exact_match_names_supplying_source():
    reference = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="SP-095",
        country_id="US",
        correct_answer=True,
        label_source="test",
        assigned_by="expert",
        reference_url="https://www.usa.gov/health",
        no_valid_link=False,
    )
    trace = UnitResolutionTrace(
        question_id="SP-095",
        portal_id="portal-us",
        resolved_url="https://usa.gov/health/",
        supplying_source="sitemap",
        link_escalated_off_portal=False,
        evidence_locus_violation=None,
        prefill_reason=None,
        terminal_state="assessed",
        resolution_history=({"source": "sitemap", "usable": True, "returned": "https://usa.gov/health/"},),
        assessor_answer=True,
        assessor_justification="Found health services page",
    )

    attr = attribute(trace, reference)
    assert attr.stage == PipelineStage.SITEMAP
    assert "sitemap" in attr.reason.lower()


def test_every_source_exhausted_lists_reasons():
    reference = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="SP-043",
        country_id="US",
        correct_answer=True,
        label_source="test",
        assigned_by="expert",
        reference_url="https://www.irs.gov/freefile",
        no_valid_link=False,
    )
    trace = UnitResolutionTrace(
        question_id="SP-043",
        portal_id="portal-us",
        resolved_url=None,
        supplying_source=None,
        link_escalated_off_portal=True,
        evidence_locus_violation=None,
        prefill_reason="no_usable_evidence",
        terminal_state="unassessable",
        resolution_history=(
            {"source": "prior_survey_kb", "usable": False, "rejection_reason": "no prior link cached"},
            {"source": "sitemap", "usable": False, "rejection_reason": "keyword mismatch"},
            {"source": "search", "usable": False, "rejection_reason": "returned CSV file analytics.usa.gov"},
        ),
    )

    attr = attribute(trace, reference)
    assert attr.stage in (PipelineStage.PRIOR_SURVEY_KB, PipelineStage.SEARCH)
    assert len(attr.source_details) == 3
    assert "no prior link cached" in attr.reason
    assert "keyword mismatch" in attr.reason
    assert "analytics.usa.gov" in attr.reason


def test_locus_refusal_names_gate_and_refused_url():
    reference = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="IF-010",
        country_id="US",
        correct_answer=True,
        label_source="test",
        assigned_by="expert",
        reference_url="https://www.usa.gov/org-chart",
        no_valid_link=False,
    )
    trace = UnitResolutionTrace(
        question_id="IF-010",
        portal_id="portal-us",
        resolved_url="https://state.gov/org-chart",
        supplying_source="search",
        link_escalated_off_portal=True,
        evidence_locus_violation={
            "candidate_url": "https://state.gov/org-chart",
            "reason": "national_portal_only indicator cannot accept state.gov domain",
        },
        prefill_reason="evidence_locus_violation",
        terminal_state="unassessable",
        resolution_history=(),
    )

    attr = attribute(trace, reference)
    assert attr.stage == PipelineStage.LOCUS_GATE
    assert attr.refused_url == "https://state.gov/org-chart"
    assert "national_portal_only" in attr.reason


def test_never_widened_distinguished_from_widened_and_failed():
    reference = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="CP-030",
        country_id="US",
        correct_answer=True,
        label_source="test",
        assigned_by="expert",
        reference_url="https://www.usaspending.gov/search",
        no_valid_link=False,
    )

    # 1. Never widened: settled for portal_default
    trace_never_widened = UnitResolutionTrace(
        question_id="CP-030",
        portal_id="portal-us",
        resolved_url="https://www.usa.gov/",
        supplying_source="portal_default",
        link_escalated_off_portal=False,
        evidence_locus_violation=None,
        prefill_reason=None,
        terminal_state="assessed",
        resolution_history=({"source": "portal_default", "usable": True, "returned": "https://www.usa.gov/"},),
    )
    attr_never = attribute(trace_never_widened, reference)
    assert attr_never.escalation_status == "never_widened"
    assert attr_never.stage == PipelineStage.OFF_PORTAL_ESCALATION

    # 2. Widened and failed
    trace_widened_failed = UnitResolutionTrace(
        question_id="CP-030",
        portal_id="portal-us",
        resolved_url="https://www.wronggov.gov/something",
        supplying_source="search",
        link_escalated_off_portal=True,
        evidence_locus_violation=None,
        prefill_reason=None,
        terminal_state="assessed",
        resolution_history=({"source": "search", "usable": True, "returned": "https://www.wronggov.gov/something"},),
    )
    attr_widened = attribute(trace_widened_failed, reference)
    assert attr_widened.escalation_status == "widened_and_failed"


def test_correct_link_with_negative_answer_attributes_to_assessment():
    reference = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="IF-337",
        country_id="US",
        correct_answer=True,
        label_source="test",
        assigned_by="expert",
        reference_url="https://www.cio.gov/about/leadership/",
        no_valid_link=False,
    )
    trace = UnitResolutionTrace(
        question_id="IF-337",
        portal_id="portal-us",
        resolved_url="https://www.cio.gov/about/leadership/",
        supplying_source="search",
        link_escalated_off_portal=True,
        evidence_locus_violation=None,
        prefill_reason=None,
        terminal_state="assessed",
        resolution_history=(),
        assessor_answer=False,
        assessor_justification="Federal CIO name not explicitly mentioned on this page",
        fill_gap_reason="missing leadership detail",
        page_text_truncated=True,
        page_text_excess_chars=2797,
    )

    attr = attribute(trace, reference)
    assert attr.stage == PipelineStage.ASSESSMENT
    assert "Federal CIO" in attr.reason or "missing leadership detail" in attr.reason
    assert attr.page_truncated is True
    assert attr.excess_chars == 2797


def test_environmental_failure_classification():
    reference = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="SP-095",
        country_id="US",
        correct_answer=True,
        label_source="test",
        assigned_by="expert",
        reference_url="https://www.usa.gov/health",
        no_valid_link=False,
    )
    trace = UnitResolutionTrace(
        question_id="SP-095",
        portal_id="portal-us",
        resolved_url=None,
        supplying_source=None,
        link_escalated_off_portal=False,
        evidence_locus_violation=None,
        prefill_reason="portal_unreachable",
        terminal_state="unassessable",
        portal_unreachable=True,
        resolution_history=(),
    )

    attr = attribute(trace, reference)
    assert attr.stage == PipelineStage.ENVIRONMENT
