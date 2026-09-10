"""The debounce store: remembers when a URL was last submitted so the same URL is not re-sent within
``debounce.per_url`` seconds. ``memory`` (per process, bounded), ``none``, a cache (Django cache or any object with
``get/set/add``) and the sqlite state file of the CLI."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from indexnowkit.cache import CacheProtocol
from indexnowkit.clock import Clock, SystemClock
from indexnowkit.exceptions import ConfigurationError

if TYPE_CHECKING:
    from indexnowkit.config import Config

__all__ = [
    "MEMORY",
    "NONE",
    "CacheDebounceStore",
    "DebounceStore",
    "MemoryDebounceStore",
    "NullDebounceStore",
    "is_shared",
    "store_from_config",
]

MEMORY = "memory"
NONE = "none"


@runtime_checkable
class DebounceStore(Protocol):
    """Implementations may raise (backend down): ``Submitter`` treats a failing :meth:`filter_recent` as "nothing is
    recent" (submits without de-duplication) and a failing :meth:`mark_submitted` as "window not recorded"; both are
    logged as warnings and never interrupt delivery."""

    def filter_recent(self, urls: Iterable[str], ttl_seconds: int) -> list[str]:
        """The subset of ``urls`` that were submitted less than ``ttl_seconds`` ago (a hint; stores that persist the
        expiry may ignore it)."""

    def mark_submitted(self, urls: Iterable[str], ttl_seconds: int) -> None: ...


class MemoryDebounceStore:
    """Per-process store, bounded to ``max_entries`` (expired entries are purged first, then the oldest). Right for
    CLI, tests and single long-running workers; web applications should share a cache so the window survives across
    requests and processes."""

    def __init__(self, clock: Clock | None = None, max_entries: int = 50_000) -> None:
        self._clock = clock or SystemClock()
        self._max_entries = max_entries
        self._entries: dict[str, float] = {}
        self._lock = threading.Lock()

    def filter_recent(self, urls: Iterable[str], ttl_seconds: int) -> list[str]:
        now = self._clock.now().timestamp()
        with self._lock:
            return [url for url in urls if self._entries.get(url, 0.0) > now]

    def mark_submitted(self, urls: Iterable[str], ttl_seconds: int) -> None:
        now = self._clock.now().timestamp()
        with self._lock:
            for url in urls:
                self._entries.pop(url, None)
                self._entries[url] = now + ttl_seconds
            if len(self._entries) > self._max_entries:
                self._entries = {url: exp for url, exp in self._entries.items() if exp > now}
                excess = len(self._entries) - self._max_entries
                if excess > 0:
                    self._entries = dict(list(self._entries.items())[excess:])

    def __len__(self) -> int:
        return len(self._entries)


class NullDebounceStore:
    """Disables debounce explicitly (every URL is sent every time). Equivalent to ``debounce.per_url = 0``."""

    __slots__ = ()

    def filter_recent(self, urls: Iterable[str], ttl_seconds: int) -> list[str]:
        return []

    def mark_submitted(self, urls: Iterable[str], ttl_seconds: int) -> None:
        return None


class CacheDebounceStore:
    """Debounce shared across processes through any cache with ``get/set`` (a Django cache, a redis-py-like object).
    Keys are ``{prefix}sha1(url)``, so they are valid for every backend regardless of URL characters. Best effort
    across processes: two workers submitting the same URL in the same instant can both pass; the engines
    de-duplicate, the window only saves requests."""

    def __init__(self, cache: CacheProtocol, prefix: str = "indexnowkit_") -> None:
        self._cache = cache
        self._prefix = prefix

    def filter_recent(self, urls: Iterable[str], ttl_seconds: int) -> list[str]:
        return [url for url in urls if self._cache.get(self._key(url)) is not None]

    def mark_submitted(self, urls: Iterable[str], ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        for url in urls:
            self._cache.set(self._key(url), 1, ttl_seconds)

    def _key(self, url: str) -> str:
        return self._prefix + hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()


def is_shared(store: str | None) -> bool:
    """Whether a ``debounce.store`` value names a store shared by every process — an id the adapter resolves to a
    cache — rather than ``memory``, ``none`` or nothing at all. Pass the adapter's default for None when the unset
    option means a store."""
    return store is not None and store not in (MEMORY, NONE)


def store_from_config(
    config: Config,
    cache_locator: Callable[[str], Any] | None = None,
    default: str = MEMORY,
    clock: Clock | None = None,
) -> DebounceStore:
    """The debounce store an adapter wires from ``debounce.store``: ``memory``, ``none``, or an id the adapter's
    locator resolves to a cache (wrapped in :class:`CacheDebounceStore` with ``debounce.key_prefix``) or to a ready
    :class:`DebounceStore`.

    :raises ConfigurationError: when the id needs a locator there is none, or resolves to neither a cache nor a store
    """
    store = config.debounce_store or default
    if store == MEMORY:
        return MemoryDebounceStore(clock)
    if store == NONE:
        return NullDebounceStore()
    if cache_locator is None:
        raise ConfigurationError(
            f'"debounce.store" "{store}" needs a cache locator: this adapter cannot resolve a store id, use "memory" '
            'or "none".'
        )
    resolved = cache_locator(store)
    if isinstance(resolved, DebounceStore):
        return resolved
    if not isinstance(resolved, CacheProtocol):
        raise ConfigurationError(
            f'"debounce.store" "{store}" resolves to {type(resolved).__name__}, which is not a cache (get/set/add/delete).'  # noqa: E501 — a text of the family, one to one with PHP
        )
    return CacheDebounceStore(resolved, config.debounce_key_prefix)
