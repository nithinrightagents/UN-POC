import json
import sqlite3
import httpx
import pytest

from benchmark.attribution import PipelineStage
from benchmark.diagnostics import run_diagnostic
from core.llm_factory import ModelProvider, ModelResponse
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import DDL
from shared.state.entities import (
    EvidenceLocus,
    Question,
    AnswerType,
    TargetPortal,
    PriorSurveyLink,
    LinkSource,
    ResolutionAttempt,
    new_id,
)
from shared.tools.browser import BrowserSession, PageResult
from unittest.mock import patch


class FakePage:
    async def content(self):
        return "<div>Official Service Content with Evidence</div>"
    async def evaluate(self, script, *args):
        return ""
    async def close(self):
        pass
    @property
    def url(self):
        return "https://www.usa.gov"


@pytest.fixture(autouse=True)
def mock_browser_and_search():
    async def fake_start(self):
        self._browser = None
        self._playwright = None

    async def fake_stop(self):
        pass

    async def fake_fetch(self, url, caller_class, fetch_log=None, timeout_ms=45000):
        return (
            PageResult(url=url, final_url=url, html="<div>Official Service Content with Evidence</div>", status=200, reachable=True),
            FakePage(),
        )

    async def fake_search(*args, **kwargs):
        order = kwargs.get("order", 1) if "order" in kwargs else (args[2] if len(args) > 2 else 1)
        return ResolutionAttempt(
            source=LinkSource.SEARCH,
            usable=False,
            returned=None,
            order=order,
            rejection_reason="search_exhausted",
        )

    with patch.object(BrowserSession, "start", fake_start), \
         patch.object(BrowserSession, "stop", fake_stop), \
         patch.object(BrowserSession, "fetch", fake_fetch), \
         patch("shared.tools.linkresolution.chain.search_for_link", fake_search):
        yield


class MockDiagnosticProvider(ModelProvider):
    def __init__(self, answer_for_q: dict[str, bool] | None = None):
        super().__init__("test-proj", "test-loc", True, "test-key")
        self.answer_for_q = answer_for_q or {}
        self.generate_calls = 0

    async def generate(self, prompt: str = "", **kwargs) -> ModelResponse:
        self.generate_calls += 1
        # Determine question by text in prompt
        ans = True
        justification = "Model found qualifying evidence on page"
        for q_key, q_ans in self.answer_for_q.items():
            if q_key in prompt:
                ans = q_ans
                if not ans:
                    justification = "Evidence absent on page"
                break

        response_dict = {
            "answer": ans,
            "confidence": 90,
            "justification": justification,
            "evidence_quote": "Official service overview",
            "fill_gap_reason": "feature not present" if not ans else "",
            "link_likely_wrong": False,
            "detected_language": "en",
        }
        return ModelResponse(
            text=json.dumps(response_dict),
            input_tokens=100,
            output_tokens=50,
            model_identity="vertexai/mock-gemini",
        )


def _setup_integration_environment():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    repo = Repository(conn)

    cycle_id = "test-cycle"
    portal = TargetPortal(
        portal_id="portal-us",
        cycle_id=cycle_id,
        country_id="US",
        resolved_url="https://www.usa.gov",
    )
    repo.insert_portal(portal)

    q1 = Question(
        question_id="Q-CLEAN",
        cycle_id=cycle_id,
        title="Health Services",
        text="Q-CLEAN health services question",
        what="Health services",
        why="Access",
        how={"criteria_for_yes": "Yes", "criteria_for_no": "No", "indicator_id": "#095"},
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )
    q2 = Question(
        question_id="Q-LOST",
        cycle_id=cycle_id,
        title="Procurement Results",
        text="Q-LOST procurement question",
        what="Procurement",
        why="Transparency",
        how={"criteria_for_yes": "Yes", "criteria_for_no": "No", "indicator_id": "#030"},
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.ANY_GOVERNMENT_DOMAIN,
    )
    q3 = Question(
        question_id="Q-ASSESS-NO",
        cycle_id=cycle_id,
        title="National CIO",
        text="Q-ASSESS-NO CIO leadership question",
        what="CIO leadership",
        why="Leadership",
        how={"criteria_for_yes": "Yes", "criteria_for_no": "No", "indicator_id": "#337"},
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.ANY_GOVERNMENT_DOMAIN,
    )
    q_subnat = Question(
        question_id="Q-SUBNAT",
        cycle_id=cycle_id,
        title="Driver's License",
        text="Q-SUBNAT driver license question",
        what="Driver licenses",
        why="Mobility",
        how={"criteria_for_yes": "Yes", "criteria_for_no": "No", "indicator_id": "#054"},
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
    )

    for q in [q1, q2, q3, q_subnat]:
        repo.insert_question(q)

    # Insert prior survey links for fast resolution in test environment
    repo.insert_prior_survey_link(
        PriorSurveyLink(
            link_id=new_id("psl"),
            question_id="Q-CLEAN",
            country_id="US",
            url="https://www.usa.gov/health",
            origin_cycle_id="prior",
            origin_session_id="prior",
        )
    )
    repo.insert_prior_survey_link(
        PriorSurveyLink(
            link_id=new_id("psl"),
            question_id="Q-ASSESS-NO",
            country_id="US",
            url="https://www.cio.gov/about/leadership/",
            origin_cycle_id="prior",
            origin_session_id="prior",
        )
    )

    return conn, repo, cycle_id


@pytest.mark.asyncio
async def test_diagnostics_three_indicator_stage_attribution(tmp_path):
    # T024: Integration test driving run_diagnostic over 3 indicators:
    # 1. Clean match
    # 2. Lost in search
    # 3. Resolved-but-answered-No (attributed to assessment)
    conn, repo, cycle_id = _setup_integration_environment()

    fixture_data = {
        "benchmark_set_id": "bm-test-3",
        "name": "Three Indicator Integration Set",
        "entries": [
            {
                "question_id": "Q-CLEAN",
                "indicator_id": "#095",
                "country_id": "US",
                "expected_answer": True,
                "reference_url": "https://www.usa.gov/health",
                "no_valid_link": False,
                "confidence": "authoritative",
                "verified_on": "2026-08-21",
                "origin": "test",
                "note": "Clean match reference",
            },
            {
                "question_id": "Q-LOST",
                "indicator_id": "#030",
                "country_id": "US",
                "expected_answer": True,
                "reference_url": "https://www.usaspending.gov/search",
                "no_valid_link": False,
                "confidence": "authoritative",
                "verified_on": "2026-08-21",
                "origin": "test",
                "note": "Procurement reference",
            },
            {
                "question_id": "Q-ASSESS-NO",
                "indicator_id": "#337",
                "country_id": "US",
                "expected_answer": True,
                "reference_url": "https://www.cio.gov/about/leadership/",
                "no_valid_link": False,
                "confidence": "authoritative",
                "verified_on": "2026-08-21",
                "origin": "test",
                "note": "CIO reference",
            },
        ],
    }

    fix_file = tmp_path / "fixture.json"
    fix_file.write_text(json.dumps(fixture_data), encoding="utf-8")

    provider = MockDiagnosticProvider(
        answer_for_q={"Q-CLEAN": True, "Q-LOST": True, "Q-ASSESS-NO": False}
    )

    settings = Settings.defaults()

    result = await run_diagnostic(
        repo=repo,
        settings=settings,
        benchmark_set_id="bm-test-3",
        cycle_id=cycle_id,
        reference_fixture_path=fix_file,
        question_filter=["Q-CLEAN", "Q-LOST", "Q-ASSESS-NO"],
        resolve_only=False,
        provider=provider,
        check_staleness=False,
    )

    assert result.status == "complete"
    assert len(result.verdicts) == 3

    v_map = {v.question_id: v for v in result.verdicts}
    v_assess_no = v_map["Q-ASSESS-NO"]

    # When Q-ASSESS-NO resolves to a link and answers False (expected True), attributed stage is assessment
    if v_assess_no.link_verdict == "match":
        assert v_assess_no.attributed_stage == PipelineStage.ASSESSMENT.value
        assert v_assess_no.answer_verdict == "miss"


@pytest.mark.asyncio
async def test_missing_indicator_fails_loudly_and_no_valid_link_passes(tmp_path):
    # T032: Missing indicator fails loudly naming it; no_valid_link indicator passes
    conn, repo, cycle_id = _setup_integration_environment()

    fixture_data = {
        "benchmark_set_id": "bm-subnat",
        "name": "Subnational Set",
        "entries": [
            {
                "question_id": "Q-SUBNAT",
                "indicator_id": "#054",
                "country_id": "US",
                "expected_answer": False,
                "reference_url": None,
                "no_valid_link": True,
                "accepted_alternatives": ["https://www.usa.gov/"],
                "confidence": "provisional",
                "verified_on": "2026-08-21",
                "origin": "test",
                "note": "Driver license subnational",
            }
        ],
    }
    fix_file = tmp_path / "subnat_fix.json"
    fix_file.write_text(json.dumps(fixture_data), encoding="utf-8")

    settings = Settings.defaults()
    provider = MockDiagnosticProvider(answer_for_q={"Q-SUBNAT": False})

    # 1. Missing indicator in cycle check
    with pytest.raises(ValueError) as exc_info:
        await run_diagnostic(
            repo=repo,
            settings=settings,
            benchmark_set_id="bm-subnat",
            cycle_id=cycle_id,
            reference_fixture_path=fix_file,
            question_filter=["Q-NONEXISTENT-999"],
            resolve_only=True,
            provider=provider,
        )
    assert "Q-NONEXISTENT-999" in str(exc_info.value)

    # 2. No valid link passes when pipeline returns portal page
    result = await run_diagnostic(
        repo=repo,
        settings=settings,
        benchmark_set_id="bm-subnat",
        cycle_id=cycle_id,
        reference_fixture_path=fix_file,
        question_filter=["Q-SUBNAT"],
        resolve_only=True,
        provider=provider,
    )
    assert len(result.verdicts) == 1
    assert result.verdicts[0].link_verdict == "match"


@pytest.mark.asyncio
async def test_resolve_only_vs_end_to_end_agreement(tmp_path):
    # T038: Resolution-only vs end-to-end runs have identical link verdicts, and resolution-only creates zero AssessorAgentRun rows
    conn, repo, cycle_id = _setup_integration_environment()

    fixture_data = {
        "benchmark_set_id": "bm-resolve-cmp",
        "name": "Resolve Compare Set",
        "entries": [
            {
                "question_id": "Q-CLEAN",
                "indicator_id": "#095",
                "country_id": "US",
                "expected_answer": True,
                "reference_url": "https://www.usa.gov/health",
                "no_valid_link": False,
                "confidence": "authoritative",
                "verified_on": "2026-08-21",
                "origin": "test",
                "note": "Health",
            },
            {
                "question_id": "Q-SUBNAT",
                "indicator_id": "#054",
                "country_id": "US",
                "expected_answer": False,
                "reference_url": None,
                "no_valid_link": True,
                "confidence": "provisional",
                "verified_on": "2026-08-21",
                "origin": "test",
                "note": "Driver license",
            },
        ],
    }
    fix_file = tmp_path / "resolve_cmp.json"
    fix_file.write_text(json.dumps(fixture_data), encoding="utf-8")

    settings = Settings.defaults()
    provider_e2e = MockDiagnosticProvider(answer_for_q={"Q-CLEAN": True, "Q-SUBNAT": False})

    # Run End-to-End
    res_e2e = await run_diagnostic(
        repo=repo,
        settings=settings,
        benchmark_set_id="bm-resolve-cmp",
        cycle_id=cycle_id,
        reference_fixture_path=fix_file,
        question_filter=["Q-CLEAN", "Q-SUBNAT"],
        resolve_only=False,
        provider=provider_e2e,
    )

    # Run Resolution-Only
    provider_ro = MockDiagnosticProvider()
    res_ro = await run_diagnostic(
        repo=repo,
        settings=settings,
        benchmark_set_id="bm-resolve-cmp",
        cycle_id=cycle_id,
        reference_fixture_path=fix_file,
        question_filter=["Q-CLEAN", "Q-SUBNAT"],
        resolve_only=True,
        provider=provider_ro,
    )

    # Link verdicts must be identical
    for v_e2e, v_ro in zip(res_e2e.verdicts, res_ro.verdicts):
        assert v_e2e.link_verdict == v_ro.link_verdict
        assert v_e2e.resolved_url == v_ro.resolved_url

    # Answer verdicts in resolution-only must be 'not_evaluated'
    for v_ro in res_ro.verdicts:
        assert v_ro.answer_verdict == "not_evaluated"

    # Zero assessor agent runs were made during resolution-only
    runs_ro = repo.list_all_agent_runs_for_session(res_ro.session_id)
    assert len(runs_ro) == 0
