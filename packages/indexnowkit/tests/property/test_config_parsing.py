"""Property tests of the configuration parser (spec 26 §9.9): ``from_mapping(to_mapping(c)) == c``,
``from_mapping(mapping_from_env(env)) == from_env(env)``, the boolean literals, ``INDEXNOW_HOSTS`` strings."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from indexnowkit.config import Config
from indexnowkit.config._parser import FALSE_LITERALS, TRUE_LITERALS, boolean
from indexnowkit.exceptions import ConfigurationError

keys = st.from_regex(r"[A-Za-z0-9-]{8,40}", fullmatch=True)
hosts = st.from_regex(r"[a-z0-9]{1,8}(\.[a-z0-9]{1,8}){0,3}", fullmatch=True)
engines = st.lists(st.sampled_from(["api", "yandex", "bing", "naver"]), min_size=1, max_size=3, unique=True)
prefixes = st.from_regex(r"[A-Za-z0-9_.-]{1,10}", fullmatch=True)
locales = st.from_regex(r"[a-z]{2}(-[A-Z]{2})?", fullmatch=True)


@st.composite
def configs(draw: st.DrawFn) -> Config:
    host_map = {host: draw(keys) for host in draw(st.lists(hosts, max_size=3, unique=True))}
    return Config(
        key=draw(keys),
        hosts=host_map,
        base_url=f"https://{draw(hosts)}",
        engines=tuple(draw(engines)),
        dry_run=draw(st.booleans()),
        strict_hosts=draw(st.booleans()),
        environment=draw(st.sampled_from([None, "prod", "dev"])),
        max_url_length=draw(st.integers(64, 4096)),
        batch_max_urls=draw(st.integers(1, 10_000)),
        debounce_per_url=draw(st.integers(0, 10_000)),
        debounce_key_prefix=draw(prefixes),
        http_timeout=draw(st.floats(0.5, 60, allow_nan=False)),
        logging_levels={"ok": draw(st.sampled_from(["debug", "info", "warning"]))},
        locale_hosts={draw(locales): draw(hosts)},
        normalizer_tracking_params=tuple(draw(st.lists(st.from_regex(r"[a-z_]{1,6}\*?", fullmatch=True), max_size=3))),
        normalizer_sort_query=draw(st.booleans()),
    )


@settings(max_examples=150)
@given(configs())
def test_to_mapping_round_trips(config: Config) -> None:
    assert Config.from_mapping(config.to_mapping()) == config


@settings(max_examples=150)
@given(
    st.dictionaries(
        st.sampled_from([f"INDEXNOW_{o.upper().replace('.', '_')}" for o in Config.OPTIONS if o not in ("hosts",)]),
        st.sampled_from(["", "true", "false", "1", "0", "yes", "no", "on", "off", "5", "2.5", "api", "sync", "x"]),
        max_size=8,
    ),
    st.lists(st.tuples(hosts, keys), max_size=3, unique_by=lambda pair: pair[0]),
)
def test_from_env_equals_from_mapping_of_mapping_from_env(
    env: dict[str, str], host_pairs: list[tuple[str, str]]
) -> None:
    env = {**env, "INDEXNOW_KEY": "abcdef1234567890abcdef1234567890"}
    if host_pairs:
        env["INDEXNOW_HOSTS"] = ",".join(f"{host}={key}" for host, key in host_pairs)
    try:
        direct = Config.from_env(env)
    except ConfigurationError as error:
        with_mapping = None
        try:
            with_mapping = Config.from_mapping(Config.mapping_from_env(env))
        except ConfigurationError as second:
            assert str(second) == str(error)
        assert with_mapping is None
        return
    assert Config.from_mapping(Config.mapping_from_env(env)) == direct
    assert set(direct.hosts) == {host for host, _ in host_pairs}


@settings(max_examples=100)
@given(st.text(max_size=8))
def test_boolean_literals_are_exhaustive(text: str) -> None:
    literal = text.strip().lower()
    if literal == "":
        assert boolean(text, None, "x") is None
    elif literal in TRUE_LITERALS:
        assert boolean(text, None, "x") is True
    elif literal in FALSE_LITERALS:
        assert boolean(text, None, "x") is False
    else:
        try:
            boolean(text, None, "x")
        except ConfigurationError:
            return
        raise AssertionError(f"{text!r} parsed as a boolean")
