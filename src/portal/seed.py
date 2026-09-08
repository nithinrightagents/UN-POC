"""Seed demo data for the UN EKAP Assessment & Workflow Platform.

Builds two real projects against real, live government portals -- not
fixtures -- so the AI pre-fill step is a genuine test of the heuristic
checker, matching the transcript's own suggested PoC method (Section 7:
"select 5 diverse test country portals... execute an AI-driven automated
evaluation script against these portals").

Denmark is included specifically because a real MSQ PDF for it was supplied
(`understanding docs/Denmark - MS MSQ 2024.pdf`) -- ingesting it here
exercises the real MSQ parser against real content, not a synthetic sample.
"""

from __future__ import annotations

import pathlib
from datetime import UTC

from portal.assignment import create_units
from portal.common import ensure_session
from portal.disagreement_labels import compute_side_observations
from portal.msq import ingest_msq_pdf
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.questionnaires.registry import load_question_set
from shared.state.entities import (
    AssessorCompletion,
    AssessorRole,
    HumanAssessorSubmission,
    ProjectType,
    DisagreementLabel,
    DisagreementLabelRecord,
    LabellingAttempt,
    LabellingPass,
    PublicationRecord,
    Question,
    SurveyCycle,
    TargetPortal,
    new_id,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DENMARK_MSQ_PATH = _REPO_ROOT / "understanding docs" / "Denmark - MS MSQ 2024.pdf"

_NATIONAL_UNITS = [
    ("DK", "Denmark", "https://www.borger.dk"),
    ("US", "United States", "https://www.usa.gov"),
    ("FR", "France", "https://www.service-public.fr"),
    ("BR", "Brazil", "https://www.gov.br"),
    ("NG", "Nigeria", "https://nigeria.gov.ng"),
    ("KE", "Kenya", "https://www.ecitizen.go.ke"),
    ("EE", "Estonia", "https://www.eesti.ee"),
]

_LOSI_UNITS = [
    ("LON", "London", "https://www.london.gov.uk"),
    ("MCR", "Manchester", "https://www.manchester.gov.uk"),
    ("EDI", "Edinburgh", "https://www.edinburgh.gov.uk"),
]


async def seed_demo_data(repo: Repository, settings: Settings) -> dict:
    questions_national = load_question_set("un_osi_2024_master", "un-egov-2026")
    for q in questions_national:
        if repo.get_question(q.question_id) is None:
            repo.insert_question(q)
    questions_losi = load_question_set("un_osi_2024_master", "losi-uk-2025")
    for q in questions_losi:
        if repo.get_question(q.question_id) is None:
            repo.insert_question(q)

    cycle_national = repo.get_cycle("un-egov-2026")
    if cycle_national is None:
        cycle_national = SurveyCycle(
            cycle_id="un-egov-2026", name="UN E-Government Survey 2026",
            questionnaire_ref="UN MSQ 2026 Indicator Set",
            country_set=[c[0] for c in _NATIONAL_UNITS], project_type=ProjectType.NATIONAL_OSI,
        )
        repo.insert_cycle(cycle_national)

    cycle_losi = repo.get_cycle("losi-uk-2025")
    if cycle_losi is None:
        cycle_losi = SurveyCycle(
            cycle_id="losi-uk-2025", name="LOSI UK 2025", questionnaire_ref="UN MSQ 2026 Indicator Set",
            country_set=[c[0] for c in _LOSI_UNITS], project_type=ProjectType.LOSI_CITY,
        )
        repo.insert_cycle(cycle_losi)

    session_national = ensure_session(repo, cycle_national.cycle_id)
    ensure_session(repo, cycle_losi.cycle_id)

    from shared.reference.domains import resolve_admissible_domain_suffixes

    national_portals = []
    new_national = []
    for code, name, url in _NATIONAL_UNITS:
        portal = repo.get_portal_by_country(cycle_national.cycle_id, code)
        suffixes = sorted(resolve_admissible_domain_suffixes(country_id=code, unit_type="country"))
        if portal is None:
            portal = TargetPortal(
                portal_id=new_id("portal"), cycle_id=cycle_national.cycle_id, country_id=code,
                resolved_url=url, unit_type="country", display_name=name,
                admissible_domain_suffixes=suffixes,
            )
            new_national.append(portal)
        elif not portal.admissible_domain_suffixes:
            portal.admissible_domain_suffixes = suffixes
            repo.update_portal(portal)
        national_portals.append(portal)
    if new_national:
        create_units(repo, cycle_national.cycle_id, new_national)

    losi_portals = []
    new_losi = []
    for code, name, url in _LOSI_UNITS:
        portal = repo.get_portal_by_country(cycle_losi.cycle_id, code)
        suffixes = sorted(resolve_admissible_domain_suffixes(country_id=code, unit_type="city"))
        if portal is None:
            portal = TargetPortal(
                portal_id=new_id("portal"), cycle_id=cycle_losi.cycle_id, country_id=code,
                resolved_url=url, unit_type="city", display_name=name,
                admissible_domain_suffixes=suffixes,
            )
            new_losi.append(portal)
        elif not portal.admissible_domain_suffixes:
            portal.admissible_domain_suffixes = suffixes
            repo.update_portal(portal)
        losi_portals.append(portal)
    if new_losi:
        create_units(repo, cycle_losi.cycle_id, new_losi)



    if _DENMARK_MSQ_PATH.exists():
        doc = ingest_msq_pdf(str(_DENMARK_MSQ_PATH), cycle_national.cycle_id, "DK", _DENMARK_MSQ_PATH.name)
        repo.insert_msq_document(doc)

    denmark = next(p for p in national_portals if p.country_id == "DK")
    usa = next(p for p in national_portals if p.country_id == "US")
    france = next(p for p in national_portals if p.country_id == "FR")
    brazil = next(p for p in national_portals if p.country_id == "BR")
    nigeria = next(p for p in national_portals if p.country_id == "NG")
    kenya = next(p for p in national_portals if p.country_id == "KE")
    estonia = next(p for p in national_portals if p.country_id == "EE")

    # 1. USA: Full consensus (0 disagreements)
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, usa.portal_id, questions_national,
        disagree_on=set(),
    )
    # 2. France: Within tolerance (2 of 157 = 1.27% <= 5%) - Established with deterministic + classifier
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, france.portal_id, questions_national,
        disagree_on={"#015", "#028"},
    )
    # 3. Brazil: Above tolerance in progress (10 disagreements, only Role A completed) - Never labelled
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, brazil.portal_id, questions_national,
        disagree_on={"#015", "#028", "#030", "#088", "#117", "#129", "#131a", "#150", "#010", "#002"},
    )
    # 4. Denmark: Reconciliation open (8 of 157 = 5.10% > 5%, both complete) - Awaiting
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, denmark.portal_id, questions_national,
        disagree_on={"#015", "#028", "#030", "#088", "#117", "#129", "#131a", "#150"},
    )
    # 5. Nigeria: Persistent discrepancy (10 disagreements, both complete, round exhausted) - Exhausted
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, nigeria.portal_id, questions_national,
        disagree_on={"#015", "#028", "#030", "#088", "#117", "#129", "#131a", "#150", "#010", "#002"},
    )
    # 6. Kenya: Access-dominated (2 of 157 = 1.27%, both complete) - Established (all ONE_BLOCKED)
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, kenya.portal_id, questions_national,
        disagree_on={"#015", "#028"},
    )
    # 7. Estonia: Interpretation-dominated (2 of 157 = 1.27%, both complete) - Established (all DIFFERENT_JUDGEMENT)
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, estonia.portal_id, questions_national,
        disagree_on={"#015", "#028"},
    )

    # Insert completions (order matters: completions before recompute per contracts/badge-tolerance-and-api.md §4)
    for p, roles in [
        (usa, ("A", "B")),
        (france, ("A", "B")),
        (brazil, ("A",)),  # Brazil only has Role A completed -> above_tolerance_in_progress, never_labelled
        (denmark, ("A", "B")),
        (nigeria, ("A", "B")),
        (kenya, ("A", "B")),
        (estonia, ("A", "B")),
    ]:
        for r_str in roles:
            repo.insert_assessor_completion(
                AssessorCompletion(
                    completion_id=new_id("comp"),
                    session_id=session_national,
                    cycle_id=cycle_national.cycle_id,
                    portal_id=p.portal_id,
                    role=r_str,
                    actor_id=f"demo-assessor-{r_str.lower()}",
                    indicator_count_at_declaration=len(questions_national),
                )
            )

    from datetime import datetime

    from portal.discrepancy import recompute_portal_discrepancy
    from portal.tolerance import effective_tolerance

    tol = effective_tolerance(repo, cycle_national.cycle_id, settings)
    q_ids = [q.question_id for q in questions_national]

    # Recompute for all units
    recompute_portal_discrepancy(repo, session_national, usa.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)
    recompute_portal_discrepancy(repo, session_national, france.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)
    recompute_portal_discrepancy(repo, session_national, brazil.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)
    recompute_portal_discrepancy(repo, session_national, denmark.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)
    recompute_portal_discrepancy(repo, session_national, nigeria.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)
    recompute_portal_discrepancy(repo, session_national, kenya.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)
    recompute_portal_discrepancy(repo, session_national, estonia.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)

    # Close Nigeria's round as exhausted so it enters persistent_discrepancy state
    ng_round = repo.open_round_for_unit(session_national, nigeria.portal_id)
    if ng_round:
        repo.close_round(ng_round.round_id, "exhausted", datetime.now(UTC))
        recompute_portal_discrepancy(repo, session_national, nigeria.portal_id, q_ids, tol, cycle_id=cycle_national.cycle_id)

    # Seed labelling passes, labels, and attempts (T077)
    def _get_qids(indicators: set[str]) -> list[str]:
        return [q.question_id for q in questions_national if q.indicator_id in indicators]

    # 1. Denmark: Awaiting state (dispatched pass, 0 attempts, 0 labels)
    dk_qids = _get_qids({"#015", "#028", "#030", "#088", "#117", "#129", "#131a", "#150"})
    repo.insert_labelling_pass(
        LabellingPass(new_id("pass"), session_national, cycle_national.cycle_id, denmark.portal_id, dk_qids, len(dk_qids), "portal")
    )

    # 2. France: Established state (with at least one deterministic and one classifier label)
    fr_qids = _get_qids({"#015", "#028"})
    pass_fr = LabellingPass(new_id("pass"), session_national, cycle_national.cycle_id, france.portal_id, fr_qids, len(fr_qids), "portal")
    repo.insert_labelling_pass(pass_fr)

    q15 = next(q.question_id for q in questions_national if q.indicator_id == "#015")
    q28 = next(q.question_id for q in questions_national if q.indicator_id == "#028")

    sub_a_15 = repo.latest_human_submission(session_national, q15, france.portal_id, AssessorRole.A)
    sub_b_15 = repo.latest_human_submission(session_national, q15, france.portal_id, AssessorRole.B)
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id=pass_fr.pass_id,
            session_id=session_national,
            portal_id=france.portal_id,
            question_id=q15,
            label=DisagreementLabel.DIFFERENT_SOURCES,
            established_by="deterministic",
            input_digest="digest-france-15",
            stated_reason="Assessors cited different evidence domains.",
            observations=compute_side_observations(sub_a_15, sub_b_15),
            submission_ids={"A": sub_a_15.submission_id if sub_a_15 else "sub-a", "B": sub_b_15.submission_id if sub_b_15 else "sub-b"},
        )
    )
    sub_a_28 = repo.latest_human_submission(session_national, q28, france.portal_id, AssessorRole.A)
    sub_b_28 = repo.latest_human_submission(session_national, q28, france.portal_id, AssessorRole.B)
    repo.insert_disagreement_label(
        DisagreementLabelRecord(
            label_id=new_id("lbl"),
            pass_id=pass_fr.pass_id,
            session_id=session_national,
            portal_id=france.portal_id,
            question_id=q28,
            label=DisagreementLabel.DIFFERENT_JUDGEMENT,
            established_by="classifier",
            input_digest="digest-france-28",
            stated_reason="Assessors reached different judgements on merits of same page.",
            model_identity="vertexai/gemini-2.5-flash-lite",
            prompt_version="1.0.0",
            observations=compute_side_observations(sub_a_28, sub_b_28),
            submission_ids={"A": sub_a_28.submission_id if sub_a_28 else "sub-a", "B": sub_b_28.submission_id if sub_b_28 else "sub-b"},
        )
    )

    # 3. Nigeria: Exhausted state (dispatched pass, 3 failed attempts per dispute, 0 labels)
    ng_qids = _get_qids({"#015", "#028", "#030", "#088", "#117", "#129", "#131a", "#150", "#010", "#002"})
    pass_ng = LabellingPass(new_id("pass"), session_national, cycle_national.cycle_id, nigeria.portal_id, ng_qids, len(ng_qids), "portal")
    repo.insert_labelling_pass(pass_ng)
    for qid in ng_qids:
        for _ in range(3):
            repo.insert_labelling_attempt(
                LabellingAttempt(
                    attempt_id=new_id("att"),
                    pass_id=pass_ng.pass_id,
                    question_id=qid,
                    failure="provider_error",
                    detail="Classifier service unavailable during seed.",
                )
            )

    # 4. Kenya: Access-dominated unit (rate 2/157 = 1.27%, all ONE_BLOCKED)
    ke_qids = _get_qids({"#015", "#028"})
    pass_ke = LabellingPass(new_id("pass"), session_national, cycle_national.cycle_id, kenya.portal_id, ke_qids, len(ke_qids), "portal")
    repo.insert_labelling_pass(pass_ke)
    for qid in ke_qids:
        sub_a = repo.latest_human_submission(session_national, qid, kenya.portal_id, AssessorRole.A)
        sub_b = repo.latest_human_submission(session_national, qid, kenya.portal_id, AssessorRole.B)
        repo.insert_disagreement_label(
            DisagreementLabelRecord(
                label_id=new_id("lbl"),
                pass_id=pass_ke.pass_id,
                session_id=session_national,
                portal_id=kenya.portal_id,
                question_id=qid,
                label=DisagreementLabel.ONE_BLOCKED,
                established_by="classifier",
                input_digest=f"digest-kenya-{qid}",
                stated_reason="One assessor encountered blocking or access failure.",
                model_identity="vertexai/gemini-2.5-flash-lite",
                prompt_version="1.0.0",
                observations=compute_side_observations(sub_a, sub_b),
                submission_ids={"A": sub_a.submission_id if sub_a else "sub-a", "B": sub_b.submission_id if sub_b else "sub-b"},
            )
        )

    # 5. Estonia: Interpretation-dominated unit (rate 2/157 = 1.27%, all DIFFERENT_JUDGEMENT)
    ee_qids = _get_qids({"#015", "#028"})
    pass_ee = LabellingPass(new_id("pass"), session_national, cycle_national.cycle_id, estonia.portal_id, ee_qids, len(ee_qids), "portal")
    repo.insert_labelling_pass(pass_ee)
    for qid in ee_qids:
        sub_a = repo.latest_human_submission(session_national, qid, estonia.portal_id, AssessorRole.A)
        sub_b = repo.latest_human_submission(session_national, qid, estonia.portal_id, AssessorRole.B)
        repo.insert_disagreement_label(
            DisagreementLabelRecord(
                label_id=new_id("lbl"),
                pass_id=pass_ee.pass_id,
                session_id=session_national,
                portal_id=estonia.portal_id,
                question_id=qid,
                label=DisagreementLabel.DIFFERENT_JUDGEMENT,
                established_by="classifier",
                input_digest=f"digest-estonia-{qid}",
                stated_reason="Assessors evaluated the same content but disagreed on interpretation.",
                model_identity="vertexai/gemini-2.5-flash-lite",
                prompt_version="1.0.0",
                observations=compute_side_observations(sub_a, sub_b),
                submission_ids={"A": sub_a.submission_id if sub_a else "sub-a", "B": sub_b.submission_id if sub_b else "sub-b"},
            )
        )

    usa_breakdown = {
        q.question_id: bool(
            repo.latest_human_submission(session_national, q.question_id, usa.portal_id, AssessorRole.A).answer
        )
        for q in questions_national
        if repo.latest_human_submission(session_national, q.question_id, usa.portal_id, AssessorRole.A)
    }
    affirmative = sum(1 for v in usa_breakdown.values() if v)
    repo.insert_publication(
        PublicationRecord(
            publication_id=new_id("pub"), cycle_id=cycle_national.cycle_id, portal_id=usa.portal_id,
            published_by_actor_id="senior-reviewer-demo-seed",
            score=(affirmative / len(usa_breakdown)) if usa_breakdown else 0.0,
            score_breakdown=usa_breakdown,
        )
    )

    return {
        "cycles": [cycle_national.cycle_id, cycle_losi.cycle_id],
        "denmark_portal_id": denmark.portal_id,
        "usa_portal_id": usa.portal_id,
        "france_portal_id": france.portal_id,
        "brazil_portal_id": brazil.portal_id,
        "nigeria_portal_id": nigeria.portal_id,
        "kenya_portal_id": kenya.portal_id,
        "estonia_portal_id": estonia.portal_id,
    }


def _seed_human_pair(
    repo: Repository, session_id: str, cycle_id: str, portal_id: str,
    questions: list[Question], disagree_on: set[str],
) -> None:
    for q in questions:
        prefill = repo.latest_prefill(session_id, q.question_id, portal_id)
        ai_answer = bool(prefill.answer) if (prefill and prefill.suggested) else True

        answer_a = ai_answer
        answer_b = (not ai_answer) if q.indicator_id in disagree_on else ai_answer

        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"), session_id=session_id, cycle_id=cycle_id,
                question_id=q.question_id, portal_id=portal_id, role=AssessorRole.A,
                assessor_actor_id="demo-assessor-a", answer=answer_a,
                evidence_url=prefill.evidence_url if prefill else None,
                ai_suggested_answer=prefill.answer if (prefill and prefill.suggested) else None,
                ai_suggestion_accepted=(answer_a == prefill.answer) if (prefill and prefill.suggested) else None,
            )
        )
        repo.insert_human_submission(
            HumanAssessorSubmission(
                submission_id=new_id("hsub"), session_id=session_id, cycle_id=cycle_id,
                question_id=q.question_id, portal_id=portal_id, role=AssessorRole.B,
                assessor_actor_id="demo-assessor-b", answer=answer_b,
                evidence_url=prefill.evidence_url if prefill else None,
                ai_suggested_answer=prefill.answer if (prefill and prefill.suggested) else None,
                ai_suggestion_accepted=(answer_b == prefill.answer) if (prefill and prefill.suggested) else None,
            )
        )


# Backward compatibility alias
seed_ekap_demo = seed_demo_data

