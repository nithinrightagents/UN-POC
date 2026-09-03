"""Assessor A/B lifecycle demo seed (client walkthrough).

Six standalone projects, each pre-frozen at one state of the human A/B
reconciliation state machine (portal/reconciliation.py) -- one project per
state rather than one project with six units, so the project list itself
narrates the lifecycle. Each carries a 20-indicator slice of the OSI master
set, not the full 157, so live in-demo answering (Stage 0/1) stays fast.

Numbered demo-stage1 .. demo-stage6 (not 0-indexed) so the cycle ids line up
1:1 with WALKTHROUGH.md's Stage 1 .. Stage 6 -- Stage 0 there is the live,
un-seeded walkthrough stage.

The AI pre-fill capability is demonstrated separately from the existing
usa-sample-2026 project (data/aiq.db) and is untouched here. Safe to
re-run: a cycle that already exists is left alone rather than reseeded.
"""

from __future__ import annotations

from datetime import UTC, datetime

from portal.common import ensure_session
from portal.discrepancy import recompute_portal_discrepancy
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.questionnaires.registry import load_question_set
from shared.state.entities import (
    AssessorCompletion,
    AssessorRole,
    HumanAssessorSubmission,
    ProjectType,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

_INDICATOR_COUNT = 20

_STAGE_UNITS: dict[str, tuple[str, str, str]] = {
    "demo-stage1": ("KE", "Kenya", "https://www.ecitizen.go.ke"),
    "demo-stage2": ("BR", "Brazil", "https://www.gov.br"),
    "demo-stage3": ("DK", "Denmark", "https://www.borger.dk"),
    "demo-stage4": ("VN", "Vietnam", "https://dichvucong.gov.vn"),
    "demo-stage5": ("PE", "Peru", "https://www.gob.pe"),
    "demo-stage6": ("NG", "Nigeria", "https://nigeria.gov.ng"),
}

_STAGE_NAMES: dict[str, str] = {
    "demo-stage1": "Demo — Assigned, Awaiting Assessment",
    "demo-stage2": "Demo — One Assessor In Progress",
    "demo-stage3": "Demo — Full Consensus",
    "demo-stage4": "Demo — Within Tolerance",
    "demo-stage5": "Demo — Reconciliation Open",
    "demo-stage6": "Demo — Persistent Discrepancy",
}

_NOTE_YES = "Confirmed live on the portal — feature present and reachable within two clicks of the homepage."
_NOTE_NO = "Could not locate a live implementation; the linked page returns a 404 / feature not present."


_DEMO_ASSESSOR_A_EMAIL = "assessor.a@ekap-demo.org"
_DEMO_ASSESSOR_B_EMAIL = "assessor.b@ekap-demo.org"


def _create_project(repo: Repository, cycle_id: str) -> tuple[TargetPortal, list[Question], str]:
    country_id, display_name, url = _STAGE_UNITS[cycle_id]

    # Every stage here starts from "assessors already assigned" -- that's
    # what makes a unit eligible to carry submissions at all under the
    # assign-assessors-then-lock workflow (admin.py assign_assessors) -- so
    # each seeded cycle is created pre-locked with the two demo assessor
    # emails already on it, exactly as assign_assessors() would leave it.
    cycle = SurveyCycle(
        cycle_id=cycle_id,
        name=_STAGE_NAMES[cycle_id],
        questionnaire_ref="UN OSI 2024 Master (20-indicator demo slice)",
        country_set=[country_id],
        project_type=ProjectType.NATIONAL_OSI,
        status="locked",
        assessor_a_email=_DEMO_ASSESSOR_A_EMAIL,
        assessor_b_email=_DEMO_ASSESSOR_B_EMAIL,
    )
    repo.insert_cycle(cycle)

    questions = load_question_set("un_osi_2024_master", cycle_id)[:_INDICATOR_COUNT]
    repo.insert_questions(questions)

    portal = TargetPortal(
        portal_id=new_id("portal"),
        cycle_id=cycle_id,
        country_id=country_id,
        resolved_url=url,
        unit_type="country",
        display_name=display_name,
    )
    repo.insert_portal(portal)

    session_id = ensure_session(repo, cycle_id)
    return portal, questions, session_id


def _submit_pair(
    repo: Repository,
    session_id: str,
    cycle_id: str,
    portal: TargetPortal,
    questions: list[Question],
    disagree_indices: set[int],
    b_answer_limit: int | None = None,
) -> None:
    """Writes Assessor A's full set of answers and Assessor B's answers
    (truncated to b_answer_limit for an in-progress assessor). Answer
    direction alternates per question so the demo never shows the uniform
    A-always-yes/B-always-no pattern a real disagreement never looks like."""
    for i, q in enumerate(questions):
        a_answer = i % 3 != 0
        b_answer = (not a_answer) if i in disagree_indices else a_answer

        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"), session_id=session_id, cycle_id=cycle_id,
                question_id=q.question_id, portal_id=portal.portal_id, role=AssessorRole.A,
                assessor_actor_id="demo-assessor-a", answer=a_answer,
                evidence_url=f"{portal.resolved_url}/services/{q.indicator_id}" if a_answer else None,
                notes=_NOTE_YES if a_answer else _NOTE_NO,
            )
        )

        if b_answer_limit is not None and i >= b_answer_limit:
            continue

        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"), session_id=session_id, cycle_id=cycle_id,
                question_id=q.question_id, portal_id=portal.portal_id, role=AssessorRole.B,
                assessor_actor_id="demo-assessor-b", answer=b_answer,
                evidence_url=f"{portal.resolved_url}/search?q={q.indicator_id}" if b_answer else None,
                notes=_NOTE_YES if b_answer else _NOTE_NO,
            )
        )


def _declare_completion(
    repo: Repository, session_id: str, cycle_id: str, portal_id: str, role: str, indicator_count: int
) -> None:
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"), session_id=session_id, cycle_id=cycle_id,
            portal_id=portal_id, role=role, actor_id=f"demo-assessor-{role.lower()}",
            indicator_count_at_declaration=indicator_count,
        )
    )


def seed_lifecycle_demo(repo: Repository, settings: Settings) -> dict:
    created: list[str] = []
    skipped: list[str] = []

    for cycle_id in _STAGE_UNITS:
        if repo.get_cycle(cycle_id) is not None:
            skipped.append(cycle_id)
            continue
        created.append(cycle_id)

        portal, questions, session_id = _create_project(repo, cycle_id)
        n = len(questions)
        tol = settings.human_discrepancy_rate_threshold

        if cycle_id == "demo-stage1":
            # Assigned, untouched: no submissions, no completions.
            pass

        elif cycle_id == "demo-stage2":
            # A complete; B partway through (12 of 20), already disagreeing
            # on 2 of those 12 (~17%) -- above tolerance, but no round opens
            # because B hasn't declared completion yet.
            _submit_pair(repo, session_id, cycle_id, portal, questions, disagree_indices={2, 7}, b_answer_limit=12)
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "A", n)

        elif cycle_id == "demo-stage3":
            # Both complete, zero disagreement.
            _submit_pair(repo, session_id, cycle_id, portal, questions, disagree_indices=set())
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "A", n)
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "B", n)

        elif cycle_id == "demo-stage4":
            # Both complete, 1 of 20 disagrees (5% -- exactly at tolerance,
            # which the state machine treats as within tolerance).
            _submit_pair(repo, session_id, cycle_id, portal, questions, disagree_indices={5})
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "A", n)
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "B", n)

        elif cycle_id == "demo-stage5":
            # Both complete, 2 of 20 disagree (10% > 5%) -- crosses the
            # threshold on the second completion and opens an automatic
            # reconciliation round on its own.
            _submit_pair(repo, session_id, cycle_id, portal, questions, disagree_indices={1, 9})
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "A", n)
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "B", n)

        elif cycle_id == "demo-stage6":
            # Both complete, 3 of 20 disagree (15%) -- the automatic round
            # opens and runs its course without resolving the disagreement,
            # so it's force-closed exhausted, same as the one-round-only
            # rule enforces for a real unresolved round.
            _submit_pair(repo, session_id, cycle_id, portal, questions, disagree_indices={1, 6, 14})
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "A", n)
            _declare_completion(repo, session_id, cycle_id, portal.portal_id, "B", n)

        q_ids = [q.question_id for q in questions]
        recompute_portal_discrepancy(repo, session_id, portal.portal_id, q_ids, tol, cycle_id=cycle_id)

        if cycle_id == "demo-stage6":
            round_obj = repo.open_round_for_unit(session_id, portal.portal_id)
            if round_obj:
                repo.close_round(round_obj.round_id, "exhausted", datetime.now(UTC))
                recompute_portal_discrepancy(repo, session_id, portal.portal_id, q_ids, tol, cycle_id=cycle_id)

    return {"created": created, "skipped": skipped}
