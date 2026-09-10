"""The ``httpx`` extra: a pooled sync transport and the async transport ``IndexNowKit.asubmit()`` uses. ``httpx`` is
imported here only, so the core has no dependency on it (``pip install "indexnowkit[httpx]"``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import IO, Any

from indexnowkit.exceptions import ConfigurationError, TransportError
from indexnowkit.http._response import MAX_RETRY_AFTER, Response
from indexnowkit.http._transport import GET_BODY_LIMIT, POST_BODY_LIMIT

__all__ = ["AsyncHttpxTransport", "HttpxTransport"]


def _httpx() -> Any:
    try:
        import httpx
    except ImportError as error:
        raise ConfigurationError(
            'http.client is "httpx" but the httpx package is not installed: pip install "indexnowkit[httpx]".'
        ) from error
    return httpx


class _Base:
    __slots__ = ("_extra_headers", "_get_body_limit", "_max_retry_after", "_post_body_limit", "_timeout", "httpx")

    def __init__(
        self,
        timeout: float = 10.0,
        extra_headers: Mapping[str, str] | None = None,
        get_body_limit: int = GET_BODY_LIMIT,
        post_body_limit: int = POST_BODY_LIMIT,
        max_retry_after: int = MAX_RETRY_AFTER,
    ) -> None:
        self.httpx = _httpx()
        self._timeout = timeout
        self._extra_headers = dict(extra_headers or {})
        self._get_body_limit = get_body_limit
        self._post_body_limit = post_body_limit
        self._max_retry_after = max_retry_after

    def _response(self, response: Any, body: bytes) -> Response:
        headers = {name.lower(): value for name, value in response.headers.items()}
        retry_after = Response.parse_retry_after(headers.get("retry-after"), self._max_retry_after)
        return Response(int(response.status_code), body, retry_after, headers)

    def _error(self, method: str, url: str, error: Exception) -> TransportError:
        return TransportError(f"{method} {self.httpx.URL(url).host} failed: {error}")


class HttpxTransport(_Base):
    """A pooled :class:`~indexnowkit.http.StreamingTransport` (one ``httpx.Client`` per transport, no redirects)."""

    __slots__ = ("_client",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client = self.httpx.Client(timeout=self._timeout, follow_redirects=False, headers=self._extra_headers)

    def post(self, url: str, json: str, headers: Mapping[str, str] | None = None) -> Response:
        request_headers = {"Content-Type": "application/json; charset=utf-8", **(headers or {})}
        try:
            with self._client.stream("POST", url, content=json.encode("utf-8"), headers=request_headers) as response:
                body = _read(response.iter_bytes(), self._post_body_limit, truncate=True, label=f"POST {url}")
                return self._response(response, body)
        except self.httpx.HTTPError as error:
            raise self._error("POST", url, error) from error

    def get(self, url: str) -> Response:
        try:
            with self._client.stream("GET", url) as response:
                body = _read(response.iter_bytes(), self._get_body_limit, truncate=False, label=f"GET {url}")
                return self._response(response, body)
        except self.httpx.HTTPError as error:
            raise self._error("GET", url, error) from error

    def download(self, url: str, sink: IO[bytes]) -> Response:
        try:
            with self._client.stream("GET", url) as response:
                read = 0
                for chunk in response.iter_bytes():
                    read += len(chunk)
                    if read > self._get_body_limit:
                        raise TransportError(f"GET {url}: response body larger than {self._get_body_limit} bytes.")
                    sink.write(chunk)
                return self._response(response, b"")
        except self.httpx.HTTPError as error:
            raise self._error("GET", url, error) from error

    def close(self) -> None:
        self._client.close()


class AsyncHttpxTransport(_Base):
    """The :class:`~indexnowkit.http.AsyncTransport` of ``asubmit()``: one ``httpx.AsyncClient`` per transport."""

    __slots__ = ("_client",)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._client = self.httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, headers=self._extra_headers
        )

    async def apost(self, url: str, json: str, headers: Mapping[str, str] | None = None) -> Response:
        request_headers = {"Content-Type": "application/json; charset=utf-8", **(headers or {})}
        try:
            request = self._client.stream("POST", url, content=json.encode("utf-8"), headers=request_headers)
            async with request as response:
                chunks = [chunk async for chunk in response.aiter_bytes()]
                body = _read(chunks, self._post_body_limit, truncate=True, label=f"POST {url}")
                return self._response(response, body)
        except self.httpx.HTTPError as error:
            raise self._error("POST", url, error) from error

    async def aget(self, url: str) -> Response:
        try:
            async with self._client.stream("GET", url) as response:
                chunks = [chunk async for chunk in response.aiter_bytes()]
                body = _read(chunks, self._get_body_limit, truncate=False, label=f"GET {url}")
                return self._response(response, body)
        except self.httpx.HTTPError as error:
            raise self._error("GET", url, error) from error

    async def aclose(self) -> None:
        await self._client.aclose()


def _read(chunks: Any, limit: int, truncate: bool, label: str) -> bytes:
    out = bytearray()
    for chunk in chunks:
        if len(out) + len(chunk) > limit:
            if not truncate:
                raise TransportError(f"{label}: response body larger than {limit} bytes.")
            out += chunk[: limit - len(out)]
            break
        out += chunk
    return bytes(out)
