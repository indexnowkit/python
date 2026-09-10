"""Rate limiting of the outgoing requests: a per-process token bucket (``throttle.max_requests_per_minute``)."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from indexnowkit._log import log
from indexnowkit.clock import Clock, SystemClock

if TYPE_CHECKING:
    from indexnowkit.config import Config

__all__ = ["NullThrottle", "Throttle", "TokenBucket"]
_logger = logging.getLogger("indexnowkit.throttle")


@runtime_checkable
class Throttle(Protocol):
    """Rate limiter consulted once per outgoing HTTP request."""

    def acquire(self) -> None:
        """Blocks (or returns immediately) until one request may be sent. Implementations SHOULD NOT raise;
        ``Client`` logs an exception as an error and sends without rate limiting."""


class NullThrottle:
    __slots__ = ()

    def acquire(self) -> None:
        return None

    async def aacquire(self) -> None:
        return None


class TokenBucket:
    """Per-process token bucket: at most N requests per minute, blocking (``time.sleep``) when exhausted; 0 means
    unlimited. Cross-process throttling is the queue's job. The wait has no upper bound: in a web request it only
    kicks in when one request sends more than N batches, so keep ``max_requests_per_minute`` well above the number of
    batches a request can produce, or use :class:`NullThrottle` there and throttle in the worker instead."""

    def __init__(
        self,
        per_minute: int,
        clock: Clock | None = None,
        sleeper: Callable[[float], None] | None = None,
        logger: logging.Logger | None = None,
        async_sleeper: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """:param sleeper: receives seconds; injectable for tests
        :param async_sleeper: the same for :meth:`aacquire` (default ``asyncio.sleep``)
        """
        self._per_minute = per_minute
        self._clock = clock or SystemClock()
        self._sleeper = sleeper or time.sleep
        self._async_sleeper = async_sleeper or asyncio.sleep
        self._logger = logger or _logger
        self._tokens = float(per_minute)
        self._last_refill = self._now()

    @classmethod
    def from_config(
        cls, config: Config, logger: logging.Logger | None = None, clock: Clock | None = None
    ) -> TokenBucket:
        """The throttle an adapter wires: ``throttle.max_requests_per_minute``, the clock, a real sleep."""
        return cls(config.throttle_max_requests_per_minute, clock, logger=logger)

    def acquire(self) -> None:
        wait = self._take()
        if wait > 0:
            self._sleeper(wait)
            self._credit(wait)

    async def aacquire(self) -> None:
        wait = self._take()
        if wait > 0:
            await self._async_sleeper(wait)
            self._credit(wait)

    def _take(self) -> float:
        """Take one token; the seconds to wait first when the bucket is empty (the token is taken on credit)."""
        if self._per_minute <= 0:
            return 0.0
        self._refill()
        wait = 0.0
        if self._tokens < 1.0:
            deficit = 1.0 - self._tokens
            wait = math.ceil(deficit * (60_000_000 / self._per_minute)) / 1_000_000
            log(
                self._logger,
                logging.DEBUG,
                "throttle limit of {per_minute} requests/min reached, waiting {wait_ms} ms",
                per_minute=self._per_minute,
                wait_ms=int(wait * 1000),
            )
            self._tokens += deficit
        self._tokens = max(0.0, self._tokens - 1.0)
        return wait

    def _credit(self, wait: float) -> None:
        # The wait was sized for exactly the deficit: move the refill mark by the time slept, so the next refill()
        # does not count that time again (a real clock has moved by it, a frozen one has not).
        self._last_refill += wait

    def _refill(self) -> None:
        now = self._now()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(float(self._per_minute), self._tokens + elapsed * (self._per_minute / 60))
        self._last_refill = now

    def _now(self) -> float:
        return self._clock.now().timestamp()
