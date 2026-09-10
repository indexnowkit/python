"""Logging helper: the texts of the family (``core/docs/operations.md`` of PHP) with ``{placeholders}`` interpolated
into the message and kept as structured fields under ``extra["indexnow"]`` for JSON loggers. Keys are masked by the
callers before they reach here."""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["log"]


class _Fields(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def log(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    """``logger.log(level, message.format(**fields), extra={"indexnow": fields})`` — with a placeholder that has no
    field left as it is, and an exception under ``exc`` attached as ``exc_info``."""
    if not logger.isEnabledFor(level):
        return
    exception = fields.pop("exc", None)
    text = message.format_map(_Fields(fields))
    logger.log(level, text, extra={"indexnow": fields}, exc_info=exception)
