"""Unit tests for PDF-upload indicator ingestion and its review queue.

Generalizes the manual, offline What/Why/How PDF extraction originally used
to build the UN OSI/LOSI master questionnaires (src/data/extract_modules.py)
into a live, admin-facing upload feature. Nothing parsed from an uploaded PDF
is ever added directly to a project's questionnaire -- every candidate lands
in a `PendingIndicator` review queue first, and only becomes a real, scored
`Question` once an admin explicitly approves it (optionally after editing).
Rejected candidates are deleted outright. This covers:

1. pdf_ingest.extract_candidate_indicators() parses one candidate per
   matching What/Why/How slide, skips non-matching pages, and never lets a
   literal "#" leak into the generated indicator_id (it would truncate the
   URL built from question_id at the browser, since compose_question_id()
   is used as a raw path segment in admin routes/templates).
2. POST /indicators/upload stages candidates as PendingIndicator rows (not
   live questions) and redirects to the review page; an unreadable file
   redirects with ingest_error=unreadable; a readable PDF with no matching
   layout redirects with ingest_error=no_indicators_found.
3. Approving a pending indicator creates a live Question and removes it from
   the queue; rejecting deletes it without creating a Question; bulk-reject
   clears every pending row for a cycle.
4. The review page and the project-detail page render the expected controls.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from shared.persistence.repositories import Repository
from shared.questionnaires.pdf_ingest import extract_candidate_indicators
from shared.state.entities import ProjectType, SurveyCycle

pytestmark = pytest.mark.unit


def _make_pdf(pages: list[list[str]]) -> bytes:
    """Hand-build a minimal multi-page PDF (no external PDF-writer library is
    installed in this project) whose content streams pypdf's extract_text()
    can read back verbatim, one Tj line per input string per page."""
    objects: list[bytes] = []
    n_pages = len(pages)
    kids = " ".join(f"{3 + i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())

    content_obj_start = 3 + n_pages
    for i in range(n_pages):
        content_obj_num = content_obj_start + i
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {content_obj_start + n_pages} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_obj_num} 0 R >>".encode()
        )

    for lines in pages:
        text_ops = []
        y = 750
        for line in lines:
            esc = line.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            text_ops.append(f"BT /F1 10 Tf 40 {y} Td ({esc}) Tj ET")
            y -= 14
        content = "\n".join(text_ops).encode("latin-1", "replace")
        objects.append(b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream")

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = [0]
    for idx, obj in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{idx} 0 obj\n".encode())
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_offset = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(b"trailer\n")
    out.write(f"<< /Size {len(objects) + 1} /Root 1 0 R >>\n".encode())
    out.write(b"startxref\n")
    out.write(f"{xref_offset}\n".encode())
    out.write(b"%%EOF")
    return out.getvalue()


_INDICATOR_SLIDE = [
    "Digital Signature Verification #050",
    "What An online tool to verify digital signatures on official documents.",
    "Why Promotes document authenticity and trust in digital transactions.",
    "How? Indicative Steps: 1. Search for 'verify signature'. Criteria for Yes: interactive validator present.",
    "Case Examples Estonia's DigiDoc validator.",
    "Check out https://example.gov/verify",
]

_COVER_SLIDE = ["Cybersecurity Module", "Section 3 of 6"]


def _make_cycle(repo: Repository, cycle_id: str) -> SurveyCycle:
    cycle = SurveyCycle(
        cycle_id=cycle_id, name="PDF Ingestion Cycle", questionnaire_ref="ref",
        country_set=[], project_type=ProjectType.NATIONAL_OSI,
    )
    repo.insert_cycle(cycle)
    return cycle


# --- extract_candidate_indicators() -----------------------------------------

def test_extract_candidate_indicators_parses_matching_slide():
    pdf_bytes = _make_pdf([_INDICATOR_SLIDE])
    candidates = extract_candidate_indicators(pdf_bytes, "Cybersecurity", "SEC", "national_portal_only")

    assert len(candidates) == 1
    c = candidates[0]
    assert c["indicator_id"] == "SEC-050"
    assert "#" not in c["indicator_id"]
    assert "verify digital signatures" in c["what"]
    assert "trust in digital transactions" in c["why"]
    assert "Search for" in c["how_scoring_guidance"]
    assert "DigiDoc" in c["benchmark_case"]
    assert c["module"] == "Cybersecurity"


def test_extract_candidate_indicators_skips_non_matching_pages():
    pdf_bytes = _make_pdf([_COVER_SLIDE, _INDICATOR_SLIDE, _COVER_SLIDE])
    candidates = extract_candidate_indicators(pdf_bytes, "Cybersecurity", "SEC", "national_portal_only")
    assert len(candidates) == 1


def test_extract_candidate_indicators_falls_back_to_slide_index_without_code():
    slide = [
        "Some Untitled Indicator",
        "What Feature description with no explicit code.",
        "Why Because it matters.",
        "How? Indicative Steps: do the thing.",
    ]
    candidates = extract_candidate_indicators(_make_pdf([slide]), "Custom Module", "CUST", "national_portal_only")
    assert len(candidates) == 1
    assert candidates[0]["indicator_id"] == "CUST-001"


def test_extract_candidate_indicators_raises_on_unreadable_bytes():
    with pytest.raises(ValueError):
        extract_candidate_indicators(b"not a pdf", "Module", "MOD", "national_portal_only")


def test_extract_candidate_indicators_returns_empty_list_when_no_slide_matches():
    candidates = extract_candidate_indicators(_make_pdf([_COVER_SLIDE]), "Module", "MOD", "national_portal_only")
    assert candidates == []


# --- POST /indicators/upload -------------------------------------------------

def test_upload_stages_pending_indicators_not_live_questions(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-upload"
    _make_cycle(repo, cycle_id)

    pdf_bytes = _make_pdf([_INDICATOR_SLIDE])
    resp = client.post(
        f"/admin/projects/{cycle_id}/indicators/upload",
        files={"pdf_file": ("cyber.pdf", pdf_bytes, "application/pdf")},
        data={"module": "Cybersecurity", "prefix": "SEC", "evidence_locus": "national_portal_only"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}/indicators/review"

    pending = repo.list_pending_indicators(cycle_id)
    assert len(pending) == 1
    assert pending[0].indicator_id == "SEC-050"
    assert repo.list_questions(cycle_id) == []


def test_upload_unreadable_pdf_redirects_with_ingest_error(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-unreadable"
    _make_cycle(repo, cycle_id)

    resp = client.post(
        f"/admin/projects/{cycle_id}/indicators/upload",
        files={"pdf_file": ("bad.pdf", b"not a pdf at all", "application/pdf")},
        data={"module": "Cybersecurity", "evidence_locus": "national_portal_only"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}?ingest_error=unreadable"
    assert repo.list_pending_indicators(cycle_id) == []


def test_upload_pdf_with_no_matching_layout_redirects_with_ingest_error(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-no-match"
    _make_cycle(repo, cycle_id)

    resp = client.post(
        f"/admin/projects/{cycle_id}/indicators/upload",
        files={"pdf_file": ("cover.pdf", _make_pdf([_COVER_SLIDE]), "application/pdf")},
        data={"module": "Cybersecurity", "evidence_locus": "national_portal_only"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}?ingest_error=no_indicators_found"
    assert repo.list_pending_indicators(cycle_id) == []


# --- approve / reject / bulk-reject -----------------------------------------

def _upload_one(client: TestClient, cycle_id: str):
    client.post(
        f"/admin/projects/{cycle_id}/indicators/upload",
        files={"pdf_file": ("cyber.pdf", _make_pdf([_INDICATOR_SLIDE]), "application/pdf")},
        data={"module": "Cybersecurity", "prefix": "SEC", "evidence_locus": "national_portal_only"},
        follow_redirects=False,
    )


def test_approve_creates_question_and_clears_pending(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-approve"
    _make_cycle(repo, cycle_id)
    _upload_one(client, cycle_id)
    pending = repo.list_pending_indicators(cycle_id)
    assert len(pending) == 1
    p = pending[0]

    resp = client.post(
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
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/admin/projects/{cycle_id}/indicators/review"

    assert repo.list_pending_indicators(cycle_id) == []
    questions = repo.list_questions(cycle_id)
    assert len(questions) == 1
    q = questions[0]
    assert q.question_id == f"{cycle_id}:SEC-050"
    assert "#" not in q.question_id
    assert q.indicator_id == "SEC-050"
    assert q.is_custom is True


def test_reject_deletes_pending_without_creating_question(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-reject"
    _make_cycle(repo, cycle_id)
    _upload_one(client, cycle_id)
    p = repo.list_pending_indicators(cycle_id)[0]

    resp = client.post(
        f"/admin/projects/{cycle_id}/indicators/review/{p.pending_id}/reject",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert repo.list_pending_indicators(cycle_id) == []
    assert repo.list_questions(cycle_id) == []


def test_bulk_reject_clears_all_pending_for_cycle(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-bulk-reject"
    _make_cycle(repo, cycle_id)
    _upload_one(client, cycle_id)
    _upload_one(client, cycle_id)
    assert len(repo.list_pending_indicators(cycle_id)) == 2

    resp = client.post(
        f"/admin/projects/{cycle_id}/indicators/review/bulk-reject",
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert repo.list_pending_indicators(cycle_id) == []


# --- rendering ---------------------------------------------------------------

def test_project_detail_renders_upload_form_and_pending_badge(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-ui-badge"
    _make_cycle(repo, cycle_id)

    resp = client.get(f"/admin/projects/{cycle_id}")
    assert resp.status_code == 200
    assert f'/admin/projects/{cycle_id}/indicators/upload' in resp.text
    assert "Review Pending Indicators" not in resp.text  # no badge when queue is empty

    _upload_one(client, cycle_id)
    resp2 = client.get(f"/admin/projects/{cycle_id}")
    assert "Review Pending Indicators (1)" in resp2.text
    assert f'/admin/projects/{cycle_id}/indicators/review' in resp2.text


def test_review_page_renders_pending_candidate_form(client: TestClient, conn):
    repo = Repository(conn)
    cycle_id = "test-ingest-review-page"
    _make_cycle(repo, cycle_id)
    _upload_one(client, cycle_id)
    p = repo.list_pending_indicators(cycle_id)[0]

    resp = client.get(f"/admin/projects/{cycle_id}/indicators/review")
    assert resp.status_code == 200
    assert p.pending_id in resp.text
    assert f'/admin/projects/{cycle_id}/indicators/review/{p.pending_id}/approve' in resp.text
    assert f'/admin/projects/{cycle_id}/indicators/review/{p.pending_id}/reject' in resp.text
    assert "SEC-050" in resp.text
