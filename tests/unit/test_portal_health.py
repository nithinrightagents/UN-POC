"""Unit tests for portal registration health check (spec 016 T021)."""

from __future__ import annotations

import httpx
import pytest

from portal.health import check_portal_registration_health
from shared.state.entities import TargetPortal

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_portal_health_unset():
    portal = TargetPortal(portal_id="p1", cycle_id="c1", country_id="US", resolved_url=None)
    async with httpx.AsyncClient() as client:
        report = await check_portal_registration_health(client, portal)
    assert report.status == "unset"


@pytest.mark.asyncio
async def test_portal_health_healthy():
    portal = TargetPortal(portal_id="p1", cycle_id="c1", country_id="US", resolved_url="https://example.gov")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OK")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    report = await check_portal_registration_health(client, portal)
    assert report.status == "healthy"
    assert report.status_code == 200


@pytest.mark.asyncio
async def test_portal_health_redirecting():
    portal = TargetPortal(portal_id="p1", cycle_id="c1", country_id="US", resolved_url="https://example.gov")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"Location": "https://new.example.gov"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    report = await check_portal_registration_health(client, portal)
    assert report.status == "redirecting"
    assert report.redirect_target == "https://new.example.gov"


@pytest.mark.asyncio
async def test_portal_health_unreachable():
    portal = TargetPortal(portal_id="p1", cycle_id="c1", country_id="US", resolved_url="https://broken.gov")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Server Error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    report = await check_portal_registration_health(client, portal)
    assert report.status == "unreachable"
    assert report.status_code == 500
