"""The transport protocols and the shipped ``urllib`` transport: no redirects, a timeout, the body limits of the PHP
family (2 KiB of a POST response for diagnostics, 50 MiB of a GET document), and streaming downloads into a sink."""

from __future__ import annotations

import io
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from email.message import Message
from typing import IO, Any, Protocol, runtime_checkable
from urllib.parse import urlsplit

from indexnowkit.exceptions import TransportError
from indexnowkit.http._response import MAX_RETRY_AFTER, Response

__all__ = [
    "GET_BODY_LIMIT",
    "POST_BODY_LIMIT",
    "AsyncTransport",
    "StreamingTransport",
    "Transport",
    "UrllibTransport",
]

#: Default of ``post_body_limit``: a submission response is diagnostics only.
POST_BODY_LIMIT = 2048
#: Default of ``get_body_limit``: a generous cap for the largest documents consumers of a transport read.
GET_BODY_LIMIT = 52_428_800
_READ_CHUNK = 65_536


@runtime_checkable
class Transport(Protocol):
    """The only HTTP surface the core needs. Implementations must never raise on HTTP status codes."""

    def post(self, url: str, json: str, headers: Mapping[str, str] | None = None) -> Response:
        """POST a JSON document (an IndexNow submission). The response body may be truncated by the implementation;
        only its beginning is used for diagnostics.

        :raises TransportError: on network failure or timeout
        """

    def get(self, url: str) -> Response:
        """GET a document in full (a key file, any document a consumer reads). Implementations should cap the body.

        :raises TransportError: on network failure, timeout or when the body exceeds the cap
        """


@runtime_checkable
class StreamingTransport(Transport, Protocol):
    """Optional extension of :class:`Transport`: GET a document without holding its body in memory."""

    def download(self, url: str, sink: IO[bytes]) -> Response:
        """GET a document and write its body to ``sink`` chunk by chunk; the response carries an empty body.

        :raises TransportError: on network failure, timeout or when the body exceeds the implementation's cap
        """


@runtime_checkable
class AsyncTransport(Protocol):
    """The async counterpart (the ``httpx`` extra ships one): the same contract, awaited."""

    async def apost(self, url: str, json: str, headers: Mapping[str, str] | None = None) -> Response: ...

    async def aget(self, url: str) -> Response: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is a response, not a place to go: the key file check and the pre-flight exist to see them."""

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None  # "do not follow"


class UrllibTransport:
    """:class:`StreamingTransport` over ``urllib.request``: TLS verified by the default context, no redirects, one
    timeout for the connection and the read, ``Connection: close`` (one request per connection; the ``httpx`` extra
    pools)."""

    __slots__ = (
        "_context",
        "_extra_headers",
        "_get_body_limit",
        "_max_retry_after",
        "_opener",
        "_post_body_limit",
        "_timeout",
    )

    def __init__(
        self,
        timeout: float = 10.0,
        extra_headers: Mapping[str, str] | None = None,
        get_body_limit: int = GET_BODY_LIMIT,
        post_body_limit: int = POST_BODY_LIMIT,
        max_retry_after: int = MAX_RETRY_AFTER,
        context: ssl.SSLContext | None = None,
    ) -> None:
        """:param extra_headers: sent with every request (a ``User-Agent`` for GETs, ``X-Mock-Scenario`` in tests)
        :param get_body_limit: bytes of a GET body (key files, streamed documents) before the request fails
        :param post_body_limit: bytes of a POST response kept for diagnostics; the rest is discarded
        :param max_retry_after: clamp of a parsed Retry-After header, seconds
        :param context: the TLS context (default: ``ssl.create_default_context()``)
        """
        self._timeout = timeout
        self._extra_headers = dict(extra_headers or {})
        self._get_body_limit = get_body_limit
        self._post_body_limit = post_body_limit
        self._max_retry_after = max_retry_after
        self._context = context or ssl.create_default_context()
        self._opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=self._context))

    def post(self, url: str, json: str, headers: Mapping[str, str] | None = None) -> Response:
        request = urllib.request.Request(url, data=json.encode("utf-8"), method="POST")
        request.add_header("Content-Type", "application/json; charset=utf-8")
        for name, value in {**self._extra_headers, **(headers or {})}.items():
            request.add_header(name, value)
        return self._send(request, self._post_body_limit, truncate=True)

    def get(self, url: str) -> Response:
        return self._send(self._get_request(url), self._get_body_limit, truncate=False)

    def download(self, url: str, sink: IO[bytes]) -> Response:
        request = self._get_request(url)
        with self._open(request) as raw:
            read = _copy(raw, self._get_body_limit, request, sink.write, truncate=False)
            _assert_complete(raw.headers, read, request)
            return Response(int(raw.status or 0), b"", self._retry_after(raw.headers), _headers(raw.headers))

    def _get_request(self, url: str) -> urllib.request.Request:
        request = urllib.request.Request(url, method="GET")
        for name, value in self._extra_headers.items():
            request.add_header(name, value)
        return request

    def _send(self, request: urllib.request.Request, limit: int, truncate: bool) -> Response:
        request.add_header("Connection", "close")
        with self._open(request) as raw:
            buffer = io.BytesIO()
            read = _copy(raw, limit, request, buffer.write, truncate)
            if not truncate:
                _assert_complete(raw.headers, read, request)
            status = int(raw.status or 0)
            return Response(status, buffer.getvalue(), self._retry_after(raw.headers), _headers(raw.headers))

    def _open(self, request: urllib.request.Request) -> urllib.response.addinfourl:
        """A 4xx/5xx is a response, not an exception; every network failure is a :class:`TransportError`."""
        if request.type not in ("http", "https"):
            raise TransportError(f"{request.get_method()} {request.full_url}: only http(s) URLs are fetched.")
        try:
            return self._opener.open(request, timeout=self._timeout)  # type: ignore[no-any-return]
        except urllib.error.HTTPError as error:
            return error  # the response: .status, .headers, .read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise TransportError(f"{request.get_method()} {_host(request)} failed: {reason}") from error

    def _retry_after(self, headers: Message) -> int | None:
        return Response.parse_retry_after(headers.get("Retry-After"), self._max_retry_after)


def _copy(
    raw: IO[bytes], limit: int, request: urllib.request.Request, write: Callable[[bytes], object], truncate: bool
) -> int:
    """Reads the body in chunks and hands each to ``write``; a body over ``limit`` is truncated (POST diagnostics) or
    rejected (GET). A connection that drops mid-body surfaces as a TransportError naming the bytes read."""
    read = 0
    try:
        while read < limit:
            chunk = raw.read(min(_READ_CHUNK, limit - read))
            if not chunk:
                return read
            read += len(chunk)
            write(chunk)
        overflow = bool(raw.read(1))
    except (TimeoutError, ConnectionError, OSError) as error:
        raise TransportError(
            f"{request.get_method()} {_host(request)}: connection lost after {read} bytes: {error}"
        ) from error
    if overflow and not truncate:
        raise TransportError(f"{request.get_method()} {_host(request)}: response body larger than {limit} bytes.")
    return read


def _assert_complete(headers: Message, read: int, request: urllib.request.Request) -> None:
    """A body shorter than the announced Content-Length is a truncated download, not a document."""
    length = str(headers.get("Content-Length", ""))
    if length.isdigit() and read < int(length) and not headers.get("Content-Encoding"):
        raise TransportError(
            f"{request.get_method()} {_host(request)}: response truncated, {read} of {length} bytes received."
        )


def _headers(raw: Message) -> dict[str, str]:
    """Every response header, lower-cased names, several values joined with ", "."""
    out: dict[str, str] = {}
    for name, value in raw.items():
        value = str(value)
        key = name.lower()
        out[key] = f"{out[key]}, {value}" if key in out else value
    return out


def _host(request: urllib.request.Request) -> str:
    return urlsplit(request.full_url).hostname or request.full_url
