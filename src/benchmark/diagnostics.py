"""Link resolution diagnostics engine.

Implements FR-LD-009, FR-LD-010, FR-LD-011, FR-LD-012, FR-LD-013, FR-LD-014,
FR-LD-015, FR-LD-016, FR-LD-017, FR-LD-018, FR-LD-019, FR-LD-020, FR-LD-021,
FR-LD-031, FR-LD-032, FR-LD-036, FR-LD-037.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

import httpx

from benchmark.attribution import PipelineStage, attribute
from benchmark.runner import run_benchmark_session
from benchmark.store import BenchmarkStore
from benchmark.trace import UnitResolutionTrace, read_unit_traces
from benchmark.urlmatch import urls_equivalent
from core.llm_factory import ModelProvider
from shared.config.settings import Settings
from shared.persistence.benchmark_repo import BenchmarkRepository
from shared.persistence.repositories import Repository
from shared.state.entities import (
    BenchmarkSet,
    GroundTruthAnswer,
    Question,
    SessionStatus,
    TargetPortal,
    new_id,
)
from shared.tools.linkresolution.admissibility import check_admissible, is_site_root
from shared.tools.linkresolution.locus import evidence_permitted


@dataclass
class IndicatorVerdict:
    question_id: str
    indicator_id: str
    country_id: str
    reference_url: str | None
    resolved_url: str | None
    link_verdict: str  # "match" | "divergent_plausible" | "miss" | "stale"
    expected_answer: object | None
    pipeline_answer: object | None
    answer_verdict: str  # "match" | "miss" | "not_evaluated"
    confidence: str  # "authoritative" | "provisional"
    no_valid_link: bool
    attributed_stage: str | None
    stage_reason: str | None
    refused_url: str | None = None
    escalation_status: str | None = None
    page_truncated: bool = False
    excess_chars: int = 0
    verified_on: str | None = None
    origin: str | None = None
    note: str | None = None
    stale_reference: bool = False


@dataclass
class DiagnosticRunResult:
    result_id: str
    session_id: str
    benchmark_set_id: str
    config_snapshot_id: str
    status: str  # "complete" | "interrupted" | "failed"
    resolve_only: bool
    verdicts: list[IndicatorVerdict]
    total_indicators: int
    authoritative_matches: int
    authoritative_divergent_plausible: int
    authoritative_misses: int
    provisional_matches: int
    provisional_misses: int
    resolution_failures: int
    assessment_failures: int
    environmental_failures: int
    stale_references_count: int
    elapsed_seconds: float = 0.0


async def check_url_staleness(
    url: str | None, client: httpx.AsyncClient | None = None
) -> bool:
    """Check if a reference URL is stale (no longer serves a page).

    Returns True if stale (broken/dead), False if reachable and serving a page.
    """
    if not url:
        return False

    async def _probe(c: httpx.AsyncClient) -> bool:
        try:
            resp = await c.head(url, follow_redirects=True, timeout=5.0)
            if resp.status_code < 400:
                return False
            if resp.status_code in (404, 410, 500, 502, 503, 504):
                # Fall back to GET before confirming dead
                get_resp = await c.get(url, follow_redirects=True, timeout=5.0)
                return get_resp.status_code >= 400
            return False
        except Exception:
            try:
                get_resp = await c.get(url, follow_redirects=True, timeout=5.0)
                return get_resp.status_code >= 400
            except Exception:
                return True

    if client is not None:
        return await _probe(client)
    async with httpx.AsyncClient() as new_client:
        return await _probe(new_client)


async def run_diagnostic(
    repo: Repository,
    settings: Settings,
    benchmark_set_id: str,
    cycle_id: str = "usa-test-2026",
    reference_fixture_path: str | Path = "data/benchmark/reference_links_us.json",
    question_filter: Sequence[str] | None = None,
    resolve_only: bool = False,
    provider: ModelProvider | None = None,
    check_staleness: bool = False,
    http_client: httpx.AsyncClient | None = None,
) -> DiagnosticRunResult:
    """Execute a link resolution diagnostic session and report per-indicator verdicts."""
    start_time = time.perf_counter()

    # 1. Load benchmark set from fixture into isolated store
    b_store = BenchmarkStore(repo.conn)
    if not b_store.get_set(benchmark_set_id):
        b_store.load_from_json(
            reference_fixture_path, benchmark_set_id, "Diagnostic Reference Set"
        )

    all_ground_truths = b_store.list_ground_truth(benchmark_set_id)
    if not all_ground_truths:
        # Load if empty
        b_store.load_from_json(
            reference_fixture_path, benchmark_set_id, "Diagnostic Reference Set"
        )
        all_ground_truths = b_store.list_ground_truth(benchmark_set_id)

    gt_by_qid = {gt.question_id: gt for gt in all_ground_truths}

    # Helper mapping for indicator IDs (#030 -> CP-030)
    def _clean_id(x: str) -> str:
        x = x.strip()
        if x.startswith("#"):
            # find matching question_id
            for gt in all_ground_truths:
                if gt.question_id.endswith(x[1:]) or (gt.note and x in gt.note):
                    return gt.question_id
        return x

    # 2. Fetch all cycle questions
    cycle_questions = repo.list_questions(cycle_id)

    cycle_q_map: dict[str, Question] = {}
    for q in cycle_questions:
        # Map both full question_id (usa-test-2026:CP-030) and bare question_id (CP-030)
        cycle_q_map[q.question_id] = q
        bare_id = q.question_id.split(":", 1)[-1] if ":" in q.question_id else q.question_id
        cycle_q_map[bare_id] = q
        how = q.how if isinstance(q.how, dict) else {}
        ind = getattr(q, "indicator_id", None) or how.get("indicator_id")
        if ind:
            cycle_q_map[ind] = q

    # 3. Determine active questions to run and check for missing indicators (FR-LD-011, D3, SC-006)
    missing_in_cycle: list[str] = []
    missing_in_ref: list[str] = []
    selected_gts: list[GroundTruthAnswer] = []
    selected_questions: list[Question] = []

    if question_filter:
        for q_token in question_filter:
            q_clean = _clean_id(q_token)
            # Check in ground truth
            gt = gt_by_qid.get(q_clean) or next(
                (g for g in all_ground_truths if g.question_id.endswith(q_clean) or q_token in (g.note or "")),
                None,
            )
            if not gt:
                missing_in_ref.append(q_token)
            else:
                selected_gts.append(gt)

            # Check in cycle
            q_entity = cycle_q_map.get(q_token) or cycle_q_map.get(q_clean) or (cycle_q_map.get(gt.question_id) if gt else None)
            if not q_entity:
                missing_in_cycle.append(q_token)
            else:
                if q_entity not in selected_questions:
                    selected_questions.append(q_entity)
    else:
        # Run over all references in benchmark set
        for gt in all_ground_truths:
            selected_gts.append(gt)
            q_entity = cycle_q_map.get(gt.question_id) or next(
                (q for q in cycle_questions if q.question_id.endswith(gt.question_id)),
                None,
            )
            if not q_entity:
                missing_in_cycle.append(gt.question_id)
            else:
                if q_entity not in selected_questions:
                    selected_questions.append(q_entity)

    # Fail loudly on any missing indicator (FR-LD-011, SC-006)
    if missing_in_cycle or missing_in_ref:
        errors = []
        if missing_in_cycle:
            errors.append(f"missing from cycle '{cycle_id}': {sorted(set(missing_in_cycle))}")
        if missing_in_ref:
            errors.append(f"missing from reference set '{benchmark_set_id}': {sorted(set(missing_in_ref))}")
        raise ValueError(f"Diagnostic cannot proceed: {'; '.join(errors)}")

    # 4. Fetch target portals for cycle
    portals = repo.list_portals(cycle_id)

    if not portals:
        # Default US target portal
        portals = [
            TargetPortal(
                portal_id="portal-us",
                cycle_id=cycle_id,
                country_id="US",
                resolved_url="https://www.usa.gov",
            )
        ]

    # 5. Check staleness if enabled (FR-LD-020, SC-008)
    stale_map: dict[str, bool] = {}
    if check_staleness:
        for gt in selected_gts:
            if gt.reference_url and not gt.no_valid_link:
                is_stale = await check_url_staleness(gt.reference_url, http_client)
                stale_map[gt.question_id] = is_stale
            else:
                stale_map[gt.question_id] = False

    # 6. Execute benchmark session (FR-LD-009, FR-LD-012, FR-LD-013)
    session_id, _ = await run_benchmark_session(
        repo=repo,
        settings=settings,
        benchmark_set_id=benchmark_set_id,
        questions=selected_questions,
        portals=portals,
        provider=provider,
        resolve_only=resolve_only,
    )

    # 7. Read traces and configuration snapshot (FR-LD-014)
    traces = read_unit_traces(repo, session_id)
    session_row = repo.get_session(session_id)
    config_snapshot_id = session_row.config_snapshot_id if session_row else ""
    session_status_str = (
        session_row.status.value
        if session_row and hasattr(session_row.status, "value")
        else "complete"
    )

    # 8. Evaluate verdicts
    verdicts: list[IndicatorVerdict] = []
    authoritative_matches = 0
    authoritative_divergent_plausible = 0
    authoritative_misses = 0
    provisional_matches = 0
    provisional_misses = 0
    resolution_failures = 0
    assessment_failures = 0
    environmental_failures = 0
    stale_count = 0

    portal_entity = portals[0] if portals else None
    portal_url = portal_entity.resolved_url if portal_entity and portal_entity.resolved_url else "https://www.usa.gov"

    for gt in selected_gts:
        # Match trace
        matching_trace = None
        for (qid, pid), tr in traces.items():
            if qid == gt.question_id or qid.endswith(":" + gt.question_id) or gt.question_id.endswith(qid):
                matching_trace = tr
                break

        if not matching_trace:
            matching_trace = UnitResolutionTrace(
                question_id=gt.question_id,
                portal_id=portals[0].portal_id if portals else "unknown",
                resolved_url=None,
                supplying_source=None,
                link_escalated_off_portal=False,
                evidence_locus_violation=None,
                prefill_reason="missing_trace",
                terminal_state="unassessable",
                resolution_history=(),
            )

        # Stage attribution
        attr = attribute(matching_trace, gt)
        is_stale = stale_map.get(gt.question_id, False)

        # Link verdict determination (FR-LD-036, FR-LD-037)
        if is_stale:
            link_verdict = "stale"
            stale_count += 1
        elif gt.no_valid_link:
            if (
                matching_trace.resolved_url is None
                or urls_equivalent(matching_trace.resolved_url, portal_url)
                or urls_equivalent(matching_trace.resolved_url, "https://www.usa.gov/")
                or urls_equivalent(matching_trace.resolved_url, "https://www.usa.gov")
                or any(urls_equivalent(matching_trace.resolved_url, alt) for alt in gt.accepted_alternatives)
            ):
                link_verdict = "match"
            else:
                link_verdict = "miss"
        elif urls_equivalent(matching_trace.resolved_url, gt.reference_url):
            link_verdict = "match"
        elif any(urls_equivalent(matching_trace.resolved_url, alt) for alt in gt.accepted_alternatives):
            link_verdict = "match"
        else:
            # Check divergent_plausible (FR-LD-036, FR-LD-037, T031)
            candidate = matching_trace.resolved_url
            if candidate and not is_site_root(candidate) and not urls_equivalent(candidate, portal_url):
                q_entity = cycle_q_map.get(gt.question_id)
                locus_val = (
                    q_entity.evidence_locus.value
                    if q_entity and hasattr(q_entity.evidence_locus, "value")
                    else "any_government_domain"
                )
                adm = check_admissible(candidate).admissible
                loc_ok, _ = evidence_permitted(locus_val, candidate, portal_url, country_id=gt.country_id)
                if adm and loc_ok:
                    link_verdict = "divergent_plausible"
                else:
                    link_verdict = "miss"
            else:
                link_verdict = "miss"

        # Answer verdict determination (FR-LD-021, T036, T001)
        # Only delivered prefills count towards delivered answer correctness.
        if resolve_only:
            answer_verdict = "not_evaluated"
            delivered_ans = None
        else:
            delivered_ans = (
                matching_trace.assessor_answer
                if matching_trace.terminal_state == "delivered"
                else None
            )
            if delivered_ans is not None and gt.correct_answer is not None:
                ans_b = bool(delivered_ans) if isinstance(delivered_ans, bool) else (str(delivered_ans).lower() in ("true", "yes", "1"))
                exp_b = bool(gt.correct_answer) if isinstance(gt.correct_answer, bool) else (str(gt.correct_answer).lower() in ("true", "yes", "1"))
                answer_verdict = "match" if ans_b == exp_b else "miss"
            else:
                answer_verdict = "miss"

        # Aggregate counts
        is_prov = gt.confidence == "provisional"
        if attr.stage == PipelineStage.ENVIRONMENT:
            environmental_failures += 1
        elif is_prov:
            if link_verdict == "match":
                provisional_matches += 1
            else:
                provisional_misses += 1
        else:
            if link_verdict == "match":
                authoritative_matches += 1
                if not resolve_only and answer_verdict == "miss":
                    assessment_failures += 1
            elif link_verdict == "divergent_plausible":
                authoritative_divergent_plausible += 1
            else:
                authoritative_misses += 1
                resolution_failures += 1

        # Extract indicator_id (#030 etc.)
        ind_id = gt.question_id
        q_ent = cycle_q_map.get(gt.question_id)
        if q_ent:
            how_d = q_ent.how if isinstance(q_ent.how, dict) else {}
            ind_id = getattr(q_ent, "indicator_id", None) or how_d.get("indicator_id") or gt.question_id

        verdict = IndicatorVerdict(
            question_id=gt.question_id,
            indicator_id=ind_id,
            country_id=gt.country_id,
            reference_url=gt.reference_url,
            resolved_url=matching_trace.resolved_url,
            link_verdict=link_verdict,
            expected_answer=gt.correct_answer,
            pipeline_answer=delivered_ans,
            answer_verdict=answer_verdict,
            confidence=gt.confidence,
            no_valid_link=gt.no_valid_link,
            attributed_stage=attr.stage.value if hasattr(attr.stage, "value") else str(attr.stage),
            stage_reason=attr.reason,
            refused_url=attr.refused_url,
            escalation_status=attr.escalation_status,
            page_truncated=attr.page_truncated,
            excess_chars=attr.excess_chars,
            verified_on=gt.verified_on,
            origin=gt.origin,
            note=gt.note,
            stale_reference=is_stale,
        )
        verdicts.append(verdict)

    elapsed_seconds = time.perf_counter() - start_time

    status_str = "complete" if session_status_str == "complete" else "interrupted"

    run_result = DiagnosticRunResult(
        result_id=new_id("diag"),
        session_id=session_id,
        benchmark_set_id=benchmark_set_id,
        config_snapshot_id=config_snapshot_id,
        status=status_str,
        resolve_only=resolve_only,
        verdicts=verdicts,
        total_indicators=len(verdicts),
        authoritative_matches=authoritative_matches,
        authoritative_divergent_plausible=authoritative_divergent_plausible,
        authoritative_misses=authoritative_misses,
        provisional_matches=provisional_matches,
        provisional_misses=provisional_misses,
        resolution_failures=resolution_failures,
        assessment_failures=assessment_failures,
        environmental_failures=environmental_failures,
        stale_references_count=stale_count,
        elapsed_seconds=elapsed_seconds,
    )

    # Persist diagnostic result via benchmark_run_results (FR-LD-032, T041)
    bm_repo = BenchmarkRepository(repo.conn)
    result_data = {
        "result_id": run_result.result_id,
        "session_id": run_result.session_id,
        "benchmark_set_id": run_result.benchmark_set_id,
        "config_snapshot_id": run_result.config_snapshot_id,
        "status": run_result.status,
        "resolve_only": run_result.resolve_only,
        "total_indicators": run_result.total_indicators,
        "authoritative_matches": run_result.authoritative_matches,
        "authoritative_divergent_plausible": run_result.authoritative_divergent_plausible,
        "authoritative_misses": run_result.authoritative_misses,
        "provisional_matches": run_result.provisional_matches,
        "provisional_misses": run_result.provisional_misses,
        "resolution_failures": run_result.resolution_failures,
        "assessment_failures": run_result.assessment_failures,
        "environmental_failures": run_result.environmental_failures,
        "stale_references_count": run_result.stale_references_count,
        "elapsed_seconds": run_result.elapsed_seconds,
        "verdicts": [asdict(v) for v in verdicts],
    }
    repo.conn.execute(
        "INSERT INTO benchmark_run_results (result_id, session_id, data) VALUES (?, ?, ?)",
        (run_result.result_id, run_result.session_id, json.dumps(result_data)),
    )
    repo.conn.commit()

    return run_result
