from fastapi.testclient import TestClient

from portal.common import ensure_session, repo_factory
from portal.webapp import build_app
from review.web.evidence import render_evidence_html
from shared.config.settings import Settings
from shared.persistence.schema import init_db
from shared.state.entities import (
    AnswerType,
    ElementReference,
    EvidenceArtifact,
    EvidenceLocus,
    LinkSource,
    Prefill,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    link_source_display_name,
    new_id,
)


def test_link_source_display_name_mappings():
    """Verify canonical display name mappings for all link source types."""
    assert link_source_display_name(LinkSource.PRIOR_SURVEY_KB) == "Previous KB"
    assert link_source_display_name("prior_survey_kb") == "Previous KB"

    assert link_source_display_name(LinkSource.MSQ) == "MSQ"
    assert link_source_display_name("msq") == "MSQ"

    assert link_source_display_name(LinkSource.SEARCH) == "Internet Searched"
    assert link_source_display_name("search") == "Internet Searched"

    assert link_source_display_name(LinkSource.SITEMAP) == "Government Portal"
    assert link_source_display_name("sitemap") == "Government Portal"

    assert link_source_display_name(LinkSource.PORTAL_DEFAULT) == "Government Portal"
    assert link_source_display_name("portal_default") == "Government Portal"

    assert link_source_display_name("govt_portal") == "Government Portal"
    assert link_source_display_name(None) is None




def test_render_evidence_html_source_badge():
    """Verify that evidence HTML renderer uses the human-readable source labels."""
    ev = EvidenceArtifact(
        artifact_id="ev-1",
        resolved_url="https://www.gov.example/services",
        element_reference=ElementReference(css_path="main p", text_hash="abc123"),
        element_text="Public online services available here.",
        verifiability_status="verified",
    )

    html_kb = render_evidence_html(ev, evidence_missing=False, supplying_source="prior_survey_kb")
    assert "Source: Previous KB" in html_kb

    html_msq = render_evidence_html(ev, evidence_missing=False, supplying_source="msq")
    assert "Source: MSQ" in html_msq

    html_search = render_evidence_html(ev, evidence_missing=False, supplying_source="search")
    assert "Source: Internet Searched" in html_search


def test_api_prefills_includes_supplying_source_label(tmp_path):
    """Verify GET /prefills returns supplying_source and supplying_source_label."""
    db_path = str(tmp_path / "test_api_prefill.db")
    init_db(db_path)
    settings = Settings(database_path=db_path, api_key="test-token")

    repo = repo_factory(db_path)()
    cycle = SurveyCycle(
        cycle_id="cycle-source-test",
        name="Source Test Cycle",
        project_type=ProjectType.NATIONAL_OSI,
        questionnaire_ref="Ref",
        country_set=["US"],
    )
    repo.insert_cycle(cycle)
    session_id = ensure_session(repo, "cycle-source-test")

    q1 = Question(
        question_id="Q-KB",
        indicator_id="IND-KB",
        text="Question from KB",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        cycle_id="cycle-source-test",
    )
    q2 = Question(
        question_id="Q-MSQ",
        indicator_id="IND-MSQ",
        text="Question from MSQ",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        cycle_id="cycle-source-test",
    )
    q3 = Question(
        question_id="Q-SEARCH",
        indicator_id="IND-SEARCH",
        text="Question from Search",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        cycle_id="cycle-source-test",
    )

    for q in (q1, q2, q3):
        repo.insert_question(q)

    portal = TargetPortal(
        portal_id="US",
        country_id="US",
        cycle_id="cycle-source-test",
        unit_type="country",
        display_name="USA",
        resolved_url="https://www.usa.gov",
    )
    repo.insert_portal(portal)

    repo.insert_prefill(
        Prefill(
            prefill_id=new_id("pf"),
            run_id="run-1",
            session_id=session_id,
            cycle_id="cycle-source-test",
            question_id="Q-KB",
            portal_id="US",
            suggested=True,
            answer=True,
            confidence=95,
            justification="Found in previous survey KB",
            evidence_url="https://www.usa.gov/services",
            supplying_source="prior_survey_kb",
        )
    )
    repo.insert_prefill(
        Prefill(
            prefill_id=new_id("pf"),
            run_id="run-1",
            session_id=session_id,
            cycle_id="cycle-source-test",
            question_id="Q-MSQ",
            portal_id="US",
            suggested=True,
            answer=True,
            confidence=90,
            justification="Found in MSQ",
            evidence_url="https://www.usa.gov/msq-link",
            supplying_source="msq",
        )
    )
    repo.insert_prefill(
        Prefill(
            prefill_id=new_id("pf"),
            run_id="run-1",
            session_id=session_id,
            cycle_id="cycle-source-test",
            question_id="Q-SEARCH",
            portal_id="US",
            suggested=True,
            answer=False,
            confidence=85,
            justification="Found via web search",
            evidence_url="https://www.usa.gov/search-link",
            supplying_source="search",
        )
    )

    app = build_app(db_path, settings)
    client = TestClient(app)
    res = client.get(
        "/api/v1/cycles/cycle-source-test/units/US/prefills",
        headers={"X-API-Key": "test-token"},
    )

    assert res.status_code == 200
    data = res.json()
    items = {item["question_id"]: item for item in data["prefills"]}

    assert items["Q-KB"]["supplying_source"] == "prior_survey_kb"
    assert items["Q-KB"]["supplying_source_label"] == "Previous KB"

    assert items["Q-MSQ"]["supplying_source"] == "msq"
    assert items["Q-MSQ"]["supplying_source_label"] == "MSQ"

    assert items["Q-SEARCH"]["supplying_source"] == "search"
    assert items["Q-SEARCH"]["supplying_source_label"] == "Internet Searched"


def test_assessor_portal_renders_source_indicators(tmp_path):
    """Verify assessor unit HTML template does not render AI suggestion boxes (portal AI removed)."""
    db_path = str(tmp_path / "test_portal_source.db")
    init_db(db_path)
    settings = Settings(database_path=db_path)

    repo = repo_factory(db_path)()
    cycle = SurveyCycle(
        cycle_id="cycle-portal-test",
        name="Portal Test Cycle",
        project_type=ProjectType.NATIONAL_OSI,
        questionnaire_ref="Ref",
        country_set=["US"],
    )
    repo.insert_cycle(cycle)
    session_id = ensure_session(repo, "cycle-portal-test")

    q = Question(
        question_id="Q-1",
        text="National portal services.",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        cycle_id="cycle-portal-test",
    )
    repo.insert_question(q)

    portal = TargetPortal(
        portal_id="US",
        country_id="US",
        cycle_id="cycle-portal-test",
        unit_type="country",
        display_name="USA",
        resolved_url="https://www.usa.gov",
    )
    repo.insert_portal(portal)

    repo.insert_prefill(
        Prefill(
            prefill_id=new_id("pf"),
            run_id="run-1",
            session_id=session_id,
            cycle_id="cycle-portal-test",
            question_id="Q-1",
            portal_id="US",
            suggested=True,
            answer=True,
            confidence=95,
            justification="Rationale text here.",
            evidence_url="https://www.usa.gov/portal-services",
            supplying_source="prior_survey_kb",
        )
    )

    app = build_app(db_path, settings)
    client = TestClient(app)

    res = client.get("/assessor/cycle-portal-test/US?role=A")
    assert res.status_code == 200
    html = res.text
    assert "AI Suggested Answer" not in html
    assert '<div class="ai-suggestion-box">' not in html
    assert "btn-ai-fill" not in html
    assert "Use AI Suggestion" not in html
