"""The exceptions of the library. Every one derives from :class:`IndexNowError`, so ``except IndexNowError`` catches
them all; the concrete ones also derive from the standard exception they replace (``ValueError``, ``RuntimeError``).

HTTP outcomes are never exceptions: the engine's answer is a :class:`~indexnowkit.result.Result`. Exceptions mark
programming errors (a bad configuration, an empty batch) and network failures (:class:`TransportError`); the
submission pipeline catches the latter and reports a failed result.
"""

from __future__ import annotations

__all__ = ["ConfigurationError", "IndexNowError", "InvalidArgumentError", "InvalidUrlError", "TransportError"]


class IndexNowError(Exception):
    """Marker base of every exception of this library."""


class InvalidArgumentError(IndexNowError, ValueError):
    """Programming error at a call site (empty batch, key length out of range). Never raised for remote failures."""


class ConfigurationError(InvalidArgumentError):
    """Invalid configuration, rule declaration or wiring. Raised when the invalid piece is used: at construction for
    ``Config`` and the rules, at resolution time for resolvers and locators. ORM hooks route resolution through
    ``GuardedUrlResolver`` / ``ObjectChangeHandler``, which log it instead of raising."""


class InvalidUrlError(InvalidArgumentError):
    """A URL that cannot be submitted. ``Submitter`` catches it and reports the URL as skipped
    (``Reason.INVALID_URL``)."""


class TransportError(IndexNowError, RuntimeError):
    """Network-level failure (connection, timeout, oversized body). Never raised for HTTP status codes."""
