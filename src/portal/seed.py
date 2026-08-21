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

import asyncio
import hashlib
import pathlib

import httpx

from agents.prefill.heuristic import run_heuristic_prefill
from portal.common import ensure_session
from portal.msq import ingest_msq_pdf
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.questionnaires.registry import load_question_set
from shared.state.entities import (
    AgentRunState,
    AssessorAgentRun,
    AssessorCompletion,
    AssessorRole,
    ElementReference,
    EvidenceArtifact,
    HumanAssessorSubmission,
    Prefill,
    ProjectType,
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
]

_LOSI_UNITS = [
    ("LON", "London", "https://www.london.gov.uk"),
    ("MCR", "Manchester", "https://www.manchester.gov.uk"),
    ("EDI", "Edinburgh", "https://www.edinburgh.gov.uk"),
]


async def _prefill_unit(
    repo: Repository, session_id: str, portal: TargetPortal, questions: list[Question]
) -> None:
    async with httpx.AsyncClient() as client:
        try:
            all_ids = [q.indicator_id or q.question_id for q in questions]
            results = await run_heuristic_prefill(client, portal.resolved_url, all_ids)
        except Exception:
            return
    by_indicator = {res.indicator_id: res for res in results}
    for q in questions:
        res = by_indicator.get(q.indicator_id or q.question_id)
        if not res:
            continue
        evidence = EvidenceArtifact(
            artifact_id=new_id("ev"),
            resolved_url=res.evidence_url,
            element_reference=ElementReference(
                css_path="(heuristic-check)",
                text_hash=hashlib.sha256(res.snippet.encode()).hexdigest()[:12],
            ),
            element_text=res.snippet or res.reasoning,
            verifiability_status="verified" if res.confidence >= 70 else "unverified",
        )
        repo.insert_evidence(evidence)
        repo.insert_prefill(
            Prefill(
                prefill_id=new_id("pf"),
                run_id=new_id("run"),
                session_id=session_id,
                cycle_id=portal.cycle_id,
                question_id=q.question_id,
                portal_id=portal.portal_id,
                suggested=True,
                answer=res.answer,
                confidence=res.confidence,
                justification=res.reasoning,
                evidence_url=res.evidence_url,
                supplying_source="heuristic",
                agreement_outcome="unanimous",
            )
        )


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
    session_losi = ensure_session(repo, cycle_losi.cycle_id)

    national_portals = []
    for code, name, url in _NATIONAL_UNITS:
        portal = repo.get_portal_by_country(cycle_national.cycle_id, code)
        if portal is None:
            portal = TargetPortal(
                portal_id=new_id("portal"), cycle_id=cycle_national.cycle_id, country_id=code,
                resolved_url=url, unit_type="country", display_name=name,
            )
            repo.insert_portal(portal)
        national_portals.append(portal)

    losi_portals = []
    for code, name, url in _LOSI_UNITS:
        portal = repo.get_portal_by_country(cycle_losi.cycle_id, code)
        if portal is None:
            portal = TargetPortal(
                portal_id=new_id("portal"), cycle_id=cycle_losi.cycle_id, country_id=code,
                resolved_url=url, unit_type="city", display_name=name,
            )
            repo.insert_portal(portal)
        losi_portals.append(portal)

    await asyncio.gather(
        *[_prefill_unit(repo, session_national, p, questions_national) for p in national_portals],
        *[_prefill_unit(repo, session_losi, p, questions_losi) for p in losi_portals],
    )

    if _DENMARK_MSQ_PATH.exists():
        doc = ingest_msq_pdf(str(_DENMARK_MSQ_PATH), cycle_national.cycle_id, "DK", _DENMARK_MSQ_PATH.name)
        repo.insert_msq_document(doc)
        if getattr(settings, "google_cloud_project", None):
            try:
                from core.llm_factory import ModelProvider
                from portal.msq import match_msq_links
                provider = ModelProvider(
                    settings.google_cloud_project,
                    settings.google_cloud_location,
                    settings.google_genai_use_vertexai,
                    settings.google_api_key,
                )
                candidates = await match_msq_links(doc, questions_national, provider, settings.validator_model)
                for candidate in candidates:
                    repo.insert_msq_link_candidate(candidate)
            except Exception:
                pass

    denmark = next(p for p in national_portals if p.country_id == "DK")
    usa = next(p for p in national_portals if p.country_id == "US")

    # Denmark: Assessor A and B mostly agree but split on 8 of the 157
    # national questions (8/157 = 5.10%), deliberately crossing the 5%
    # human_discrepancy_rate_threshold so the arbitration queue has a real
    # case to show. All 8 are single-occurrence Content Provision indicators
    # (no sector-breakdown duplication) so the count is exact.
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, denmark.portal_id, questions_national,
        disagree_on={"#015", "#028", "#030", "#088", "#117", "#129", "#131a", "#150"},
    )

    # USA: Assessor A and B fully agree -- the clean path straight to publish.
    _seed_human_pair(
        repo, session_national, cycle_national.cycle_id, usa.portal_id, questions_national,
        disagree_on=set(),
    )

    from portal.discrepancy import recompute_portal_discrepancy

    recompute_portal_discrepancy(
        repo, session_national, denmark.portal_id, [q.question_id for q in questions_national],
        settings.human_discrepancy_rate_threshold,
    )
    recompute_portal_discrepancy(
        repo, session_national, usa.portal_id, [q.question_id for q in questions_national],
        settings.human_discrepancy_rate_threshold,
    )

    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_national,
            cycle_id=cycle_national.cycle_id,
            portal_id=usa.portal_id,
            role="A",
            actor_id="demo-assessor-a",
            indicator_count_at_declaration=len(questions_national),
        )
    )
    repo.insert_assessor_completion(
        AssessorCompletion(
            completion_id=new_id("comp"),
            session_id=session_national,
            cycle_id=cycle_national.cycle_id,
            portal_id=usa.portal_id,
            role="B",
            actor_id="demo-assessor-b",
            indicator_count_at_declaration=len(questions_national),
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

