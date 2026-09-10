"""The clock the debounce, the throttle and the submission records read (a protocol, so tests freeze it)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

__all__ = ["Clock", "SystemClock"]


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware (UTC)."""


class SystemClock:
    """The system time."""

    __slots__ = ()

    def now(self) -> datetime:
        return datetime.now(UTC)
