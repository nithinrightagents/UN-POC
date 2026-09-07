"""URL staleness and liveness probing (spec 009 / spec 016 T018)."""

from __future__ import annotations

import httpx


async def check_url_staleness(
    url: str | None, client: httpx.AsyncClient | None = None
) -> bool:
    """Check if a reference URL is stale (no longer serves a page).

    Returns True if stale (broken/dead), False if reachable and serving a page.
    """
    if not url:
        return False

    async def _probe(c: httpx.AsyncClient) -> bool:
        try:
            resp = await c.head(url, follow_redirects=True, timeout=5.0)
            if resp.status_code < 400:
                return False
            if resp.status_code in (404, 410, 500, 502, 503, 504):
                # Fall back to GET before confirming dead
                get_resp = await c.get(url, follow_redirects=True, timeout=5.0)
                return get_resp.status_code >= 400
            return False
        except Exception:
            try:
                get_resp = await c.get(url, follow_redirects=True, timeout=5.0)
                return get_resp.status_code >= 400
            except Exception:
                return True

    if client is not None:
        return await _probe(client)
    async with httpx.AsyncClient() as new_client:
        return await _probe(new_client)
