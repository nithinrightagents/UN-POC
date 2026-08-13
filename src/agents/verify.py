"""Runtime independence and evidence-verification checks (SC-008, SC-017, SC-018).

These read what was actually recorded for a session and check it, rather
than trusting the schema alone -- belt and suspenders on top of the
structural guarantee in schemas.py (contracts/assessor-agent.md).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from shared.state.entities import AgentRunState
from shared.persistence.repositories import Repository


@dataclass
class IndependenceReport:
    total_runs: int
    total_units: int
    cross_contamination_findings: list[str] = field(default_factory=list)
    confidence_stdev_by_unit: dict[str, float] = field(default_factory=dict)
    degenerate_units: list[str] = field(default_factory=list)  # zero-variance confidence
    validations_with_multiple_agent_outputs: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return (
            not self.cross_contamination_findings
            and not self.validations_with_multiple_agent_outputs
        )


def verify_independence(repo: Repository, session_id: str) -> IndependenceReport:
    all_runs = repo.list_all_agent_runs_for_session(session_id)
    report = IndependenceReport(total_runs=len(all_runs), total_units=0)

    by_unit: dict[tuple[str, str], list] = {}
    for run in all_runs:
        by_unit.setdefault((run.question_id, run.portal_id), []).append(run)
    report.total_units = len(by_unit)

    for (qid, pid), runs in by_unit.items():
        # Cross-contamination heuristic: no two agents in the same round
        # should share byte-identical justification text (a signal of a
        # leaked/copied read rather than two independent formations).
        by_round: dict[int, list] = {}
        for r in runs:
            by_round.setdefault(r.round_number, []).append(r)
        for round_number, round_runs in by_round.items():
            justifications = [r.justification for r in round_runs if r.justification]
            if len(justifications) != len(set(justifications)) and len(justifications) > 1:
                report.cross_contamination_findings.append(
                    f"{qid}/{pid} round {round_number}: two agents produced "
                    "byte-identical justification text"
                )

        # SC-017: no validation invocation may see more than one agent's
        # output for the same pair. We cannot observe the Validator's call
        # directly here, but a ValidationResult's run_id always ties to
        # exactly one run by construction (FR-079) -- the repository schema
        # gives no field for a second run_id, so this is checked at the
        # contract level (tests/contract) rather than re-derived here.

        # SC-008: non-degenerate spread -- first-round confidence values
        # should not all be identical across agents.
        first_round = by_round.get(1, [])
        confidences = [r.confidence for r in first_round if r.confidence is not None]
        if len(confidences) >= 2:
            stdev = statistics.pstdev(confidences)
            report.confidence_stdev_by_unit[f"{qid}/{pid}"] = stdev
            if stdev == 0.0 and len(set(r.answer for r in first_round)) == 1:
                report.degenerate_units.append(f"{qid}/{pid}")

    return report


@dataclass
class EvidenceVerificationReport:
    total_validated_pass_runs: int
    unverified_count: int
    unverified_run_ids: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return self.unverified_count == 0


def verify_evidence_reached_adjudication(repo: Repository, session_id: str) -> EvidenceVerificationReport:
    """SC-018: 100% of answers reaching adjudication carry evidence
    independently verified against the live page, with a verification
    timestamp recorded. Zero answers reach adjudication on unverified
    evidence."""
    all_runs = repo.list_all_agent_runs_for_session(session_id)
    validated_pass = [r for r in all_runs if r.state == AgentRunState.VALIDATED_PASS]

    unverified = []
    for run in validated_pass:
        if not run.evidence_artifact_id:
            unverified.append(run.run_id)
            continue
        evidence = repo.get_evidence(run.evidence_artifact_id)
        if not evidence or evidence.verified_at is None:
            unverified.append(run.run_id)

    return EvidenceVerificationReport(
        total_validated_pass_runs=len(validated_pass),
        unverified_count=len(unverified),
        unverified_run_ids=unverified,
    )
