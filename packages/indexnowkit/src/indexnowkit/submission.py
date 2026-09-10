"""Where submissions are remembered: one record per :class:`Result` (skipped results included), written by
``Submitter`` after every ``submit()``. The core ships :class:`NullSubmissionStore`; the ``history`` module brings the
sqlite store and the ``history``/``status`` commands."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from indexnowkit.result import Result, ResultStatus

__all__ = ["NullSubmissionStore", "ResultSummary", "SubmissionRecord", "SubmissionStore"]


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """One remembered submission: the URLs of the batch, the Result the engine (or the pipeline) gave, and when."""

    urls: tuple[str, ...]
    result: Result
    at: datetime

    @classmethod
    def of(cls, result: Result, at: datetime) -> SubmissionRecord:
        return cls(result.urls, result, at)


@runtime_checkable
class SubmissionStore(Protocol):
    """Implement tier (docs/bc.md): the core calls you, methods are not added in a minor. A store must never raise
    out of :meth:`record`: ``Submitter`` logs and goes on."""

    def record(self, result: Result, at: datetime) -> None:
        """One record for one Result, with the time the Submitter's clock gave."""

    def recent(
        self, limit: int = 100, host: str | None = None, status: ResultStatus | None = None
    ) -> Iterable[SubmissionRecord]:
        """The newest records first, optionally of one host and/or one status."""

    def last_for(self, url: str) -> SubmissionRecord | None:
        """The latest record whose URLs contain ``url``, whatever its status; None when it was never submitted."""


class NullSubmissionStore:
    """Remembers nothing: the default until a store is wired."""

    __slots__ = ()

    def record(self, result: Result, at: datetime) -> None:
        return None

    def recent(
        self, limit: int = 100, host: str | None = None, status: ResultStatus | None = None
    ) -> list[SubmissionRecord]:
        return []

    def last_for(self, url: str) -> SubmissionRecord | None:
        return None


class ResultSummary:
    """Aggregated results of a run that submits in batches: results are folded into (engine, host, status, http,
    reason) rows with URL counts as they arrive, so a million-URL run keeps a handful of rows in memory."""

    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}
        self._failed = False
        self._urls = 0

    def add(self, results: Iterable[Result]) -> None:
        for r in results:
            self._failed = self._failed or r.status is ResultStatus.FAILED
            self._urls += r.url_count
            key = "|".join(
                [r.engine, r.host, r.status.value, str(r.http_code or ""), r.reason.value if r.reason else ""]
            )
            row = self._rows.setdefault(
                key,
                {
                    "engine": r.engine,
                    "host": r.host,
                    "status": r.status.value,
                    "http": r.http_code,
                    "reason": r.reason.value if r.reason else None,
                    "retryable": r.retryable,
                    "error": r.error,
                    "url_count": 0,
                    "batches": 0,
                },
            )
            row["url_count"] += r.url_count
            row["batches"] += 1
            row["retryable"] = row["retryable"] or r.retryable
            row["error"] = row["error"] if row["error"] is not None else r.error

    @property
    def url_count(self) -> int:
        return self._urls

    @property
    def is_empty(self) -> bool:
        return not self._rows

    @property
    def failed(self) -> bool:
        return self._failed

    def rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._rows.values()]
