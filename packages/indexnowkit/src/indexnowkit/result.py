"""The outcome of one submission attempt (:class:`Result`), its status and its machine-readable reason."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["NO_ENGINE", "Reason", "Result", "ResultStatus"]

#: Engine label of results that never reached an engine (skipped).
NO_ENGINE = "none"


class ResultStatus(StrEnum):
    #: HTTP 200: accepted.
    OK = "ok"
    #: HTTP 202: accepted, key verification pending. Treated as success.
    PENDING = "pending"
    #: Rejected (4xx/5xx) or not delivered (network). See ``Result.retryable``.
    FAILED = "failed"
    #: Nothing was sent: dry_run, or the host has no key. See ``Result.error``.
    SKIPPED = "skipped"

    @property
    def is_success(self) -> bool:
        return self in (ResultStatus.OK, ResultStatus.PENDING)


class Reason(StrEnum):
    """Machine-readable reason of a Result that is not a success. Stable identifiers for metrics, dashboards and
    alerts; ``Result.error`` carries the human sentence."""

    # Skipped: nothing was sent.
    #: Config ``enabled: false``.
    DISABLED = "disabled"
    #: Config ``dry_run: true`` (or the non-production safety net).
    DRY_RUN = "dry_run"
    #: The same URL was submitted less than ``debounce.per_url`` seconds ago.
    DEBOUNCED = "debounced"
    #: No key configured for the URL's host (``hosts`` map / ``key``).
    NO_KEY = "no_key"
    #: The URL failed normalization (unsupported scheme, credentials, relative without base_url, ...).
    INVALID_URL = "invalid_url"

    # Skipped by the pre-flight check of the page (the ``verify`` module).
    #: The page says ``noindex`` (``<meta name="robots">`` or ``X-Robots-Tag``): the engine would not index it.
    NOINDEX = "noindex"
    #: robots.txt disallows the URL for the engines' bots.
    ROBOTS_DISALLOWED = "robots_disallowed"
    #: The page's ``<link rel="canonical">`` points elsewhere; submit the canonical URL instead.
    NON_CANONICAL = "non_canonical"
    #: The URL answers 3xx and the policy is to skip redirects (submit the target instead).
    REDIRECTED = "redirected"
    #: The origin answered 5xx or failed while fetching the page: nothing to tell the engine yet. Retryable.
    ORIGIN_ERROR = "origin_error"

    # Failed: the engine answered or the request could not be delivered.
    #: HTTP 400.
    INVALID_REQUEST = "invalid_request"
    #: HTTP 403: key file not found or does not match.
    INVALID_KEY = "invalid_key"
    #: HTTP 422: URLs do not belong to the host or keyLocation is invalid.
    UNPROCESSABLE = "unprocessable"
    #: HTTP 429. Retryable.
    RATE_LIMITED = "rate_limited"
    #: HTTP 5xx. Retryable.
    SERVER_ERROR = "server_error"
    #: Network failure or timeout. Retryable.
    TRANSPORT = "transport"
    #: Anything else: unexpected status, JSON encoding failure, a raising HTTP client.
    UNEXPECTED = "unexpected"

    @property
    def is_skip(self) -> bool:
        return self in _SKIPS

    @property
    def is_retryable(self) -> bool:
        """Whether a later attempt may succeed without a change on your side (what ``Result.retryable`` says)."""
        return self in _RETRYABLE

    @property
    def translation_key(self) -> str:
        """Translation key for UIs (``indexnowkit.reason.<value>``); :attr:`message` is the English text for logs."""
        return f"indexnowkit.reason.{self.value}"

    @property
    def message(self) -> str:
        """Short human sentence for logs and CLI output."""
        return _MESSAGES[self]


_SKIPS = frozenset(
    {
        Reason.DISABLED,
        Reason.DRY_RUN,
        Reason.DEBOUNCED,
        Reason.NO_KEY,
        Reason.INVALID_URL,
        Reason.NOINDEX,
        Reason.ROBOTS_DISALLOWED,
        Reason.NON_CANONICAL,
        Reason.REDIRECTED,
        Reason.ORIGIN_ERROR,
    }
)
_RETRYABLE = frozenset({Reason.RATE_LIMITED, Reason.SERVER_ERROR, Reason.TRANSPORT, Reason.ORIGIN_ERROR})
_MESSAGES = {
    Reason.DISABLED: "IndexNow is disabled (enabled: false).",
    Reason.DRY_RUN: "dry_run is on: request logged, not sent.",
    Reason.DEBOUNCED: "Submitted recently (debounce.per_url).",
    Reason.NO_KEY: "No IndexNow key configured for this host.",
    Reason.INVALID_URL: "URL cannot be submitted.",
    Reason.NOINDEX: "Page is noindex: not submitted.",
    Reason.ROBOTS_DISALLOWED: "robots.txt disallows the page: not submitted.",
    Reason.NON_CANONICAL: "Page has another canonical URL: not submitted.",
    Reason.REDIRECTED: "Page redirects: not submitted.",
    Reason.ORIGIN_ERROR: "Origin error while fetching the page: not submitted yet.",
    Reason.INVALID_REQUEST: "Invalid request format (400).",
    Reason.INVALID_KEY: "Invalid key (403): key file not found or does not match.",
    Reason.UNPROCESSABLE: "Unprocessable URLs (422).",
    Reason.RATE_LIMITED: "Rate limited (429).",
    Reason.SERVER_ERROR: "Engine server error (5xx).",
    Reason.TRANSPORT: "Network failure or timeout.",
    Reason.UNEXPECTED: "Unexpected failure.",
}


@dataclass(frozen=True, slots=True)
class Result:
    """Outcome of one submission attempt: one endpoint, one host, up to ``batch.max_urls`` URLs.

    Successful results (200 / 202) have ``reason is None``. Skipped results (dry-run, disabled, debounced, unmanaged
    host, invalid URL) carry no HTTP code and ``engine == NO_ENGINE``; failed ones carry the HTTP code when the engine
    answered. ``reason`` is the stable identifier, ``error`` the human sentence.
    """

    #: engine label ("api", "yandex", a custom host) or :data:`NO_ENGINE`
    engine: str
    host: str
    #: URLs of this batch
    urls: tuple[str, ...]
    status: ResultStatus
    http_code: int | None = None
    error: str | None = None
    retryable: bool = False
    #: seconds suggested by the engine (429/5xx), when given
    retry_after: int | None = None
    endpoint: str = ""
    reason: Reason | None = None

    @classmethod
    def ok(cls, engine: str, host: str, urls: Iterable[str], http_code: int, endpoint: str) -> Result:
        status = ResultStatus.PENDING if http_code == 202 else ResultStatus.OK
        return cls(engine, host, tuple(urls), status, http_code, endpoint=endpoint)

    @classmethod
    def skipped(
        cls,
        host: str,
        urls: Iterable[str],
        reason: Reason,
        error: str | None = None,
        engine: str = NO_ENGINE,
        endpoint: str = "",
    ) -> Result:
        """Nothing was sent. ``error`` defaults to the reason's standard sentence."""
        return cls(
            engine,
            host,
            tuple(urls),
            ResultStatus.SKIPPED,
            None,
            error or reason.message,
            False,
            None,
            endpoint,
            reason,
        )

    @classmethod
    def failed(
        cls,
        engine: str,
        host: str,
        urls: Iterable[str],
        reason: Reason,
        error: str | None = None,
        http_code: int | None = None,
        retryable: bool = False,
        retry_after: int | None = None,
        endpoint: str = "",
    ) -> Result:
        """Rejected by the engine or not delivered."""
        return cls(
            engine,
            host,
            tuple(urls),
            ResultStatus.FAILED,
            http_code,
            error or reason.message,
            retryable,
            retry_after,
            endpoint,
            reason,
        )

    @property
    def url_count(self) -> int:
        return len(self.urls)

    @property
    def is_success(self) -> bool:
        return self.status.is_success

    def metric_labels(self) -> dict[str, str]:
        """Low-cardinality string labels for counters (Prometheus, StatsD): status, engine, reason, http_code,
        retryable. The host is deliberately absent (unbounded in multi-tenant setups); add ``result.host`` yourself."""
        return {
            "status": self.status.value,
            "engine": self.engine,
            "reason": self.reason.value if self.reason is not None else "",
            "http_code": str(self.http_code) if self.http_code is not None else "",
            "retryable": "true" if self.retryable else "false",
        }


def retryable_urls(results: Iterable[Result]) -> list[str]:
    """URLs of the results that may be retried later (429, 5xx, network), de-duplicated."""
    return urls_where(results, lambda result: result.retryable)


def all_urls(results: Iterable[Result]) -> list[str]:
    """Every URL of every result, de-duplicated."""
    return urls_where(results, lambda result: True)


def urls_where(results: Iterable[Result], predicate: Callable[[Result], bool]) -> list[str]:
    """URLs of the results matching a predicate, de-duplicated, in order of first appearance."""
    urls: dict[str, None] = {}
    for result in results:
        if predicate(result):
            for url in result.urls:
                urls.setdefault(url)
    return list(urls)


__all__ += ["all_urls", "retryable_urls", "urls_where"]
