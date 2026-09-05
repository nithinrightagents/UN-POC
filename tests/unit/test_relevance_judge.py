"""T038: Unit tests for LLM-based semantic relevance judge (US3).

Tests choose_best with a stubbed provider for:
1. Distinguishing personal data access vs accessibility (#022-shaped case)
2. Returning None when no candidate semantically fits the question.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.tools.linkresolution.relevance import choose_best

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_choose_best_picks_semantically_correct_candidate():
    mock_provider = MagicMock()
    mock_response = MagicMock()
    # Model selects candidate index 1 ("Your Online Account") over index 0 ("Accessibility Statement")
    mock_response.text = json.dumps({"index": 1})
    mock_provider.generate = AsyncMock(return_value=mock_response)

    candidates = [
        {"url": "https://www.usa.gov/accessibility", "title": "Accessibility Statement", "snippet": "Section 508 accessibility"},
        {"url": "https://www.login.gov", "title": "Your Online Account and Personal Data", "snippet": "Access your personal data and profile online"},
    ]

    index = await choose_best(
        provider=mock_provider,
        model="gemini-2.5-flash",
        question={"title": "Personal Data Access", "what": "Can citizens access personal records online?"},
        candidates=candidates,
    )

    assert index == 1


@pytest.mark.asyncio
async def test_choose_best_returns_none_when_no_candidate_fits():
    mock_provider = MagicMock()
    mock_response = MagicMock()
    mock_response.text = json.dumps({"index": None})
    mock_provider.generate = AsyncMock(return_value=mock_response)

    candidates = [
        {"url": "https://www.usa.gov/weather", "title": "Weather", "snippet": "Forecasts"},
    ]

    index = await choose_best(
        provider=mock_provider,
        model="gemini-2.5-flash",
        question={"title": "National CIO", "what": "Name and office of the National CIO"},
        candidates=candidates,
    )

    assert index is None
