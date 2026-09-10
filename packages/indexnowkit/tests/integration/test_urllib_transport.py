"""The ``urllib`` transport against the mock IndexNow server (spec 20 §5; the risks of §7.1 and the redirect/timeout
questions of the pre-flight): the scenarios of spec 03, no redirects, the timeout, the body limits, streaming."""

from __future__ import annotations

import gzip
import io
import json
import time

import pytest

from indexnowkit.exceptions import TransportError
from indexnowkit.http import LazyTransport, UrllibTransport
from indexnowkit.testing.mock_server import SCENARIOS, MockIndexNowServer

KEY = "abcdef1234567890abcdef1234567890"


def body(url: str = "https://www.example.com/a") -> str:
    return json.dumps({"host": "www.example.com", "key": KEY, "urlList": [url]})


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s != "timeout"])
def test_every_scenario_answers_its_status(mock_indexnow: MockIndexNowServer, scenario: str) -> None:
    transport = UrllibTransport(timeout=2, extra_headers={"X-Mock-Scenario": scenario})
    response = transport.post(mock_indexnow.endpoint, body(), {"User-Agent": "indexnowkit-test"})
    assert response.status == SCENARIOS[scenario]
    request = mock_indexnow.requests[-1]
    assert request["method"] == "POST" and request["json"]["key"] == KEY
    assert request["headers"]["User-Agent"] == "indexnowkit-test"
    assert request["headers"]["Content-Type"] == "application/json; charset=utf-8"


def test_then_ok_scenarios_and_retry_after(mock_indexnow: MockIndexNowServer) -> None:
    transport = UrllibTransport(timeout=2)
    first = transport.post(mock_indexnow.endpoint + "?scenario=ratelimit429-then-ok&n=1", body())
    second = transport.post(mock_indexnow.endpoint + "?scenario=ratelimit429-then-ok&n=1", body())
    assert (first.status, first.retry_after, second.status) == (429, 1, 200)
    assert transport.post(mock_indexnow.endpoint + "?scenario=ratelimit429", body()).retry_after == 2
    flaky = transport.post(mock_indexnow.endpoint + "?scenario=flaky500-then-ok", body())
    assert flaky.status == 503 and flaky.text == "oops"


def test_validation_precedes_the_scenario(mock_indexnow: MockIndexNowServer) -> None:
    transport = UrllibTransport(timeout=2)
    assert transport.post(mock_indexnow.endpoint, "{}").status == 400
    assert transport.post(mock_indexnow.endpoint, body("https://other.example/x")).status == 422
    too_many = json.dumps({"host": "www.example.com", "key": KEY, "urlList": ["https://www.example.com/"] * 10_001})
    assert transport.post(mock_indexnow.endpoint, too_many).status == 400
    assert transport.post(mock_indexnow.endpoint + "?scenario=nope", body()).status == 400


def test_c14_timeout_is_a_transport_error_within_the_timeout(mock_indexnow: MockIndexNowServer) -> None:
    transport = UrllibTransport(timeout=0.5, extra_headers={"X-Mock-Scenario": "timeout"})
    started = time.monotonic()
    with pytest.raises(TransportError, match="POST 127.0.0.1 failed"):
        transport.post(mock_indexnow.endpoint, body())
    assert time.monotonic() - started < 1.5


def test_connection_refused_is_a_transport_error() -> None:
    with pytest.raises(TransportError, match="failed"):
        UrllibTransport(timeout=1).get("http://127.0.0.1:9/x")


def test_key_file_and_404(mock_indexnow: MockIndexNowServer) -> None:
    mock_indexnow.keys = frozenset({KEY})
    transport = UrllibTransport(timeout=2)
    ok = transport.get(f"{mock_indexnow.url}/{KEY}.txt")
    assert ok.status == 200 and ok.text == KEY and ok.content_type() == "text/plain"
    assert transport.get(f"{mock_indexnow.url}/other.txt").status == 404
    assert transport.get(f"{mock_indexnow.url}/{KEY}.txt".replace(KEY, "f" * 32)).status == 404


def test_get_is_not_truncated_and_download_streams(mock_indexnow: MockIndexNowServer) -> None:
    transport = UrllibTransport(timeout=5)
    document = transport.get(f"{mock_indexnow.url}/large-document.xml")
    assert document.status == 200 and len(document.body) > 100_000 and document.body.endswith(b"</entries>")
    sink = io.BytesIO()
    streamed = transport.download(f"{mock_indexnow.url}/large-document.xml.gz", sink)
    assert streamed.status == 200 and streamed.body == b""
    assert gzip.decompress(sink.getvalue()) == document.body


def test_get_body_limit_rejects_post_limit_truncates(mock_indexnow: MockIndexNowServer) -> None:
    transport = UrllibTransport(timeout=5, get_body_limit=1000, post_body_limit=3)
    with pytest.raises(TransportError, match="larger than 1000 bytes"):
        transport.get(f"{mock_indexnow.url}/large-document.xml")
    with pytest.raises(TransportError, match="larger than 1000 bytes"):
        transport.download(f"{mock_indexnow.url}/large-document.xml", io.BytesIO())
    truncated = transport.post(mock_indexnow.endpoint + "?scenario=forbidden403", body())
    assert truncated.status == 403 and truncated.body == b"for"


def test_request_log_can_be_read_and_cleared_over_http(mock_indexnow: MockIndexNowServer) -> None:
    transport = UrllibTransport(timeout=2)
    transport.post(mock_indexnow.endpoint, body())
    listed = json.loads(transport.get(f"{mock_indexnow.url}/_mock/requests").text)
    assert len(listed) == 1 and listed[0]["scenario"] == "ok200"
    assert transport.get(f"{mock_indexnow.url}/no-such").status == 404


def test_lazy_transport_builds_once_and_buffers_downloads(mock_indexnow: MockIndexNowServer) -> None:
    built: list[int] = []

    class Plain:
        def post(self, url: str, json: str, headers: object = None) -> object:
            raise AssertionError

        def get(self, url: str) -> object:
            return UrllibTransport(timeout=2).get(url)

    def factory() -> Plain:
        built.append(1)
        return Plain()

    lazy = LazyTransport(factory)  # type: ignore[arg-type]
    sink = io.BytesIO()
    assert lazy.download(f"{mock_indexnow.url}/large-document.xml", sink).body == b""
    assert sink.getvalue().endswith(b"</entries>")
    lazy.get(f"{mock_indexnow.url}/large-document.xml")
    assert built == [1]
