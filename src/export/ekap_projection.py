"""Projection onto EKAP_AOSQInteractions table (T109, contracts/ekap-integration.md).

Projects EKAP AIQ session audit logs onto EKAP's mandated AI interaction audit schema.
"""

from __future__ import annotations

from typing import Any
from shared.persistence.repositories import Repository


def project_to_ekap_aosq_interactions(
    repo: Repository,
    session_id: str,
) -> list[dict[str, Any]]:
    """Project session agent runs and validations to EKAP_AOSQInteractions schema (T109)."""
    rows = []

    # 1. Assessor Agent runs -> PRE_ASSESSMENT
    agent_runs = repo.list_all_agent_runs_for_session(session_id)
    for run in agent_runs:
        # Check human decision if any
        dec = repo.get_assessor_decision(session_id, run.question_id, run.portal_id) if hasattr(repo, "get_assessor_decision") else None
        rows.append({
            "InteractionId": run.run_id,
            "SessionId": session_id,
            "AssessorId": f"agent-{run.agent_index}_{run.model_identity or 'default'}",
            "QuestionId": run.question_id,
            "AgentType": "PRE_ASSESSMENT",
            "InputRef": f"input://runs/{run.run_id}",
            "OutputRef": f"output://runs/{run.run_id}",
            "ModelVersion": run.model_identity or "gemini-2.0-flash",
            "HumanReviewRequired": True,  # Mandatory per FR-043a
            "ReviewedBy": dec.actor_id if dec else None,
            "ReviewDecision": dec.action.value if dec else None,
            "Timestamp": run.session_id,  # Or run timestamp
        })

    # 2. Validator runs -> QA
    validations = repo.list_validation_results(session_id) if hasattr(repo, "list_validation_results") else []
    for val in validations:
        rows.append({
            "InteractionId": val.validation_id,
            "SessionId": session_id,
            "AssessorId": "validator-qa",
            "QuestionId": "",
            "AgentType": "QA",
            "InputRef": f"input://validations/{val.validation_id}",
            "OutputRef": f"output://validations/{val.validation_id}",
            "ModelVersion": "validator-v1",
            "HumanReviewRequired": True,
            "ReviewedBy": None,
            "ReviewDecision": None,
            "Timestamp": val.validation_id,
        })

    return rows
