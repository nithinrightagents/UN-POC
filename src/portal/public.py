"""Public Knowledge Base (spec 005 Section 3.7).

Reads *only* PublicationRecord rows -- never a unit's live assessment state.
Once a Senior Reviewer clicks Publish (admin.py), the same database row is
what this surface renders; there is no export/import step between assessment
and publication, which is the "feeds directly into public reporting views"
requirement from the transcript. One code path serves both a national OSI
ranking table and a LOSI city table -- `cycle.project_type` only changes the
label, not the query, per spec 005 Section 3.7.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from portal.common import repo_factory
from shared.state.entities import ProjectType


def build_public_router(database_path: str, templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()
    repo = repo_factory(database_path)

    @router.get("/public", response_class=HTMLResponse)
    def index(request: Request):
        r = repo()
        published_cycle_ids = r.list_all_published_cycles()
        cycles = [r.get_cycle(cid) for cid in published_cycle_ids]
        cycles = [c for c in cycles if c]
        return templates.TemplateResponse(request, "public_index.html", {"cycles": cycles})

    @router.get("/public/{cycle_id}", response_class=HTMLResponse)
    def cycle_rankings(request: Request, cycle_id: str):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        records = r.list_published_portals(cycle_id)
        rows = []
        for rec in sorted(records, key=lambda x: x.score, reverse=True):
            portal = r.get_portal(rec.portal_id)
            rows.append({"record": rec, "portal": portal})
        is_losi = cycle and cycle.project_type == ProjectType.LOSI_CITY
        return templates.TemplateResponse(
            request, "public_rankings.html",
            {"cycle": cycle, "rows": rows, "is_losi": is_losi},
        )

    @router.get("/public/{cycle_id}/{portal_id}", response_class=HTMLResponse)
    def unit_profile(request: Request, cycle_id: str, portal_id: str):
        r = repo()
        cycle = r.get_cycle(cycle_id)
        portal = r.get_portal(portal_id)
        record = r.latest_publication(cycle_id, portal_id)
        # include_retired=True: this renders an already-published scorecard, a
        # historical record -- an indicator retired after publication should
        # still show its title/text here, not silently blank out.
        questions_by_id = {q.question_id: q for q in r.list_questions(cycle_id, include_retired=True)}
        breakdown = []
        if record:
            for qid, answer in record.score_breakdown.items():
                q = questions_by_id.get(qid)
                breakdown.append({"question": q, "question_id": qid, "answer": answer})
        return templates.TemplateResponse(
            request, "public_profile.html",
            {"cycle": cycle, "portal": portal, "portal_id": portal_id, "record": record, "breakdown": breakdown},
        )

    return router
