"""The factory of the core tests (the PHP ``tests/Support/Factory.php``): a configuration with a key, a base URL and no
debounce window, and a submitter over a :class:`FakeTransport`."""

from __future__ import annotations

import logging
from typing import Any

from indexnowkit.client import Client
from indexnowkit.config import Config
from indexnowkit.debounce import DebounceStore, MemoryDebounceStore
from indexnowkit.key import StaticKeyProvider
from indexnowkit.submitter import Submitter
from indexnowkit.testing import FakeTransport
from indexnowkit.throttle import NullThrottle, Throttle

KEY = "abcdef1234567890abcdef1234567890"
BASE_URL = "https://www.example.com"


def config(**overrides: Any) -> Config:
    return Config.from_mapping({"key": KEY, "base_url": BASE_URL, "debounce": {"per_url": 0}, **overrides})


def submitter(
    transport: FakeTransport,
    cfg: Config | None = None,
    logger: logging.Logger | None = None,
    debounce: DebounceStore | None = None,
    throttle: Throttle | None = None,
) -> Submitter:
    cfg = cfg or config()
    logger = logger or logging.getLogger("indexnowkit")
    keys = StaticKeyProvider.from_config(cfg)
    client = Client(transport, keys, cfg, logger, throttle or NullThrottle())
    return Submitter(client, cfg, debounce if debounce is not None else MemoryDebounceStore(), logger)
