from __future__ import annotations

from indexnowkit.http import Response


def test_headers_are_lower_cased_and_readable() -> None:
    response = Response(200, b"body", headers={"Content-Type": "Text/Plain; charset=utf-8", "Age": " 12 "})
    assert response.header("content-TYPE") == "Text/Plain; charset=utf-8"
    assert response.content_type() == "text/plain"
    assert response.age() == 12
    assert response.body == b"body" and response.text == "body"
    assert Response(200).content_type() is None and Response(200).age() is None
    assert Response(200, headers={"Content-Type": ""}).content_type() is None
    assert Response(200, headers={"Age": "x"}).age() is None


def test_cache_max_age() -> None:
    assert Response(200, headers={"Cache-Control": "public, max-age=300"}).cache_max_age() == 300
    assert Response(200, headers={"Cache-Control": 'max-age=300, s-maxage="60"'}).cache_max_age() == 60
    assert Response(200, headers={"Cache-Control": "no-store"}).cache_max_age() == 0
    assert Response(200, headers={"Cache-Control": "private"}).cache_max_age() is None
    assert Response(200).cache_max_age() is None


def test_parse_retry_after() -> None:
    assert Response.parse_retry_after(None) is None and Response.parse_retry_after("  ") is None
    assert Response.parse_retry_after("30") == 30
    assert Response.parse_retry_after("999999") == 86_400
    assert Response.parse_retry_after("999999", maximum=100) == 100
    assert Response.parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412480 - 90) == 90
    assert Response.parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT", now=1445412480 + 90) == 0
    assert Response.parse_retry_after("120, 60") == 120
    assert Response.parse_retry_after("soon") is None
    assert Response.parse_retry_after("soon, later") is None


def test_undecodable_bytes_do_not_raise() -> None:
    assert Response(200, b"\xff\xfeok").text.endswith("ok")
