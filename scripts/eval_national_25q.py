"""National-level retrieval evaluation harness (goal: prefill retrieval tuning, 2026-09).

Creates a fresh evaluation project (national_osi scope) covering US and DK,
samples a fixed random set of indicators from the national questionnaire, and
runs link resolution (resolve_only) for each indicator against BOTH country
portals -- no reference-link fixture exists for this project, so there is no
correctness scoring here; this only captures what the pipeline resolves so it
can be compared against independent web verification.

Denmark's real MSQ PDF (understanding docs/Denmark - MS MSQ 2024.pdf) is
ingested and matched against the sample so the "msq" source in the resolution
chain has real candidates to offer, mirroring how a national project with a
self-reported questionnaire would actually be run. USA has no MSQ, so its
questions rely entirely on live search.

Usage:
    python scripts/eval_national_25q.py [--sample-size 25] [--seed 42] [--output-json PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from benchmark.runner import run_benchmark_session
from benchmark.trace import read_unit_traces
from core.llm_factory import ModelProvider
from portal.msq import ingest_msq_pdf, match_msq_links
from shared.config.settings import load_settings
from shared.persistence.repositories import Repository
from shared.persistence.schema import connect, init_db
from shared.questionnaires.registry import load_question_set
from shared.reference.domains import resolve_admissible_domain_suffixes
from shared.state.entities import ProjectType, SurveyCycle, TargetPortal, new_id

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CYCLE_ID = "eval-national-25q-2026"
BENCHMARK_SET_ID = "eval-national-25q"
DB_PATH = str(REPO_ROOT / "data" / "eval_national_25q.db")
DENMARK_MSQ_PATH = REPO_ROOT / "understanding docs" / "Denmark - MS MSQ 2024.pdf"

_COUNTRIES = [
    ("DK", "Denmark", "https://www.borger.dk"),
    ("US", "United States", "https://www.usa.gov"),
]


async def _ensure_project(repo: Repository) -> tuple[list, list[TargetPortal]]:
    questions = load_question_set("un_osi_2024_master", CYCLE_ID)
    for q in questions:
        if repo.get_question(q.question_id) is None:
            repo.insert_question(q)

    cycle = repo.get_cycle(CYCLE_ID)
    if cycle is None:
        cycle = SurveyCycle(
            cycle_id=CYCLE_ID,
            name="Retrieval Eval — National 25Q (US/DK)",
            questionnaire_ref="UN MSQ 2026 Indicator Set",
            country_set=[c[0] for c in _COUNTRIES],
            project_type=ProjectType.NATIONAL_OSI,
        )
        repo.insert_cycle(cycle)

    portals: list[TargetPortal] = []
    for code, name, url in _COUNTRIES:
        portal = repo.get_portal_by_country(CYCLE_ID, code)
        if portal is None:
            suffixes = sorted(resolve_admissible_domain_suffixes(country_id=code, unit_type="country"))
            portal = TargetPortal(
                portal_id=new_id("portal"), cycle_id=CYCLE_ID, country_id=code,
                resolved_url=url, unit_type="country", display_name=name,
                admissible_domain_suffixes=suffixes,
            )
            repo.insert_portal(portal)
        portals.append(portal)

    return questions, portals


async def _ingest_denmark_msq(repo: Repository, questions: list, provider: ModelProvider, model: str) -> int:
    if not DENMARK_MSQ_PATH.exists():
        print(f"    (no MSQ file at {DENMARK_MSQ_PATH}, skipping)")
        return 0
    existing = repo.find_msq_document(CYCLE_ID, "DK")
    if existing is None:
        doc = ingest_msq_pdf(str(DENMARK_MSQ_PATH), CYCLE_ID, "DK", DENMARK_MSQ_PATH.name)
        repo.insert_msq_document(doc)
    else:
        doc = existing
    candidates = await match_msq_links(doc, questions, provider, model)
    for c in candidates:
        repo.insert_msq_link_candidate(c)
    return len(candidates)


async def main(sample_size: int, seed: int, output_json: str | None) -> None:
    settings = load_settings()
    settings.database_path = DB_PATH
    init_db(DB_PATH)
    conn = connect(DB_PATH)
    repo = Repository(conn)

    print("==> Effective retrieval configuration:")
    print(f"    resolution_order            = {settings.resolution_order}")
    print(f"    msq_link_source_enabled     = {settings.msq_link_source_enabled}")
    print(f"    kb_link_source_enabled      = {settings.kb_link_source_enabled}")
    print(f"    serper_api_key configured   = {bool(getattr(settings, 'serper_api_key', ''))}")
    print(f"    firecrawl_api_key configured= {bool(getattr(settings, 'firecrawl_api_key', ''))}")
    print()

    print("==> Building evaluation project (national_osi, US + DK) ...")
    questions, portals = await _ensure_project(repo)
    print(f"    {len(questions)} national indicators loaded, {len(portals)} portals ready")

    provider = ModelProvider(
        settings.google_cloud_project,
        settings.google_cloud_location,
        settings.google_genai_use_vertexai,
        settings.google_api_key,
    )

    print("==> Ingesting Denmark MSQ and matching to sample ...")
    msq_count = await _ingest_denmark_msq(repo, questions, provider, settings.validator_model)
    print(f"    {msq_count} MSQ link candidates matched")

    rng = random.Random(seed)
    sample = rng.sample(questions, min(sample_size, len(questions)))
    sample.sort(key=lambda q: q.indicator_id or q.question_id)
    print(f"==> Sampled {len(sample)} indicators (seed={seed}):")
    for q in sample:
        print(f"    {q.indicator_id or q.question_id}: {q.title or q.text[:60]}")
    print()

    print(f"==> Resolving links for {len(sample)} indicators x {len(portals)} countries (resolve_only) ...")
    session_id, _ = await run_benchmark_session(
        repo=repo,
        settings=settings,
        benchmark_set_id=BENCHMARK_SET_ID,
        questions=sample,
        portals=portals,
        provider=provider,
        resolve_only=True,
    )
    traces = read_unit_traces(repo, session_id)
    print(f"    session_id = {session_id}, {len(traces)} units resolved")
    print()

    portal_by_id = {p.portal_id: p for p in portals}
    results = []
    resolved_count = 0
    unresolved_count = 0
    by_source: dict[str, int] = {}

    for (qid, pid), tr in sorted(traces.items()):
        portal = portal_by_id.get(pid)
        country = portal.country_id if portal else pid
        q = next((q for q in sample if q.question_id == qid), None)
        indicator_id = q.indicator_id if q else qid
        title = q.title or (q.text[:80] if q else "")

        if tr.resolved_url:
            resolved_count += 1
        else:
            unresolved_count += 1
        src = tr.supplying_source or "none"
        by_source[src] = by_source.get(src, 0) + 1

        results.append({
            "question_id": qid,
            "indicator_id": indicator_id,
            "title": title,
            "country_id": country,
            "resolved_url": tr.resolved_url,
            "supplying_source": tr.supplying_source,
            "history": list(tr.resolution_history),
        })

        print(f"[{country}] {indicator_id} {title}")
        print(f"    -> {tr.resolved_url or 'UNRESOLVED'}  (source={tr.supplying_source})")
        for h in tr.resolution_history:
            reason = h.get("rejection_reason") if isinstance(h, dict) else None
            src_h = h.get("source") if isinstance(h, dict) else None
            ret_h = h.get("returned") if isinstance(h, dict) else None
            usable = h.get("usable") if isinstance(h, dict) else None
            if not usable and ret_h:
                print(f"       [{src_h}] rejected {ret_h}: {reason}")
            elif not usable and not ret_h:
                print(f"       [{src_h}] no candidate: {reason}")
        print()

    print("=" * 70)
    print(f"Resolved: {resolved_count} / {len(traces)}  |  Unresolved: {unresolved_count}")
    print("By supplying source:")
    for src, cnt in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  - {src}: {cnt}")
    print("=" * 70)

    if output_json:
        out_path = pathlib.Path(output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({
            "session_id": session_id,
            "sample_size": len(sample),
            "seed": seed,
            "resolved_count": resolved_count,
            "unresolved_count": unresolved_count,
            "by_source": by_source,
            "results": results,
        }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"\nSaved detailed results to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-json", type=str, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.sample_size, args.seed, args.output_json))
