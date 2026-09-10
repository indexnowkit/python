"""URL normalization (spec 01: RFC 3986, punycode, no fragment) and the canonical form of ``normalizer.*``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from indexnowkit.url._canonical import (
    TRACKING_PARAMS,
    TRAILING_SLASH_ADD,
    TRAILING_SLASH_KEEP,
    TRAILING_SLASH_MODES,
    TRAILING_SLASH_STRIP,
    CanonicalUrlNormalizer,
)
from indexnowkit.url._normalizer import MAX_URL_LENGTH, UrlNormalizer, UrlNormalizerProtocol, host_of
from indexnowkit.url._punycode import MAX_HOST_LENGTH, MAX_LABEL_LENGTH, encode_host

if TYPE_CHECKING:
    from indexnowkit.config import Config

__all__ = [
    "MAX_HOST_LENGTH",
    "MAX_LABEL_LENGTH",
    "MAX_URL_LENGTH",
    "TRACKING_PARAMS",
    "TRAILING_SLASH_ADD",
    "TRAILING_SLASH_KEEP",
    "TRAILING_SLASH_MODES",
    "TRAILING_SLASH_STRIP",
    "CanonicalUrlNormalizer",
    "UrlNormalizer",
    "UrlNormalizerProtocol",
    "encode_host",
    "host_of",
    "normalizer_from_config",
]


def normalizer_from_config(config: Config) -> UrlNormalizerProtocol:
    """The normalizer of a configuration: :class:`UrlNormalizer` over ``base_url`` and ``max_url_length``, wrapped in
    :class:`CanonicalUrlNormalizer` when the ``normalizer.*`` options ask for anything (which they do by default:
    ``normalizer.strip_tracking_params`` is on). The one place the core and the adapters build it."""
    inner = UrlNormalizer(config.base_url, config.max_url_length)
    if (
        not config.normalizer_strip_tracking_params
        and not config.normalizer_sort_query
        and config.normalizer_trailing_slash == TRAILING_SLASH_KEEP
    ):
        return inner
    return CanonicalUrlNormalizer(
        inner,
        config.normalizer_strip_tracking_params,
        config.normalizer_tracking_params,
        config.normalizer_trailing_slash,
        config.normalizer_sort_query,
    )
