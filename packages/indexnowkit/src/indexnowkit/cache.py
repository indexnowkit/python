"""The cache surface the debounce store, the 403 counter and the robots cache share: ``get/set/add/delete`` as a
Django cache has them (``cache.get(key, default)``, ``cache.set(key, value, timeout)``), so ``settings.CACHES`` and
any object with those methods plug in; an ``incr``/``increment`` method, when present, counts atomically."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["CacheProtocol", "increment"]


@runtime_checkable
class CacheProtocol(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...

    def set(self, key: str, value: Any, timeout: float | None = None) -> None: ...

    def add(self, key: str, value: Any, timeout: float | None = None) -> bool: ...

    def delete(self, key: str) -> Any: ...


def increment(cache: Any, key: str, ttl: float) -> int:
    """One more on a counter that expires ``ttl`` seconds after its first hit: the cache's atomic ``incr`` /
    ``increment`` when it has one (a fresh counter is created with the TTL first), else get + set."""
    incr = getattr(cache, "incr", None) or getattr(cache, "increment", None)
    if incr is not None:
        if cache.add(key, 1, ttl):
            return 1
        try:
            return int(incr(key))
        except (ValueError, KeyError):  # the counter expired between add() and incr(): start over
            cache.set(key, 1, ttl)
            return 1
    current = cache.get(key, 0)
    count = (int(current) if isinstance(current, (int, str)) and str(current).isdigit() else 0) + 1
    cache.set(key, count, ttl)
    return count
