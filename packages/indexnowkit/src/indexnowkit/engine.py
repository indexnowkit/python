"""Known IndexNow endpoints. ``api`` is the shared endpoint that fans out to every participating engine, so it is the
right default; name engines explicitly only to reach a single one.

The list follows https://www.indexnow.org/searchengines.json and each engine's ``meta.json`` (snapshot 2026-09-05:
bing, yandex, seznam, naver, yep, internetarchive, amazonbot). Endpoints are the ``api`` field of the meta files;
Yandex answers on both ``yandex.com`` and ``www.yandex.com`` without a redirect.
"""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit

from indexnowkit.exceptions import ConfigurationError

__all__ = ["Engine"]

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]"})


class Engine(StrEnum):
    API = "api"
    YANDEX = "yandex"
    BING = "bing"
    NAVER = "naver"
    SEZNAM = "seznam"
    YEP = "yep"
    #: Internet Archive (Wayback Machine). Its meta.json declares the endpoint below; the host did not resolve on
    #: 2026-09-05 — reach it through ``api``.
    INTERNETARCHIVE = "internetarchive"
    #: Amazonbot (registry id ``amazonbot``).
    AMAZON = "amazon"

    @property
    def endpoint(self) -> str:
        return _ENDPOINTS[self]

    @classmethod
    def resolve_endpoint(cls, value: str) -> str:
        """Resolve a configured engine value (case-insensitive name or full endpoint URL) into an endpoint URL.
        Custom endpoints must use https, except on loopback hosts (mock servers).

        :raises ConfigurationError: on an unknown name, a plain-http endpoint off loopback, or credentials in the URL
        """
        value = value.strip()
        try:
            return cls(value.lower()).endpoint
        except ValueError:
            pass
        parts = urlsplit(value)
        if parts.scheme and parts.hostname:
            if parts.username is not None or parts.password is not None:
                raise ConfigurationError(f'Custom IndexNow endpoint "{value}" must not contain credentials.')
            scheme = parts.scheme.lower()
            host = _netloc_host(parts.netloc).lower()
            if scheme == "https" or (scheme == "http" and host in _LOOPBACK_HOSTS):
                port = f":{parts.port}" if parts.port is not None else ""
                query = f"?{parts.query}" if parts.query else ""
                return f"{scheme}://{host}{port}{parts.path}{query}"
            raise ConfigurationError(
                f'Custom IndexNow endpoint "{value}" must use https (the key travels in the request body).'
            )
        names = ", ".join(engine.value for engine in cls)
        raise ConfigurationError(
            f'Unknown IndexNow engine "{value}". Use one of: {names}, an alias from engine_aliases, '
            "or a full https endpoint URL."
        )

    @classmethod
    def label_for(cls, endpoint: str) -> str:
        """Human-readable name for logs and results: the enum value for known endpoints, the host for custom ones."""
        for engine in cls:
            if engine.endpoint == endpoint:
                return engine.value
        host = urlsplit(endpoint).hostname
        return host if host else endpoint


_ENDPOINTS = {
    Engine.API: "https://api.indexnow.org/indexnow",
    Engine.YANDEX: "https://yandex.com/indexnow",
    Engine.BING: "https://www.bing.com/indexnow",
    Engine.NAVER: "https://searchadvisor.naver.com/indexnow",
    Engine.SEZNAM: "https://search.seznam.cz/indexnow",
    Engine.YEP: "https://indexnow.yep.com/indexnow",
    Engine.INTERNETARCHIVE: "https://internetarchive.indexnow.org/indexnow",
    Engine.AMAZON: "https://indexnow.amazonbot.amazon/indexnow",
}


def _netloc_host(netloc: str) -> str:
    """The host part of a netloc with the port and userinfo removed, IPv6 brackets kept."""
    host = netloc.rsplit("@", 1)[-1]
    if host.startswith("["):
        return host[: host.index("]") + 1] if "]" in host else host
    return host.split(":", 1)[0]
