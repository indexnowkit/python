"""pytest fixtures of the testing extra: ``pytest_plugins = ["indexnowkit.testing.pytest"]`` in a ``conftest.py``
gives ``mock_indexnow`` (a running :class:`~indexnowkit.testing.mock_server.MockIndexNowServer` with a 2-second
``timeout`` scenario, no keys) and ``fake_transport``."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from indexnowkit.testing import FakeTransport
from indexnowkit.testing.mock_server import MockIndexNowServer

__all__ = ["fake_transport", "mock_indexnow"]


@pytest.fixture
def mock_indexnow() -> Iterator[MockIndexNowServer]:
    with MockIndexNowServer(timeout_delay=2.0) as server:
        yield server


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()
