"""Pipeline invariants verification REST API router (FR-112–FR-118)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import make_repo_dependency
from api.schemas import NotFound, VerifyRequest, VerifyResponse
from portal.common import ensure_session
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def build_verify_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["verify"])
    get_repo = make_repo_dependency(database_path)

    @router.post("/cycles/{cycle_id}/verify", response_model=VerifyResponse)
    def run_cycle_verifications(
        cycle_id: str,
        body: VerifyRequest = VerifyRequest(),
        session_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        sess_id = session_id or ensure_session(repo, cycle_id)
        findings: list[str] = []
        details: dict = {}
        all_clean = True

        checks = set(body.checks)

        if "independence" in checks:
            try:
                from agents.verify import verify_independence
                rep = verify_independence(repo, sess_id)
                details["independence"] = {
                    "clean": rep.clean,
                    "total_runs": rep.total_runs,
                    "total_units": rep.total_units,
                    "cross_contamination": rep.cross_contamination_findings,
                    "degenerate_units": rep.degenerate_units,
                }
                if not rep.clean:
                    all_clean = False
                    findings.extend(rep.cross_contamination_findings)
            except Exception as exc:
                details["independence"] = {"error": str(exc)}

        if "evidence" in checks:
            try:
                from agents.verify import verify_evidence_reached_adjudication
                rep = verify_evidence_reached_adjudication(repo, sess_id)
                details["evidence"] = {
                    "clean": rep.clean,
                    "unverified_count": rep.unverified_count,
                    "unverified_run_ids": rep.unverified_run_ids,
                }
                if not rep.clean:
                    all_clean = False
                    findings.append(
                        f"{rep.unverified_count} run(s) reached validated_pass without verified evidence."
                    )
            except Exception as exc:
                details["evidence"] = {"error": str(exc)}

        if "resume" in checks:
            try:
                from orchestration.verify import verify_resume
                rep = verify_resume(repo, sess_id, settings.assessor_agent_count)
                details["resume"] = {
                    "clean": rep.clean,
                    "duplicated_units": rep.duplicated_units,
                    "lost_units": rep.lost_units,
                }
                if not rep.clean:
                    all_clean = False
                    findings.extend(rep.duplicated_units)
                    findings.extend(rep.lost_units)
            except Exception as exc:
                details["resume"] = {"error": str(exc)}

        if "benchmark_isolation" in checks:
            try:
                from benchmark.verify import verify_benchmark_isolation
                rep = verify_benchmark_isolation(repo, sess_id)
                details["benchmark_isolation"] = {
                    "clean": rep.clean,
                    "leakage_findings": rep.leakage_findings,
                }
                if not rep.clean:
                    all_clean = False
                    findings.extend(rep.leakage_findings)
            except Exception as exc:
                details["benchmark_isolation"] = {"error": str(exc)}

        if "telemetry" in checks:
            try:
                from telemetry.verify import verify_telemetry_hygiene
                rep = verify_telemetry_hygiene(repo.conn, sess_id)
                details["telemetry_hygiene"] = {
                    "clean": rep.clean,
                    "findings": rep.findings,
                }
                if not rep.clean:
                    all_clean = False
                    findings.extend(rep.findings)
            except Exception as exc:
                details["telemetry_hygiene"] = {"error": str(exc)}

        if "credentials" in checks:
            try:
                from telemetry.verify import verify_no_credentials
                rep = verify_no_credentials(repo.conn)
                details["no_credentials"] = {
                    "clean": rep.clean,
                    "findings": rep.findings,
                }
                if not rep.clean:
                    all_clean = False
                    findings.extend(rep.findings)
            except Exception as exc:
                details["no_credentials"] = {"error": str(exc)}

        return VerifyResponse(
            clean=all_clean, findings=findings, details=details
        )

    return router
