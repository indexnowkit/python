"""A transport built on first use, and the factory of the ``http.client`` option."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import IO, TYPE_CHECKING, Any

from indexnowkit.exceptions import ConfigurationError, TransportError
from indexnowkit.http._response import Response
from indexnowkit.http._transport import GET_BODY_LIMIT, StreamingTransport, Transport, UrllibTransport

if TYPE_CHECKING:
    from indexnowkit.config import Config

__all__ = ["LazyTransport", "transport_from_config"]

URLLIB = "urllib"
HTTPX = "httpx"


class LazyTransport:
    """Defers building the real transport (client construction, an ``httpx`` import) until the first request, so a
    request that submits nothing, a dry-run setup or ``check`` never pays for it and never fails on it."""

    __slots__ = ("_factory", "_transport")

    def __init__(self, factory: Callable[[], Transport]) -> None:
        self._factory = factory
        self._transport: Transport | None = None

    def post(self, url: str, json: str, headers: Mapping[str, str] | None = None) -> Response:
        return self.transport().post(url, json, headers)

    def get(self, url: str) -> Response:
        return self.transport().get(url)

    def download(self, url: str, sink: IO[bytes]) -> Response:
        """Streams when the real transport can, otherwise buffers through :meth:`Transport.get`."""
        transport = self.transport()
        if isinstance(transport, StreamingTransport):
            return transport.download(url, sink)
        response = transport.get(url)
        if response.body:
            sink.write(response.body)
        return Response(response.status, b"", response.retry_after, response.headers)

    def transport(self) -> Transport:
        """:raises TransportError: when the factory cannot build a transport (the httpx extra is not installed); the
        ConfigurationError is chained so ``check`` can explain it"""
        if self._transport is not None:
            return self._transport
        try:
            self._transport = self._factory()
        except ConfigurationError as error:
            raise TransportError(f"No HTTP client available: {error}") from error
        return self._transport


def transport_from_config(
    config: Config,
    client_locator: Callable[[str], Any] | None = None,
    extra_headers: Mapping[str, str] | None = None,
    get_body_limit: int | None = None,
) -> LazyTransport:
    """The transport an adapter wires from ``http.client`` and ``http.timeout``, built on first use only.

    ``http.client`` unset or ``urllib``: :class:`UrllibTransport` with the timeout. ``httpx``: the transport of the
    ``httpx`` extra. Anything else: the adapter's locator resolves the id (a container binding, a setting) and the
    result must be a :class:`Transport`.

    :param client_locator: how the adapter resolves ``http.client``; required for an id that is not a built-in name
    :param extra_headers: sent with every request of this transport (a ``User-Agent`` for GETs, which take no
        headers; POSTs carry ``http.user_agent``)
    :param get_body_limit: bytes of a GET body before the request fails (:data:`GET_BODY_LIMIT`)
    """
    client = config.http_client
    if client not in (None, URLLIB, HTTPX) and client_locator is None:
        raise ConfigurationError(
            f'"http.client" is "{client}" but this adapter has no way to resolve it; pass a client locator or unset '
            "the option."
        )
    headers = dict(extra_headers or {})
    limit = GET_BODY_LIMIT if get_body_limit is None else get_body_limit

    def build() -> Transport:
        if client is None or client == URLLIB:
            return UrllibTransport(config.http_timeout, headers, limit)
        if client == HTTPX:
            from indexnowkit.http.httpx import HttpxTransport

            return HttpxTransport(config.http_timeout, headers, limit)
        if client_locator is None:  # pragma: no cover — checked above, kept for the type checker
            raise ConfigurationError('"http.client" needs a client locator.')
        return transport_of(client_locator(client), client)

    return LazyTransport(build)


def transport_of(instance: Any, client: str) -> Transport:
    """What an ``http.client`` id resolved to, checked to be a :class:`Transport`.

    :raises ConfigurationError: with the id and the type it resolved to
    """
    if not isinstance(instance, Transport):
        raise ConfigurationError(
            f'"http.client" "{client}" resolves to {type(instance).__name__}, which is not a Transport '
            "(an object with post() and get())."
        )
    return instance
