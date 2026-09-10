"""The two readers of ``Config``: the canonical nested mapping of framework settings (:func:`from_mapping`, the body of
``Config.from_mapping()``) and the ``INDEXNOW_*`` environment variables (:func:`mapping_from_env`, the body of
``Config.mapping_from_env()``), with the scalar parsers the keys share (``"3"``, ``"true"``, ``"1.5"`` and ``""`` for
"not set"). Reading only: the values go to the constructor of ``Config``, which checks the invariants.

Internal: part of ``Config``, not of the compatibility promise (docs/bc.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from indexnowkit.config._normalizer import describe, string_list
from indexnowkit.exceptions import ConfigurationError

if TYPE_CHECKING:
    from indexnowkit.config import Config

#: The eight boolean literals (spec 20 §3.2, audit 0.13 W1): parsed, never cast.
TRUE_LITERALS = frozenset({"true", "1", "yes", "on"})
FALSE_LITERALS = frozenset({"false", "0", "no", "off"})
#: Options whose environment variable is a comma-separated list.
LIST_OPTIONS = frozenset({"engines", "production_environments", "normalizer.tracking_params"})
#: Options whose environment variable is ``name=value,name2=value2``.
PAIR_OPTIONS = frozenset({"hosts", "engine_aliases", "locale_hosts", "logging.levels"})


def mapping(value: Any) -> dict[str, Any]:
    """A mapping value as a dict with string keys, else an empty dict."""
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def flag(value: Any, default: bool, option: str) -> bool:
    """:func:`boolean` with a non-None default."""
    parsed = boolean(value, default, option)
    return default if parsed is None else parsed


def from_mapping(data: Mapping[str, Any]) -> Config:
    """The nested mapping shape to a ``Config``; strings are coerced, the non-production dry-run safety net applied."""
    from indexnowkit.config import PRODUCTION_ENVIRONMENTS, Config

    batch, debounce, throttle = sub(data, "batch"), sub(data, "debounce"), sub(data, "throttle")
    http = sub(data, "http")
    logging, retry, resolver = sub(data, "logging"), sub(data, "retry"), sub(data, "resolver")
    collector, key_file, normalizer = sub(data, "collector"), sub(data, "key_file"), sub(data, "normalizer")
    production = _list_or(data.get("production_environments"), PRODUCTION_ENVIRONMENTS)
    hosts = mapping(data.get("hosts"))
    engines = _list_or(data.get("engines"), ("api",))
    key = string(data.get("key"))
    dry_run_value = boolean(data.get("dry_run"), None, "dry_run")
    dry_run = dry_run_value if dry_run_value is not None else False
    environment = string(data.get("environment"))
    non_production = environment is not None and environment.lower() not in [p.lower() for p in production]
    if key is None and not hosts and non_production:
        dry_run = True
    return Config(
        enabled=flag(data.get("enabled"), True, "enabled"),
        key=key,
        hosts=hosts,
        key_location=string(data.get("key_location")),
        base_url=string(data.get("base_url")),
        engines=engines,
        dispatch=string(data.get("dispatch")) or "sync",
        strict_hosts=flag(data.get("strict_hosts"), False, "strict_hosts"),
        environment=environment,
        production_environments=production,
        dry_run=dry_run,
        dry_run_explicit=dry_run_value is not None,
        previous_key=string(data.get("previous_key")),
        max_url_length=integer(data.get("max_url_length"), Config.DEFAULT_MAX_URL_LENGTH, "max_url_length"),
        batch_max_urls=integer(batch.get("max_urls"), Config.DEFAULT_BATCH_MAX_URLS, "batch.max_urls"),
        debounce_per_url=integer(debounce.get("per_url"), Config.DEFAULT_DEBOUNCE_PER_URL, "debounce.per_url"),
        debounce_store=string(debounce.get("store")),
        debounce_key_prefix=string(debounce.get("key_prefix")) or Config.DEFAULT_DEBOUNCE_KEY_PREFIX,
        throttle_max_requests_per_minute=integer(
            throttle.get("max_requests_per_minute"),
            Config.DEFAULT_THROTTLE_PER_MINUTE,
            "throttle.max_requests_per_minute",
        ),
        http_timeout=number(http.get("timeout"), Config.DEFAULT_HTTP_TIMEOUT, "http.timeout"),
        http_user_agent=string(http.get("user_agent")),
        http_client=string(http.get("client")),
        key_file_enabled=flag(key_file.get("enabled"), True, "key_file.enabled"),
        key_file_cache_max_age=integer(
            key_file.get("cache_max_age"), Config.DEFAULT_KEY_FILE_MAX_AGE, "key_file.cache_max_age"
        ),
        logging_max_urls=integer(logging.get("max_urls"), Config.DEFAULT_LOG_URLS, "logging.max_urls"),
        logging_forbidden_escalation=integer(
            logging.get("forbidden_escalation"), Config.DEFAULT_FORBIDDEN_ESCALATION, "logging.forbidden_escalation"
        ),
        logging_levels=mapping(logging.get("levels")),
        logging_max_body=integer(logging.get("max_body"), Config.DEFAULT_LOG_BODY, "logging.max_body"),
        retry_max_attempts=integer(retry.get("max_attempts"), Config.DEFAULT_RETRY_MAX_ATTEMPTS, "retry.max_attempts"),
        retry_base_delay=integer(retry.get("base_delay"), Config.DEFAULT_RETRY_BASE_DELAY, "retry.base_delay"),
        retry_multiplier=number(retry.get("multiplier"), Config.DEFAULT_RETRY_MULTIPLIER, "retry.multiplier"),
        retry_max_delay=integer(retry.get("max_delay"), Config.DEFAULT_RETRY_MAX_DELAY, "retry.max_delay"),
        retry_server_error_delay=integer(
            retry.get("server_error_delay"), Config.DEFAULT_RETRY_SERVER_ERROR_DELAY, "retry.server_error_delay"
        ),
        resolver_max_via_depth=integer(
            resolver.get("max_via_depth"), Config.DEFAULT_RESOLVER_MAX_VIA_DEPTH, "resolver.max_via_depth"
        ),
        resolver_max_via_fanout=integer(
            resolver.get("max_via_fanout"), Config.DEFAULT_RESOLVER_MAX_VIA_FANOUT, "resolver.max_via_fanout"
        ),
        collector_max_urls=integer(collector.get("max_urls"), 0, "collector.max_urls"),
        collector_detect_leaks=flag(collector.get("detect_leaks"), True, "collector.detect_leaks"),
        engine_aliases=mapping(data.get("engine_aliases")),
        locale_hosts=mapping(data.get("locale_hosts")),
        normalizer_strip_tracking_params=flag(
            normalizer.get("strip_tracking_params"), True, "normalizer.strip_tracking_params"
        ),
        normalizer_tracking_params=string_list(normalizer.get("tracking_params")),
        normalizer_trailing_slash=string(normalizer.get("trailing_slash")) or Config.DEFAULT_TRAILING_SLASH,
        normalizer_sort_query=flag(normalizer.get("sort_query"), False, "normalizer.sort_query"),
    )


def _list_or(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    """A list option: the default when unset (None or ""), else the items as given — an empty list stays empty so
    the constructor reports it."""
    return default if value is None or value == "" else string_list(value)


def mapping_from_env(env: Mapping[str, str], prefix: str, options: Iterable[str]) -> dict[str, Any]:
    """The ``INDEXNOW_*`` variables to the nested mapping of :func:`from_mapping`, only the variables that are set:
    an unset (or empty) variable leaves no key. Every dotted option ``a.b`` is the variable ``<prefix>A_B``; lists
    are comma-separated, maps are ``name=value,name2=value2``; ``environment`` also reads ``<prefix>ENV`` and
    ``APP_ENV``. Values stay strings; :func:`from_mapping` coerces them."""
    out: dict[str, Any] = {}
    for option in options:
        raw = env.get(prefix + option.upper().replace(".", "_"))
        if option == "environment" and (raw is None or raw == ""):
            raw = env.get(prefix + "ENV") or env.get("APP_ENV")
        if raw is None or raw == "":
            continue
        value: Any = raw
        if option in LIST_OPTIONS:
            value = list(string_list(raw))
        elif option in PAIR_OPTIONS:
            value = pairs(raw, prefix + option.upper().replace(".", "_"))
        set_path(out, option, value)
    return out


def pairs(spec: str, variable: str) -> dict[str, str]:
    """``host=key,host2=key2`` (``INDEXNOW_HOSTS``, the alias and locale maps, the log levels)."""
    out: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if pair == "":
            continue
        if "=" not in pair:
            raise ConfigurationError(f'{variable} entries must look like "name=value", got "{pair}".')
        name, value = pair.split("=", 1)
        out[name.strip()] = value.strip()
    return out


def set_path(target: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value


def sub(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    """A nested block of the mapping, or an empty one when the key is missing or not a mapping."""
    value = data.get(name)
    return value if isinstance(value, Mapping) else {}


def string(value: Any) -> str | None:
    """A non-empty string, else None ("" is "not set")."""
    return value if isinstance(value, str) and value != "" else None


def boolean(value: Any, default: bool | None, option: str) -> bool | None:
    """``true/1/yes/on`` and ``false/0/no/off`` (case-insensitive), a real bool, or the default for None and "".

    :raises ConfigurationError: for anything else — a boolean is parsed, never cast
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        literal = value.strip().lower()
        if literal in TRUE_LITERALS:
            return True
        if literal in FALSE_LITERALS:
            return False
    raise ConfigurationError(f'"{option}" must be a boolean (true/false, 1/0, yes/no, on/off), got {describe(value)}.')


def integer(value: Any, default: int, option: str) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ConfigurationError(f'"{option}" must be an integer, got {describe(value)}.')
    if isinstance(value, str):
        text = value.strip()
        digits = text[1:] if text[:1] in "+-" else text
        if not digits.isdigit():
            raise ConfigurationError(f'"{option}" must be an integer, got "{value}".')
        return int(text)
    return value


def number(value: Any, default: float, option: str) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigurationError(f'"{option}" must be a number, got {describe(value)}.')
    try:
        return float(value)
    except ValueError as error:
        raise ConfigurationError(f'"{option}" must be a number, got "{value}".') from error
