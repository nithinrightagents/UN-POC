"""Full audit reconstruction from the session identifier alone (FR-061, SC-005).

For any delivered answer, this reconstructs: the sources consulted and the
URL resolution outcome; the detected language and any human language
decision; each Assessor Agent's answer, confidence, justification, and
evidence for every round; the adjudication outcome of every round; every
retry and its addendum; any escalation; and the human decision.
"""

from __future__ import annotations

from dataclasses import asdict

from shared.persistence.repositories import Repository


def reconstruct_question_history(
    repo: Repository, session_id: str, question_id: str, portal_id: str
) -> dict:
    portal = repo.get_portal(portal_id)
    question = repo.get_question(question_id)

    all_runs = repo.list_agent_runs(session_id, question_id, portal_id)
    runs_by_round: dict[int, list[dict]] = {}
    for run in sorted(all_runs, key=lambda r: (r.round_number, r.agent_index, r.run_id)):
        entry = asdict(run)
        entry["validation_results"] = [
            asdict(v) for v in repo.list_validation_results(run.run_id)
        ]
        runs_by_round.setdefault(run.round_number, []).append(entry)

    adjudications = [
        asdict(a)
        for a in repo.list_adjudication_results(session_id, question_id, portal_id)
    ]

    language_decisions = (
        [asdict(d) for d in repo.list_language_decisions(portal_id)] if portal else []
    )

    escalations = [
        asdict(e)
        for e in repo.list_escalations(session_id)
        if e.question_id == question_id and e.portal_id == portal_id
    ]
    for esc in escalations:
        disposition = repo.get_disposition(esc["item_id"])
        esc["disposition"] = disposition

    human_decisions = [
        asdict(d) for d in repo.list_assessor_decisions(session_id, question_id, portal_id)
    ]

    return {
        "session_id": session_id,
        "question": asdict(question) if question else None,
        "portal": {
            **asdict(portal),
            "resolution_history": [asdict(a) for a in portal.resolution_history],
        }
        if portal
        else None,
        "language_decisions": language_decisions,
        "rounds": runs_by_round,
        "adjudications": adjudications,
        "escalations": escalations,
        "human_decisions": human_decisions,
    }


def reconstruct_session_summary(repo: Repository, session_id: str) -> dict:
    """A coarser reconstruction covering the whole session -- every record
    reachable from the session identifier, with no orphans (SC-007)."""
    all_runs = repo.list_all_agent_runs_for_session(session_id)
    escalations = repo.list_escalations(session_id)
    return {
        "session_id": session_id,
        "session": (
            asdict(repo.get_session(session_id)) if repo.get_session(session_id) else None
        ),
        "agent_run_count": len(all_runs),
        "escalation_count": len(escalations),
        "unique_units": sorted({(r.question_id, r.portal_id) for r in all_runs}),
    }
