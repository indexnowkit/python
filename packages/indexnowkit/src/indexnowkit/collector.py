"""The per-unit-of-work buffer of normalized URLs (spec 02): a ``contextvars`` scope per request or task, de-duplicated,
drained once by ``IndexNowKit.flush()``. A ``reset()`` of a non-empty buffer is logged: the unit of work ended without
a flush, the URLs are gone."""

from __future__ import annotations

import atexit
import contextvars
import logging
import weakref
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from indexnowkit._log import log

if TYPE_CHECKING:
    from indexnowkit.config import Config

__all__ = ["Collector", "CollectorProtocol"]
_logger = logging.getLogger("indexnowkit.collector")


@runtime_checkable
class CollectorProtocol(Protocol):
    """ "May grow" protocol (docs/bc.md); decorate :class:`Collector` for a durable outbox or a per-tenant buffer."""

    def add(self, urls: Iterable[str]) -> None:
        """Already normalized URLs (see ``SubmitterProtocol.prepare()``)."""

    def is_empty(self) -> bool: ...

    def __len__(self) -> int: ...

    def all(self) -> list[str]:
        """Buffered URLs without draining (profilers, diagnostics)."""

    def drain(self) -> list[str]:
        """The buffered URLs (de-duplicated, insertion order); the buffer is empty afterwards."""

    def reset(self) -> None:
        """Empties the buffer without delivering (between requests in long-running runtimes)."""


class Collector:
    """A buffer per scope: inside :meth:`collecting` (a request, a task) the URLs live in the scope's context variable;
    outside any scope in the collector itself (a management command, a worker). Every scope is its own buffer, so two
    requests served by one process never see each other's URLs."""

    def __init__(self, logger: logging.Logger | None = None, detect_leaks: bool = True, log_urls: int = 20) -> None:
        """:param detect_leaks: warn at interpreter exit when URLs were collected but never drained
        :param log_urls: URLs listed in a leak/discard log line (``logging.max_urls``)
        """
        self._logger = logger or _logger
        self._log_urls = log_urls
        self._scope: contextvars.ContextVar[dict[str, None] | None] = contextvars.ContextVar(
            "indexnowkit.collector", default=None
        )
        self._global: dict[str, None] = {}
        self._drained = False
        if detect_leaks:
            weak = weakref.ref(self)
            atexit.register(lambda: (lambda c: c.report_leak() if c is not None else None)(weak()))

    @classmethod
    def from_config(cls, config: Config, logger: logging.Logger | None = None) -> Collector:
        return cls(logger, config.collector_detect_leaks, config.logging_max_urls)

    @contextmanager
    def collecting(self) -> Iterator[Collector]:
        """Open a scope: a fresh buffer for the current context, reset when the block ends (the caller flushes)."""
        token = self._scope.set({})
        try:
            yield self
        finally:
            leftover = self._scope.get()
            self._scope.reset(token)
            if leftover:
                self._discarded(leftover)

    def _buffer(self) -> dict[str, None]:
        scope = self._scope.get()
        return scope if scope is not None else self._global

    def add(self, urls: Iterable[str]) -> None:
        buffer = self._buffer()
        for url in urls:
            buffer.setdefault(url)

    def is_empty(self) -> bool:
        return not self._buffer()

    def __len__(self) -> int:
        return len(self._buffer())

    def all(self) -> list[str]:
        return list(self._buffer())

    def drain(self) -> list[str]:
        buffer = self._buffer()
        urls = list(buffer)
        buffer.clear()
        self._drained = True
        return urls

    def reset(self) -> None:
        buffer = self._buffer()
        if buffer:
            self._discarded(buffer)
        buffer.clear()

    def _discarded(self, buffer: dict[str, None]) -> None:
        log(
            self._logger,
            logging.WARNING,
            "{count} collected URL(s) discarded: the unit of work ended without flush() (request end hook not run?)",
            count=len(buffer),
            urls=list(buffer)[: self._log_urls],
        )

    def report_leak(self) -> None:
        """The exit hook: URLs collected outside any scope and never drained."""
        if self._global and not self._drained:
            log(
                self._logger,
                logging.WARNING,
                "{count} collected URL(s) never flushed before the process ended (fatal error or early exit before the request-end hook?)",  # noqa: E501 — a text of the family, one to one with PHP
                count=len(self._global),
                urls=list(self._global)[: self._log_urls],
            )
