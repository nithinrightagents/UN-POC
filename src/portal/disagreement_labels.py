"""Disagreement labelling pass for human assessor discrepancies.

This module implements the labelling pass that characterises discrepancies between
human assessors once both have declared completion.

NOTE: This module imports `_compare` from `portal.discrepancy` read-only and
NEVER writes through `recompute_portal_discrepancy`.

Seven contractual prohibitions (contracts/labelling-pass.md §7):
1. Never import from or write through `recompute_portal_discrepancy`.
2. Never write a `DiscrepancyCase`, `EscalationQueueItem`, `ReconciliationRound` or `JointAnswer`.
3. Never issue `UPDATE` or `DELETE` against any of its three tables.
4. Never be called from a GET handler.
5. Never raise into a request handler.
6. Never pass `Prefill.answer`, `Prefill.justification`, `ai_suggested_answer`, a role, or an actor id to the classifier.
7. Disagreement labelling must never gate, divert, or modify sign-off or publication.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from portal.discrepancy import _compare
from portal.label_classifier import (
    ClassifierInput,
    InvalidResponseError,
    LABEL_PROMPT_VERSION,
    SchemaRejectedError,
    classify,
    compute_input_digest,
    order_positions,
    render_classifier_payload,
)
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import (
    DISAGREEMENT_LABEL_BADGES,
    AssessorRole,
    DisagreementLabel,
    DisagreementLabelRecord,
    HumanAssessorSubmission,
    LabellingAttempt,
    LabellingPass,
    SideObservation,
    new_id,
)

if TYPE_CHECKING:
    from api.runtime import AIRuntime

logger = logging.getLogger(__name__)


# --- Deterministic pre-pass (contracts/labelling-pass.md §3, data-model.md §7) ---


def normalise_host(url: str | None) -> str:
    """Normalises a URL host for source comparison.

    Lowercases, strips userinfo and port, strips leading www. and trailing dot.
    An unparseable or garbage URL yields an empty host and is treated as no evidence cited.
    """
    if not url:
        return ""
    try:
        raw = url.strip()
        parsed = urlparse(raw)
        netloc = parsed.netloc
        host = netloc.lower().split("@")[-1].split(":")[0]
        # Handle cases where scheme was omitted like "gov.sg"
        if not host and parsed.path and ("." in parsed.path) and (" " not in parsed.path) and not parsed.scheme:
            host = parsed.path.lower().split("/")[0].split(":")[0]
        if host.startswith("www."):
            host = host[4:]
        host = host.rstrip(".")
        if " " in host or not host:
            return ""
        return host
    except Exception:
        return ""


def same_source(url_a: str | None, url_b: str | None) -> bool:
    """Tests if two URLs originate from the same source.

    Compares normalised hosts: host equality or a dot-boundary suffix match in
    either direction (e.g. gov.sg and e-services.gov.sg are same source).
    Never uses eTLD+1 (which would incorrectly equate dvla.gov.uk and hmrc.gov.uk).
    Resolves toward same source when uncertain to allow the classifier to evaluate.
    """
    ha = normalise_host(url_a)
    hb = normalise_host(url_b)
    if not ha or not hb:
        return False
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def classify_deterministically(a: Any, b: Any) -> DisagreementLabel | None:
    """Evaluates the deterministic pre-pass for two positions.

    Returns DIFFERENT_SOURCES if both cite parseable evidence from different sources.
    Returns ONE_FOUND_NOTHING if exactly one position cites parseable evidence.
    Returns None if both cite the same source or neither cites evidence (falls through to classifier).
    An unparseable URL yields an empty host and is treated as no evidence cited.
    """
    url_a = getattr(a, "evidence_url", None) if not isinstance(a, dict) else a.get("evidence_url")
    url_b = getattr(b, "evidence_url", None) if not isinstance(b, dict) else b.get("evidence_url")

    ha = normalise_host(url_a)
    hb = normalise_host(url_b)

    has_a = bool(ha)
    has_b = bool(hb)

    if has_a and has_b:
        if not same_source(url_a, url_b):
            return DisagreementLabel.DIFFERENT_SOURCES
        return None

    if has_a != has_b:
        return DisagreementLabel.ONE_FOUND_NOTHING

    return None


# --- Per-side observations (data-model.md §8) ----------------------------


def extract_side_observations(sub: Any) -> list[SideObservation]:
    """Extracts deterministic free observations for a single position."""
    obs: list[SideObservation] = []
    if sub is None:
        obs.append(SideObservation.NO_NOTES)
        return obs

    notes = getattr(sub, "notes", None) if not isinstance(sub, dict) else sub.get("notes")
    if not notes or not str(notes).strip():
        obs.append(SideObservation.NO_NOTES)

    accepted_ai = getattr(sub, "ai_suggestion_accepted", None) if not isinstance(sub, dict) else sub.get("ai_suggestion_accepted")
    if accepted_ai is True:
        obs.append(SideObservation.ACCEPTED_AI_UNCHANGED)

    return obs


def compute_side_observations(sub_a: Any, sub_b: Any) -> dict[str, list[SideObservation]]:
    """Computes free per-side observations for both Assessor A and B."""
    return {
        "A": extract_side_observations(sub_a),
        "B": extract_side_observations(sub_b),
    }


# --- State projection (contracts/labelling-pass.md §4) ------------------


@dataclass(frozen=True)
class DisputeLabelState:
    question_id: str
    state: str  # 'never_labelled' | 'awaiting' | 'established' | 'exhausted'
    label: DisagreementLabel | None
    badge: str | None  # "Judged differently", etc.
    observations: dict[str, list[SideObservation]]
    stale: bool  # current submissions differ from those labelled (FR-DL-068)
    record: DisagreementLabelRecord | None


def unit_labelling_state(
    repo: Repository,
    session_id: str,
    portal_id: str,
) -> dict[str, DisputeLabelState]:
    """Pure read projection deriving labelling state for all disputed questions in a unit.

    Makes NO model call and writes nothing (FR-DL-045).
    """
    pass_ = repo.get_labelling_pass(session_id, portal_id)
    latest_a_list = repo.list_human_submissions(session_id, portal_id, role=AssessorRole.A)
    latest_b_list = repo.list_human_submissions(session_id, portal_id, role=AssessorRole.B)

    latest_a: dict[str, HumanAssessorSubmission] = {s.question_id: s for s in latest_a_list}
    latest_b: dict[str, HumanAssessorSubmission] = {s.question_id: s for s in latest_b_list}

    states: dict[str, DisputeLabelState] = {}

    if pass_ is None:
        # Unit was never dispatched or labelling is not yet run
        common_qids = sorted(set(latest_a.keys()) & set(latest_b.keys()))
        for qid in common_qids:
            sub_a = latest_a[qid]
            sub_b = latest_b[qid]
            if sub_a.answer != sub_b.answer:
                obs = compute_side_observations(sub_a, sub_b)
                states[qid] = DisputeLabelState(
                    question_id=qid,
                    state="never_labelled",
                    label=None,
                    badge="Not labelled",
                    observations=obs,
                    stale=False,
                    record=None,
                )
        return states

    # Pass exists: read stored labels and attempt counts
    labels = repo.list_labels_for_unit(session_id, portal_id)
    labels_by_qid = {l.question_id: l for l in labels}

    for qid in pass_.disputed_question_ids:
        sub_a = latest_a.get(qid)
        sub_b = latest_b.get(qid)

        if qid in labels_by_qid:
            record = labels_by_qid[qid]
            curr_sub_ids = {}
            if sub_a:
                curr_sub_ids["A"] = sub_a.submission_id
            if sub_b:
                curr_sub_ids["B"] = sub_b.submission_id
            is_stale = curr_sub_ids != record.submission_ids
            badge = DISAGREEMENT_LABEL_BADGES.get(record.label, record.label.value)
            states[qid] = DisputeLabelState(
                question_id=qid,
                state="established",
                label=record.label,
                badge=badge,
                observations=record.observations,
                stale=is_stale,
                record=record,
            )
        else:
            attempts = repo.count_attempts(pass_.pass_id, qid)
            obs = compute_side_observations(sub_a, sub_b)
            if attempts >= 3:
                states[qid] = DisputeLabelState(
                    question_id=qid,
                    state="exhausted",
                    label=None,
                    badge="Labelling was attempted and could not be completed",
                    observations=obs,
                    stale=False,
                    record=None,
                )
            else:
                states[qid] = DisputeLabelState(
                    question_id=qid,
                    state="awaiting",
                    label=None,
                    badge="Labelling not yet complete",
                    observations=obs,
                    stale=False,
                    record=None,
                )

    return states


# --- Observability counts (contracts/labelling-pass.md §5) ---------------


@dataclass(frozen=True)
class LabellingCounts:
    awaiting: int
    exhausted: int
    established_deterministic: int
    established_by_classifier: int


def labelling_counts(repo: Repository, cycle_id: str | None = None) -> LabellingCounts:
    """Aggregates dispute labelling counts (awaiting, exhausted, deterministic, classifier)."""
    if cycle_id is not None:
        passes = repo.list_labelling_passes(cycle_id)
    else:
        cursor = repo.conn.execute("SELECT * FROM labelling_passes ORDER BY created_at ASC")
        from shared.persistence.repositories import _row_to_labelling_pass
        passes = [_row_to_labelling_pass(r) for r in cursor.fetchall()]

    awaiting = 0
    exhausted = 0
    established_deterministic = 0
    established_by_classifier = 0

    for p in passes:
        labels = repo.list_labels_for_unit(p.session_id, p.portal_id)
        labels_by_qid = {l.question_id: l for l in labels}
        for qid in p.disputed_question_ids:
            if qid in labels_by_qid:
                rec = labels_by_qid[qid]
                if rec.established_by == "deterministic":
                    established_deterministic += 1
                else:
                    established_by_classifier += 1
            else:
                attempts = repo.count_attempts(p.pass_id, qid)
                if attempts >= 3:
                    exhausted += 1
                else:
                    awaiting += 1

    return LabellingCounts(
        awaiting=awaiting,
        exhausted=exhausted,
        established_deterministic=established_deterministic,
        established_by_classifier=established_by_classifier,
    )


# --- Dispatch & Runner (contracts/labelling-pass.md §1-§2) ---------------


def dispatch_labelling_pass(
    repo: Repository,
    settings: Settings,
    session_id: str,
    cycle_id: str,
    portal_id: str,
    question_ids: list[str],
    threshold: float,
    dispatched_by: str,
    provider_available: bool,
) -> LabellingPass | None:
    """Synchronous dispatch with six preconditions in order (FR-DL-001 to FR-DL-008).

    Calls _compare read-only and attempts insert to enforce once-only semantics.
    """
    # 1. Operator switch
    if not getattr(settings, "disagreement_labelling_enabled", False):
        return None

    # 2. Model provider availability (R6)
    if not provider_available:
        return None

    # 3. Both roles have declared completion
    role_a = AssessorRole.A.value if hasattr(AssessorRole.A, "value") else "A"
    role_b = AssessorRole.B.value if hasattr(AssessorRole.B, "value") else "B"
    comp_a = repo.latest_assessor_completion(session_id, portal_id, role_a)
    comp_b = repo.latest_assessor_completion(session_id, portal_id, role_b)
    if comp_a is None or comp_b is None:
        return None

    # 4. _compare returns non-None
    cmp_res = _compare(repo, session_id, portal_id, question_ids, threshold)
    if cmp_res is None:
        return None
    common, disagreements, rate, flagged = cmp_res

    # 5. Non-empty disputed set
    if not disagreements:
        return None

    # 6. Insert attempt (IntegrityError caught and returns None)
    pass_record = LabellingPass(
        pass_id=new_id("pass"),
        session_id=session_id,
        cycle_id=cycle_id,
        portal_id=portal_id,
        disputed_question_ids=list(disagreements),
        compared_count=len(common),
        dispatched_by=dispatched_by,
        created_at=datetime.now(timezone.utc),
    )
    try:
        inserted = repo.insert_labelling_pass(pass_record)
        if not inserted:
            return None
        return pass_record
    except sqlite3.IntegrityError:
        return None


@dataclass(frozen=True)
class LabellingPassResult:
    pass_id: str
    total_disputes: int
    labelled_deterministic: int
    labelled_classifier: int
    attempts_recorded: int
    skipped_already_complete: int


async def run_labelling_pass(
    database_path: str,
    settings: Settings,
    runtime: Any,
    pass_id: str,
) -> LabellingPassResult:
    """Processes each outstanding dispute in the pass with its own SQLite connection.

    Idempotent and resumable. Catching exceptions per-dispute ensures one failure
    never halts the pass.
    """
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    repo = Repository(conn)
    try:
        cursor = conn.execute("SELECT * FROM labelling_passes WHERE pass_id = ?", (pass_id,))
        row = cursor.fetchone()
        if row is None:
            return LabellingPassResult(
                pass_id=pass_id,
                total_disputes=0,
                labelled_deterministic=0,
                labelled_classifier=0,
                attempts_recorded=0,
                skipped_already_complete=0,
            )
        from shared.persistence.repositories import _row_to_labelling_pass

        pass_ = _row_to_labelling_pass(row)
        session_id = pass_.session_id
        portal_id = pass_.portal_id
        cycle_id = pass_.cycle_id
        disputed_qids = pass_.disputed_question_ids

        questions = repo.list_questions(cycle_id)
        question_text_map = {
            q.question_id: getattr(q, "text", "") or getattr(q, "indicator_text", "") or q.question_id
            for q in questions
        }

        det_count = 0
        clf_count = 0
        att_count = 0
        skip_count = 0

        for qid in disputed_qids:
            try:
                existing_labels = repo.list_labels_for_unit(session_id, portal_id)
                if any(l.question_id == qid for l in existing_labels):
                    skip_count += 1
                    continue

                attempts = repo.count_attempts(pass_id, qid)
                if attempts >= 3:
                    skip_count += 1
                    continue

                sub_a = repo.latest_human_submission(session_id, qid, portal_id, AssessorRole.A)
                sub_b = repo.latest_human_submission(session_id, qid, portal_id, AssessorRole.B)
                if sub_a is None or sub_b is None:
                    skip_count += 1
                    continue

                obs = compute_side_observations(sub_a, sub_b)

                interval_seconds = None
                if sub_a.submitted_at and sub_b.submitted_at:
                    t_a = sub_a.submitted_at
                    t_b = sub_b.submitted_at
                    if isinstance(t_a, str):
                        t_a = datetime.fromisoformat(t_a)
                    if isinstance(t_b, str):
                        t_b = datetime.fromisoformat(t_b)
                    interval_seconds = abs(int((t_a - t_b).total_seconds()))

                ordered_positions, order_map = order_positions(sub_a, sub_b)
                indicator_text = question_text_map.get(qid, qid)
                clf_input = ClassifierInput(
                    indicator_text=indicator_text,
                    positions=ordered_positions,
                    interval_seconds=interval_seconds,
                )
                rendered_payload = render_classifier_payload(clf_input)
                input_digest = compute_input_digest(rendered_payload)

                det_label = classify_deterministically(sub_a, sub_b)
                if det_label is not None:
                    label_rec = DisagreementLabelRecord(
                        label_id=new_id("lbl"),
                        pass_id=pass_id,
                        session_id=session_id,
                        portal_id=portal_id,
                        question_id=qid,
                        label=det_label,
                        established_by="deterministic",
                        input_digest=input_digest,
                        stated_reason=DISAGREEMENT_LABEL_BADGES.get(det_label, det_label.value),
                        observations=obs,
                        submission_ids={"A": sub_a.submission_id, "B": sub_b.submission_id},
                        interval_seconds=interval_seconds,
                        model_identity=None,
                        prompt_version=None,
                        created_at=datetime.now(timezone.utc),
                    )
                    repo.insert_disagreement_label(label_rec)
                    det_count += 1
                    continue

                # One attempt per dispute per run (T051).
                # A failure writes a single attempt row and moves on rather than retrying
                # in a tight loop — the provider has already exhausted its own backoffs
                # before raising (R8), so an immediate retry fails identically and burns the cap.
                # Remaining attempts are consumed by later runs.
                provider = getattr(runtime, "provider", None)
                if provider is None:
                    att = LabellingAttempt(
                        attempt_id=new_id("att"),
                        pass_id=pass_id,
                        question_id=qid,
                        failure="provider_error",
                        detail="No model provider available on runtime",
                        created_at=datetime.now(timezone.utc),
                    )
                    repo.insert_labelling_attempt(att)
                    att_count += 1
                    continue

                try:
                    res = await classify(provider, settings, clf_input)
                except SchemaRejectedError as exc:
                    att = LabellingAttempt(
                        attempt_id=new_id("att"),
                        pass_id=pass_id,
                        question_id=qid,
                        failure="schema_rejected",
                        detail=str(exc)[:200],
                        created_at=datetime.now(timezone.utc),
                    )
                    repo.insert_labelling_attempt(att)
                    att_count += 1
                    continue
                except InvalidResponseError as exc:
                    att = LabellingAttempt(
                        attempt_id=new_id("att"),
                        pass_id=pass_id,
                        question_id=qid,
                        failure="invalid_response",
                        detail=str(exc)[:200],
                        created_at=datetime.now(timezone.utc),
                    )
                    repo.insert_labelling_attempt(att)
                    att_count += 1
                    continue
                except Exception as exc:
                    att = LabellingAttempt(
                        attempt_id=new_id("att"),
                        pass_id=pass_id,
                        question_id=qid,
                        failure="provider_error",
                        detail=str(exc)[:200],
                        created_at=datetime.now(timezone.utc),
                    )
                    repo.insert_labelling_attempt(att)
                    att_count += 1
                    continue

                # Map contradiction observations back to roles (FR-DL-062)
                contra_1, contra_2 = res.notes_contradict
                if contra_1:
                    role_1 = order_map[0]
                    if SideObservation.NOTES_CONTRADICT_ANSWER not in obs[role_1]:
                        obs[role_1].append(SideObservation.NOTES_CONTRADICT_ANSWER)
                if contra_2:
                    role_2 = order_map[1]
                    if SideObservation.NOTES_CONTRADICT_ANSWER not in obs[role_2]:
                        obs[role_2].append(SideObservation.NOTES_CONTRADICT_ANSWER)

                label_rec = DisagreementLabelRecord(
                    label_id=new_id("lbl"),
                    pass_id=pass_id,
                    session_id=session_id,
                    portal_id=portal_id,
                    question_id=qid,
                    label=res.label,
                    established_by="classifier",
                    input_digest=res.input_digest,
                    stated_reason=res.stated_reason,
                    observations=obs,
                    submission_ids={"A": sub_a.submission_id, "B": sub_b.submission_id},
                    interval_seconds=interval_seconds,
                    model_identity=res.model_identity,
                    prompt_version=LABEL_PROMPT_VERSION,
                    created_at=datetime.now(timezone.utc),
                )
                repo.insert_disagreement_label(label_rec)
                clf_count += 1

                # Record cost for classifier call (FR-DL-090, T036)
                try:
                    from core.llm_factory import estimate_cost
                    from core.telemetry.cost_ledger import CostLedger

                    cost = estimate_cost(res.model_identity, res.input_tokens, res.output_tokens)
                    ledger = CostLedger(conn, session_id)
                    ledger.record(
                        stage="disagreement_labelling",
                        model_identity=res.model_identity,
                        input_units=res.input_tokens,
                        output_units=res.output_tokens,
                        cost=cost,
                        agent_index=None,
                    )
                except Exception as cost_exc:
                    logger.warning("Failed to record cost for labelling dispute %s: %s", qid, cost_exc)

            except Exception as per_dispute_exc:
                logger.exception("Unexpected error processing dispute %s in pass %s", qid, pass_id)
                try:
                    att = LabellingAttempt(
                        attempt_id=new_id("att"),
                        pass_id=pass_id,
                        question_id=qid,
                        failure="provider_error",
                        detail=str(per_dispute_exc)[:200],
                        created_at=datetime.now(timezone.utc),
                    )
                    repo.insert_labelling_attempt(att)
                    att_count += 1
                except Exception:
                    pass

        return LabellingPassResult(
            pass_id=pass_id,
            total_disputes=len(disputed_qids),
            labelled_deterministic=det_count,
            labelled_classifier=clf_count,
            attempts_recorded=att_count,
            skipped_already_complete=skip_count,
        )
    finally:
        conn.close()


# --- Counts for observability (contracts/labelling-pass.md §5, FR-DL-091, FR-DL-092) ---


@dataclass(frozen=True)
class LabellingCounts:
    awaiting: int
    exhausted: int
    established_deterministic: int
    established_by_classifier: int


def labelling_counts(repo: Repository, cycle_id: str | None = None) -> LabellingCounts:
    """Returns awaiting, exhausted, established_deterministic, established_by_classifier (FR-DL-091, FR-DL-092)."""
    if cycle_id is not None:
        passes = repo.list_labelling_passes(cycle_id)
    else:
        rows = repo.conn.execute("SELECT * FROM labelling_passes ORDER BY created_at ASC").fetchall()
        from shared.persistence.repositories import _row_to_labelling_pass
        passes = [_row_to_labelling_pass(r) for r in rows]

    awaiting = 0
    exhausted = 0
    det_count = 0
    clf_count = 0

    for p in passes:
        labels = repo.list_labels_for_unit(p.session_id, p.portal_id)
        labels_by_qid = {l.question_id: l for l in labels}
        for qid in p.disputed_question_ids:
            if qid in labels_by_qid:
                rec = labels_by_qid[qid]
                if rec.established_by == "deterministic":
                    det_count += 1
                else:
                    clf_count += 1
            else:
                attempts = repo.count_attempts(p.pass_id, qid)
                if attempts >= 3:
                    exhausted += 1
                else:
                    awaiting += 1

    return LabellingCounts(
        awaiting=awaiting,
        exhausted=exhausted,
        established_deterministic=det_count,
        established_by_classifier=clf_count,
    )


# --- Unit label composition (contracts/surfaces-and-measures.md §1, FR-DL-061) ---


def unit_label_composition(
    repo: Repository,
    session_id: str,
    portal_id: str,
) -> dict[str, int]:
    """Pure read returning per-label counts for a unit over unit_labelling_state (FR-DL-061)."""
    states = unit_labelling_state(repo, session_id, portal_id)
    counts: dict[str, int] = {}
    for st in states.values():
        if st.state == "established" and st.label is not None:
            lbl_key = DISAGREEMENT_LABEL_BADGES.get(st.label, st.label.value)
            counts[lbl_key] = counts.get(lbl_key, 0) + 1
        elif st.state in ("awaiting", "exhausted", "never_labelled"):
            badge_or_state = st.badge or st.state
            counts[badge_or_state] = counts.get(badge_or_state, 0) + 1
    return counts


# --- Ambiguity Measure & Thin Notes (contracts/surfaces-and-measures.md §3, FR-DL-070 to FR-DL-075) ---


@dataclass(frozen=True)
class IndicatorAmbiguity:
    indicator_key: str          # indicator_id where present, else question_id (R11)
    judged_differently: int     # DIFFERENT_JUDGEMENT count
    units_measured: int         # units contributing at least one labelled dispute
    units_total: int            # units whose pass ran
    labelled_share: float       # proportion of disputes labelled at all


class AmbiguityReport(list):
    """List of IndicatorAmbiguity with attached cycle-level insufficient notes proportion (FR-DL-074)."""
    def __init__(self, items: list[IndicatorAmbiguity], insufficient_notes_share: float = 0.0):
        super().__init__(items)
        self.insufficient_notes_share = insufficient_notes_share
        self.not_enough_notes_share = insufficient_notes_share


def insufficient_notes_proportion(repo: Repository, cycle_id: str | None = None) -> float:
    """Returns the proportion of labelled disputes in the cycle carrying NOT_ENOUGH_NOTES (FR-DL-074, SC-007)."""
    return indicator_ambiguity(repo, cycle_id).insufficient_notes_share


def indicator_ambiguity(
    repo: Repository,
    cycle_id: str | None = None,
) -> AmbiguityReport:
    """Computes ranked indicator ambiguity measures (FR-DL-070 to FR-DL-075).

    Only DIFFERENT_JUDGEMENT counts toward judged_differently (FR-DL-071).
    Keyed by indicator_id where present, falling back to question_id (R11).
    units_measured and labelled_share are present on every row (FR-DL-072, FR-DL-073).
    """
    if cycle_id is not None:
        passes = repo.list_labelling_passes(cycle_id)
        cursor_q = repo.conn.execute(
            "SELECT question_id, data FROM questions WHERE cycle_id = ?",
            (cycle_id,),
        )
        labels = repo.list_labels_for_cycle(cycle_id)
    else:
        cursor_p = repo.conn.execute("SELECT * FROM labelling_passes ORDER BY created_at ASC")
        from shared.persistence.repositories import _row_to_labelling_pass, _row_to_disagreement_label
        passes = [_row_to_labelling_pass(r) for r in cursor_p.fetchall()]
        cursor_q = repo.conn.execute("SELECT question_id, data FROM questions")
        cursor_l = repo.conn.execute("SELECT * FROM disagreement_labels ORDER BY created_at ASC")
        labels = [_row_to_disagreement_label(r) for r in cursor_l.fetchall()]

    qid_to_key: dict[str, str] = {}
    for row in cursor_q.fetchall():
        qid = row[0]
        raw_data = row[1]
        q_data = json.loads(raw_data) if isinstance(raw_data, str) else (raw_data or {})
        ind_id = q_data.get("indicator_id")
        qid_to_key[qid] = ind_id if ind_id else qid

    units_total = len(passes)

    # Count disputes across all passes
    total_disputes: dict[str, int] = {}
    for p in passes:
        for qid in p.disputed_question_ids:
            k = qid_to_key.get(qid, qid)
            total_disputes[k] = total_disputes.get(k, 0) + 1

    judged_diff: dict[str, int] = {}
    units_measured_set: dict[str, set[str]] = {}
    labelled_disputes: dict[str, int] = {}
    insufficient_count = 0

    for lbl in labels:
        k = qid_to_key.get(lbl.question_id, lbl.question_id)
        labelled_disputes[k] = labelled_disputes.get(k, 0) + 1

        if k not in units_measured_set:
            units_measured_set[k] = set()
        units_measured_set[k].add(lbl.portal_id)

        lbl_val = lbl.label.value if hasattr(lbl.label, "value") else str(lbl.label)
        if lbl_val == DisagreementLabel.DIFFERENT_JUDGEMENT.value:
            judged_diff[k] = judged_diff.get(k, 0) + 1
        if lbl_val == DisagreementLabel.NOT_ENOUGH_NOTES.value:
            insufficient_count += 1

    insufficient_notes_share = (insufficient_count / len(labels)) if labels else 0.0

    all_keys = sorted(set(total_disputes.keys()) | set(labelled_disputes.keys()))
    items: list[IndicatorAmbiguity] = []
    for k in all_keys:
        tot_disp = total_disputes.get(k, 0)
        lab_disp = labelled_disputes.get(k, 0)
        lab_share = (lab_disp / tot_disp) if tot_disp > 0 else (1.0 if lab_disp > 0 else 0.0)
        items.append(
            IndicatorAmbiguity(
                indicator_key=k,
                judged_differently=judged_diff.get(k, 0),
                units_measured=len(units_measured_set.get(k, set())),
                units_total=units_total,
                labelled_share=lab_share,
            )
        )

    # Rank by judged_differently DESC, then units_measured DESC, then indicator_key ASC
    items.sort(key=lambda x: (-x.judged_differently, -x.units_measured, x.indicator_key))

    return AmbiguityReport(items, insufficient_notes_share=insufficient_notes_share)


