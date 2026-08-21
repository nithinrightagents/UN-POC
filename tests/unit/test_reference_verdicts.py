import pytest
from benchmark.attribution import PipelineStage, attribute
from benchmark.diagnostics import IndicatorVerdict, check_url_staleness
from benchmark.trace import UnitResolutionTrace
from shared.state.entities import GroundTruthAnswer, new_id
import httpx


def test_no_valid_link_scores_portal_page_as_pass():
    # FR-LD-019: When no valid national link exists, returning portal's own page is a pass
    reference = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="SP-054",
        country_id="US",
        correct_answer=False,
        label_source="test",
        assigned_by="expert",
        reference_url=None,
        no_valid_link=True,
        accepted_alternatives=["https://www.usa.gov/renew-drivers-license", "https://www.usa.gov/"],
        confidence="provisional",
    )

    trace = UnitResolutionTrace(
        question_id="SP-054",
        portal_id="portal-us",
        resolved_url="https://www.usa.gov/",
        supplying_source="portal_default",
        link_escalated_off_portal=False,
        evidence_locus_violation=None,
        prefill_reason=None,
        terminal_state="assessed",
        resolution_history=({"source": "portal_default", "usable": True, "returned": "https://www.usa.gov/"},),
        assessor_answer=False,
        assessor_justification="Driver's licenses are issued at state level",
    )

    attr = attribute(trace, reference)
    assert attr.stage == PipelineStage.PORTAL_DEFAULT
    assert "matched" in attr.reason.lower()


def test_provisional_reference_tracked_distinctly():
    # FR-LD-004, FR-LD-031
    prov_ref = GroundTruthAnswer(
        truth_id=new_id("gt"),
        set_id="test-set",
        question_id="IF-339",
        country_id="US",
        correct_answer=True,
        label_source="test",
        assigned_by="expert",
        reference_url="https://www.foia.gov/",
        no_valid_link=False,
        confidence="provisional",
        note="Known target is generic",
    )
    assert prov_ref.confidence == "provisional"


@pytest.mark.asyncio
async def test_stale_reference_checking_and_detection():
    # FR-LD-020, SC-008: Reference whose URL no longer serves a page is detected as stale
    def mock_handler(request: httpx.Request):
        if "dead-gov-link.gov" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>Active Gov Page</body></html>")

    transport = httpx.MockTransport(mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        is_stale_dead = await check_url_staleness("https://dead-gov-link.gov/404page", client)
        assert is_stale_dead is True

        is_stale_live = await check_url_staleness("https://live-gov-link.gov/page", client)
        assert is_stale_live is False
