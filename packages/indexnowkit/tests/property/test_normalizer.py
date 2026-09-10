"""Property tests of the normalizer (spec 26 §9.9): idempotence, punycode round-trip, tracking parameters, the
length bound. Hypothesis generates the URLs; every accepted URL must be a fixed point of ``normalize``."""

from __future__ import annotations

from urllib.parse import urlsplit

from hypothesis import given, settings
from hypothesis import strategies as st

from indexnowkit.exceptions import InvalidUrlError
from indexnowkit.url import CanonicalUrlNormalizer, UrlNormalizer, host_of

BASE = "https://www.example.com"
label = st.from_regex(r"[a-z0-9]([a-z0-9-]{0,10}[a-z0-9])?", fullmatch=True)
idn_label = st.text(alphabet="абвгдежзийклмнопрстуфхцчшщъыьэюяäöüßéèçñ", min_size=1, max_size=8)
hosts = st.lists(label | idn_label, min_size=1, max_size=4).map(".".join)
path_alphabet = st.characters(whitelist_categories=("L", "N"), whitelist_characters="-._~%/:@!$&'()*+,;=")
query_alphabet = st.characters(whitelist_categories=("L", "N"), whitelist_characters="-._~%=&+")
path_chars = st.text(alphabet=path_alphabet, max_size=20)
query_chars = st.text(alphabet=query_alphabet, max_size=20)
schemes = st.sampled_from(["http", "https", "HTTP", "Https"])
ports = st.sampled_from(["", ":80", ":443", ":8080"])
fragments = st.sampled_from(["", "#top", "#a/b"])


@st.composite
def urls(draw: st.DrawFn) -> str:
    path = draw(path_chars)
    query = draw(query_chars)
    query_part = f"?{query}" if draw(st.booleans()) else ""
    return f"{draw(schemes)}://{draw(hosts)}{draw(ports)}/{path}{query_part}{draw(fragments)}"


def normalize_or_none(normalizer: UrlNormalizer | CanonicalUrlNormalizer, url: str) -> str | None:
    try:
        return normalizer.normalize(url)
    except InvalidUrlError:
        return None


@settings(max_examples=300)
@given(urls())
def test_normalize_is_idempotent(url: str) -> None:
    normalizer = UrlNormalizer(BASE)
    once = normalize_or_none(normalizer, url)
    if once is None:
        return
    assert normalizer.normalize(once) == once


@settings(max_examples=300)
@given(urls())
def test_canonical_form_is_idempotent_and_ascii_hosted(url: str) -> None:
    normalizer = CanonicalUrlNormalizer(UrlNormalizer(BASE), tracking_params=["ref", "mtm_*"], sort_query=True)
    once = normalize_or_none(normalizer, url)
    if once is None:
        return
    assert normalizer.normalize(once) == once
    assert host_of(once).isascii()
    assert "#" not in once
    assert urlsplit(once).scheme in ("http", "https")


@settings(max_examples=200)
@given(hosts)
def test_punycode_host_round_trips_through_the_idna_codec(host: str) -> None:
    normalizer = UrlNormalizer(BASE)
    once = normalize_or_none(normalizer, f"https://{host}/")
    if once is None:
        return
    ascii_host = host_of(once)
    assert ascii_host.isascii()
    decoded = ascii_host.encode("ascii").decode("idna")
    assert normalizer.normalize(f"https://{decoded}/") == once


@settings(max_examples=200)
@given(st.text(min_size=1, max_size=120))
def test_normalize_never_raises_anything_but_invalid_url(text: str) -> None:
    normalizer = CanonicalUrlNormalizer(UrlNormalizer(BASE))
    try:
        result = normalizer.normalize(text)
    except InvalidUrlError:
        return
    assert len(result.encode()) <= 2048


@settings(max_examples=200)
@given(urls())
def test_tracking_parameters_never_survive(url: str) -> None:
    normalizer = CanonicalUrlNormalizer(UrlNormalizer(BASE))
    once = normalize_or_none(normalizer, url + ("&" if "?" in url.split("#")[0] else "?") + "utm_source=x&gclid=1")
    if once is None:
        return
    for pair in urlsplit(once).query.split("&"):
        assert not normalizer.is_tracking_param(pair.split("=", 1)[0])
