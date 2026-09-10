from __future__ import annotations

import pytest

from indexnowkit.exceptions import InvalidUrlError
from indexnowkit.url import CanonicalUrlNormalizer, UrlNormalizer, encode_host, host_of

BASE = "https://www.example.com"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("https://www.example.com/a", "https://www.example.com/a"),
        ("HTTPS://WWW.Example.COM/A?b=C#frag", "https://www.example.com/A?b=C"),
        ("https://www.example.com:443/a", "https://www.example.com/a"),
        ("http://www.example.com:80/a", "http://www.example.com/a"),
        ("https://www.example.com:8443/a", "https://www.example.com:8443/a"),
        ("https://www.example.com", "https://www.example.com/"),
        ("https://www.example.com/a/./b/../c", "https://www.example.com/a/c"),
        ("https://www.example.com/a/b/..", "https://www.example.com/a/"),
        ("https://www.example.com/a b", "https://www.example.com/a%20b"),
        ("https://www.example.com/%7euser/%3a?x=%2F", "https://www.example.com/~user/%3A?x=%2F"),
        ("https://www.example.com/a?", "https://www.example.com/a?"),
        ("HTTPS://Сайт.рф/Путь?q=1#top", "https://xn--80aswg.xn--p1ai/Путь?q=1"),
        ("https://www.example.com./a", "https://www.example.com/a"),
        ("https://[::1]:8080/a", "https://[::1]:8080/a"),
        ("https://[::1]:443/a", "https://[::1]/a"),
        ("/relative", "https://www.example.com/relative"),
        ("relative", "https://www.example.com/relative"),
        ("//cdn.example.com/x", "https://cdn.example.com/x"),
        ("  https://www.example.com/trim  ", "https://www.example.com/trim"),
    ],
)
def test_normalize(given: str, expected: str) -> None:
    assert UrlNormalizer(BASE).normalize(given) == expected


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ("", "Empty URL."),
        ("ftp://www.example.com/a", "only http and https"),
        ("https://user:pw@www.example.com/a", "contains credentials"),
        ("https://www.example.com/a\x00b", "control characters"),
        ("https://", "Cannot parse URL"),
        ("https://exa mple.com/", "Invalid host name"),
        ("https://[zz]/", "Cannot parse URL|Invalid IPv6 host"),
        ("https://www.example.com:99999/", "Cannot parse URL"),
        ("https://-bad-.example.com/", "Invalid host name"),
    ],
)
def test_normalize_rejects(given: str, message: str) -> None:
    with pytest.raises(InvalidUrlError, match=message):
        UrlNormalizer(BASE).normalize(given)


def test_relative_without_base_url_is_invalid() -> None:
    with pytest.raises(InvalidUrlError, match="no base_url configured"):
        UrlNormalizer().normalize("/a")


def test_max_url_length_is_in_bytes() -> None:
    assert UrlNormalizer(BASE, 64).normalize("https://www.example.com/" + "a" * 40)
    with pytest.raises(InvalidUrlError, match="longer than 64 bytes"):
        UrlNormalizer(BASE, 64).normalize("https://www.example.com/" + "a" * 41)
    with pytest.raises(InvalidUrlError, match="longer than 64 bytes"):
        UrlNormalizer(BASE, 64).normalize("https://www.example.com/" + "я" * 21)


def test_host_of() -> None:
    assert host_of("https://WWW.Example.com:8443/a") == "www.example.com"
    assert host_of("https://[::1]/a") == "[::1]"
    with pytest.raises(InvalidUrlError, match="has no host"):
        host_of("/a")


def test_encode_host() -> None:
    assert encode_host("www.example.com") == "www.example.com"
    assert encode_host("сайт.рф") == "xn--80aswg.xn--p1ai"
    assert encode_host("Пример.www.example.com") == "xn--e1afmkfd.www.example.com"
    assert encode_host("bücher.example") == "xn--bcher-kva.example"
    with pytest.raises(InvalidUrlError, match="longer than 63"):
        encode_host("я" * 64 + ".example")


def test_canonical_strips_tracking_params_and_keeps_the_rest() -> None:
    normalizer = CanonicalUrlNormalizer(UrlNormalizer(BASE))
    assert normalizer.normalize("/a?utm_source=x&id=1&fbclid=y") == "https://www.example.com/a?id=1"
    assert normalizer.normalize("/a?utm_source=x") == "https://www.example.com/a"
    assert normalizer.normalize("/a?") == "https://www.example.com/a"
    assert normalizer.normalize("/a?UTM_Campaign=x&Utm%5Fterm=y&b=2") == "https://www.example.com/a?b=2"
    assert normalizer.is_tracking_param("gclid") and not normalizer.is_tracking_param("id")


def test_canonical_custom_params_prefixes_sorting_and_trailing_slash() -> None:
    normalizer = CanonicalUrlNormalizer(UrlNormalizer(BASE), tracking_params=["ref", "mtm_*"], sort_query=True)
    assert normalizer.normalize("/a?z=1&ref=x&mtm_cid=2&a=3&z=0") == "https://www.example.com/a?a=3&z=1&z=0"
    add = CanonicalUrlNormalizer(UrlNormalizer(BASE), trailing_slash="add")
    assert add.normalize("/a/b") == "https://www.example.com/a/b/"
    assert add.normalize("/a/b.html") == "https://www.example.com/a/b.html"
    strip = CanonicalUrlNormalizer(UrlNormalizer(BASE), trailing_slash="strip")
    assert strip.normalize("/a/b/") == "https://www.example.com/a/b"
    assert strip.normalize("/") == "https://www.example.com/"


def test_canonical_off_is_the_inner_normalizer() -> None:
    normalizer = CanonicalUrlNormalizer(UrlNormalizer(BASE), strip_tracking_params=False)
    assert normalizer.normalize("/a?utm_source=x&") == "https://www.example.com/a?utm_source=x&"
    assert normalizer.normalize("/a?") == "https://www.example.com/a?"
    assert normalizer.host_of("https://www.example.com/a") == "www.example.com"
