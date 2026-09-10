"""HTTP: the response and transport contracts of the protocol layer, the shipped ``urllib`` transport, the lazy
transport of ``http.client`` and the ``httpx`` extra (``indexnowkit.http.httpx``)."""

from __future__ import annotations

from indexnowkit.exceptions import TransportError
from indexnowkit.http._lazy import HTTPX, URLLIB, LazyTransport, transport_from_config, transport_of
from indexnowkit.http._response import MAX_RETRY_AFTER, Response
from indexnowkit.http._transport import (
    GET_BODY_LIMIT,
    POST_BODY_LIMIT,
    AsyncTransport,
    StreamingTransport,
    Transport,
    UrllibTransport,
)

__all__ = [
    "GET_BODY_LIMIT",
    "HTTPX",
    "MAX_RETRY_AFTER",
    "POST_BODY_LIMIT",
    "URLLIB",
    "AsyncTransport",
    "LazyTransport",
    "Response",
    "StreamingTransport",
    "Transport",
    "TransportError",
    "UrllibTransport",
    "transport_from_config",
    "transport_of",
]
