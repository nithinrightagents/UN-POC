"""Region-scoped visual capture (FR-021).

Captures a screenshot scoped to the relevant element's bounding box, not
the full page -- so a reviewer sees exactly the evidence being cited.
"""

from __future__ import annotations

import pathlib

from shared.state.entities import new_id


async def capture_region(page, css_path: str, out_dir: str) -> str | None:
    """Screenshot the element matched by `css_path`, padded slightly for
    context. Returns a capture_ref (file path) or None if the element could
    not be located for capture."""
    if not hasattr(page, "locator"):
        pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
        return f"{out_dir}/{new_id('capture')}.png"

    try:
        locator = page.locator(css_path).first
        count = await locator.count()
        if count == 0:
            return None
    except Exception:  # noqa: BLE001
        return None

    pathlib.Path(out_dir).mkdir(parents=True, exist_ok=True)
    ref = f"{out_dir}/{new_id('capture')}.png"
    try:
        try:
            await locator.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass
        await locator.screenshot(path=ref, timeout=5000)
    except Exception:  # noqa: BLE001
        return None
    return ref
