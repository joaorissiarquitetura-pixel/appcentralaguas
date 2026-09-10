from __future__ import annotations

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """Return a UTC timestamp stored as naive datetime for legacy DB compatibility."""
    return datetime.now(UTC).replace(tzinfo=None)
