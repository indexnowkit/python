"""Canonical form on top of another normalizer: the inner one makes the URL absolute and well-formed, this one removes
what an engine should not be told about (tracking parameters that external traffic sources append and routing never
generates), fixes the trailing slash when the site has a policy, and optionally sorts the query so the same page is one
URL for the debounce store and the engines. Applied by ``Submitter`` before de-duplication and debounce.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import unquote, unquote_plus, urlsplit

from indexnowkit.url._normalizer import UrlNormalizerProtocol

__all__ = ["TRACKING_PARAMS", "TRAILING_SLASH_MODES", "CanonicalUrlNormalizer"]

#: Query parameters removed by ``normalizer.strip_tracking_params`` (a growing list, like an enum: entries are added in
#: minor versions, never removed; ``normalizer.tracking_params`` adds yours). ``utm_*`` is a prefix.
TRACKING_PARAMS: tuple[str, ...] = (
    "utm_*",
    "gclid",
    "dclid",
    "wbraid",
    "gbraid",
    "fbclid",
    "msclkid",
    "yclid",
    "ysclid",
    "_openstat",
    "etext",
    "ttclid",
    "twclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "mkt_tok",
    "_hsenc",
    "_hsmi",
    "_ga",
)

TRAILING_SLASH_KEEP = "keep"
TRAILING_SLASH_ADD = "add"
TRAILING_SLASH_STRIP = "strip"
TRAILING_SLASH_MODES: tuple[str, ...] = (TRAILING_SLASH_KEEP, TRAILING_SLASH_ADD, TRAILING_SLASH_STRIP)


class CanonicalUrlNormalizer:
    """:class:`UrlNormalizerProtocol` over an inner normalizer, driven by the ``normalizer.*`` options."""

    __slots__ = ("_exact", "_inner", "_prefixes", "_sort_query", "_strip", "_trailing_slash")

    def __init__(
        self,
        inner: UrlNormalizerProtocol,
        strip_tracking_params: bool = True,
        tracking_params: Iterable[str] = (),
        trailing_slash: str = TRAILING_SLASH_KEEP,
        sort_query: bool = False,
    ) -> None:
        """:param strip_tracking_params: remove :data:`TRACKING_PARAMS` and ``tracking_params`` from the query
        :param tracking_params: more names to remove (``name`` or ``prefix*``), case-insensitive
        :param trailing_slash: ``keep`` (default), ``add`` (a path without an extension ends with ``/``) or ``strip``
            (no trailing ``/`` except the root)
        :param sort_query: order the query parameters by name (stable)
        """
        self._inner = inner
        self._strip = strip_tracking_params
        self._trailing_slash = trailing_slash
        self._sort_query = sort_query
        exact: dict[str, None] = {}
        prefixes: dict[str, None] = {}
        for raw in (*TRACKING_PARAMS, *tracking_params):
            name = raw.strip().lower()
            if name in ("", "*"):
                continue
            if name.endswith("*"):
                prefixes.setdefault(name[:-1])
            else:
                exact.setdefault(name)
        self._exact = frozenset(exact)
        self._prefixes = tuple(prefixes)

    def normalize(self, url: str) -> str:
        url = self._inner.normalize(url)
        if not self._strip and not self._sort_query and self._trailing_slash == TRAILING_SLASH_KEEP:
            return url
        parts = urlsplit(url)
        if not parts.scheme or not parts.netloc:
            return url  # the inner normalizer guarantees a parseable absolute URL; nothing to canonicalize otherwise
        path = self._path(parts.path or "/")
        had_query = "?" in url
        query = self._query(parts.query if had_query else None)
        return f"{parts.scheme}://{parts.netloc}{path}" + ("" if query is None else f"?{query}")

    def host_of(self, normalized_url: str) -> str:
        return self._inner.host_of(normalized_url)

    def is_tracking_param(self, name: str) -> bool:
        """Whether a query parameter name is one of the tracking parameters."""
        name = unquote_plus(name).lower()  # form encoding: ``+`` is a space
        if name in self._exact:
            return True
        return any(name.startswith(prefix) for prefix in self._prefixes)

    def _path(self, path: str) -> str:
        if self._trailing_slash == TRAILING_SLASH_STRIP:
            stripped = path.rstrip("/")
            return stripped or "/"
        if self._trailing_slash == TRAILING_SLASH_ADD and not path.endswith("/"):
            last = path.rsplit("/", 1)[-1]
            if "." not in last:
                return path + "/"
        return path

    def _query(self, query: str | None) -> str | None:
        """The query with the tracking parameters removed and, when asked, sorted; None when nothing is left."""
        if query is None:
            return None
        if query == "":
            return None if self._strip else ""
        pairs: list[tuple[str, str]] = []
        for pair in query.split("&"):
            if pair == "":
                continue
            name = pair.split("=", 1)[0]
            if self._strip and self.is_tracking_param(name):
                continue
            pairs.append((unquote(name).lower(), pair))
        if not pairs:
            return None
        if self._sort_query:
            pairs.sort(key=lambda item: item[0])  # stable: equal names keep their order
        return "&".join(pair for _, pair in pairs)
