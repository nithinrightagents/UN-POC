"""Benchmark evaluation measures report (FR-096, FR-097, SC-002, SC-003).

Computes accuracy against ground truth (pre-human-review), accuracy by class,
accuracy by confidence band, discrepancy flag rate, non-independence floor checks,
and escalation counts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from benchmark.store import BenchmarkStore
from shared.config.settings import Settings
from shared.persistence.benchmark_repo import BenchmarkRepository
from shared.persistence.repositories import Repository
from shared.state.entities import BenchmarkRunResult, new_id

if TYPE_CHECKING:
    pass


def _confidence_band(confidence: int | None) -> str:
    if confidence is None:
        return "none"
    if confidence <= 50:
        return "0-50"
    if confidence <= 70:
        return "51-70"
    if confidence <= 85:
        return "71-85"
    return "86-100"


def compute_benchmark_measures(
    repo: Repository,
    session_id: str,
    set_id: str,
    benchmark_store: BenchmarkStore,
    settings: Settings,
) -> BenchmarkRunResult:
    """Compute benchmark measures for a session against a benchmark set (FR-096, FR-097, SC-003)."""
    ground_truths = benchmark_store.list_ground_truth(set_id)
    gt_map = {(gt.question_id, gt.country_id): gt for gt in ground_truths}

    # Fetch all delivered adjudication results for session
    adj_results = repo.list_all_adjudication_results_for_session(session_id)
    # Map (question_id, portal_id) -> AdjudicationResult
    adj_map = {(a.question_id, a.portal_id): a for a in adj_results}

    portals = {p.portal_id: p for p in repo.list_portals_for_session(session_id)} if hasattr(repo, "list_portals_for_session") else {}
    if not portals:
        # Fallback query from DB directly
        rows = repo.conn.execute(
            "SELECT portal_id, country_id FROM target_portals"
        ).fetchall()
        portals_country_map = {r["portal_id"]: r["country_id"] for r in rows}
    else:
        portals_country_map = {pid: p.country_id for pid, p in portals.items()}

    total_pairs = len(ground_truths)
    correct_count = 0

    class_correct: dict[str, int] = {}
    class_total: dict[str, int] = {}

    band_correct: dict[str, int] = {}
    band_total: dict[str, int] = {}

    discrepancy_count = 0
    total_adjudicated = len(adj_results)

    for (qid, cid), gt in gt_map.items():
        # Find portal_id for country
        portal_id = next((pid for pid, country in portals_country_map.items() if country == cid), None)
        adj = adj_map.get((qid, portal_id)) if portal_id else None

        q_class = gt.question_class or "default"
        class_total[q_class] = class_total.get(q_class, 0) + 1

        is_correct = False
        if adj and adj.consensus_answer is not None:
            # Compare consensus answer with ground truth (pre-human-review, FR-097)
            if str(adj.consensus_answer).strip().lower() == str(gt.correct_answer).strip().lower():
                is_correct = True
                correct_count += 1
                class_correct[q_class] = class_correct.get(q_class, 0) + 1

            band = _confidence_band(adj.consensus_confidence)
            band_total[band] = band_total.get(band, 0) + 1
            if is_correct:
                band_correct[band] = band_correct.get(band, 0) + 1
        else:
            band = "unassessed"
            band_total[band] = band_total.get(band, 0) + 1

    for adj in adj_results:
        if adj.discrepancy_flagged:
            discrepancy_count += 1

    overall_accuracy = (correct_count / total_pairs) if total_pairs > 0 else 0.0
    discrepancy_flag_rate = (discrepancy_count / total_adjudicated) if total_adjudicated > 0 else 0.0

    accuracy_by_class = {
        cls: (class_correct.get(cls, 0) / count)
        for cls, count in class_total.items()
    }

    accuracy_by_confidence_band = {
        band: (band_correct.get(band, 0) / count)
        for band, count in band_total.items()
    }

    # Escalation counts by reason
    esc_items = repo.list_escalations(session_id)
    escalations_by_reason: dict[str, int] = {}
    for esc in esc_items:
        reason_str = esc.reason.value if hasattr(esc.reason, "value") else str(esc.reason)
        escalations_by_reason[reason_str] = escalations_by_reason.get(reason_str, 0) + 1

    # SC-003: Check non-independence floor
    # Failing the run when rate falls at or below non_independence_floor or > max_threshold
    floor = getattr(settings, "discrepancy_non_independence_floor", 0.05)
    max_thresh = getattr(settings, "discrepancy_max_threshold", 0.25)
    non_independence_failed = (discrepancy_flag_rate <= floor) or (discrepancy_flag_rate > max_thresh)

    result = BenchmarkRunResult(
        result_id=new_id("bmres"),
        session_id=session_id,
        config_snapshot_id=repo.get_session(session_id).config_snapshot_id if repo.get_session(session_id) else "",
        overall_accuracy=overall_accuracy,
        accuracy_by_class=accuracy_by_class,
        accuracy_by_confidence_band=accuracy_by_confidence_band,
        discrepancy_flag_rate=discrepancy_flag_rate,
        portal_measures={"non_independence_failed": non_independence_failed, "floor": floor, "max_threshold": max_thresh},
        escalations_by_reason=escalations_by_reason,
    )

    bm_repo = BenchmarkRepository(repo.conn)
    bm_repo.insert_run_result(result)
    return result
