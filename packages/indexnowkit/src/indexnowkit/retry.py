"""Retries and the 403 counter: :class:`RetryPolicy` (the backoff of spec 01), :class:`RetryingSubmitter` (in-process
retries for CLI runs), :class:`WorkerOutcome` (what a queue worker decides), :class:`ForbiddenCounter` (consecutive
403s per host, escalated once per streak)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from indexnowkit._log import log
from indexnowkit.cache import increment
from indexnowkit.result import Result, ResultStatus, retryable_urls, urls_where

if TYPE_CHECKING:
    from indexnowkit.submitter import SubmitterProtocol

__all__ = ["ForbiddenCounter", "RetryPolicy", "RetryingSubmitter", "WorkerOutcome"]
_logger = logging.getLogger("indexnowkit.retry")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Backoff for retryable results: honours Retry-After, otherwise exponential (base × multiplier^(attempt-1)),
    capped. The base is 60 s after a 429 (the engine asked to slow down) and 5 s after 5xx / network failures.
    Shared by queue handlers and :class:`RetryingSubmitter` so every adapter retries the same way."""

    #: total attempts including the first one
    max_attempts: int = 3
    #: seconds before the second attempt after a 429 without Retry-After
    base_delay: int = 60
    multiplier: float = 2.0
    max_delay: int = 3600
    #: seconds before the second attempt after 5xx / network failures
    server_error_delay: int = 5

    def delay_after(self, results: Iterable[Result], attempt: int) -> int | None:
        """Seconds to wait before the next attempt, or None when no retry should happen.

        :param attempt: 1-based number of the attempt just made
        """
        if attempt >= self.max_attempts:
            return None
        retry_after: int | None = None
        retryable = rate_limited = False
        for result in results:
            if not result.retryable:
                continue
            retryable = True
            rate_limited = rate_limited or result.http_code == 429
            if result.retry_after is not None:
                retry_after = max(retry_after or 0, result.retry_after)
        if not retryable:
            return None
        base = self.base_delay if rate_limited else self.server_error_delay
        delay = retry_after if retry_after is not None else round(base * self.multiplier ** (attempt - 1))
        return max(0, min(delay, self.max_delay))


class RetryingSubmitter:
    """Decorator that re-submits retryable URLs in-process, sleeping between attempts: the path for synchronous
    delivery and CLI runs (``submit``, cron). Not for web requests (the delay blocks the response) and not for queue
    workers: a queued job hands the retryable URLs back to its queue with a delay through :class:`WorkerOutcome`."""

    def __init__(
        self,
        inner: SubmitterProtocol,
        policy: RetryPolicy | None = None,
        logger: logging.Logger | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self._logger = logger or _logger
        self._sleeper = sleeper or time.sleep

    def submit(self, urls: Iterable[str]) -> list[Result]:
        """Results of the last attempt for each URL: retried URLs replace their earlier failed result."""
        attempt = 1
        results = self._inner.submit(urls)
        while (delay := self._policy.delay_after(results, attempt)) is not None:
            retry = retryable_urls(results)
            log(
                self._logger,
                logging.INFO,
                "retrying {count} URL(s) in {delay}s (attempt {attempt} of {max})",
                count=len(retry),
                delay=delay,
                attempt=attempt + 1,
                max=self._policy.max_attempts,
            )
            if delay > 0:
                self._sleeper(delay)
            attempt += 1
            results = [r for r in results if not r.retryable] + self._inner.submit(retry)
        return results

    def prepare(self, urls: Iterable[str]) -> list[str]:
        return self._inner.prepare(urls)

    def add_listener(self, listener: Callable[[Result], None]) -> None:
        self._inner.add_listener(listener)


@dataclass(frozen=True, slots=True)
class WorkerOutcome:
    """What a queue worker decides after one submission: which URLs to retry, which were rejected for good, and the
    log lines for both. The worker keeps only its framework's action (re-enqueue with :meth:`delay`)."""

    #: URLs of retryable failures (429, 5xx, network)
    retry_urls: tuple[str, ...]
    #: URLs of final failures (400, 403, 422): a retry would not help
    final_urls: tuple[str, ...]
    #: unique, ``<engine> <http code or reason>``: "api 403", "yandex unprocessable"
    final_reasons: tuple[str, ...]
    #: the largest Retry-After among the retryable results, in seconds
    retry_after: int | None
    results: tuple[Result, ...]

    @classmethod
    def of(cls, results: Iterable[Result]) -> WorkerOutcome:
        items = tuple(results)
        retry_after: int | None = None
        reasons: dict[str, None] = {}
        for result in items:
            if result.retryable:
                if result.retry_after is not None:
                    retry_after = max(retry_after or 0, result.retry_after)
                continue
            if result.status is not ResultStatus.FAILED:
                continue
            code = str(result.http_code) if result.http_code is not None else (result.reason or "failed")
            reasons.setdefault(f"{result.engine} {code}")
        final = urls_where(items, lambda r: r.status is ResultStatus.FAILED and not r.retryable)
        return cls(tuple(retryable_urls(items)), tuple(final), tuple(reasons), retry_after, items)

    @property
    def has_retryable(self) -> bool:
        return bool(self.retry_urls)

    @property
    def has_final_failures(self) -> bool:
        return bool(self.final_urls)

    def delay(self, policy: RetryPolicy, attempt: int) -> int | None:
        """Seconds before the next attempt per the policy (Retry-After wins), None when the attempts are used up."""
        return policy.delay_after(self.results, attempt)

    def retry_log(
        self, job_id: str, delay: int | None = None, attempt: int | None = None
    ) -> tuple[str, dict[str, Any]]:
        """``{count} URL(s) of job {id} will be retried{delay}{attempt}`` at info: the message and its fields."""
        return "{count} URL(s) of job {id} will be retried{delay}{attempt}", {
            "count": len(self.retry_urls),
            "id": job_id,
            "delay": "" if delay is None else f" in {delay}s",
            "attempt": "" if attempt is None else f" (attempt {attempt})",
        }

    def gave_up_log(self, job_id: str, attempt: int) -> tuple[str, dict[str, Any]]:
        """``giving up on {count} URL(s) of job {id} after {attempt} attempt(s)`` at error."""
        return "giving up on {count} URL(s) of job {id} after {attempt} attempt(s)", {
            "count": len(self.retry_urls),
            "id": job_id,
            "attempt": attempt,
        }

    def final_log(self, job_id: str, check_command: str) -> tuple[str, dict[str, Any]]:
        """``{count} URL(s) of job {id} rejected permanently ({reasons}); run "{check}"`` at error."""
        return '{count} URL(s) of job {id} rejected permanently ({reasons}); run "{check}"', {
            "count": len(self.final_urls),
            "id": job_id,
            "reasons": ", ".join(self.final_reasons),
            "check": check_command,
        }


class ForbiddenCounter:
    """Consecutive 403s per host, and the one crossing of the escalation threshold per streak. ``Client`` counts here
    on every 403 and resets on every other answer; ``status`` reads the counters back.

    With a cache (:class:`~indexnowkit.cache.CacheProtocol`) the counter and the escalation flag live under
    ``<prefix>403.<host>`` and ``…_escalated`` with a TTL, shared by every process of the application, so a fleet of
    workers escalates once. Without a cache, or while it fails (logged once, the process counts on), the counter
    lives in the process."""

    #: Default TTL: a 403 streak older than an hour without a new 403 is forgotten.
    TTL = 3600

    def __init__(
        self,
        cache: Any | None,
        key_prefix: str,
        threshold: int,
        ttl: int = TTL,
        logger: logging.Logger | None = None,
    ) -> None:
        self._cache = cache
        self._prefix = key_prefix
        self._threshold = threshold
        self._ttl = ttl
        self._logger = logger or _logger
        self._counts: dict[str, int] = {}
        self._escalated: set[str] = set()
        self._cleared: set[str] = set()
        self._warned = False

    @property
    def threshold(self) -> int:
        return self._threshold

    def key(self, host: str, escalated: bool = False) -> str:
        """``<prefix>403.<host>`` and ``…_escalated``; an IPv6 literal loses its reserved characters."""
        safe = host.replace("[", "").replace("]", "").replace(":", "_")
        return f"{self._prefix}403.{safe}" + ("_escalated" if escalated else "")

    def hit(self, host: str) -> tuple[int, bool]:
        """One more consecutive 403 for ``host``: the new count, and whether this one crosses the threshold (once
        per streak)."""
        self._cleared.discard(host)
        if self._cache is not None:
            try:
                count = increment(self._cache, self.key(host), self._ttl)
                escalate = count >= self._threshold and not bool(self._cache.get(self.key(host, True), False))
                if escalate:
                    self._cache.set(self.key(host, True), True, self._ttl)
                return count, escalate
            except Exception as error:
                self._warn(error)
        count = self._counts[host] = self._counts.get(host, 0) + 1
        escalate = count >= self._threshold and host not in self._escalated
        if escalate:
            self._escalated.add(host)
        return count, escalate

    def reset(self, host: str) -> None:
        """A non-403 answer ends the streak: the shared counter is deleted only when it is set (no write per
        success)."""
        self._counts.pop(host, None)
        self._escalated.discard(host)
        if self._cache is None or host in self._cleared:
            return
        try:
            if self._stored(host) > 0:
                self._cache.delete(self.key(host))
                self._cache.delete(self.key(host, True))
            self._cleared.add(host)
        except Exception as error:
            self._warn(error)

    def count(self, host: str) -> int:
        """The current streak of ``host``: from the shared cache when there is one (0 when it fails), else the
        process count."""
        if self._cache is not None:
            try:
                return self._stored(host)
            except Exception as error:
                self._warn(error)
                return 0
        return self._counts.get(host, 0)

    def is_escalated(self, host: str) -> bool:
        """Whether the current streak of ``host`` already crossed the threshold (the critical line was written)."""
        if self._cache is not None:
            try:
                return bool(self._cache.get(self.key(host, True), False))
            except Exception as error:
                self._warn(error)
                return False
        return self._counts.get(host, 0) >= self._threshold

    def _stored(self, host: str) -> int:
        stored = self._cache.get(self.key(host), 0) if self._cache is not None else 0
        return int(stored) if isinstance(stored, (int, str)) and str(stored).isdigit() else 0

    def _warn(self, error: Exception) -> None:
        if self._warned:
            return
        self._warned = True
        log(
            self._logger,
            logging.WARNING,
            "failure cache unavailable, counting 403s per process: {error}",
            error=str(error),
            exc=error,
        )
