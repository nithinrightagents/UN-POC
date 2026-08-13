"""Assembles the review-surface read model from repository records (FR-043).

Presents, for one question, the proposed answer, justification, numeric
confidence as a percentage, resolved URL, supplying source, and the
complete evidence set -- without the reviewer navigating to any external
tool (FR-023).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.state.confidence import is_below_acceptance_threshold
from shared.state.entities import EvidenceArtifact
from shared.persistence.repositories import Repository


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
class QuestionReviewView:
    question_id: str
    portal_id: str
    question_text: str
    delivered_answer: object
    system_proposed_answer: object
    consensus_confidence: int | None
    below_acceptance_threshold: bool
    justification: str
    resolved_url: str | None
    supplying_source: str | None
    evidence: EvidenceArtifact | None
    evidence_missing: bool
    escalated: bool
    escalation_reason: str | None
    agent_positions: list[AgentPositionView]
    discrepancy_flagged: bool
    provenance: str  # "system_proposed" | "human_edited" | "human_overridden"
    actor_id: str | None
    acted_at: str | None


def build_question_review(
    repo: Repository, session_id: str, question_id: str, portal_id: str, confidence_threshold: int
) -> QuestionReviewView | None:
    question = repo.get_question(question_id)
    portal = repo.get_portal(portal_id)
    if not question:
        return None

    unit = repo.get_unit(session_id, question_id, portal_id)
    unit_state = unit["state"] if unit else "pending"
    escalated = unit_state == "escalated"
    escalation_reason = unit.get("escalation_reason") if unit else None

    adjudications = repo.list_adjudication_results(session_id, question_id, portal_id)
    latest_adj = adjudications[-1] if adjudications else None

    # Per-agent positions from the round the delivered adjudication used.
    round_number = latest_adj.round_number if latest_adj else 1
    runs = repo.list_agent_runs(session_id, question_id, portal_id, round_number=round_number)

    agent_views: list[AgentPositionView] = []
    evidence: EvidenceArtifact | None = None
    for run in sorted(runs, key=lambda r: r.agent_index):
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
    system_proposed_answer = latest_adj.consensus_answer if latest_adj else None
    delivered_answer = system_proposed_answer
    consensus_confidence = latest_adj.consensus_confidence if latest_adj else None

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

    return QuestionReviewView(
        question_id=question_id,
        portal_id=portal_id,
        question_text=question.text,
        delivered_answer=delivered_answer,
        system_proposed_answer=system_proposed_answer,
        consensus_confidence=consensus_confidence,
        below_acceptance_threshold=below_threshold,
        justification=agent_views[0].justification if agent_views else "",
        resolved_url=portal.resolved_url if portal else None,
        supplying_source=portal.supplying_source.value if portal and portal.supplying_source else None,
        evidence=evidence,
        evidence_missing=evidence_missing,
        escalated=escalated,
        escalation_reason=escalation_reason,
        agent_positions=agent_views,
        discrepancy_flagged=latest_adj.discrepancy_flagged if latest_adj else False,
        provenance=provenance,
        actor_id=actor_id,
        acted_at=acted_at,
    )
