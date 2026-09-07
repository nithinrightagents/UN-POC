"""Portal registration health check (spec 016 T021).

Probes TargetPortal.resolved_url and reports unreachable, redirecting, or unset registrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from shared.state.entities import TargetPortal


PortalHealthStatus = Literal["healthy", "redirecting", "unreachable", "unset"]


@dataclass(frozen=True)
class PortalHealthReport:
    portal_id: str
    url: str | None
    status: PortalHealthStatus
    status_code: int | None = None
    redirect_target: str | None = None
    detail: str = ""


async def check_portal_registration_health(
    client: httpx.AsyncClient,
    portal: TargetPortal,
) -> PortalHealthReport:
    """Probe portal.resolved_url and check if reachable, redirecting, or unset."""
    if not portal.resolved_url:
        return PortalHealthReport(
            portal_id=portal.portal_id,
            url=None,
            status="unset",
            detail="No portal URL registered",
        )

    url = portal.resolved_url
    try:
        resp = await client.get(url, follow_redirects=False, timeout=5.0)
        if 300 <= resp.status_code < 400:
            dest = resp.headers.get("Location")
            return PortalHealthReport(
                portal_id=portal.portal_id,
                url=url,
                status="redirecting",
                status_code=resp.status_code,
                redirect_target=dest,
                detail=f"Redirects with {resp.status_code} to {dest}",
            )
        if resp.status_code >= 400:
            return PortalHealthReport(
                portal_id=portal.portal_id,
                url=url,
                status="unreachable",
                status_code=resp.status_code,
                detail=f"HTTP {resp.status_code}",
            )
        return PortalHealthReport(
            portal_id=portal.portal_id,
            url=url,
            status="healthy",
            status_code=resp.status_code,
            detail="Reachable and live",
        )
    except Exception as exc:
        return PortalHealthReport(
            portal_id=portal.portal_id,
            url=url,
            status="unreachable",
            detail=str(exc),
        )


def check_portal_registration_health_sync(
    portal: TargetPortal,
    timeout: float = 2.0,
) -> PortalHealthReport:
    """Synchronous portal registration health check."""
    if not portal.resolved_url:
        return PortalHealthReport(
            portal_id=portal.portal_id,
            url=None,
            status="unset",
            detail="No portal URL registered",
        )
    url = portal.resolved_url
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            resp = client.get(url)
            if 300 <= resp.status_code < 400:
                dest = resp.headers.get("Location")
                return PortalHealthReport(
                    portal_id=portal.portal_id,
                    url=url,
                    status="redirecting",
                    status_code=resp.status_code,
                    redirect_target=dest,
                    detail=f"Redirects with {resp.status_code} to {dest}",
                )
            if resp.status_code >= 400:
                return PortalHealthReport(
                    portal_id=portal.portal_id,
                    url=url,
                    status="unreachable",
                    status_code=resp.status_code,
                    detail=f"HTTP {resp.status_code}",
                )
            return PortalHealthReport(
                portal_id=portal.portal_id,
                url=url,
                status="healthy",
                status_code=resp.status_code,
                detail="Reachable and live",
            )
    except Exception as exc:
        return PortalHealthReport(
            portal_id=portal.portal_id,
            url=url,
            status="unreachable",
            detail=str(exc),
        )

