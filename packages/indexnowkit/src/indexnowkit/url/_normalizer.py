"""Default normalizer: absolute http(s) URL, lower-cased scheme and host, IDN host as punycode, default port and
fragment removed, dot-segments resolved, userinfo rejected.

Path and query are kept as given (apart from dot-segments and percent-encoding) so the submitted URL matches what the
site actually serves.
"""

from __future__ import annotations

import re
from typing import Protocol
from urllib.parse import SplitResult, urlsplit

from indexnowkit.exceptions import InvalidUrlError
from indexnowkit.url._punycode import MAX_HOST_LENGTH, MAX_LABEL_LENGTH, encode_host

__all__ = ["UrlNormalizer", "UrlNormalizerProtocol", "host_of"]

MAX_URL_LENGTH = 2048
_DEFAULT_PORTS = {"http": 80, "https": 443}
_SCHEME = re.compile(r"^([a-z][a-z0-9+.-]*):", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_IPV6 = re.compile(r"^\[[0-9a-f:.]+\]$", re.IGNORECASE)
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class UrlNormalizerProtocol(Protocol):
    """Canonical form of a URL before dedup, debounce and submission. Replace it to strip tracking parameters,
    enforce a trailing-slash policy or map hosts."""

    def normalize(self, url: str) -> str:
        """An absolute http(s) URL for an absolute, protocol-relative or base_url-relative one.

        :raises InvalidUrlError: when the URL cannot be submitted (wrong scheme, no host, no base_url for a relative
            path, ...). Implementations MUST raise only this exception: anything else escapes to the caller and breaks
            the never-raise contract of ``submit()``
        """

    def host_of(self, normalized_url: str) -> str:
        """Lower-cased host of an already normalized URL.

        :raises InvalidUrlError: when there is none
        """


class UrlNormalizer:
    """The shipped :class:`UrlNormalizerProtocol`."""

    __slots__ = ("_base_url", "_max_url_length")

    def __init__(self, base_url: str | None = None, max_url_length: int = MAX_URL_LENGTH) -> None:
        self._base_url = base_url
        self._max_url_length = max_url_length

    def normalize(self, url: str) -> str:
        url = url.strip()
        if url == "":
            raise InvalidUrlError("Empty URL.")
        if len(url.encode("utf-8", "surrogateescape")) > self._max_url_length:
            raise InvalidUrlError(f"URL longer than {self._max_url_length} bytes (max_url_length).")
        if _CONTROL.search(url):
            raise InvalidUrlError(f'URL "{_excerpt(url)}" contains control characters.')
        try:
            url.encode("utf-8")
        except UnicodeEncodeError as error:
            raise InvalidUrlError("URL is not valid UTF-8.") from error
        url = url.replace(" ", "%20")
        url = self._make_absolute(url)
        parts = _split(url)
        if not parts.scheme or not parts.hostname:
            raise InvalidUrlError(f'Cannot parse URL "{_excerpt(url)}".')
        if parts.username is not None or parts.password is not None:
            raise InvalidUrlError(f'URL "{_excerpt(url)}" contains credentials; only public URLs can be submitted.')
        scheme = parts.scheme.lower()
        host = _normalize_host(_raw_host(parts.netloc))
        port = _port(parts)
        port_part = f":{port}" if port is not None and port != _DEFAULT_PORTS.get(scheme) else ""
        path = _normalize_percent_encoding(_remove_dot_segments(parts.path or "/"))
        query = f"?{_normalize_percent_encoding(parts.query)}" if _has_query(url, parts) else ""
        return f"{scheme}://{host}{port_part}{path}{query}"

    def host_of(self, normalized_url: str) -> str:
        return host_of(normalized_url)

    def _make_absolute(self, url: str) -> str:
        match = _SCHEME.match(url)
        if match:
            scheme = match.group(1).lower()
            if scheme not in _DEFAULT_PORTS:
                raise InvalidUrlError(
                    f'URL "{_excerpt(url)}" uses scheme "{scheme}"; only http and https can be submitted.'
                )
            return url
        if url.startswith("//"):
            scheme = urlsplit(self._base_url).scheme if self._base_url is not None else "https"
            return f"{scheme or 'https'}:{url}"
        if self._base_url is None:
            raise InvalidUrlError(f'Relative URL "{_excerpt(url)}" given but no base_url configured.')
        if url.startswith("/"):
            origin = urlsplit(self._base_url)
            if origin.scheme and origin.netloc:
                return f"{origin.scheme}://{origin.netloc}{url}"
        return self._base_url.rstrip("/") + "/" + url.lstrip("/")


def host_of(normalized_url: str) -> str:
    """Lower-cased host of an already normalized URL (IPv6 literals keep their brackets)."""
    host = _raw_host(_split(normalized_url).netloc)
    if host == "":
        raise InvalidUrlError(f'URL "{_excerpt(normalized_url)}" has no host.')
    return host.lower()


def _split(url: str) -> SplitResult:
    try:
        return urlsplit(url)
    except ValueError as error:
        raise InvalidUrlError(f'Cannot parse URL "{_excerpt(url)}".') from error


def _raw_host(netloc: str) -> str:
    """The host of a netloc, userinfo and port removed, IPv6 brackets kept, case as given."""
    host = netloc.rsplit("@", 1)[-1]
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1] if end >= 0 else host
    return host.split(":", 1)[0]


def _port(parts: SplitResult) -> int | None:
    try:
        return parts.port
    except ValueError as error:
        raise InvalidUrlError(f'Cannot parse URL "{_excerpt(parts.geturl())}".') from error


def _has_query(url: str, parts: SplitResult) -> bool:
    """``urlsplit`` cannot tell ``?`` from no query: an empty query is kept as ``?`` only when the URL had one."""
    return bool(parts.query) or "?" in url.split("#", 1)[0]


def _normalize_host(host: str) -> str:
    host = host.lower().rstrip(".")
    if host == "":
        raise InvalidUrlError("URL has an empty host.")
    if host.startswith("["):
        if not _IPV6.match(host) or not _is_ipv6(host[1:-1]):
            raise InvalidUrlError(f'Invalid IPv6 host "{host}".')
        return host
    host = encode_host(host)
    if len(host) > MAX_HOST_LENGTH:
        raise InvalidUrlError(f"Host name longer than {MAX_HOST_LENGTH} characters.")
    for label in host.split("."):
        if label == "" or len(label) > MAX_LABEL_LENGTH or not _LABEL.match(label):
            raise InvalidUrlError(f'Invalid host name "{host}".')
    return host


def _is_ipv6(address: str) -> bool:
    import ipaddress

    try:
        ipaddress.IPv6Address(address)
    except ValueError:
        return False
    return True


def _normalize_percent_encoding(component: str) -> str:
    """RFC 3986 §6.2.2: a percent-escape of an unreserved character (``A-Za-z0-9-._~``) becomes the character, every
    other escape gets upper-case hex digits — ``%7e`` and ``~``, ``%3a`` and ``%3A`` are one URL and one debounce
    entry."""
    if "%" not in component:
        return component

    def replace(match: re.Match[str]) -> str:
        char = chr(int(match.group(1), 16))
        return char if char in _UNRESERVED else "%" + match.group(1).upper()

    return _PERCENT.sub(replace, component)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4."""
    if path == "":
        return "/"
    if "/." not in path:
        return path
    output: list[str] = []
    for segment in path.split("/"):
        if segment == ".":
            continue
        if segment == "..":
            if len(output) > 1:
                output.pop()
            continue
        output.append(segment)
    result = "/".join(output)
    if path.endswith(("/.", "/..")):
        result += "/"
    return "/" + result.lstrip("/") if result == "" or not result.startswith("/") else result


def _excerpt(url: str) -> str:
    """Short, log-safe rendering of a rejected URL: control characters escaped, length capped."""
    safe = "".join(f"\\x{ord(char):02x}" if ord(char) < 0x20 or ord(char) == 0x7F else char for char in url)
    return safe[:117] + "..." if len(safe) > 120 else safe
