"""Disagreement labelling REST API endpoints (spec 017, T073, FR-DL-081).

Read-only projections over disagreement labels, ambiguity measures, and labelling counts.
None of these endpoints creates records or invokes models (FR-DL-045).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import make_repo_dependency
from api.schemas import (
    IndicatorAmbiguityItemResponse,
    LabelProvenanceResponse,
    LabellingCountsResponse,
    NotFound,
    UnitLabelItemResponse,
)
from portal.common import session_id_for_cycle
from portal.disagreement_labels import (
    indicator_ambiguity,
    labelling_counts,
    unit_labelling_state,
)
from shared.config.settings import Settings
from shared.persistence.repositories import Repository


def build_labels_router(database_path: str, settings: Settings) -> APIRouter:
    router = APIRouter(tags=["labels"])
    get_repo = make_repo_dependency(database_path)

    @router.get(
        "/cycles/{cycle_id}/units/{portal_id}/labels",
        response_model=list[UnitLabelItemResponse],
    )
    def get_unit_labels(
        cycle_id: str,
        portal_id: str,
        repo: Repository = Depends(get_repo),
    ) -> list[UnitLabelItemResponse]:
        """Returns the disagreement label projection and provenance for a unit (FR-DL-081).

        A pure read over the projection. Carries no field capable of holding an assessor's answer or notes.
        """
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id})
        portal = repo.get_portal(portal_id)
        if portal is None:
            raise NotFound(f"Portal '{portal_id}' not found.", details={"portal_id": portal_id})

        session_id = session_id_for_cycle(cycle_id)
        states = unit_labelling_state(repo, session_id, portal_id)
        items = []
        for qid, st in states.items():
            prov = None
            if st.record:
                prov = LabelProvenanceResponse(
                    established_by=st.record.established_by,
                    model_identity=st.record.model_identity,
                    prompt_version=st.record.prompt_version,
                    input_digest=st.record.input_digest,
                    created_at=(
                        st.record.created_at.isoformat()
                        if hasattr(st.record.created_at, "isoformat")
                        else str(st.record.created_at)
                    ),
                )
            obs = {}
            for role_k, obs_list in st.observations.items():
                obs[role_k] = [o.value if hasattr(o, "value") else str(o) for o in obs_list]
            items.append(
                UnitLabelItemResponse(
                    question_id=st.question_id,
                    state=st.state,
                    label=st.label.value if st.label else None,
                    badge=st.badge,
                    observations=obs,
                    stale=st.stale,
                    provenance=prov,
                )
            )
        return items

    @router.get(
        "/cycles/{cycle_id}/indicator-ambiguity",
        response_model=list[IndicatorAmbiguityItemResponse],
    )
    def get_cycle_indicator_ambiguity(
        cycle_id: str,
        repo: Repository = Depends(get_repo),
    ) -> list[IndicatorAmbiguityItemResponse]:
        """Returns the ranked indicator ambiguity measure for a cycle (FR-DL-070 to FR-DL-075, FR-DL-081)."""
        cycle = repo.get_cycle(cycle_id)
        if cycle is None:
            raise NotFound(f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id})
        report = indicator_ambiguity(repo, cycle_id=cycle_id)
        return [
            IndicatorAmbiguityItemResponse(
                indicator_key=item.indicator_key,
                judged_differently=item.judged_differently,
                units_measured=item.units_measured,
                units_total=item.units_total,
                labelled_share=item.labelled_share,
            )
            for item in report
        ]

    @router.get(
        "/labelling/counts",
        response_model=LabellingCountsResponse,
    )
    def get_labelling_counts(
        cycle_id: str | None = None,
        repo: Repository = Depends(get_repo),
    ) -> LabellingCountsResponse:
        """Returns dispute labelling operational counts (FR-DL-091, FR-DL-092).

        A rising awaiting indicates a down model provider; a rising exhausted indicates 3 failed retries.
        """
        if cycle_id:
            cycle = repo.get_cycle(cycle_id)
            if cycle is None:
                raise NotFound(f"Cycle '{cycle_id}' not found.", details={"cycle_id": cycle_id})
        counts = labelling_counts(repo, cycle_id=cycle_id)
        return LabellingCountsResponse(
            awaiting=counts.awaiting,
            exhausted=counts.exhausted,
            established_deterministic=counts.established_deterministic,
            established_by_classifier=counts.established_by_classifier,
        )

    return router
