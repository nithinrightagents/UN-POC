"""End-to-end test verifying that test and understanding-doc PDFs get ingested properly into project questionnaires."""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from shared.persistence.repositories import Repository
from shared.state.entities import ProjectType, SurveyCycle

pytestmark = pytest.mark.unit

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SAMPLES_DIR = _REPO_ROOT / "data" / "test_samples"
_DOCS_DIR = _REPO_ROOT / "understanding docs"


def test_sample_losi_pdf_extraction_and_ingestion(client: TestClient, conn):
    cycle_id = "test-losi-ingest-cycle"
    repo = Repository(conn)

    # 1. Create a test project
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Test LOSI Ingestion Project",
            questionnaire_ref="Base Template",
            country_set=[],
            project_type=ProjectType.LOSI_CITY,
        )
    )

    pdf_path = _SAMPLES_DIR / "test_losi_sample.pdf"
    assert pdf_path.exists(), "test_losi_sample.pdf must exist"

    # 2. Upload test LOSI PDF
    with open(pdf_path, "rb") as f:
        resp = client.post(
            f"/admin/projects/{cycle_id}/indicators/upload",
            data={
                "module": "Municipal Services",
                "prefix": "L-TEST",
                "evidence_locus": "national_portal_only",
            },
            files={"pdf_file": ("test_losi_sample.pdf", f, "application/pdf")},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}/indicators/review"

    # 3. Check pending review queue
    pending = repo.list_pending_indicators(cycle_id)
    assert len(pending) == 3

    p0 = pending[0]
    assert "Transit Map" in p0.title
    assert "map" in p0.what.lower() or "gps" in p0.what.lower()
    assert "https://tfl.gov.uk" in p0.reference_links[0]
    assert p0.how["criteria_for_yes"]
    assert p0.how["criteria_for_no"]

    # 4. Review page renders the pending indicators
    review_resp = client.get(f"/admin/projects/{cycle_id}/indicators/review")
    assert review_resp.status_code == 200
    assert "Transit Map" in review_resp.text
    assert "Waste Collection" in review_resp.text

    # 5. Approve all 3 candidates
    for p in pending:
        appr_resp = client.post(
            f"/admin/projects/{cycle_id}/indicators/review/{p.pending_id}/approve",
            data={
                "indicator_id": p.indicator_id,
                "title": p.title,
                "what": p.what,
                "why": p.why,
                "how": p.how.get("scoring_guidance", ""),
                "module": p.module,
                "evidence_locus": p.evidence_locus.value,
                "benchmark_case": p.benchmark_case or "",
            },
            follow_redirects=False,
        )
        assert appr_resp.status_code == 303

    # 6. Verify review queue is now empty
    assert len(repo.list_pending_indicators(cycle_id)) == 0

    # 7. Verify live questions in project questionnaire
    questions = repo.list_questions(cycle_id)
    assert len(questions) == 3
    q_titles = [q.title for q in questions]
    assert any("Transit Map" in t for t in q_titles)
    assert any("Council Live" in t for t in q_titles)
    assert any("Waste Collection" in t for t in q_titles)


def test_sample_national_pdf_extraction_and_ingestion(client: TestClient, conn):
    cycle_id = "test-nat-ingest-cycle"
    repo = Repository(conn)

    # 1. Create a test project
    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Test National Ingestion Project",
            questionnaire_ref="Base Template",
            country_set=[],
            project_type=ProjectType.NATIONAL_OSI,
        )
    )

    pdf_path = _SAMPLES_DIR / "test_national_sample.pdf"
    assert pdf_path.exists(), "test_national_sample.pdf must exist"

    # 2. Upload test National PDF
    with open(pdf_path, "rb") as f:
        resp = client.post(
            f"/admin/projects/{cycle_id}/indicators/upload",
            data={
                "module": "National Infrastructure",
                "prefix": "N-TEST",
                "evidence_locus": "national_portal_only",
            },
            files={"pdf_file": ("test_national_sample.pdf", f, "application/pdf")},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}/indicators/review"

    # 3. Check pending review queue
    pending = repo.list_pending_indicators(cycle_id)
    assert len(pending) == 3

    # 4. Approve candidates
    for p in pending:
        appr_resp = client.post(
            f"/admin/projects/{cycle_id}/indicators/review/{p.pending_id}/approve",
            data={
                "indicator_id": p.indicator_id,
                "title": p.title,
                "what": p.what,
                "why": p.why,
                "how": p.how.get("scoring_guidance", ""),
                "module": p.module,
                "evidence_locus": p.evidence_locus.value,
                "benchmark_case": p.benchmark_case or "",
            },
            follow_redirects=False,
        )
        assert appr_resp.status_code == 303

    # 5. Verify live questions in project questionnaire
    questions = repo.list_questions(cycle_id)
    assert len(questions) == 3
    q_titles = [q.title for q in questions]
    assert any("Digital Identity" in t for t in q_titles)
    assert any("e-Procurement" in t for t in q_titles)
    assert any("Open Government Data" in t for t in q_titles)


def test_understanding_doc_real_pdf_ingestion(client: TestClient, conn):
    cycle_id = "test-real-un-pdf-cycle"
    repo = Repository(conn)

    repo.insert_cycle(
        SurveyCycle(
            cycle_id=cycle_id,
            name="Test Real UN PDF Ingestion Project",
            questionnaire_ref="Base Template",
            country_set=[],
            project_type=ProjectType.LOSI_CITY,
        )
    )

    pdf_path = _DOCS_DIR / "LOSI Questionnare" / "Module 2.1 Institutional framework (2).pdf"
    assert pdf_path.exists()

    with open(pdf_path, "rb") as f:
        resp = client.post(
            f"/admin/projects/{cycle_id}/indicators/upload",
            data={
                "module": "Institutional Framework",
                "prefix": "L-IF",
                "evidence_locus": "national_portal_only",
            },
            files={"pdf_file": (pdf_path.name, f, "application/pdf")},
            follow_redirects=False,
        )
    assert resp.status_code == 303

    pending = repo.list_pending_indicators(cycle_id)
    assert len(pending) == 6  # 6 candidate slides in this module

    # Approve the first candidate
    cand = pending[0]
    appr_resp = client.post(
        f"/admin/projects/{cycle_id}/indicators/review/{cand.pending_id}/approve",
        data={
            "indicator_id": cand.indicator_id,
            "title": cand.title,
            "what": cand.what,
            "why": cand.why,
            "how": cand.how.get("scoring_guidance", ""),
            "module": cand.module,
            "evidence_locus": cand.evidence_locus.value,
            "benchmark_case": cand.benchmark_case or "",
        },
        follow_redirects=False,
    )
    assert appr_resp.status_code == 303

    questions = repo.list_questions(cycle_id)
    assert len(questions) == 1
    assert questions[0].what == cand.what
