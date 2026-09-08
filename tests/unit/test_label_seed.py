"""Unit test verifying seed_demo_data produces all 4 states and composition fixtures (T077)."""

from __future__ import annotations

import pytest

from portal.common import ensure_session
from portal.disagreement_labels import (
    unit_label_composition,
    unit_labelling_state,
)
from portal.seed import seed_demo_data
from shared.persistence.repositories import Repository
from shared.state.entities import DisagreementLabel

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_seed_demo_data_labelling_states_and_compositions(conn, settings):
    repo = Repository(conn)
    result = await seed_demo_data(repo, settings)

    session_id = ensure_session(repo, "un-egov-2026")

    # 1. Brazil: never_labelled
    br_states = unit_labelling_state(repo, session_id, result["brazil_portal_id"])
    assert len(br_states) == 10
    assert all(s.state == "never_labelled" for s in br_states.values())

    # 2. Denmark: awaiting
    dk_states = unit_labelling_state(repo, session_id, result["denmark_portal_id"])
    assert len(dk_states) == 8
    assert all(s.state == "awaiting" for s in dk_states.values())

    # 3. France: established (with deterministic and classifier labels)
    fr_states = unit_labelling_state(repo, session_id, result["france_portal_id"])
    assert len(fr_states) == 2
    assert all(s.state == "established" for s in fr_states.values())
    labels = [s.label for s in fr_states.values()]
    established_bies = [s.record.established_by for s in fr_states.values() if s.record]
    assert DisagreementLabel.DIFFERENT_SOURCES in labels
    assert DisagreementLabel.DIFFERENT_JUDGEMENT in labels
    assert "deterministic" in established_bies
    assert "classifier" in established_bies

    # 4. Nigeria: exhausted
    ng_states = unit_labelling_state(repo, session_id, result["nigeria_portal_id"])
    assert len(ng_states) == 10
    assert all(s.state == "exhausted" for s in ng_states.values())

    # 5. Access-dominated (Kenya) and interpretation-dominated (Estonia) at same rate
    from portal.discrepancy import _compare

    qs = repo.list_questions("un-egov-2026")
    q_ids = [q.question_id for q in qs]
    cmp_ke = _compare(repo, session_id, result["kenya_portal_id"], q_ids, 0.05)
    cmp_ee = _compare(repo, session_id, result["estonia_portal_id"], q_ids, 0.05)
    assert cmp_ke is not None and cmp_ee is not None
    assert cmp_ke[2] == cmp_ee[2]
    assert cmp_ke[2] > 0.0

    ke_comp = unit_label_composition(repo, session_id, result["kenya_portal_id"])
    ee_comp = unit_label_composition(repo, session_id, result["estonia_portal_id"])
    assert ke_comp == {"One couldn't access": 2}
    assert ee_comp == {"Judged differently": 2}
