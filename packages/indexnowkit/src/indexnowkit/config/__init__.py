"""Immutable configuration shared by every indexnowkit adapter. Keys mirror docs/spec/02 and the PHP ``Config`` one to
one; the constructor checks the invariants, ``from_mapping()`` / ``from_env()`` read the two shapes, ``replace()``
derives copies.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields
from dataclasses import replace as _replace
from typing import Any, ClassVar

from indexnowkit.config import _normalizer as norm
from indexnowkit.config import _parser
from indexnowkit.engine import Engine
from indexnowkit.exceptions import ConfigurationError
from indexnowkit.key import KEY_FILE_DEFAULT_MAX_AGE, KeyValidator, key_file_headers
from indexnowkit.url import TRAILING_SLASH_KEEP, TRAILING_SLASH_MODES, encode_host

__all__ = ["LOG_EVENTS", "LOG_LEVELS", "OPTIONS", "PRODUCTION_ENVIRONMENTS", "Config"]

#: Every key ``from_mapping()`` understands, dotted-path form. Adapters validate their own config against it with
#: ``unknown_options()``. Nested keys are listed as ``block.key`` only.
OPTIONS: tuple[str, ...] = (
    "enabled", "key", "hosts", "key_location", "base_url", "engines", "dispatch", "dry_run",
    "strict_hosts", "environment", "production_environments", "max_url_length", "previous_key",
    "key_file.enabled", "key_file.cache_max_age",
    "batch.max_urls", "debounce.per_url", "debounce.key_prefix", "debounce.store", "throttle.max_requests_per_minute",
    "http.timeout", "http.user_agent", "http.client",
    "logging.max_urls", "logging.forbidden_escalation", "logging.levels", "logging.max_body",
    "engine_aliases", "locale_hosts",
    "retry.max_attempts", "retry.base_delay", "retry.multiplier", "retry.max_delay", "retry.server_error_delay",
    "resolver.max_via_depth", "resolver.max_via_fanout", "collector.max_urls", "collector.detect_leaks",
    "normalizer.strip_tracking_params", "normalizer.tracking_params", "normalizer.trailing_slash",
    "normalizer.sort_query",
)  # fmt: skip
#: Default of ``production_environments``: names for which the missing-key dry-run safety net is off.
PRODUCTION_ENVIRONMENTS: tuple[str, ...] = ("prod", "production")
#: Outcomes whose log level ``logging.levels`` may override, with the shipped level.
LOG_EVENTS: Mapping[str, str] = {
    "ok": "debug", "pending": "info", "invalid_request": "error", "unprocessable": "warning", "rate_limited": "warning",
    "server_error": "warning", "unexpected": "error", "transport": "warning", "no_key": "warning", "dry_run": "info",
    "disabled": "info", "debounced": "debug", "invalid_url": "warning",
}  # fmt: skip
#: The level names ``logging.levels`` accepts: Python's five plus the PSR-3 names of the PHP family.
LOG_LEVELS: tuple[str, ...] = ("emergency", "alert", "critical", "error", "warning", "notice", "info", "debug")
_LEVEL_NUMBERS = {
    "emergency": logging.CRITICAL, "alert": logging.CRITICAL, "critical": logging.CRITICAL, "error": logging.ERROR,
    "warning": logging.WARNING, "notice": logging.INFO, "info": logging.INFO, "debug": logging.DEBUG,
}  # fmt: skip
_DISPATCH = re.compile(r"^[a-z0-9_-]+$", re.IGNORECASE)
_KEY_PREFIX_RESERVED = re.compile(r"[{}()/\\@:\s]")


@dataclass(frozen=True, slots=True)
class Config:
    """The configuration. Construct it directly with keyword arguments, or through :meth:`from_mapping` /
    :meth:`from_env`; every check raises :class:`ConfigurationError` at construction, never at the first submission."""

    MAX_BATCH_URLS: ClassVar[int] = 10_000
    DEFAULT_BATCH_MAX_URLS: ClassVar[int] = 10_000
    #: Yandex accepts the same URL at most once per 10 minutes.
    DEFAULT_DEBOUNCE_PER_URL: ClassVar[int] = 600
    DEFAULT_THROTTLE_PER_MINUTE: ClassVar[int] = 60
    DEFAULT_HTTP_TIMEOUT: ClassVar[float] = 10.0
    #: Conservative browser-era ceiling; the protocol itself sets none.
    DEFAULT_MAX_URL_LENGTH: ClassVar[int] = 2048
    #: URLs listed in one log line (the count is always logged in full).
    DEFAULT_LOG_URLS: ClassVar[int] = 20
    #: Consecutive 403s for one host after which the log level escalates to critical.
    DEFAULT_FORBIDDEN_ESCALATION: ClassVar[int] = 5
    #: Bytes of a response body kept in a failure log line.
    DEFAULT_LOG_BODY: ClassVar[int] = 300
    DEFAULT_RETRY_MAX_ATTEMPTS: ClassVar[int] = 3
    DEFAULT_RETRY_BASE_DELAY: ClassVar[int] = 60
    DEFAULT_RETRY_MULTIPLIER: ClassVar[float] = 2.0
    DEFAULT_RETRY_MAX_DELAY: ClassVar[int] = 3600
    DEFAULT_RETRY_SERVER_ERROR_DELAY: ClassVar[int] = 5
    DEFAULT_RESOLVER_MAX_VIA_DEPTH: ClassVar[int] = 3
    DEFAULT_RESOLVER_MAX_VIA_FANOUT: ClassVar[int] = 100
    DEFAULT_DEBOUNCE_KEY_PREFIX: ClassVar[str] = "indexnowkit_"
    DEFAULT_KEY_FILE_MAX_AGE: ClassVar[int] = KEY_FILE_DEFAULT_MAX_AGE
    #: Default of ``normalizer.trailing_slash``: the path is submitted as the site generates it.
    DEFAULT_TRAILING_SLASH: ClassVar[str] = TRAILING_SLASH_KEEP
    OPTIONS: ClassVar[tuple[str, ...]] = OPTIONS
    LOG_EVENTS: ClassVar[Mapping[str, str]] = LOG_EVENTS
    PRODUCTION_ENVIRONMENTS: ClassVar[tuple[str, ...]] = PRODUCTION_ENVIRONMENTS
    ENV_PREFIX: ClassVar[str] = "INDEXNOW_"

    enabled: bool = True
    key: str | None = None
    #: host => key after construction; the constructor also takes ``{host: {key, key_location, base_url, engines,
    #: previous_key}}`` entries, unpacked into the four tables below
    hosts: Mapping[str, Any] = field(default_factory=dict)
    key_location: str | None = None
    base_url: str | None = None
    #: engine names, aliases or endpoint URLs as configured
    engines: tuple[str, ...] = ("api",)
    #: adapter-defined delivery mode (sync, none, thread, asyncio, callable, ...); the core only reports it
    dispatch: str = "sync"
    strict_hosts: bool = False
    environment: str | None = None
    production_environments: tuple[str, ...] = PRODUCTION_ENVIRONMENTS
    dry_run: bool = False
    #: whether ``dry_run`` was set by the configuration rather than left to its default (``from_mapping()`` sets it
    #: False when it saw no ``dry_run`` key): ``check`` tells the two apart outside production
    dry_run_explicit: bool = True
    #: the key before a rotation: still served/accepted by the key file, never submitted
    previous_key: str | None = None
    max_url_length: int = DEFAULT_MAX_URL_LENGTH
    batch_max_urls: int = DEFAULT_BATCH_MAX_URLS
    debounce_per_url: int = DEFAULT_DEBOUNCE_PER_URL
    #: None = the adapter's default; ``memory``, ``none``, ``state``, or an id the adapter resolves to a cache
    debounce_store: str | None = None
    debounce_key_prefix: str = DEFAULT_DEBOUNCE_KEY_PREFIX
    throttle_max_requests_per_minute: int = DEFAULT_THROTTLE_PER_MINUTE
    http_timeout: float = DEFAULT_HTTP_TIMEOUT
    http_user_agent: str | None = None
    #: ``http.client``: ``urllib`` (default), ``httpx``, or an id the adapter resolves to a client
    http_client: str | None = None
    key_file_enabled: bool = True
    key_file_cache_max_age: int = DEFAULT_KEY_FILE_MAX_AGE
    logging_max_urls: int = DEFAULT_LOG_URLS
    logging_forbidden_escalation: int = DEFAULT_FORBIDDEN_ESCALATION
    #: log event (:data:`LOG_EVENTS`) => level, overriding the shipped level
    logging_levels: Mapping[str, str] = field(default_factory=dict)
    logging_max_body: int = DEFAULT_LOG_BODY
    retry_max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS
    retry_base_delay: int = DEFAULT_RETRY_BASE_DELAY
    retry_multiplier: float = DEFAULT_RETRY_MULTIPLIER
    retry_max_delay: int = DEFAULT_RETRY_MAX_DELAY
    retry_server_error_delay: int = DEFAULT_RETRY_SERVER_ERROR_DELAY
    resolver_max_via_depth: int = DEFAULT_RESOLVER_MAX_VIA_DEPTH
    resolver_max_via_fanout: int = DEFAULT_RESOLVER_MAX_VIA_FANOUT
    collector_max_urls: int = 0
    collector_detect_leaks: bool = True
    #: short names for custom endpoints: ``{"corp": "https://index.corp.example/indexnow"}``
    engine_aliases: Mapping[str, str] = field(default_factory=dict)
    #: locale => host for multi-domain locales: ``{"en": "www.example.com", "de": "example.de"}``
    locale_hosts: Mapping[str, str] = field(default_factory=dict)
    normalizer_strip_tracking_params: bool = True
    normalizer_tracking_params: tuple[str, ...] = ()
    normalizer_trailing_slash: str = DEFAULT_TRAILING_SLASH
    normalizer_sort_query: bool = False
    #: per-host overrides of ``key_location`` (also given inside ``hosts`` entries)
    key_locations: Mapping[str, str] = field(default_factory=dict)
    #: per-host overrides of ``base_url`` for URL generation outside requests
    host_base_urls: Mapping[str, str] = field(default_factory=dict)
    #: per-host engine lists overriding ``engines``
    host_engines: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: per-host previous keys
    previous_keys: Mapping[str, str] = field(default_factory=dict)
    #: resolved, de-duplicated endpoint URLs of ``engines`` (derived)
    endpoints: tuple[str, ...] = field(init=False, default=())
    #: host => resolved endpoints of ``hosts.<host>.engines`` (derived)
    host_endpoints: Mapping[str, tuple[str, ...]] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        s = self._set
        if self.normalizer_trailing_slash not in TRAILING_SLASH_MODES:
            raise ConfigurationError(
                f'"normalizer.trailing_slash" must be one of {", ".join(TRAILING_SLASH_MODES)}, '
                f'got "{self.normalizer_trailing_slash}".'
            )
        s("normalizer_tracking_params", norm.tracking_params(self.normalizer_tracking_params))
        _at_least("logging.max_body", self.logging_max_body, 0)
        _at_least("key_file.cache_max_age", self.key_file_cache_max_age, 0, " seconds")
        if self.debounce_store == "":
            raise ConfigurationError(
                '"debounce.store" must be "memory", "none" or the id of a cache, not an empty string.'
            )
        if self.http_client == "":
            raise ConfigurationError(
                '"http.client" must be "urllib", "httpx" or the id of a client, not an empty string.'
            )
        s("engine_aliases", norm.engine_aliases(self.engine_aliases))
        s("locale_hosts", norm.locale_hosts(self.locale_hosts))
        if self.previous_key is not None:
            KeyValidator.assert_valid(self.previous_key)
        s("logging_levels", norm.log_levels(self.logging_levels, LOG_EVENTS, LOG_LEVELS))
        _at_least(
            "resolver.max_via_depth", self.resolver_max_via_depth, 0, " (0 = rules may not follow `via:` at all)"
        )
        _at_least(
            "resolver.max_via_fanout", self.resolver_max_via_fanout, 1, " (related objects one `via:` hop may yield)"
        )
        _at_least("collector.max_urls", self.collector_max_urls, 0, " (0 = no early flush)")
        if self.debounce_key_prefix == "" or _KEY_PREFIX_RESERVED.search(self.debounce_key_prefix):
            raise ConfigurationError(
                '"debounce.key_prefix" must be a non-empty string without the characters PSR-6 reserves in cache keys '
                f'({{}}()/\\@:) or whitespace, got "{self.debounce_key_prefix}". '
                'Letters, digits, "_", "-" and "." are safe.'
            )
        s("production_environments", norm.production_environments(self.production_environments))
        _at_least("max_url_length", self.max_url_length, 64, " bytes")
        _at_least("logging.max_urls", self.logging_max_urls, 0, " (0 = list no URL)")
        _at_least("logging.forbidden_escalation", self.logging_forbidden_escalation, 1)
        _at_least("retry.max_attempts", self.retry_max_attempts, 1, " (the first attempt counts; 1 = never retry)")
        _at_least(
            "retry.base_delay", self.retry_base_delay, 0, " seconds (the wait before the second attempt after a 429)"
        )
        if self.retry_multiplier < 1.0:
            raise ConfigurationError(
                '"retry.multiplier" must be >= 1.0 (each further wait is the previous one times this), '
                f"got {self.retry_multiplier}."
            )
        _at_least("retry.max_delay", self.retry_max_delay, 0, " seconds (the ceiling of the growing wait)")
        _at_least(
            "retry.server_error_delay",
            self.retry_server_error_delay,
            0,
            " seconds (the wait after a 5xx or a network failure)",
        )
        if self.enabled and not self.dry_run and self.key is None and not self.hosts:
            raise ConfigurationError(
                'IndexNow is enabled but no "key" (or "hosts" map) is configured. Set INDEXNOW_KEY, or enable dry_run.'
            )
        if self.key is not None:
            KeyValidator.assert_valid(self.key)
        keys, locations, base_urls, engines, previous = norm.hosts(self.hosts)
        s("hosts", keys)
        s("key_locations", {**{h.lower(): u for h, u in self.key_locations.items()}, **locations})
        s("host_base_urls", {**{h.lower(): u for h, u in self.host_base_urls.items()}, **base_urls})
        s("host_engines", {**{h.lower(): tuple(e) for h, e in self.host_engines.items()}, **engines})
        s("previous_keys", {**{h.lower(): k for h, k in self.previous_keys.items()}, **previous})
        if self.base_url is not None and not norm.is_absolute_http_url(self.base_url):
            raise ConfigurationError(f'"base_url" must be an absolute http(s) URL, got "{self.base_url}".')
        if self.key_location is not None and not norm.is_key_file_url(self.key_location):
            raise ConfigurationError(
                f'"key_location" must be an absolute http(s) URL to the key file, got "{self.key_location}".'
            )
        if (
            self.key_location is not None
            and self.base_url is not None
            and norm.host_of(self.key_location) != norm.host_of(self.base_url)
        ):
            raise ConfigurationError(
                f'"key_location" ({norm.host_of(self.key_location)}) must be on the host of "base_url" '
                f"({norm.host_of(self.base_url)}): engines only accept a key file served from the submitted host."
            )
        if self.batch_max_urls < 1 or self.batch_max_urls > self.MAX_BATCH_URLS:
            raise ConfigurationError(
                f'"batch.max_urls" must be between 1 and {self.MAX_BATCH_URLS}, got {self.batch_max_urls}.'
            )
        _at_least("debounce.per_url", self.debounce_per_url, 0, " seconds")
        _at_least("throttle.max_requests_per_minute", self.throttle_max_requests_per_minute, 0, " (0 = unlimited)")
        if self.http_timeout <= 0:
            raise ConfigurationError(f'"http.timeout" must be > 0 seconds, got {self.http_timeout}.')
        s("engines", tuple(self.engines))
        if not self.engines:
            raise ConfigurationError('"engines" must contain at least one engine.')
        if not _DISPATCH.match(self.dispatch):
            raise ConfigurationError(
                f'"dispatch" must be a short identifier such as sync, queue or none, got "{self.dispatch}".'
            )
        if self.http_user_agent is not None and ("\r" in self.http_user_agent or "\n" in self.http_user_agent):
            raise ConfigurationError('"http.user_agent" must not contain line breaks.')
        if self.strict_hosts and self.base_url is None and not self.hosts:
            raise ConfigurationError('"strict_hosts" needs at least one known host: set "base_url" or a "hosts" map.')
        s("endpoints", _unique(self.resolve_engine(engine) for engine in self.engines))
        s(
            "host_endpoints",
            {host: _unique(self.resolve_engine(e) for e in items) for host, items in self.host_engines.items()},
        )

    def _set(self, name: str, value: Any) -> None:
        object.__setattr__(self, name, value)

    # -- construction ------------------------------------------------------------------------------------------------

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Config:
        """Build from the canonical nested mapping shape used by framework settings. Outside production
        (``environment`` not in :attr:`PRODUCTION_ENVIRONMENTS`) a missing key switches ``dry_run`` on instead of
        failing, so dev setups never hit the real API."""
        return _parser.from_mapping(data)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, prefix: str = ENV_PREFIX) -> Config:
        """Build from environment variables: :meth:`from_mapping` of :meth:`mapping_from_env`."""
        return cls.from_mapping(cls.mapping_from_env(env, prefix))

    @classmethod
    def mapping_from_env(
        cls, env: Mapping[str, str] | None = None, prefix: str = ENV_PREFIX, options: Iterable[str] | None = None
    ) -> dict[str, Any]:
        """The same variables :meth:`from_env` reads, as the nested mapping :meth:`from_mapping` takes — **only the
        variables that are set**: an unset or empty variable leaves no key, values stay strings. Every option ``a.b``
        of :data:`OPTIONS` (or ``options``: the CLI passes the blocks of the sitemap, verify and history modules too)
        is the variable ``<prefix>A_B``; ``environment`` also reads ``<prefix>ENV`` and ``APP_ENV``. This is what an
        application without a framework merges over its configuration file, environment on top.
        ``Config.from_mapping(Config.mapping_from_env(env))`` equals ``Config.from_env(env)``."""
        return _parser.mapping_from_env(os.environ if env is None else env, prefix, options or OPTIONS)

    def replace(self, **changes: Any) -> Config:
        """A copy with some values replaced, by field name: ``config.replace(dry_run=True, engines=("yandex",))``.
        Changing ``dry_run`` makes the copy explicit (:attr:`dry_run_explicit`); other changes keep the flag."""
        known = {f.name for f in fields(self) if f.init}
        unknown = [name for name in changes if name not in known]
        if unknown:
            raise ConfigurationError(
                f'Unknown Config option "{unknown[0]}". Known options: {", ".join(sorted(known))}.'
            )
        if "dry_run" in changes and "dry_run_explicit" not in changes:
            changes["dry_run_explicit"] = True
        changes.setdefault("hosts", self._hosts_for_constructor())
        return _replace(self, **changes)

    def to_mapping(self) -> dict[str, Any]:
        """The effective configuration in the nested shape :meth:`from_mapping` takes, every option of
        :data:`OPTIONS` present with its resolved value. Keys are **not** masked: the ``config`` command does that.
        ``Config.from_mapping(config.to_mapping())`` is an equal configuration."""
        return {
            "enabled": self.enabled,
            "key": self.key,
            "previous_key": self.previous_key,
            "hosts": self._hosts_for_constructor(),
            "key_location": self.key_location,
            "base_url": self.base_url,
            "strict_hosts": self.strict_hosts,
            "engines": list(self.engines),
            "engine_aliases": dict(self.engine_aliases),
            "locale_hosts": dict(self.locale_hosts),
            "dispatch": self.dispatch,
            "dry_run": self.dry_run,
            "environment": self.environment,
            "production_environments": list(self.production_environments),
            "max_url_length": self.max_url_length,
            "key_file": {"enabled": self.key_file_enabled, "cache_max_age": self.key_file_cache_max_age},
            "batch": {"max_urls": self.batch_max_urls},
            "debounce": {
                "per_url": self.debounce_per_url,
                "key_prefix": self.debounce_key_prefix,
                "store": self.debounce_store,
            },
            "throttle": {"max_requests_per_minute": self.throttle_max_requests_per_minute},
            "http": {"timeout": self.http_timeout, "user_agent": self.http_user_agent, "client": self.http_client},
            "logging": {
                "max_urls": self.logging_max_urls,
                "forbidden_escalation": self.logging_forbidden_escalation,
                "levels": dict(self.logging_levels),
                "max_body": self.logging_max_body,
            },
            "retry": {
                "max_attempts": self.retry_max_attempts,
                "base_delay": self.retry_base_delay,
                "multiplier": self.retry_multiplier,
                "max_delay": self.retry_max_delay,
                "server_error_delay": self.retry_server_error_delay,
            },
            "resolver": {"max_via_depth": self.resolver_max_via_depth, "max_via_fanout": self.resolver_max_via_fanout},
            "collector": {"max_urls": self.collector_max_urls, "detect_leaks": self.collector_detect_leaks},
            "normalizer": {
                "strip_tracking_params": self.normalizer_strip_tracking_params,
                "tracking_params": list(self.normalizer_tracking_params),
                "trailing_slash": self.normalizer_trailing_slash,
                "sort_query": self.normalizer_sort_query,
            },
        }

    @staticmethod
    def unknown_options(data: Mapping[str, Any], allowed: Iterable[str] = ()) -> list[str]:
        """Keys of ``data`` that :meth:`from_mapping` does not understand, as dotted paths. Adapters add their own
        keys via ``allowed`` (a prefix like ``messenger`` allows the whole block) and warn on the remainder, so
        ``debounce.per_urls`` does not pass silently. A nested block is walked down as long as a known key starts
        with its path, so a block is reported by its unknown leaves, never as a whole because it has children."""
        known = (*OPTIONS, *allowed)
        unknown: list[str] = []
        for name, value in data.items():
            name = str(name)
            if name == "hosts" or name in known:
                continue
            if isinstance(value, Mapping):
                _unknown_in(value, name, known, unknown)
                continue
            unknown.append(name)
        return unknown

    # -- derived values ----------------------------------------------------------------------------------------------

    def resolve_engine(self, engine: str) -> str:
        """Engine name, alias (:attr:`engine_aliases`) or endpoint URL to its endpoint."""
        return Engine.resolve_endpoint(self.engine_aliases.get(engine.strip().lower(), engine))

    def host_for_locale(self, locale: str | None) -> str | None:
        """Host of a locale (:attr:`locale_hosts`), or None when the locale has no host of its own."""
        return None if locale is None else self.locale_hosts.get(locale.lower())

    def endpoints_for(self, host: str) -> tuple[str, ...]:
        """Endpoint URLs the URLs of ``host`` go to: ``hosts.<host>.engines`` when set, else ``engines``."""
        return self.host_endpoints.get(host.lower(), self.endpoints)

    def log_level(self, event: str) -> str:
        """Level name for a log event (:data:`LOG_EVENTS`): the configured override, else the shipped default."""
        return self.logging_levels.get(event) or LOG_EVENTS.get(event, "info")

    def logging_level(self, event: str) -> int:
        """The same as a ``logging`` level number (PSR-3 names map to the closest Python level)."""
        return _LEVEL_NUMBERS[self.log_level(event)]

    def user_agent(self) -> str:
        from indexnowkit import __version__

        return self.http_user_agent or f"indexnowkit-python/{__version__} (+https://indexnowkit.dev/python/)"

    def is_production(self) -> bool:
        """Whether ``environment`` is one of ``production_environments``; False when unknown."""
        return self.environment is not None and self.environment.lower() in self.production_environments

    def key_file_headers(self) -> dict[str, str]:
        """Response headers of the key file: ``key_file.cache_max_age``, and ``Vary: Host`` when the body depends on
        the host (a ``hosts`` map, or ``strict_hosts``)."""
        return key_file_headers(self.key_file_cache_max_age, bool(self.hosts) or self.strict_hosts)

    def log_sample(self, urls: Iterable[str]) -> list[str]:
        """The first ``logging.max_urls`` entries of a URL list, for log context (the count goes in the message)."""
        return list(urls)[: self.logging_max_urls]

    def base_url_for(self, host: str) -> str | None:
        """Base URL to generate absolute URLs for a host: the per-host override, else ``base_url`` when it is that
        host, else None."""
        host = host.lower()
        if host in self.host_base_urls:
            return self.host_base_urls[host]
        return self.base_url if self.base_host() == host else None

    def base_host(self) -> str | None:
        """Host of ``base_url``, lower-cased and in punycode (the form the normalizer gives every submitted URL, so
        an IDN base_url matches its own URLs in ``strict_hosts``), or None."""
        if self.base_url is None:
            return None
        host = norm.host_of(self.base_url)
        if host == "":
            return None
        return host if host.startswith("[") else encode_host(host)

    def _hosts_for_constructor(self) -> dict[str, Any]:
        hosts: dict[str, Any] = {}
        for host, key in self.hosts.items():
            entry: dict[str, Any] = {"key": key}
            if host in self.key_locations:
                entry["key_location"] = self.key_locations[host]
            if host in self.host_base_urls:
                entry["base_url"] = self.host_base_urls[host]
            if host in self.host_engines:
                entry["engines"] = list(self.host_engines[host])
            if host in self.previous_keys:
                entry["previous_key"] = self.previous_keys[host]
            hosts[host] = key if len(entry) == 1 else entry
        return hosts


def _at_least(option: str, value: float, minimum: float, hint: str = "") -> None:
    if value < minimum:
        raise ConfigurationError(f'"{option}" must be >= {minimum}{hint}, got {value}.')


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _unknown_in(block: Mapping[Any, Any], prefix: str, known: tuple[str, ...], unknown: list[str]) -> None:
    for sub, value in block.items():
        path = f"{prefix}.{sub}"
        if path in known:
            continue
        if isinstance(value, Mapping) and any(option.startswith(path + ".") for option in known):
            _unknown_in(value, path, known, unknown)
            continue
        unknown.append(path)
