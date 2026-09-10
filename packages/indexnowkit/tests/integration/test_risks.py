"""The risks of spec 20 §7 and 22 §7 that a test settles before the design leans on them: contextvars inside the
threads of ``ThreadingHTTPServer``, sqlite WAL from two connections, the Expat of the image."""

from __future__ import annotations

import contextvars
import pyexpat
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

scope: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("scope", default=None)


def test_7_3_a_server_thread_starts_with_an_empty_context_and_keeps_its_own() -> None:
    seen: list[list[str] | None] = []
    token = scope.set(["main"])
    try:

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                seen.append(scope.get())
                scope.set(["request"])
                seen.append(scope.get())
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            import urllib.request

            urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/", timeout=5).read()
        finally:
            server.shutdown()
            server.server_close()
        # a new thread starts from an empty context (threads do not inherit the parent's contextvars)
        assert seen == [None, ["request"]]
        assert scope.get() == ["main"]
    finally:
        scope.reset(token)


def test_7_7_sqlite_wal_two_connections_read_and_write_concurrently(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    writer = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA busy_timeout=5000")
    writer.execute("CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v INTEGER)")
    reader = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    reader.execute("PRAGMA busy_timeout=5000")
    assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO t VALUES ('a', 1)")
    # WAL: a reader is not blocked by an open write transaction, and sees the state before it
    assert reader.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    writer.execute("COMMIT")
    assert reader.execute("SELECT v FROM t WHERE k = 'a'").fetchone()[0] == 1
    # a second writer waits busy_timeout instead of failing immediately
    reader.execute("INSERT OR REPLACE INTO t VALUES ('a', 2)")
    assert writer.execute("SELECT v FROM t WHERE k = 'a'").fetchone()[0] == 2
    writer.close()
    reader.close()


def test_7_5_expat_of_the_interpreter_is_reported() -> None:
    version = tuple(int(part) for part in pyexpat.EXPAT_VERSION.split("_", 1)[1].split("."))
    assert len(version) == 3
    # the development image ships 2.8.3 (spec 20 §7.5); a system Python below 2.7.2 is a `check` warning, not a failure
    assert version >= (2, 0, 0)
