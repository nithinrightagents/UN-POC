"""MSQ document ingestion and link extraction router (spec 005 / 006)."""

from __future__ import annotations

import logging
import pathlib
import tempfile

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from api.deps import make_repo_dependency
from api.schemas import (
    InvalidRequest,
    MSQDetailResponse,
    MSQUploadResponse,
    NotFound,
)
from portal.msq import extract_pdf_text, ingest_msq_pdf, match_msq_links, parse_msq_text
from shared.config.settings import Settings
from shared.persistence.repositories import Repository
from shared.state.entities import MSQDocument, new_id

logger = logging.getLogger(__name__)


def build_msq_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["msq"])
    get_repo = make_repo_dependency(database_path)

    @router.post(
        "/cycles/{cycle_id}/units/{portal_id}/msq",
        response_model=MSQUploadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_msq(
        cycle_id: str,
        portal_id: str,
        msq_file: UploadFile | None = File(None),
        text_content: str | None = Form(None),
        page_count: int = Form(1),
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        portal = repo.get_portal(portal_id)
        if portal is None or portal.cycle_id != cycle_id:
            raise NotFound(
                f"Unit '{portal_id}' not found in cycle '{cycle_id}'.",
                details={"portal_id": portal_id, "cycle_id": cycle_id},
            )

        doc: MSQDocument | None = None
        pg_count = page_count

        if msq_file is not None:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
                try:
                    contents = await msq_file.read()
                    tmp.write(contents)
                    tmp.flush()
                    doc = ingest_msq_pdf(
                        tmp_path,
                        cycle_id,
                        portal.country_id,
                        msq_file.filename or "uploaded.pdf",
                    )
                finally:
                    pathlib.Path(tmp_path).unlink(missing_ok=True)
        elif text_content is not None:
            raw = text_content.strip()
            if not raw:
                raise InvalidRequest("The text_content was empty.")
            parsed = parse_msq_text(raw)
            doc = MSQDocument(
                msq_id=new_id("msq"),
                country_id=portal.country_id,
                cycle_id=cycle_id,
                source_filename="text_upload.txt",
                raw_text=raw,
                sections=parsed["sections"],
                extracted_urls=parsed["urls"],
            )
        else:
            raise InvalidRequest(
                "Either 'msq_file' or 'text_content' must be provided."
            )

        if doc is None or not doc.raw_text:
            raise InvalidRequest(
                "The MSQ content was empty or could not be read."
            )

        repo.insert_msq_document(doc)

        questions = repo.list_questions(cycle_id)
        extracted: dict[str, str] = {}
        try:
            # Use direct URL candidate mapping from extracted URLs if LLM provider not configured or as fallback
            extracted = match_msq_links(doc.raw_text, questions)
            for q_id, url in extracted.items():
                repo.insert_prefill_candidate(
                    cycle_id, portal.country_id, q_id, url, "msq_match"
                )
        except Exception as exc:
            logger.warning(
                "MSQ link matching error for cycle=%s country=%s: %s",
                cycle_id,
                portal.country_id,
                exc,
            )

        return MSQUploadResponse(
            country_id=portal.country_id,
            cycle_id=cycle_id,
            page_count=pg_count,
            extracted_links_count=len(extracted),
            extracted_links=extracted,
        )

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/msq",
        response_model=MSQDetailResponse,
    )
    def get_msq_status(
        cycle_id: str,
        portal_id: str,
        repo: Repository = Depends(get_repo),
    ):
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(
                f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id}
            )

        portal = repo.get_portal(portal_id)
        if portal is None or portal.cycle_id != cycle_id:
            raise NotFound(
                f"Unit '{portal_id}' not found in cycle '{cycle_id}'.",
                details={"portal_id": portal_id, "cycle_id": cycle_id},
            )

        msq = repo.find_msq_document(cycle_id, portal.country_id)
        if msq is None:
            return MSQDetailResponse(
                has_msq=False,
                cycle_id=cycle_id,
                country_id=portal.country_id,
                page_count=None,
                text_snippet=None,
                matched_candidate_count=0,
            )

        text_snippet = msq.raw_text[:200] if hasattr(msq, "raw_text") and msq.raw_text else None
        extracted_cnt = len(msq.extracted_urls) if hasattr(msq, "extracted_urls") and msq.extracted_urls else 0

        return MSQDetailResponse(
            has_msq=True,
            cycle_id=cycle_id,
            country_id=portal.country_id,
            page_count=1,
            text_snippet=text_snippet,
            matched_candidate_count=extracted_cnt,
        )

    return router
