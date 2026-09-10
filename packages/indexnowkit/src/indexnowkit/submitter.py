"""One submission: normalize (canonical form: ``normalizer.*``) → dedupe → debounce → Client (group, chunk, throttle,
POST) → mark submitted. Ancillary failures (debounce store down, a listener raising, a submission store raising) are
logged and never abort delivery. Every outcome, including skipped URLs, is a Result handed to listeners and to the
submission store."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from typing import Protocol, runtime_checkable

from indexnowkit._log import log
from indexnowkit.client import ClientProtocol
from indexnowkit.clock import Clock, SystemClock
from indexnowkit.config import Config
from indexnowkit.debounce import DebounceStore, MemoryDebounceStore
from indexnowkit.exceptions import InvalidUrlError
from indexnowkit.result import Reason, Result, retryable_urls, urls_where
from indexnowkit.submission import SubmissionStore
from indexnowkit.url import UrlNormalizerProtocol, normalizer_from_config

__all__ = ["Submitter", "SubmitterProtocol"]
_logger = logging.getLogger("indexnowkit.submitter")


@runtime_checkable
class SubmitterProtocol(Protocol):
    """Entry point for sending URLs. Never raises for remote failures; see ``Result.status``. "May grow" protocol
    (docs/bc.md); decorating the shipped implementation is safe."""

    def submit(self, urls: Iterable[str]) -> list[Result]:
        """Normalize, de-duplicate, debounce and send. Invalid URLs are dropped with a warning; one Result per
        endpoint × host × batch, empty when nothing was sent."""

    def prepare(self, urls: Iterable[str]) -> list[str]:
        """Normalize and de-duplicate without sending (what a collector stores)."""

    def add_listener(self, listener: Callable[[Result], None]) -> None:
        """Called with every Result (also skipped ones) right after it is produced; exceptions are logged and
        swallowed. A decorator MUST forward it to the decorated submitter."""


class Submitter:
    def __init__(
        self,
        client: ClientProtocol,
        config: Config,
        debounce: DebounceStore | None = None,
        logger: logging.Logger | None = None,
        normalizer: UrlNormalizerProtocol | None = None,
        store: SubmissionStore | None = None,
        clock: Clock | None = None,
    ) -> None:
        """:param store: remembers every Result; None = nothing is kept
        :param clock: the time a record gets; default the system clock
        """
        self._client = client
        self._config = config
        self._debounce: DebounceStore = debounce if debounce is not None else MemoryDebounceStore(clock)
        self._logger = logger or _logger
        self._normalizer = normalizer or normalizer_from_config(config)
        self._store = store
        self._clock = clock or SystemClock()
        self._listeners: list[Callable[[Result], None]] = []

    def add_listener(self, listener: Callable[[Result], None]) -> None:
        self._listeners.append(listener)

    def submit(self, urls: Iterable[str]) -> list[Result]:
        normalized, results = self._normalize(urls)
        if normalized and not self._config.enabled:
            log(
                self._logger,
                self._config.logging_level("disabled"),
                "disabled (enabled: false), dropping {count} URL(s)",
                count=len(normalized),
                urls=self._config.log_sample(normalized),
            )
            results.extend(self._skipped(normalized, Reason.DISABLED))
            normalized = []
        ttl = self._config.debounce_per_url
        if normalized and ttl > 0 and not self._config.dry_run:
            fresh = self._without_recent(normalized, ttl)
            results.extend(self._skipped([u for u in normalized if u not in fresh], Reason.DEBOUNCED))
            normalized = fresh
        if normalized:
            results.extend(self._client.submit_all(normalized))
        for result in results:
            self._notify(result)
        self._remember(results)
        if ttl > 0:
            self._mark(results, ttl)
        return results

    async def asubmit(self, urls: Iterable[str]) -> list[Result]:
        """The same pipeline off the event loop: ``await asyncio.to_thread(submit, urls)``."""
        return await asyncio.to_thread(self.submit, list(urls))

    def prepare(self, urls: Iterable[str]) -> list[str]:
        return self._normalize(urls)[0]

    def _normalize(self, urls: Iterable[str]) -> tuple[list[str], list[Result]]:
        seen: dict[str, None] = {}
        invalid: list[Result] = []
        for url in urls:
            try:
                seen.setdefault(self._normalizer.normalize(url))
            except InvalidUrlError as error:
                log(self._logger, self._config.logging_level("invalid_url"), "dropping URL: {error}", error=str(error))
                invalid.append(Result.skipped("", [url], Reason.INVALID_URL, str(error)))
        return list(seen), invalid

    def _without_recent(self, urls: list[str], ttl: int) -> list[str]:
        """Debounce filter; fails open (submits everything) when the store is unavailable."""
        try:
            recent = set(self._debounce.filter_recent(urls, ttl))
        except Exception as error:
            log(
                self._logger,
                logging.WARNING,
                "debounce store unavailable, submitting without de-duplication: {error}",
                error=str(error),
                exc=error,
            )
            return urls
        if not recent:
            return urls
        log(
            self._logger,
            self._config.logging_level("debounced"),
            "debounced {count} URL(s) submitted within the last {ttl}s",
            count=len(recent),
            ttl=ttl,
            urls=self._config.log_sample(recent),
        )
        return [url for url in urls if url not in recent]

    def _mark(self, results: list[Result], ttl: int) -> None:
        # A URL accepted by one engine but retryable (429, 5xx, transport) at another is not marked: the retry of the
        # failed engine must pass the window. A permanent refusal (403, 422) at one engine does not unmark it.
        retryable = set(retryable_urls(results))
        sent = [url for url in urls_where(results, lambda r: r.is_success) if url not in retryable]
        if not sent:
            return
        try:
            self._debounce.mark_submitted(sent, ttl)
        except Exception as error:
            log(
                self._logger,
                logging.WARNING,
                "debounce store failed after a successful submission, URLs may be re-sent within {ttl}s: {error}",
                ttl=ttl,
                error=str(error),
                exc=error,
            )

    def _skipped(self, urls: Iterable[str], reason: Reason) -> list[Result]:
        """One skipped result per host, so callers can tell "nothing sent" reasons apart."""
        by_host: dict[str, list[str]] = {}
        for url in urls:
            by_host.setdefault(self._normalizer.host_of(url), []).append(url)
        return [Result.skipped(host, host_urls, reason) for host, host_urls in by_host.items()]

    def _remember(self, results: list[Result]) -> None:
        if self._store is None or not results:
            return
        try:
            at = self._clock.now()
            for result in results:
                self._store.record(result, at)
        except Exception as error:
            log(
                self._logger,
                logging.ERROR,
                "submission store failed, {count} result(s) not recorded: {error}",
                count=len(results),
                error=str(error),
                exc=error,
            )

    def _notify(self, result: Result) -> None:
        for listener in self._listeners:
            try:
                listener(result)
            except Exception as error:
                log(
                    self._logger,
                    logging.ERROR,
                    "result listener {listener} failed: {error}",
                    listener=getattr(listener, "__qualname__", repr(listener)),
                    error=str(error),
                    exc=error,
                )
