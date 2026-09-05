"""Assembles the review-surface read model from repository records (FR-043).

Presents, for one question, the proposed answer, justification, numeric
confidence as a percentage, resolved URL, supplying source, and the
complete evidence set -- without the reviewer navigating to any external
tool (FR-023).

A blocked unit (ESCALATED or UNASSESSABLE, see shared.state.reason_tags)
never carries a forced or placeholder answer -- its delivered/system-proposed
answer stays None until a human decision exists (FR-BF-002) -- and carries a
canonical Reason Tag plus the full attempt history the pipeline already
recorded before it blocked (FR-BF-005, FR-BF-008, FR-BF-009).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.persistence.repositories import Repository
from shared.state.confidence import is_below_acceptance_threshold
from shared.state.entities import EvidenceArtifact
from shared.state.reason_tags import ReasonTag, is_blocked, prefill_reason_tag, reason_tag


@dataclass
class AgentPositionView:
    agent_index: int
    answer: object
    confidence: int
    justification: str
    below_acceptance_threshold: bool
    model_identity: str | None
    validation_passed: bool | None
    validation_gaps: list[str] = field(default_factory=list)


@dataclass
class AttemptHistoryView:
    resolution_attempts: list[dict]
    reachability_attempts: int | None
    verification_attempts: int | None
    retry_counts: list[dict]
    points_of_disagreement: list[str]
    has_any_evidence: bool


@dataclass
class QuestionReviewView:
    question_id: str
    portal_id: str
    question_text: str
    delivered_answer: object
    system_proposed_answer: object
    answer_category: str
    consensus_confidence: int | None
    below_acceptance_threshold: bool
    justification: str
    resolved_url: str | None
    supplying_source: str | None
    evidence: EvidenceArtifact | None
    evidence_missing: bool
    escalated: bool
    escalation_reason: str | None
    reason_tag: ReasonTag | None
    agent_positions: list[AgentPositionView]
    discrepancy_flagged: bool
    provenance: str  # "system_proposed" | "human_edited" | "human_overridden"
    actor_id: str | None
    acted_at: str | None
    attempt_history: AttemptHistoryView | None


def build_question_review(
    repo: Repository, session_id: str, question_id: str, portal_id: str, confidence_threshold: int
) -> QuestionReviewView | None:
    question = repo.get_question(question_id)
    portal = repo.get_portal(portal_id)
    if not question:
        return None

    unit = repo.get_unit(session_id, question_id, portal_id)
    unit_data = unit or {}
    unit_state = unit["state"] if unit else "pending"
    escalated = is_blocked(unit_state)
    escalation_reason = unit.get("escalation_reason") if unit else None

    adjudications = repo.list_adjudication_results(session_id, question_id, portal_id)
    latest_adj = adjudications[-1] if adjudications else None

    # Per-agent positions: the round the delivered adjudication used, unless
    # the unit is blocked -- a disagreement block shows every round (FR-BF-009).
    round_number = latest_adj.round_number if latest_adj else 1
    if escalated:
        runs = repo.list_agent_runs(session_id, question_id, portal_id)
    else:
        runs = repo.list_agent_runs(session_id, question_id, portal_id, round_number=round_number)

    agent_views: list[AgentPositionView] = []
    evidence: EvidenceArtifact | None = None
    for run in sorted(runs, key=lambda r: (r.round_number, r.agent_index)):
        validations = repo.list_validation_results(run.run_id)
        latest_validation = validations[-1] if validations else None
        agent_views.append(
            AgentPositionView(
                agent_index=run.agent_index,
                answer=run.answer,
                confidence=run.confidence or 0,
                justification=run.justification or "",
                below_acceptance_threshold=run.below_acceptance_threshold,
                model_identity=run.model_identity,
                validation_passed=latest_validation.passed if latest_validation else None,
                validation_gaps=latest_validation.gaps if latest_validation else [],
            )
        )
        if run.evidence_artifact_id and evidence is None:
            evidence = repo.get_evidence(run.evidence_artifact_id)

    # FR-046: the original system-proposed answer is the adjudicator's consensus
    # answer, full stop -- it must never be derived from a prior human decision.
    # A human decision changes what is *delivered*, never what was *proposed*.
    # For a blocked unit there is no adjudicated consensus, so both stay None
    prefill = repo.latest_prefill(session_id, question_id, portal_id)
    if latest_adj:
        system_proposed_answer = latest_adj.consensus_answer
        consensus_confidence = latest_adj.consensus_confidence
        answer_category = "yes" if system_proposed_answer else "no"
    elif prefill and prefill.suggested:
        system_proposed_answer = prefill.answer
        consensus_confidence = prefill.confidence
        answer_category = prefill.answer_category()
    elif not escalated and "consensus_answer" in unit_data:
        system_proposed_answer = unit_data.get("consensus_answer")
        consensus_confidence = unit_data.get("consensus_confidence")
        # write_prefill persists this directly; fall back to a plain
        # yes/no read of the raw answer only for pre-Step-5 unit rows
        # that predate the field.
        answer_category = unit_data.get(
            "answer_category", "yes" if system_proposed_answer else "no"
        )
    else:
        system_proposed_answer = None
        consensus_confidence = None
        answer_category = "maybe"

    delivered_answer = system_proposed_answer

    decision = repo.latest_assessor_decision(session_id, question_id, portal_id)
    provenance = "system_proposed"
    actor_id = None
    acted_at = None
    if decision:
        delivered_answer = decision.delivered_answer
        actor_id = decision.actor_id
        acted_at = decision.decided_at.isoformat() if decision.decided_at else None
        provenance = {
            "approve": "system_proposed",
            "edit": "human_edited",
            "reject_override": "human_overridden",
        }[decision.action.value]

    evidence_missing = evidence is None
    # FR-024: missing/unresolvable evidence caps confidence below the acceptance
    # threshold regardless of what was recorded -- enforced here at the display
    # boundary as a second line of defence alongside domain/confidence.py.
    below_threshold = (
        True
        if evidence_missing
        else (
            is_below_acceptance_threshold(consensus_confidence, confidence_threshold)
            if consensus_confidence is not None
            else True
        )
    )

    tag: ReasonTag | None = None
    attempt_history: AttemptHistoryView | None = None
    if escalated and escalation_reason:
        resolution_manner = None
        if escalation_reason == "language_declined":
            language_decisions = repo.list_language_decisions(portal_id)
            if language_decisions:
                resolution_manner = language_decisions[-1].resolution_manner
        tag = reason_tag(escalation_reason, unit_data, resolution_manner=resolution_manner)
    elif prefill and prefill.reason:
        reason_val = prefill.reason.value if hasattr(prefill.reason, "value") else str(prefill.reason)
        tag = prefill_reason_tag(reason_val, unit_data)

    if escalated or (prefill and prefill.reason):
        points_of_disagreement = [adj.flag_reason for adj in adjudications if adj.flag_reason]
        verification_attempt_counts = [
            v.verification_attempts for run in runs for v in repo.list_validation_results(run.run_id)
        ]
        attempt_history = AttemptHistoryView(
            resolution_attempts=list(unit_data.get("resolution_history", [])),
            reachability_attempts=unit_data.get("attempts") or unit_data.get("reachability_attempts"),
            verification_attempts=max(verification_attempt_counts, default=None),
            retry_counts=[
                {
                    "agent_index": run.agent_index,
                    "confidence_retry_count": run.confidence_retry_count,
                    "validation_retry_count": run.validation_retry_count,
                }
                for run in sorted(runs, key=lambda r: (r.round_number, r.agent_index))
            ],
            points_of_disagreement=points_of_disagreement,
            has_any_evidence=evidence is not None,
        )

    return QuestionReviewView(
        question_id=question_id,
        portal_id=portal_id,
        question_text=question.text,
        delivered_answer=delivered_answer,
        system_proposed_answer=system_proposed_answer,
        answer_category=answer_category,
        consensus_confidence=consensus_confidence,
        below_acceptance_threshold=below_threshold,
        justification=agent_views[0].justification if agent_views else "",
        resolved_url=portal.resolved_url if portal else None,
        supplying_source=portal.supplying_source.value if portal and portal.supplying_source else None,
        evidence=evidence,
        evidence_missing=evidence_missing,
        escalated=escalated,
        escalation_reason=escalation_reason,
        reason_tag=tag,
        agent_positions=agent_views,
        discrepancy_flagged=latest_adj.discrepancy_flagged if latest_adj else False,
        provenance=provenance,
        actor_id=actor_id,
        acted_at=acted_at,
        attempt_history=attempt_history,
    )
