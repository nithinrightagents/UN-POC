"""Per-session configuration snapshotting (FR-063, FR-075).

Retries read the snapshot taken when their session started, never live
configuration — so a retry stays comparable to the run that triggered it.
A mid-session .env change takes effect only for subsequent sessions.
"""

from __future__ import annotations

from shared.state.entities import ConfigurationSnapshot, new_id, utcnow

from .settings import Settings


def take_snapshot(session_id: str, settings: Settings) -> ConfigurationSnapshot:
    return ConfigurationSnapshot(
        snapshot_id=new_id("snap"),
        session_id=session_id,
        values=settings.as_dict(),
        captured_at=utcnow(),
    )


def settings_from_snapshot(snapshot: ConfigurationSnapshot) -> Settings:
    """Reconstruct a Settings object from a stored snapshot so retries and
    audits operate on frozen values rather than the live environment."""
    s = Settings()
    for key, value in snapshot.values.items():
        if hasattr(s, key):
            setattr(s, key, value)
    return s
