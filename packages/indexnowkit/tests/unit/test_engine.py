from __future__ import annotations

import pytest

from indexnowkit.engine import Engine
from indexnowkit.exceptions import ConfigurationError


def test_every_engine_has_an_https_endpoint() -> None:
    assert len(Engine) == 8
    for engine in Engine:
        assert engine.endpoint.startswith("https://")
        assert engine.endpoint.endswith("/indexnow")
    assert Engine.API.endpoint == "https://api.indexnow.org/indexnow"
    assert Engine.YANDEX.endpoint == "https://yandex.com/indexnow"


@pytest.mark.parametrize(
    ("value", "endpoint"),
    [
        ("api", "https://api.indexnow.org/indexnow"),
        (" Bing ", "https://www.bing.com/indexnow"),
        ("https://index.corp.example/indexnow", "https://index.corp.example/indexnow"),
        ("HTTPS://Index.Corp.Example:8443/x?y=1", "https://index.corp.example:8443/x?y=1"),
        ("http://127.0.0.1:8089/indexnow", "http://127.0.0.1:8089/indexnow"),
        ("http://localhost/indexnow", "http://localhost/indexnow"),
        ("http://[::1]:8089/indexnow", "http://[::1]:8089/indexnow"),
    ],
)
def test_resolve_endpoint(value: str, endpoint: str) -> None:
    assert Engine.resolve_endpoint(value) == endpoint


def test_resolve_endpoint_rejects_plain_http_off_loopback() -> None:
    with pytest.raises(ConfigurationError, match="must use https"):
        Engine.resolve_endpoint("http://index.corp.example/indexnow")


def test_resolve_endpoint_rejects_credentials() -> None:
    with pytest.raises(ConfigurationError, match="must not contain credentials"):
        Engine.resolve_endpoint("https://user:pw@index.corp.example/indexnow")


def test_resolve_endpoint_rejects_unknown_names() -> None:
    with pytest.raises(ConfigurationError, match='Unknown IndexNow engine "google"'):
        Engine.resolve_endpoint("google")


def test_label_for() -> None:
    assert Engine.label_for("https://yandex.com/indexnow") == "yandex"
    assert Engine.label_for("https://index.corp.example/indexnow") == "index.corp.example"
    assert Engine.label_for("garbage") == "garbage"
