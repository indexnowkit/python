"""Minimal HTTP response as seen by the protocol layer."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any

__all__ = ["MAX_RETRY_AFTER", "Response"]

#: Upper bound applied to Retry-After values (one day).
MAX_RETRY_AFTER = 86_400
_DIGITS = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True)
class Response:
    """:param status: the HTTP status
    :param body: the body as bytes (a POST response is truncated to a diagnostics limit by the transport)
    :param retry_after: seconds, already clamped to ``[0, MAX_RETRY_AFTER]``; None when the header is absent or
        unparseable
    :param headers: response headers, name => value (several values joined with ", "); names are lower-cased here.
        Empty when the transport does not expose headers, which ``check`` tells apart from "the header is absent"
        only by this mapping being empty
    """

    status: int
    body: bytes = b""
    retry_after: int | None = None
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", {name.lower(): value for name, value in self.headers.items()})
        body: Any = self.body
        if isinstance(body, str):  # a convenience for tests and doubles
            object.__setattr__(self, "body", body.encode("utf-8"))

    @property
    def text(self) -> str:
        """The body decoded as UTF-8 (undecodable bytes replaced): for diagnostics and text documents."""
        return self.body.decode("utf-8", "replace")

    def header(self, name: str) -> str | None:
        """One header by name (case-insensitive), None when absent."""
        return self.headers.get(name.lower())

    def content_type(self) -> str | None:
        """The media type of the body (``text/plain`` for ``Content-Type: text/plain; charset=utf-8``), lower-cased;
        None when the header is absent."""
        header = self.header("content-type")
        if header is None:
            return None
        media_type = header.split(";", 1)[0].strip().lower()
        return media_type or None

    def cache_max_age(self) -> int | None:
        """How long a shared cache may keep this response, from ``Cache-Control`` (``s-maxage`` wins over
        ``max-age``; RFC 9111); None when the header is absent or names no lifetime (``no-store`` and ``no-cache``
        are 0)."""
        header = self.header("cache-control")
        if header is None:
            return None
        directives: dict[str, str | None] = {}
        for directive in header.lower().split(","):
            name, _, value = directive.strip().partition("=")
            directives[name.strip()] = value.strip(' \t"') if _ else None
        if "no-store" in directives or "no-cache" in directives:
            return 0
        for name in ("s-maxage", "max-age"):
            lifetime = directives.get(name)
            if lifetime is not None and _DIGITS.match(lifetime):
                return int(lifetime)
        return None

    def age(self) -> int | None:
        """The ``Age`` header (seconds this response spent in a cache), None when absent or malformed."""
        age = self.header("age")
        return int(age.strip()) if age is not None and _DIGITS.match(age.strip()) else None

    @staticmethod
    def parse_retry_after(header: str | None, maximum: int = MAX_RETRY_AFTER, now: float | None = None) -> int | None:
        """Parse a Retry-After header value (RFC 9110: delta-seconds or HTTP-date) into clamped delay seconds.
        Custom transports use it so every adapter interprets the header the same way.

        :param now: Unix timestamp used for HTTP-date values (default: ``time.time()``)
        """
        header = (header or "").strip()
        if header == "":
            return None
        if _DIGITS.match(header):
            return min(int(header), maximum)
        try:
            date = parsedate_to_datetime(header)
        except (TypeError, ValueError, IndexError):
            # Several Retry-After headers joined by a header line ("120, 60"): the longest wait wins.
            parts = [part.strip() for part in header.split(",")]
            if len(parts) > 1:
                delays = [Response.parse_retry_after(part, maximum, now) for part in parts]
                found = [delay for delay in delays if delay is not None]
                return max(found) if found else None
            return None
        current = time.time() if now is None else now
        return max(0, min(int(date.timestamp() - current), maximum))
