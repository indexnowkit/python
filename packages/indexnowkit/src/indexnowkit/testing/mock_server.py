"""The mock IndexNow server of the family (spec 03), on ``http.server`` in the test process: ``/indexnow`` answers by
scenario (``X-Mock-Scenario`` header or ``?scenario=``), ``/_mock/requests`` returns the request log (DELETE clears),
``/<key>.txt`` answers 200 for the keys of the allow-list (``MOCK_KEYS`` or the constructor),
``/large-document.xml[.gz]`` is the >100 KB regression document. The same contract as the PHP ``router.php``; the
``timeout`` scenario sleeps ``timeout_delay`` seconds (30 in PHP; tests pass 2).

    with MockIndexNowServer(keys=["abc..."]) as server:
        config = Config(key=..., engines=[server.endpoint], base_url=server.url)
"""

from __future__ import annotations

import gzip
import json
import os
import threading
import time
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from indexnowkit.key import KeyValidator

__all__ = ["SCENARIOS", "MockIndexNowServer"]

#: The scenarios and the status they answer (contract of spec 03).
SCENARIOS: dict[str, int] = {
    "ok200": 200,
    "pending202": 202,
    "bad400": 400,
    "forbidden403": 403,
    "unprocessable422": 422,
    "ratelimit429": 429,
    "ratelimit429-then-ok": 429,
    "flaky500-then-ok": 503,
    "timeout": 200,
}


def large_xml() -> bytes:
    """A large XML document (>100 KB), used to regression-test that GET responses are not truncated at the 2 KB
    POST-diagnostics limit."""
    entries = "".join(f"<entry>https://www.example.com/page-{i}</entry>" for i in range(3000))
    return f'<?xml version="1.0" encoding="UTF-8"?><entries>{entries}</entries>'.encode()


class MockIndexNowServer:
    def __init__(self, keys: Iterable[str] = (), timeout_delay: float = 30.0, host: str = "127.0.0.1") -> None:
        env_keys = [key.strip() for key in os.environ.get("MOCK_KEYS", "").split(",") if key.strip()]
        self.keys = frozenset([*keys, *env_keys])
        self.timeout_delay = timeout_delay
        self._host = host
        self._log: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------------------------------------------------

    def start(self) -> MockIndexNowServer:
        mock = self

        class Handler(_Handler):
            server_mock = mock

        self._server = ThreadingHTTPServer((self._host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="indexnowkit-mock", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def __enter__(self) -> MockIndexNowServer:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- addresses and the log ---------------------------------------------------------------------------------------

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("the mock server is not running: call start() or use it as a context manager")
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        """``http://127.0.0.1:<port>`` — plain HTTP is accepted on loopback hosts only."""
        return f"http://{self._host}:{self.port}"

    @property
    def endpoint(self) -> str:
        return f"{self.url}/indexnow"

    @property
    def requests(self) -> list[dict[str, Any]]:
        """Every ``/indexnow`` request so far: method, path, query, body, json, headers, time, scenario."""
        with self._lock:
            return [dict(entry) for entry in self._log]

    def clear(self) -> None:
        with self._lock:
            self._log.clear()

    def _record(self, entry: dict[str, Any]) -> int:
        """Append and return how many requests of the entry's scenario there are now (this one included)."""
        with self._lock:
            self._log.append(entry)
            return sum(1 for item in self._log if item["scenario"] == entry["scenario"])


class _Handler(BaseHTTPRequestHandler):
    server_mock: MockIndexNowServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _respond(
        self,
        status: int,
        text: bytes | str = b"",
        extra: dict[str, str] | None = None,
        content_type: str = "text/plain",
    ) -> None:
        body = text.encode() if isinstance(text, str) else text
        self.send_response(status)
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def do_DELETE(self) -> None:
        self._handle("DELETE")

    def do_PUT(self) -> None:
        self._handle("PUT")

    def _handle(self, method: str) -> None:
        parts = urlsplit(self.path)
        path = parts.path or "/"
        query = {name: values[-1] for name, values in parse_qs(parts.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if method == "GET" and path == "/large-document.xml":
            self._respond(200, large_xml())
            return
        if method == "GET" and path == "/large-document.xml.gz":
            self._respond(200, gzip.compress(large_xml()))
            return
        if path == "/_mock/requests":
            if method == "DELETE":
                self.server_mock.clear()
                self._respond(204)
                return
            self._respond(200, json.dumps(self.server_mock.requests), content_type="application/json")
            return
        match = KeyValidator.PATTERN.match(path[1:-4]) if method == "GET" and path.endswith(".txt") else None
        if match is not None:
            key = path[1:-4]
            if key in self.server_mock.keys:
                self._respond(200, key)
            else:
                self._respond(404, "not found")
            return
        if path != "/indexnow":
            self._respond(404, "not found")
            return
        scenario = self.headers.get("X-Mock-Scenario") or query.get("scenario") or "ok200"
        try:
            decoded = json.loads(body) if body else None
        except ValueError:
            decoded = None
        count = self.server_mock._record(
            {
                "method": method,
                "path": path,
                "query": query,
                "body": body.decode("utf-8", "replace"),
                "json": decoded,
                "headers": {name: value for name, value in self.headers.items()},
                "time": time.time(),
                "scenario": scenario,
            }
        )
        if method not in ("GET", "POST"):
            self._respond(405)
            return
        if method == "POST":
            if not isinstance(decoded, dict) or not all(field in decoded for field in ("host", "key", "urlList")):
                self._respond(400, "invalid body")
                return
            if not isinstance(decoded["urlList"], list):
                self._respond(400, "invalid body")
                return
            if len(decoded["urlList"]) > 10_000:
                self._respond(400, "too many urls")
                return
            for url in decoded["urlList"]:
                host = urlsplit(url).hostname if isinstance(url, str) else None
                if host is None or host.lower() != str(decoded["host"]).lower():
                    self._respond(422, "url host mismatch")
                    return
        n = int(query.get("n", "1"))
        if scenario == "ok200":
            self._respond(200)
        elif scenario == "pending202":
            self._respond(202)
        elif scenario == "bad400":
            self._respond(400, "bad")
        elif scenario == "forbidden403":
            self._respond(403, "forbidden")
        elif scenario == "unprocessable422":
            self._respond(422, "unprocessable")
        elif scenario == "ratelimit429":
            self._respond(429, "slow down", {"Retry-After": "2"})
        elif scenario == "ratelimit429-then-ok":
            self._respond(429, "slow down", {"Retry-After": "1"}) if count <= n else self._respond(200)
        elif scenario == "flaky500-then-ok":
            self._respond(503, "oops") if count <= n else self._respond(200)
        elif scenario == "timeout":
            time.sleep(self.server_mock.timeout_delay)
            self._respond(200)
        else:
            self._respond(400, "unknown scenario")
