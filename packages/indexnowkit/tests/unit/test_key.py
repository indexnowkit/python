from __future__ import annotations

import re

import pytest

from indexnowkit.config import Config
from indexnowkit.exceptions import ConfigurationError, InvalidArgumentError
from indexnowkit.key import KeyFileResponder, KeyValidator, StaticKeyProvider, generate_key, key_file_headers

KEY = "abcdef1234567890abcdef1234567890"
KEY2 = "fedcba0987654321fedcba0987654321"
OLD = "0123456789abcdef0123456789abcdef"


def test_validator() -> None:
    assert KeyValidator.is_valid("a" * 8) and KeyValidator.is_valid("A-1" * 42 + "aa")
    assert not KeyValidator.is_valid("a" * 7) and not KeyValidator.is_valid("a" * 129)
    assert not KeyValidator.is_valid("abc def!")
    assert KeyValidator.mask(KEY) == "abcd********"
    assert KeyValidator.mask("abc") == "***" and KeyValidator.mask("abcdef") == "abcd**"
    with pytest.raises(ConfigurationError, match='IndexNow key "abcd\\*\\*" is invalid: 8-128 characters'):
        KeyValidator.assert_valid("abcdef")


def test_c21_generate_key() -> None:
    a, b = generate_key(), generate_key()
    assert re.fullmatch(r"[a-f0-9]{32}", a) and a != b
    assert len(generate_key(64)) == 64 and len(generate_key(9)) == 9
    assert re.fullmatch(r"[A-Za-z0-9]{40}", generate_key(40, hex=False))
    with pytest.raises(InvalidArgumentError, match="between 8 and 128"):
        generate_key(7)


def test_static_provider_default_key_and_map() -> None:
    keys = StaticKeyProvider(KEY, {"Blog.example.com": KEY2}, "https://www.example.com/k.txt", "www.example.com")
    assert keys.key_for("WWW.example.com") == KEY and keys.key_for("other.example") == KEY
    assert keys.key_for("blog.example.com") == KEY2
    assert keys.key_location_for("www.example.com") == "https://www.example.com/k.txt"
    assert keys.key_location_for("blog.example.com") is None
    assert keys.is_known_key(KEY) and keys.is_known_key(KEY2) and not keys.is_known_key(OLD)
    assert keys.is_known_key(KEY2, "blog.example.com") and not keys.is_known_key(KEY, "blog.example.com")
    assert keys.managed_hosts() == ["blog.example.com", "www.example.com"]


def test_static_provider_strict_hosts_and_previous_keys() -> None:
    keys = StaticKeyProvider(
        KEY, {"blog.example.com": KEY2}, None, "www.example.com", strict_hosts=True, previous_key=OLD,
        previous_keys={"blog.example.com": "1111111111111111"},
    )  # fmt: skip
    assert keys.key_for("other.example") is None and keys.key_for("www.example.com") == KEY
    assert keys.previous_key_for("www.example.com") == OLD and keys.previous_key_for("other.example") is None
    assert keys.previous_key_for("blog.example.com") == "1111111111111111"
    assert keys.is_known_key(OLD, "www.example.com") and not keys.is_known_key(OLD, "blog.example.com")
    assert keys.is_known_key("1111111111111111")


def test_provider_from_config() -> None:
    config = Config(key=KEY, base_url="https://www.example.com", previous_key=OLD, hosts={"blog.example.com": KEY2})
    keys = StaticKeyProvider.from_config(config)
    assert keys.key_for("www.example.com") == KEY and keys.key_for("blog.example.com") == KEY2
    assert keys.previous_key_for("www.example.com") == OLD
    assert keys.managed_hosts() == ["blog.example.com", "www.example.com"]


def test_key_file_responder_h01_h02_h03() -> None:
    keys = StaticKeyProvider(KEY, {"blog.example.com": KEY2}, default_host="www.example.com")
    responder = KeyFileResponder(keys)
    assert responder.body_for_path(f"/{KEY}.txt") == KEY
    assert responder.body_for_path(f"/{KEY}.txt", "www.example.com") == KEY
    assert responder.body_for_path(f"/{KEY}.txt", "blog.example.com") is None
    assert responder.body_for_path("/other.txt") is None
    assert responder.body_for_path(f"/{KEY}.txt/") is None
    assert responder.body_for_path("/robots.txt") is None
    assert responder.body_for_key(KEY2, "blog.example.com") == KEY2
    assert KeyFileResponder(keys, enabled=False).body_for_path(f"/{KEY}.txt") is None
    config = Config(key=KEY, key_file_enabled=False)
    assert KeyFileResponder.from_config(config, keys).body_for_key(KEY) is None


def test_key_file_headers() -> None:
    assert key_file_headers() == {"Content-Type": "text/plain; charset=utf-8", "Cache-Control": "public, max-age=300"}
    assert key_file_headers(-5, True) == {
        "Content-Type": "text/plain; charset=utf-8",
        "Cache-Control": "public, max-age=0",
        "Vary": "Host",
    }
    assert KeyFileResponder.headers(10) == key_file_headers(10)
