"""IndexNow keys: the format (spec 01), generation, masking, the providers that map hosts to keys, and the key file
responder every WSGI/ASGI/framework route builds on."""

from __future__ import annotations

import hmac
import re
import secrets
from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from indexnowkit.exceptions import ConfigurationError, InvalidArgumentError

if TYPE_CHECKING:
    from indexnowkit.config import Config

__all__ = [
    "KEY_FILE_CONTENT_TYPE",
    "KEY_FILE_DEFAULT_MAX_AGE",
    "KEY_FILE_PATH_PATTERN",
    "KeyFileResponder",
    "KeyProvider",
    "KeyValidator",
    "StaticKeyProvider",
    "generate_key",
    "key_file_headers",
]


class KeyValidator:
    """IndexNow key rules: 8-128 characters from ``[A-Za-z0-9-]``."""

    MIN_LENGTH = 8
    MAX_LENGTH = 128
    ALPHABET = "A-Za-z0-9-"
    PATTERN = re.compile(rf"^[{ALPHABET}]{{{MIN_LENGTH},{MAX_LENGTH}}}$")

    @classmethod
    def is_valid(cls, key: str) -> bool:
        return cls.PATTERN.match(key) is not None

    @classmethod
    def assert_valid(cls, key: str) -> None:
        """:raises ConfigurationError: with the key masked"""
        if not cls.is_valid(key):
            raise ConfigurationError(
                f'IndexNow key "{cls.mask(key)}" is invalid: {cls.MIN_LENGTH}-{cls.MAX_LENGTH} characters '
                "from [A-Za-z0-9-] required."
            )

    @staticmethod
    def mask(key: str) -> str:
        """Keys are public (served at ``/{key}.txt``) but must not be logged verbatim: the first 4 characters, the
        rest masked."""
        if len(key) <= 4:
            return "*" * len(key)
        return key[:4] + "*" * min(8, len(key) - 4)


_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def generate_key(length: int = 32, hex: bool = True) -> str:
    """A cryptographically random key (CSPRNG). Default: 32 hex characters = 128 bits of entropy.

    :param hex: hex digits only (the documented default); False uses the full ``[A-Za-z0-9]`` alphabet
    :raises InvalidArgumentError: when ``length`` is outside 8..128
    """
    if length < KeyValidator.MIN_LENGTH or length > KeyValidator.MAX_LENGTH:
        raise InvalidArgumentError(
            f"Key length must be between {KeyValidator.MIN_LENGTH} and {KeyValidator.MAX_LENGTH}."
        )
    if hex:
        return secrets.token_hex((length + 1) // 2)[:length]
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


@runtime_checkable
class KeyProvider(Protocol):
    """Maps hosts to IndexNow keys. Implement it to load keys from a database or a multi-tenant registry.

    Every method is called on the submission path; implementations should be cheap (cache per request) and must not
    raise for unknown hosts (return None).
    """

    def key_for(self, host: str) -> str | None:
        """Key for the given (lower-cased) host, or None if the host is not managed: its URLs are skipped with a
        warning and never sent under another host's key."""

    def key_location_for(self, host: str) -> str | None:
        """Absolute URL of the key file when it is not served at ``https://{host}/{key}.txt``."""

    def is_known_key(self, key: str, host: str | None = None) -> bool:
        """Whether ``GET /{key}.txt`` should be answered with this key.

        :param host: host the request arrived at; providers managing several hosts should only confirm keys belonging
            to that host so tenant A's key file is not served on tenant B's host. None = any managed host (single-site
            adapters, CLI diagnostics).
        """

    def managed_hosts(self) -> list[str]:
        """Hosts this provider has keys for, when enumerable (diagnostics). Empty when unknown."""


class StaticKeyProvider:
    """Keys from configuration: a per-host map plus a default key.

    The default key applies to every host not in the map (single-site setups usually only set it). Without a default
    key, or with ``strict_hosts``, hosts missing from the map (and different from the base host) are unmanaged: their
    URLs are skipped, never sent under another host's key.
    """

    __slots__ = (
        "_default_host",
        "_default_key",
        "_hosts",
        "_key_location",
        "_key_locations",
        "_previous_key",
        "_previous_keys",
        "_strict_hosts",
    )

    def __init__(
        self,
        default_key: str | None,
        hosts: Mapping[str, str] | None = None,
        key_location: str | None = None,
        default_host: str | None = None,
        key_locations: Mapping[str, str] | None = None,
        strict_hosts: bool = False,
        previous_key: str | None = None,
        previous_keys: Mapping[str, str] | None = None,
    ) -> None:
        """:param key_locations: per-host overrides of ``key_location``
        :param strict_hosts: apply the default key only to ``default_host`` (multi-domain setups)
        :param previous_key: the default key before a rotation: still accepted by :meth:`is_known_key` so the old key
            file keeps resolving while engines re-verify; never submitted
        :param previous_keys: per-host previous keys
        """
        self._default_key = default_key
        self._hosts = {host.lower(): key for host, key in (hosts or {}).items()}
        self._key_location = key_location
        self._default_host = default_host.lower() if default_host is not None else None
        self._key_locations = {host.lower(): url for host, url in (key_locations or {}).items()}
        self._strict_hosts = strict_hosts
        self._previous_key = previous_key
        self._previous_keys = {host.lower(): key for host, key in (previous_keys or {}).items()}

    @classmethod
    def from_config(cls, config: Config) -> StaticKeyProvider:
        return cls(
            config.key,
            config.hosts,
            config.key_location,
            config.base_host(),
            config.key_locations,
            config.strict_hosts,
            config.previous_key,
            config.previous_keys,
        )

    def key_for(self, host: str) -> str | None:
        host = host.lower()
        if host in self._hosts:
            return self._hosts[host]
        if self._strict_hosts and host != self._default_host:
            return None
        return self._default_key

    def key_location_for(self, host: str) -> str | None:
        host = host.lower()
        if host in self._key_locations:
            return self._key_locations[host]
        if host in self._hosts:
            return None  # mapped host without an override: key file at the default location
        return self._key_location

    def is_known_key(self, key: str, host: str | None = None) -> bool:
        if host is not None:
            expected = self.key_for(host)
            previous = self.previous_key_for(host)
            return (expected is not None and _equal(expected, key)) or (previous is not None and _equal(previous, key))
        candidates = [self._default_key, self._previous_key, *self._hosts.values(), *self._previous_keys.values()]
        return any(known is not None and _equal(known, key) for known in candidates)

    def previous_key_for(self, host: str) -> str | None:
        """The key ``host`` used before its current one, while ``previous_key`` is configured."""
        host = host.lower()
        if host in self._previous_keys:
            return self._previous_keys[host]
        if host in self._hosts or (self._strict_hosts and host != self._default_host):
            return None
        return self._previous_key

    def managed_hosts(self) -> list[str]:
        hosts: dict[str, None] = dict.fromkeys(self._hosts)
        if self._default_host is not None and self._default_key is not None:
            hosts.setdefault(self._default_host)
        return list(hosts)


def _equal(expected: str, given: str) -> bool:
    return hmac.compare_digest(expected.encode(), given.encode())


#: Request path pattern of the key file; group 1 is the key.
KEY_FILE_PATH_PATTERN = re.compile(
    rf"^/([{KeyValidator.ALPHABET}]{{{KeyValidator.MIN_LENGTH},{KeyValidator.MAX_LENGTH}}})\.txt$"
)
KEY_FILE_CONTENT_TYPE = "text/plain; charset=utf-8"
#: Keep it short: after a key rotation a cached old file makes every submission fail with 403.
KEY_FILE_DEFAULT_MAX_AGE = 300


def key_file_headers(max_age: int = KEY_FILE_DEFAULT_MAX_AGE, vary_host: bool = False) -> dict[str, str]:
    """:param vary_host: add ``Vary: Host`` (multi-domain setups behind one shared cache: the body depends on the
    host)"""
    headers = {"Content-Type": KEY_FILE_CONTENT_TYPE, "Cache-Control": f"public, max-age={max(0, max_age)}"}
    if vary_host:
        headers["Vary"] = "Host"
    return headers


class KeyFileResponder:
    """Framework-agnostic key-file endpoint: the adapter matches the request path, this class decides the answer.
    Serve the body with HTTP 200, :data:`KEY_FILE_CONTENT_TYPE` and no redirect; answer 404 when it returns None
    (conformance H01-H03)."""

    PATH_PATTERN = KEY_FILE_PATH_PATTERN
    CONTENT_TYPE = KEY_FILE_CONTENT_TYPE
    DEFAULT_MAX_AGE = KEY_FILE_DEFAULT_MAX_AGE

    __slots__ = ("_enabled", "_keys")

    def __init__(self, keys: KeyProvider, enabled: bool = True) -> None:
        self._keys = keys
        self._enabled = enabled

    @classmethod
    def from_config(cls, config: Config, keys: KeyProvider) -> KeyFileResponder:
        """The responder an adapter wires: ``key_file.enabled`` over the adapter's key provider; the response headers
        are ``Config.key_file_headers()``."""
        return cls(keys, config.key_file_enabled)

    def body_for_path(self, path: str, host: str | None = None) -> str | None:
        """Body to serve for a request path (``/abc...123.txt``), or None for 404.

        :param host: host the request arrived at (see :meth:`KeyProvider.is_known_key`)
        """
        match = self.PATH_PATTERN.match(path)
        if match is None:
            return None
        return self.body_for_key(match.group(1), host)

    def body_for_key(self, key: str, host: str | None = None) -> str | None:
        """Body to serve for an already extracted key, or None for 404. The body is the key once it passed
        :class:`KeyValidator`: nothing a request can put into it survives, so it needs no escaping on the way out."""
        if not self._enabled or not KeyValidator.is_valid(key) or not self._keys.is_known_key(key, host):
            return None
        return key

    @staticmethod
    def headers(max_age: int = KEY_FILE_DEFAULT_MAX_AGE, vary_host: bool = False) -> dict[str, str]:
        return key_file_headers(max_age, vary_host)
