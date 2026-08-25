"""Final answer derivation and publication readiness (spec 005, spec 007, spec 008).

Shared by both the portal admin publisher and the REST API publisher to guarantee
strict parity.
"""

from __future__ import annotations

from dataclasses import dataclass

from portal.discrepancy import find_resolved_answer
from shared.persistence.repositories import Repository
from shared.state.entities import AssessorRole


@dataclass(frozen=True)
class RoleCompletion:
    role: str                     # 'A' | 'B'
    declared: bool
    actor_id: str | None
    declared_at: str | None
    answered_count: int
    total_indicators: int
    outstanding_question_ids: list[str]
    complete: bool                # declared AND not outstanding


@dataclass(frozen=True)
class PublicationReadiness:
    ready: bool                   # every required role complete
    roles: dict[str, RoleCompletion]
    blocking_reason: str | None


def publication_readiness(
    repo: Repository,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    questions: list[Question] | None = None,
    submissions: list[HumanAssessorSubmission] | None = None,
) -> PublicationReadiness:
    if questions is None:
        questions = repo.list_questions(cycle_id)
    total_indicators = len(questions)
    roles_dict: dict[str, RoleCompletion] = {}

    if submissions is None:
        submissions = repo.list_human_submissions(session_id, portal_id)

    subs_by_role: dict[AssessorRole, dict[str, HumanAssessorSubmission]] = {
        AssessorRole.A: {},
        AssessorRole.B: {},
    }
    for sub in submissions:
        if sub.role in subs_by_role:
            subs_by_role[sub.role][sub.question_id] = sub

    for r_str in ("A", "B"):
        role_enum = AssessorRole(r_str)
        decl = repo.latest_assessor_completion(session_id, portal_id, r_str)
        outstanding: list[str] = []
        answered_count = 0
        role_subs = subs_by_role.get(role_enum, {})
        for q in questions:
            sub = role_subs.get(q.question_id)
            if sub is not None and sub.answer is not None:
                answered_count += 1
            else:
                outstanding.append(q.question_id)

        declared = decl is not None
        complete = declared and len(outstanding) == 0
        roles_dict[r_str] = RoleCompletion(
            role=r_str,
            declared=declared,
            actor_id=decl.actor_id if decl else None,
            declared_at=(
                decl.declared_at.isoformat()
                if hasattr(decl.declared_at, "isoformat")
                else str(decl.declared_at)
            )
            if decl
            else None,
            answered_count=answered_count,
            total_indicators=total_indicators,
            outstanding_question_ids=outstanding,
            complete=complete,
        )

    ready = roles_dict["A"].complete and roles_dict["B"].complete
    blocking_reason = None
    if not ready:
        a_comp = roles_dict["A"]
        b_comp = roles_dict["B"]
        if not a_comp.declared and not b_comp.declared:
            blocking_reason = "Assessors A and B have not declared their assessment complete."
        elif not a_comp.declared:
            blocking_reason = "Assessor A has not declared their assessment complete."
        elif not b_comp.declared:
            blocking_reason = "Assessor B has not declared their assessment complete."
        elif a_comp.outstanding_question_ids and b_comp.outstanding_question_ids:
            blocking_reason = (
                f"Assessors A and B have {len(a_comp.outstanding_question_ids)} and "
                f"{len(b_comp.outstanding_question_ids)} indicators outstanding."
            )
        elif a_comp.outstanding_question_ids:
            cnt = len(a_comp.outstanding_question_ids)
            s = "indicator" if cnt == 1 else "indicators"
            first_q = a_comp.outstanding_question_ids[0]
            blocking_reason = f"Assessor A has {cnt} {s} outstanding: {first_q}."
        elif b_comp.outstanding_question_ids:
            cnt = len(b_comp.outstanding_question_ids)
            s = "indicator" if cnt == 1 else "indicators"
            first_q = b_comp.outstanding_question_ids[0]
            blocking_reason = f"Assessor B has {cnt} {s} outstanding: {first_q}."

    if ready:
        open_round = repo.open_round_for_unit(session_id, portal_id)
        if open_round is not None:
            ready = False
            blocking_reason = "A reconciliation round is currently open for this unit."

    return PublicationReadiness(
        ready=ready,
        roles=roles_dict,
        blocking_reason=blocking_reason,
    )


def final_answer(
    repo: Repository, session_id: str, question_id: str, portal_id: str
) -> bool | None:
    """Precedence for what a Senior Reviewer publishes (spec 005 Section 3.6, spec 008, spec 012):
    a resolved arbitration decision beats a joint answer, which beats simple A/B agreement,
    which beats a single human answer. Never invents an answer nobody gave."""
    ans, _ = final_answer_detail(repo, session_id, question_id, portal_id)
    return ans


def final_answer_detail(
    repo: Repository, session_id: str, question_id: str, portal_id: str
) -> tuple[bool | None, str]:
    """Precedence for what a Senior Reviewer publishes (spec 005 Section 3.6, spec 008, spec 012):
    1. Senior Reviewer arbitration for this indicator (find_resolved_answer)
    2. Joint answer for this indicator (latest_joint_answer)
    3. A/B consensus agreement
    4. Single assessor answer (A or B)
    5. Unresolved disagreement (returns Assessor A's answer, marked contested)
    """
    resolved = find_resolved_answer(repo, session_id, portal_id, question_id)
    if resolved is not None:
        return resolved, "arbitration"

    joint = repo.latest_joint_answer(session_id, portal_id, question_id)
    if joint is not None:
        return bool(joint.answer), "joint_answer"

    a = repo.latest_human_submission(session_id, question_id, portal_id, AssessorRole.A)
    b = repo.latest_human_submission(session_id, question_id, portal_id, AssessorRole.B)

    if a and b:
        if a.answer == b.answer:
            return bool(a.answer), "consensus"
        return bool(a.answer), "contested_a_wins"

    if a:
        return bool(a.answer), "single_assessor_a"
    if b:
        return bool(b.answer), "single_assessor_b"
    return None, "none"

