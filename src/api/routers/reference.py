"""Reference metadata router (question sets and UN member state registry)."""

from __future__ import annotations

from fastapi import APIRouter

from api.schemas import (
    CountryItem,
    CountryListResponse,
    QuestionSetListResponse,
    QuestionSetSummary,
)
from shared.config.settings import Settings
from shared.questionnaires.registry import list_question_sets
from shared.reference.countries import list_countries


def build_reference_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["reference"])

    @router.get("/reference/question-sets", response_model=QuestionSetListResponse)
    def get_question_sets():
        qsets = list_question_sets()
        return QuestionSetListResponse(
            question_sets=[
                QuestionSetSummary(
                    set_id=s.set_id,
                    label=s.label,
                    description=s.label,
                    indicator_count=s.question_count,
                )
                for s in qsets
            ]
        )

    @router.get("/reference/countries", response_model=CountryListResponse)
    def get_countries():
        countries = list_countries()
        return CountryListResponse(
            countries=[
                CountryItem(
                    code=c.code,
                    name=c.name,
                    most_populous_city=c.most_populous_city,
                )
                for c in countries
            ]
        )

    return router
