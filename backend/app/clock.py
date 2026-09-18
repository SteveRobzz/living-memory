"""Demo clock.

Every "now" in the engine comes from here. In demo mode an offset can be
applied so a January -> March -> May timeline can be shown in 5 minutes.
The UI always displays the simulated date, so nothing is hidden from judges.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

_offset: timedelta = timedelta(0)


def now() -> datetime:
    return datetime.now(timezone.utc) + _offset


def set_simulated(target: Optional[datetime]) -> datetime:
    """Pin the engine's clock to `target` (or clear it with None)."""
    global _offset
    if target is None:
        _offset = timedelta(0)
    else:
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        _offset = target - datetime.now(timezone.utc)
    return now()


def offset_seconds() -> float:
    return _offset.total_seconds()


def is_simulated() -> bool:
    return abs(_offset.total_seconds()) > 60
