"""The raw mappings the constructor of ``Config`` accepts (``hosts``, ``engine_aliases``, ``locale_hosts``,
``logging.levels``, ``normalizer.tracking_params``, ``production_environments``) to their validated, lower-cased
shape, plus the URL predicates the constructor and those checks share. Pure functions: every one either returns the
normalised value or raises a ConfigurationError naming the option.

Internal: part of ``Config``, not of the compatibility promise (docs/bc.md).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from indexnowkit.engine import Engine
from indexnowkit.exceptions import ConfigurationError
from indexnowkit.key import KeyValidator

#: Bare host name: labels, or an IPv6 literal in brackets; no scheme, port or path.
_HOST_PATTERN = re.compile(r"^(\[[0-9a-f:.]+\]|[a-z0-9.-]+)$", re.IGNORECASE)
_TRACKING_PARAM = re.compile(r"^[A-Za-z0-9_.\-\[\]]+\*?$")
_ALIAS = re.compile(r"^[a-z][a-z0-9_-]*$", re.IGNORECASE)

HostTables = tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, tuple[str, ...]], dict[str, str]]


def tracking_params(params: Iterable[Any]) -> tuple[str, ...]:
    out: dict[str, None] = {}
    for name in params:
        if not isinstance(name, str) or not _TRACKING_PARAM.match(name.strip()):
            raise ConfigurationError(
                f'"normalizer.tracking_params" must list query parameter names ("ref", "mtm_*"), got {describe(name)}.'
            )
        out.setdefault(name.strip().lower())
    return tuple(out)


def engine_aliases(aliases: Mapping[Any, Any]) -> dict[str, str]:
    """Lower-cased alias => endpoint."""
    out: dict[str, str] = {}
    for name, endpoint in aliases.items():
        if not isinstance(name, str) or not _ALIAS.match(name) or _is_engine(name):
            raise ConfigurationError(
                f'"engine_aliases" names must be identifiers that are not built-in engines, got "{name}".'
            )
        if not isinstance(endpoint, str) or not is_absolute_http_url(endpoint):
            raise ConfigurationError(f'"engine_aliases.{name}" must be an endpoint URL.')
        out[name.lower()] = Engine.resolve_endpoint(endpoint)
    return out


def locale_hosts(hosts: Mapping[Any, Any]) -> dict[str, str]:
    """Lower-cased locale => lower-cased host."""
    out: dict[str, str] = {}
    for locale, host in hosts.items():
        if not isinstance(locale, str) or locale == "" or not isinstance(host, str) or not _HOST_PATTERN.match(host):
            raise ConfigurationError(
                f'"locale_hosts" must map locales to bare host names, got "{locale}" => {describe(host)}.'
            )
        out[locale.lower()] = host.lower()
    return out


def log_levels(levels: Mapping[Any, Any], events: Mapping[str, str], known: Iterable[str]) -> dict[str, str]:
    """Event => lower-cased level; every event one of ``events`` (the known log events), every level in ``known``."""
    out: dict[str, str] = {}
    known_levels = tuple(known)
    for event, level in levels.items():
        if not isinstance(event, str) or event not in events:
            raise ConfigurationError(f'"logging.levels" has an unknown event "{event}"; known: {", ".join(events)}.')
        if not isinstance(level, str) or level.lower() not in known_levels:
            raise ConfigurationError(
                f'"logging.levels.{event}" must be a log level ({", ".join(known_levels)}), got {describe(level)}.'
            )
        out[event] = level.lower()
    return out


def production_environments(environments: Iterable[Any]) -> tuple[str, ...]:
    """Lower-cased, trimmed, unique; at least one."""
    out: dict[str, None] = {}
    for environment in environments:
        if isinstance(environment, str) and environment.strip() != "":
            out.setdefault(environment.strip().lower())
    if not out:
        raise ConfigurationError('"production_environments" must name at least one environment.')
    return tuple(out)


def hosts(raw: Mapping[Any, Any]) -> HostTables:
    """The ``hosts`` map to its five per-host tables: keys, key file URLs, base URLs, engine lists, previous keys."""
    keys: dict[str, str] = {}
    locations: dict[str, str] = {}
    base_urls: dict[str, str] = {}
    engines: dict[str, tuple[str, ...]] = {}
    previous: dict[str, str] = {}
    for host, entry in raw.items():
        if not isinstance(host, str) or host == "" or not _HOST_PATTERN.match(host):
            raise ConfigurationError(
                f'"hosts" must map bare host names (no scheme, port or path) to keys, got "{host}".'
            )
        host = host.lower()
        key = entry.get("key", "") if isinstance(entry, Mapping) else entry
        if not isinstance(key, str):
            raise ConfigurationError(f'"hosts.{host}" must be a key string or {{key, key_location}}.')
        KeyValidator.assert_valid(key)
        keys[host] = key
        location = _host_url(entry, "key_location", host, True)
        if location is not None:
            locations[host] = location
        base_url = _host_url(entry, "base_url", host, False)
        if base_url is not None:
            base_urls[host] = base_url
        host_engines = entry.get("engines") if isinstance(entry, Mapping) else None
        if host_engines is not None:
            items = string_list(host_engines)
            if not items:
                raise ConfigurationError(f'"hosts.{host}.engines" must list at least one engine.')
            engines[host] = items
        previous_key = entry.get("previous_key") if isinstance(entry, Mapping) else None
        if previous_key is not None:
            if not isinstance(previous_key, str):
                raise ConfigurationError(f'"hosts.{host}.previous_key" must be a key string.')
            KeyValidator.assert_valid(previous_key)
            previous[host] = previous_key
    return keys, locations, base_urls, engines, previous


def _host_url(entry: Any, option: str, host: str, key_file: bool) -> str | None:
    """A URL entry of a host (``key_location``, ``base_url``): absolute, http(s), on that very host."""
    url = entry.get(option) if isinstance(entry, Mapping) else None
    if url is None:
        return None
    valid = isinstance(url, str) and (is_key_file_url(url) if key_file else is_absolute_http_url(url))
    if not valid:
        raise ConfigurationError(f'"hosts.{host}.{option}" must be an absolute http(s) URL.')
    if host_of(url) != host:
        raise ConfigurationError(f'"hosts.{host}.{option}" must be on host {host}, got {host_of(url)}.')
    return str(url)


def string_list(value: Any) -> tuple[str, ...]:
    """A list of trimmed, non-empty strings from a list/tuple or a comma-separated string; empty when neither."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip() != "")


def is_absolute_http_url(url: str) -> bool:
    """Absolute http(s) URL with a host and without userinfo."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if not parts.scheme or not parts.hostname:
        return False
    return parts.scheme.lower() in ("http", "https") and "@" not in parts.netloc


def host_of(url: str) -> str:
    """Lower-cased host of a URL (IPv6 literals keep their brackets), empty when there is none."""
    try:
        netloc = urlsplit(url).netloc
    except ValueError:
        return ""
    host = netloc.rsplit("@", 1)[-1]
    if host.startswith("["):
        end = host.find("]")
        return host[: end + 1].lower() if end >= 0 else host.lower()
    return host.split(":", 1)[0].lower()


def is_key_file_url(url: str) -> bool:
    """An absolute http(s) URL with a path other than "/": where a key file can live."""
    if not is_absolute_http_url(url):
        return False
    path = urlsplit(url).path
    return path not in ("", "/")


def describe(value: Any) -> str:
    """A value for an error message: quoted when scalar, its type otherwise."""
    if isinstance(value, (str, int, float, bool)):
        return f'"{value}"'
    return type(value).__name__


def _is_engine(name: str) -> bool:
    try:
        Engine(name.lower())
    except ValueError:
        return False
    return True
