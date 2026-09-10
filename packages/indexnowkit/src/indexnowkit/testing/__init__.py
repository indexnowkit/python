"""Test doubles published for adapters and applications (no pytest needed here): :class:`FakeTransport`,
:class:`FrozenClock`, :class:`RecordingDispatcher`, :class:`MemoryCache`. The conformance kits live in
``indexnowkit.testing.conformance`` (pytest), the mock IndexNow server in ``indexnowkit.testing.mock_server``."""

from __future__ import annotations

import json as _json
import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import IO, Any

from indexnowkit.exceptions import TransportError
from indexnowkit.http import Response

__all__ = ["FakeTransport", "FrozenClock", "MemoryCache", "RecordingDispatcher"]


class FakeTransport:
    """Records POSTs (decoded body included), answers queued responses or raises queued exceptions; GETs answer what
    :meth:`on_get` registered, 404 otherwise."""

    def __init__(self, default: Response | None = None) -> None:
        #: every POST: ``{"url", "json", "headers", "body"}`` with ``body`` the decoded JSON
        self.posts: list[dict[str, Any]] = []
        #: every GET URL, in order
        self.gets: list[str] = []
        #: URLs fetched through :meth:`download` (a subset of ``gets``)
        self.downloads: list[str] = []
        #: called with the URL before every GET is answered (a test that advances a clock)
        self.before_get: Callable[[str], None] | None = None
        self._default = default or Response(200)
        self._queue: list[Response | BaseException] = []
        self._get_responses: dict[str, list[Response | BaseException]] = {}

    def will_respond(self, *responses: Response | BaseException) -> FakeTransport:
        """Queue the answers of the next POSTs; the default (200) answers once the queue is empty."""
        self._queue.extend(responses)
        return self

    def on_get(self, url: str, *responses: Response | BaseException) -> FakeTransport:
        """Responses for GET ``url``, consumed in order; the last one is repeated (so a single one is permanent).
        Headers the check reads go on the response: ``Response(200, key, headers={"Content-Type": "text/plain"})``."""
        if responses:
            self._get_responses[url] = list(responses)
        return self

    def post(self, url: str, json: str, headers: Mapping[str, str] | None = None) -> Response:
        self.posts.append({"url": url, "json": json, "headers": dict(headers or {}), "body": _json.loads(json)})
        answer = self._queue.pop(0) if self._queue else self._default
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def get(self, url: str) -> Response:
        self.gets.append(url)
        if self.before_get is not None:
            self.before_get(url)
        queue = self._get_responses.get(url)
        if queue is None:
            return Response(404, b"not found")
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def download(self, url: str, sink: IO[bytes]) -> Response:
        response = self.get(url)
        self.downloads.append(url)
        sink.write(response.body)
        return Response(response.status, b"", response.retry_after, response.headers)

    @staticmethod
    def failing(message: str = "connection refused") -> TransportError:
        return TransportError(message)

    @property
    def last_post(self) -> dict[str, Any]:
        if not self.posts:
            raise AssertionError("expected a POST")
        return self.posts[-1]


class FrozenClock:
    """A clock that only moves when :meth:`advance` is called."""

    def __init__(self, at: datetime | str = "2026-09-03T12:00:00+00:00") -> None:
        moment = datetime.fromisoformat(at) if isinstance(at, str) else at
        self._now = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now = self._now + timedelta(seconds=seconds)


class RecordingDispatcher:
    """A dispatcher that keeps every batch it was handed instead of delivering it."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def dispatch(self, urls: Iterable[str]) -> None:
        self.batches.append(list(urls))

    @property
    def urls(self) -> list[str]:
        return [url for batch in self.batches for url in batch]


class MemoryCache:
    """An in-process cache with the ``get/set/add/delete/incr`` surface of a Django cache (what
    ``CacheDebounceStore`` and the 403 counter need), with a clock for the TTLs; ``failing`` makes every call raise."""

    def __init__(self, clock: FrozenClock | None = None) -> None:
        self._clock = clock
        self._entries: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.Lock()
        self.failing: Exception | None = None
        self.calls: list[str] = []

    def _time(self) -> float:
        return self._clock.now().timestamp() if self._clock is not None else datetime.now(UTC).timestamp()

    def _check(self, name: str) -> None:
        self.calls.append(name)
        if self.failing is not None:
            raise self.failing

    def get(self, key: str, default: Any = None) -> Any:
        self._check("get")
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or (entry[1] is not None and entry[1] <= self._time()):
                self._entries.pop(key, None)
                return default
            return entry[0]

    def set(self, key: str, value: Any, timeout: float | None = None) -> None:
        self._check("set")
        with self._lock:
            self._entries[key] = (value, None if timeout is None else self._time() + timeout)

    def add(self, key: str, value: Any, timeout: float | None = None) -> bool:
        self._check("add")
        if self.get(key) is not None:
            return False
        self.set(key, value, timeout)
        return True

    def delete(self, key: str) -> None:
        self._check("delete")
        with self._lock:
            self._entries.pop(key, None)

    def incr(self, key: str, delta: int = 1) -> int:
        self._check("incr")
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                raise ValueError(f"Key '{key}' not found.")
            value = int(entry[0]) + delta
            self._entries[key] = (value, entry[1])
            return value

    def __len__(self) -> int:
        return len(self._entries)
