from __future__ import annotations

import logging
from typing import Any

import pytest

from indexnowkit.config import LOG_EVENTS, OPTIONS, Config
from indexnowkit.exceptions import ConfigurationError

KEY = "abcdef1234567890abcdef1234567890"
KEY2 = "fedcba0987654321fedcba0987654321"


def config(**overrides: Any) -> Config:
    return Config.from_mapping({"key": KEY, "base_url": "https://www.example.com", **overrides})


def test_options_are_the_keys_of_the_php_family() -> None:
    assert len(OPTIONS) == 42  # the 43 keys of Config::OPTIONS (PHP) without the deprecated serve_key_file
    assert "serve_key_file" not in OPTIONS
    assert len(set(OPTIONS)) == len(OPTIONS)
    assert Config.OPTIONS is OPTIONS


def test_defaults() -> None:
    c = config()
    assert c.enabled and not c.dry_run and c.dry_run_explicit is False
    assert c.engines == ("api",) and c.endpoints == ("https://api.indexnow.org/indexnow",)
    assert c.dispatch == "sync" and c.batch_max_urls == 10_000 and c.debounce_per_url == 600
    assert c.http_timeout == 10.0 and c.throttle_max_requests_per_minute == 60
    assert c.production_environments == ("prod", "production")
    assert c.base_host() == "www.example.com"
    assert c.user_agent().startswith("indexnowkit-python/")


def test_c15_short_key_fails_at_construction() -> None:
    with pytest.raises(ConfigurationError, match=r'IndexNow key "\*\*\*" is invalid'):
        config(key="abc")
    with pytest.raises(ConfigurationError, match=r'IndexNow key "abcd\*\*" is invalid'):
        Config(key="abcdef")


def test_key_or_hosts_required_when_enabled_and_not_dry_run() -> None:
    with pytest.raises(ConfigurationError, match=r'no "key" \(or "hosts" map\)'):
        Config()
    with pytest.raises(ConfigurationError, match='"debounce.store" must be'):
        Config(key=KEY, debounce_store="")
    with pytest.raises(ConfigurationError, match='"http.client" must be'):
        Config(key=KEY, http_client="")
    assert Config(dry_run=True).key is None
    assert Config(enabled=False).key is None
    assert Config(hosts={"www.example.com": KEY}).hosts == {"www.example.com": KEY}


def test_hosts_entries_are_unpacked_and_lower_cased() -> None:
    c = Config(
        key=None,
        hosts={
            "WWW.Example.com": {
                "key": KEY,
                "key_location": "https://www.example.com/k/x.txt",
                "base_url": "https://www.example.com",
                "engines": ["yandex", "api"],
                "previous_key": KEY2,
            },
            "blog.example.com": KEY2,
        },
    )
    assert c.hosts == {"www.example.com": KEY, "blog.example.com": KEY2}
    assert c.key_locations == {"www.example.com": "https://www.example.com/k/x.txt"}
    assert c.host_base_urls == {"www.example.com": "https://www.example.com"}
    assert c.host_engines == {"www.example.com": ("yandex", "api")}
    assert c.previous_keys == {"www.example.com": KEY2}
    assert c.endpoints_for("WWW.example.com") == ("https://yandex.com/indexnow", "https://api.indexnow.org/indexnow")
    assert c.endpoints_for("blog.example.com") == c.endpoints
    assert c.base_url_for("www.example.com") == "https://www.example.com"
    assert c.base_url_for("blog.example.com") is None
    assert c.to_mapping()["hosts"] == {
        "www.example.com": {
            "key": KEY,
            "key_location": "https://www.example.com/k/x.txt",
            "base_url": "https://www.example.com",
            "engines": ["yandex", "api"],
            "previous_key": KEY2,
        },
        "blog.example.com": KEY2,
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"hosts": {"https://x.example": KEY}}, '"hosts" must map bare host names'),
        ({"hosts": {"x.example": {"key": KEY, "base_url": "https://y.example"}}}, "must be on host x.example"),
        ({"hosts": {"x.example": {"key": KEY, "engines": []}}}, "must list at least one engine"),
        ({"base_url": "www.example.com"}, r'"base_url" must be an absolute http\(s\) URL'),
        ({"key_location": "https://www.example.com/"}, r'"key_location" must be an absolute http\(s\) URL to the key'),
        ({"key_location": "https://other.example/k.txt"}, 'must be on the host of "base_url"'),
        ({"batch": {"max_urls": 0}}, '"batch.max_urls" must be between 1 and 10000'),
        ({"batch": {"max_urls": 10001}}, '"batch.max_urls" must be between 1 and 10000'),
        ({"debounce": {"per_url": -1}}, '"debounce.per_url" must be >= 0'),
        ({"debounce": {"key_prefix": "a b"}}, '"debounce.key_prefix" must be a non-empty string'),
        ({"throttle": {"max_requests_per_minute": -1}}, '"throttle.max_requests_per_minute" must be >= 0'),
        ({"http": {"timeout": 0}}, '"http.timeout" must be > 0'),
        ({"http": {"user_agent": "a\nb"}}, '"http.user_agent" must not contain line breaks'),
        ({"engines": ["google"]}, 'Unknown IndexNow engine "google"'),
        ({"dispatch": "a b"}, '"dispatch" must be a short identifier'),
        ({"strict_hosts": True, "base_url": None}, '"strict_hosts" needs at least one known host'),
        ({"max_url_length": 10}, '"max_url_length" must be >= 64'),
        ({"logging": {"max_urls": -1}}, '"logging.max_urls" must be >= 0'),
        ({"logging": {"forbidden_escalation": 0}}, '"logging.forbidden_escalation" must be >= 1'),
        ({"logging": {"max_body": -1}}, '"logging.max_body" must be >= 0'),
        ({"logging": {"levels": {"nope": "info"}}}, 'unknown event "nope"'),
        ({"logging": {"levels": {"ok": "loud"}}}, '"logging.levels.ok" must be a log level'),
        ({"retry": {"max_attempts": 0}}, '"retry.max_attempts" must be >= 1'),
        ({"retry": {"multiplier": 0.5}}, '"retry.multiplier" must be >= 1.0'),
        ({"retry": {"max_delay": -1}}, '"retry.max_delay" must be >= 0'),
        ({"resolver": {"max_via_fanout": 0}}, '"resolver.max_via_fanout" must be >= 1'),
        ({"collector": {"max_urls": -5}}, '"collector.max_urls" must be >= 0'),
        ({"engine_aliases": {"api": "https://x.example/i"}}, '"engine_aliases" names must be identifiers'),
        ({"engine_aliases": {"corp": "ftp://x"}}, '"engine_aliases.corp" must be an endpoint URL'),
        ({"locale_hosts": {"de": "https://example.de"}}, '"locale_hosts" must map locales to bare host names'),
        ({"production_environments": []}, '"production_environments" must name at least one'),
        ({"normalizer": {"trailing_slash": "maybe"}}, '"normalizer.trailing_slash" must be one of keep, add, strip'),
        ({"normalizer": {"tracking_params": ["a b"]}}, '"normalizer.tracking_params" must list query parameter names'),
        ({"key_file": {"cache_max_age": -1}}, '"key_file.cache_max_age" must be >= 0'),
        ({"previous_key": "short"}, "is invalid"),
    ],
)
def test_invariants(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        config(**overrides)


@pytest.mark.parametrize("literal", ["true", "TRUE", "1", "yes", "on", " On "])
def test_true_literals(literal: str) -> None:
    assert config(dry_run=literal).dry_run is True


@pytest.mark.parametrize("literal", ["false", "False", "0", "no", "off", "OFF"])
def test_false_literals_are_false_not_truthy(literal: str) -> None:
    c = config(dry_run=literal)
    assert c.dry_run is False and c.dry_run_explicit is True


def test_other_strings_are_not_booleans() -> None:
    with pytest.raises(ConfigurationError, match='"dry_run" must be a boolean'):
        config(dry_run="maybe")
    with pytest.raises(ConfigurationError, match='"enabled" must be a boolean'):
        config(enabled=2)


def test_empty_string_means_not_set() -> None:
    c = config(dry_run="", batch={"max_urls": ""}, http={"timeout": ""}, engines="")
    assert c.dry_run is False and c.dry_run_explicit is False
    assert c.batch_max_urls == 10_000 and c.http_timeout == 10.0 and c.engines == ("api",)


def test_numbers_are_coerced_from_strings() -> None:
    c = config(batch={"max_urls": "+500"}, http={"timeout": "2.5"}, retry={"multiplier": "3"})
    assert c.batch_max_urls == 500 and c.http_timeout == 2.5 and c.retry_multiplier == 3.0
    with pytest.raises(ConfigurationError, match='"batch.max_urls" must be an integer, got "1.5"'):
        config(batch={"max_urls": "1.5"})
    with pytest.raises(ConfigurationError, match='"http.timeout" must be a number'):
        config(http={"timeout": "fast"})
    with pytest.raises(ConfigurationError, match='"batch.max_urls" must be an integer'):
        config(batch={"max_urls": True})


def test_dry_run_safety_net_outside_production() -> None:
    dev = Config.from_mapping({"environment": "dev"})
    assert dev.dry_run is True and dev.dry_run_explicit is False and dev.is_production() is False
    with pytest.raises(ConfigurationError, match='no "key"'):
        Config.from_mapping({"environment": "PROD"})
    with pytest.raises(ConfigurationError):
        Config.from_mapping({"environment": "dev", "production_environments": ["dev"]})
    assert config(environment="Production").is_production() is True


def test_engines_aliases_and_per_host_engines() -> None:
    c = config(engines=["yandex", "Bing", "corp", "yandex"], engine_aliases={"Corp": "https://index.corp.example/i"})
    assert c.endpoints == (
        "https://yandex.com/indexnow",
        "https://www.bing.com/indexnow",
        "https://index.corp.example/i",
    )
    assert c.engine_aliases == {"corp": "https://index.corp.example/i"}
    assert c.resolve_engine("CORP") == "https://index.corp.example/i"


def test_log_levels_and_events() -> None:
    c = config(logging={"levels": {"ok": "INFO", "debounced": "notice"}})
    assert c.log_level("ok") == "info" and c.logging_level("ok") == logging.INFO
    assert c.logging_level("debounced") == logging.INFO
    assert c.log_level("pending") == LOG_EVENTS["pending"]
    assert c.logging_level("unknown-event") == logging.INFO


def test_locale_hosts_and_key_file_headers() -> None:
    c = config(locale_hosts={"DE": "Example.DE"}, strict_hosts=True, key_file={"cache_max_age": 60})
    assert c.host_for_locale("de") == "example.de" and c.host_for_locale("fr") is None
    assert c.key_file_headers() == {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=60",
        "Vary": "Host",
    }
    assert "Vary" not in config().key_file_headers()


def test_idn_base_host_is_punycode() -> None:
    assert config(base_url="https://Сайт.рф").base_host() == "xn--80aswg.xn--p1ai"
    assert config(base_url="https://[::1]:8080").base_host() == "[::1]"


def test_replace() -> None:
    c = config(hosts={"blog.example.com": {"key": KEY2, "engines": ["bing"]}})
    d = c.replace(dry_run=True, engines=("yandex",))
    assert d.dry_run and d.dry_run_explicit and d.endpoints == ("https://yandex.com/indexnow",)
    assert d.host_engines == c.host_engines and d.key == c.key
    assert c.replace(logging_max_urls=3).dry_run_explicit is False
    with pytest.raises(ConfigurationError, match='Unknown Config option "dry_runn"'):
        c.replace(dry_runn=True)
    with pytest.raises(ConfigurationError, match='Unknown Config option "endpoints"'):
        c.replace(endpoints=())


def test_to_mapping_round_trips() -> None:
    c = config(
        hosts={"blog.example.com": {"key": KEY2, "previous_key": KEY}},
        engines=["yandex", "corp"],
        engine_aliases={"corp": "https://index.corp.example/i"},
        logging={"levels": {"ok": "info"}},
        normalizer={"tracking_params": ["ref"], "sort_query": True},
        dry_run="false",
    )
    data = c.to_mapping()
    assert set(data) | {f"{b}.{k}" for b, v in data.items() if isinstance(v, dict) and b != "hosts" for k in v} >= set(
        o for o in OPTIONS if "." not in o or o.split(".")[0] in data
    )
    assert Config.from_mapping(data) == c


def test_unknown_options_walk_nested_blocks() -> None:
    data = {
        "key": KEY,
        "debounce": {"per_urls": 1, "per_url": 2},
        "hosts": {"x": "y"},
        "messenger": {"transport": "async"},
        "history": {"sqlite": {"path": "/tmp/x", "mode": 1}, "store": "sqlite"},
        "typo": 1,
    }
    assert Config.unknown_options(data, allowed=["messenger", "history.store", "history.sqlite.path"]) == [
        "debounce.per_urls",
        "history.sqlite.mode",
        "typo",
    ]
    assert Config.unknown_options({"logging": {"levels": {"ok": "info"}}}) == []


def test_from_env_reads_every_option_by_its_path_and_only_what_is_set() -> None:
    env = {
        "INDEXNOW_KEY": KEY,
        "INDEXNOW_BASE_URL": "https://www.example.com",
        "INDEXNOW_ENGINES": "yandex, bing",
        "INDEXNOW_HOSTS": "blog.example.com=" + KEY2 + ", shop.example.com = " + KEY,
        "INDEXNOW_DEBOUNCE_PER_URL": "30",
        "INDEXNOW_DRY_RUN": "false",
        "INDEXNOW_LOGGING_MAX_URLS": "",
        "INDEXNOW_LOGGING_LEVELS": "ok=info",
        "INDEXNOW_LOCALE_HOSTS": "de=example.de",
        "INDEXNOW_NORMALIZER_TRACKING_PARAMS": "ref,mtm_*",
        "INDEXNOW_THROTTLE_MAX_REQUESTS_PER_MINUTE": "5",
        "APP_ENV": "prod",
        "UNRELATED": "x",
    }
    mapping = Config.mapping_from_env(env)
    assert mapping == {
        "key": KEY,
        "base_url": "https://www.example.com",
        "engines": ["yandex", "bing"],
        "hosts": {"blog.example.com": KEY2, "shop.example.com": KEY},
        "debounce": {"per_url": "30"},
        "dry_run": "false",
        "logging": {"levels": {"ok": "info"}},
        "locale_hosts": {"de": "example.de"},
        "normalizer": {"tracking_params": ["ref", "mtm_*"]},
        "throttle": {"max_requests_per_minute": "5"},
        "environment": "prod",
    }
    c = Config.from_env(env)
    assert c == Config.from_mapping(mapping)
    assert c.debounce_per_url == 30 and c.dry_run is False and c.dry_run_explicit and c.is_production()
    assert Config.mapping_from_env({"INDEXNOW_ENV": "staging", "APP_ENV": "prod"})["environment"] == "staging"
    assert Config.mapping_from_env({"INDEXNOW_ENVIRONMENT": "test"})["environment"] == "test"
    with pytest.raises(ConfigurationError, match='INDEXNOW_HOSTS entries must look like "name=value"'):
        Config.mapping_from_env({"INDEXNOW_HOSTS": "nokey"})


def test_from_env_with_extra_options_reads_the_blocks_of_the_modules() -> None:
    env = {"INDEXNOW_KEY": KEY, "INDEXNOW_SITEMAP_MAX_DEPTH": "2", "INDEXNOW_HISTORY_STORE": "none"}
    mapping = Config.mapping_from_env(env, options=[*OPTIONS, "sitemap.max_depth", "history.store"])
    assert mapping["sitemap"] == {"max_depth": "2"} and mapping["history"] == {"store": "none"}
    assert "sitemap" not in Config.mapping_from_env(env)


def test_log_sample() -> None:
    assert config(logging={"max_urls": 2}).log_sample(["a", "b", "c"]) == ["a", "b"]
    assert config(logging={"max_urls": 0}).log_sample(["a"]) == []
