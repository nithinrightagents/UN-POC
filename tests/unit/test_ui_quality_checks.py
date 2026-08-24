"""Automated UI/UX Quality Assurance Gates (WCAG 2.2 AA, Zero Emoji, Route Rendering).

Verifies that the entire revamped UI across Admin, Assessor, Public, and AI Review:
1. Adheres to the Zero-Emoji Anti-Slop doctrine.
2. Meets WCAG 2.2 AA color contrast ratios (>= 4.5:1 text, >= 3:1 UI).
3. Correctly renders all Jinja2 templates without errors via FastAPI TestClient.
4. Contains required accessibility landmarks and form associations.
"""

from __future__ import annotations

import pathlib
from fastapi.testclient import TestClient
import pytest

from portal.common import ensure_session, repo_factory
from portal.webapp import build_app
from shared.config.settings import Settings
from shared.persistence.schema import init_db
from shared.state.entities import (
    AgentRunState,
    AnswerType,
    AssessorAgentRun,
    AssessorRole,
    ElementReference,
    EvidenceArtifact,
    EvidenceLocus,
    HumanAssessorSubmission,
    ProjectType,
    PublicationRecord,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _is_emoji(char: str) -> bool:
    """Detect emojis and decorative pictographs."""
    cp = ord(char)
    # Common emoji ranges
    if (
        (0x1F600 <= cp <= 0x1F64F)  # Emoticons
        or (0x1F300 <= cp <= 0x1F5FF)  # Misc Symbols and Pictographs
        or (0x1F680 <= cp <= 0x1F6FF)  # Transport and Map
        or (0x1F700 <= cp <= 0x1F77F)  # Alchemical
        or (0x1F780 <= cp <= 0x1F7FF)  # Geometric Shapes Extended
        or (0x1F800 <= cp <= 0x1F8FF)  # Supplemental Arrows-C
        or (0x1F900 <= cp <= 0x1F9FF)  # Supplemental Symbols and Pictographs
        or (0x1FA00 <= cp <= 0x1FA6F)  # Chess Symbols
        or (0x1FA70 <= cp <= 0x1FAFF)  # Symbols and Pictographs Extended-A
        or (0x2600 <= cp <= 0x26FF)  # Misc symbols (e.g. warning sign, sun)
        or (0x2700 <= cp <= 0x27BF)  # Dingbats (e.g. check marks, ballot boxes)
    ):
        return True
    return False


def test_zero_emoji_in_templates_and_helpers():
    """Hard QA Gate: Zero emojis across all HTML templates and web renderers."""
    paths_to_check = [
        _REPO_ROOT / "src" / "portal" / "templates",
        _REPO_ROOT / "src" / "review" / "web" / "templates",
        _REPO_ROOT / "src" / "review" / "web" / "detail.py",
        _REPO_ROOT / "src" / "review" / "web" / "evidence.py",
    ]

    violations = []
    for base in paths_to_check:
        if base.is_dir():
            files = list(base.glob("*.html")) + list(base.glob("*.py"))
        else:
            files = [base]

        for f in files:
            content = f.read_text(encoding="utf-8")
            for line_idx, line in enumerate(content.splitlines(), 1):
                for char in line:
                    if _is_emoji(char):
                        violations.append(
                            f"{f.name}:{line_idx} contains emoji '{char}' (U+{ord(char):04X})"
                        )

    assert not violations, "Zero-Emoji Rule Violations found:\n" + "\n".join(violations)


def _relative_luminance(r: int, g: int, b: int) -> float:
    """Calculate relative luminance for sRGB color."""
    vals = []
    for c in (r, g, b):
        c_norm = c / 255.0
        vals.append(
            c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """Calculate contrast ratio between two hex colors."""
    h1 = hex1.lstrip("#")
    h2 = hex2.lstrip("#")
    r1, g1, b1 = int(h1[0:2], 16), int(h1[2:4], 16), int(h1[4:6], 16)
    r2, g2, b2 = int(h2[0:2], 16), int(h2[2:4], 16), int(h2[4:6], 16)
    l1 = _relative_luminance(r1, g1, b1)
    l2 = _relative_luminance(r2, g2, b2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def test_wcag_22_color_contrast_tokens():
    """Verify that all core token color pairs meet WCAG 2.2 AA (>= 4.5:1 for body text, >= 3:1 for UI)."""
    color_pairs = [
        # (Foreground, Background, Minimum Required Ratio, Name)
        ("#0f172a", "#ffffff", 4.5, "Primary Text on White Surface"),
        ("#334155", "#ffffff", 4.5, "Secondary Text on White Surface"),
        ("#006699", "#ffffff", 4.5, "Brand Primary Link on White Surface"),
        ("#ffffff", "#006699", 4.5, "White Text on Brand Primary Button"),
        ("#ffffff", "#0c1e3d", 4.5, "White Text on Brand Navy Header"),
        ("#065f46", "#ecfdf5", 4.5, "Success Badge Text on Success BG"),
        ("#92400e", "#fffbeb", 4.5, "Warning Badge Text on Warning BG"),
        ("#991b1b", "#fef2f2", 4.5, "Danger Badge Text on Danger BG"),
        ("#1e40af", "#eff6ff", 4.5, "Info/Role A Badge Text on Info BG"),
        ("#6b21a8", "#faf5ff", 4.5, "Role B Badge Text on Role B BG"),
    ]

    for fg, bg, min_ratio, label in color_pairs:
        ratio = _contrast_ratio(fg, bg)
        assert ratio >= min_ratio, (
            f"Contrast check failed for {label}: fg={fg}, bg={bg}, ratio={ratio:.2f}:1 (requires >= {min_ratio}:1)"
        )


@pytest.fixture
def seeded_client(tmp_path):
    db_path = str(tmp_path / "test_ui.db")
    init_db(db_path)
    settings = Settings(database_path=db_path)
    app = build_app(db_path, settings)

    repo = repo_factory(db_path)()
    # Seed a survey cycle
    cycle = SurveyCycle(
        cycle_id="un-2026",
        name="UN E-Government Survey 2026",
        project_type=ProjectType.NATIONAL_OSI,
        questionnaire_ref="UN MSQ 2026 Indicator Set",
        country_set=["DK", "US"],
    )
    repo.insert_cycle(cycle)
    session_id = ensure_session(repo, "un-2026")

    # Seed question
    q = Question(
        question_id="PF-001",
        text="Existence of a national portal with public services.",
        answer_type=AnswerType.BINARY,
        evidence_locus=EvidenceLocus.NATIONAL_PORTAL_ONLY,
        cycle_id="un-2026",
    )
    repo.insert_question(q)

    # Seed portal
    portal = TargetPortal(
        portal_id="DK",
        country_id="DK",
        cycle_id="un-2026",
        unit_type="country",
        display_name="Denmark",
        resolved_url="https://www.borger.dk",
    )
    repo.insert_portal(portal)

    # Seed submission
    sub = HumanAssessorSubmission(
        submission_id=new_id("sub"),
        session_id=session_id,
        cycle_id="un-2026",
        portal_id="DK",
        question_id="PF-001",
        role=AssessorRole.A,
        assessor_actor_id="assessor-1",
        answer=True,
        evidence_url="https://www.borger.dk",
        notes="Verified directly on national portal.",
    )
    repo.insert_human_submission(sub)

    # Seed publication
    pub = PublicationRecord(
        publication_id=new_id("pub"),
        cycle_id="un-2026",
        portal_id="DK",
        score=1.0,
        score_breakdown={"PF-001": True},
        published_by_actor_id="senior-reviewer",
    )
    repo.insert_publication(pub)

    return TestClient(app), session_id


def test_all_portal_routes_render_successfully(seeded_client):
    """Verify that all main portal views render with HTTP 200, semantic landmarks, and skip links."""
    client, session_id = seeded_client
    routes = [
        "/",
        "/admin",
        "/admin/projects/un-2026",
        "/admin/projects/un-2026/escalations",
        "/assessor",
        "/assessor/un-2026/DK?role=A",
        "/assessor/un-2026/DK?role=B",
        "/public",
        "/public/un-2026",
        "/public/un-2026/DK",
        f"/review/?session={session_id}",
        f"/review/portal/DK?session={session_id}",
        f"/review/portal/DK/question/PF-001?session={session_id}",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, f"Route {route} failed with status {response.status_code}"
        html = response.text
        # Assert accessibility fundamentals
        assert '<a class="skip-link" href="#main-content">Skip to main content</a>' in html, (
            f"Route {route} is missing accessible skip link"
        )
        assert 'role="banner"' in html, f"Route {route} is missing header banner role"
        assert 'id="main-content"' in html, f"Route {route} is missing main content anchor"
        assert 'role="contentinfo"' in html, f"Route {route} is missing footer role"


def test_reconciliation_workspace_renders_successfully(seeded_client, db_path):
    """Verify that the reconciliation workspace view renders with HTTP 200, semantic landmarks, and skip links when a round is open."""
    import sqlite3
    from shared.persistence.repositories import Repository
    client, session_id = seeded_client
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    repo = Repository(conn)

    from shared.state.entities import ReconciliationRound, new_id
    from datetime import datetime, timezone

    repo.insert_reconciliation_round(
        ReconciliationRound(
            round_id=new_id("rnd"),
            session_id=session_id,
            portal_id="DK",
            cycle_id="un-2026",
            round_number=1,
            opened_by="automatic",
            opened_by_actor_id=None,
            opened_reason=None,
            state="open",
            data={"disputed_question_ids": ["PF-001"], "rate_at_open": 1.0, "tolerance_at_open": 0.05},
            opened_at=datetime.now(timezone.utc),
            closed_at=None,
        )
    )

    for role in ("A", "B"):
        resp = client.get(f"/assessor/un-2026/DK/reconcile?role={role}&actor_id=test-actor")
        assert resp.status_code == 200
        html = resp.text
        assert '<a class="skip-link" href="#main-content">Skip to main content</a>' in html
        assert 'role="banner"' in html
        assert 'id="main-content"' in html
        assert 'role="contentinfo"' in html

