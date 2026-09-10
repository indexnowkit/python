"""Scenarios C01–C22 of docs/spec/03-conformance.md, against the submitter of the core over a FakeTransport."""

from __future__ import annotations

import logging
import math
import re

import pytest

from indexnowkit.config import Config
from indexnowkit.debounce import MemoryDebounceStore
from indexnowkit.exceptions import ConfigurationError
from indexnowkit.http import Response
from indexnowkit.key import generate_key
from indexnowkit.result import Reason, ResultStatus
from indexnowkit.retry import RetryingSubmitter, RetryPolicy
from indexnowkit.testing import FakeTransport, FrozenClock
from indexnowkit.throttle import TokenBucket
from tests.support import KEY, config, submitter


def messages(caplog: pytest.LogCaptureFixture, level: int | None = None) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if level is None or r.levelno == level)


def test_c01_submit_one_url_is_one_post_with_host_key_url_list_and_no_key_location() -> None:
    t = FakeTransport()
    results = submitter(t).submit(["https://www.example.com/a"])
    assert len(t.posts) == 1
    assert t.posts[0]["url"] == "https://api.indexnow.org/indexnow"
    assert t.posts[0]["body"] == {"host": "www.example.com", "key": KEY, "urlList": ["https://www.example.com/a"]}
    assert t.posts[0]["headers"]["User-Agent"].startswith("indexnowkit-python/")
    assert results[0].status is ResultStatus.OK


def test_c02_key_location_configured_is_present_in_the_body() -> None:
    t = FakeTransport()
    submitter(t, config(key_location=f"https://www.example.com/keys/{KEY}.txt")).submit(["/a"])
    assert t.posts[0]["body"]["keyLocation"] == f"https://www.example.com/keys/{KEY}.txt"


def test_c03_10001_urls_of_one_host_are_two_posts() -> None:
    t = FakeTransport()
    submitter(t).submit([f"/p/{i}" for i in range(10_001)])
    assert len(t.posts) == 2
    assert len(t.posts[0]["body"]["urlList"]) == 10_000 and len(t.posts[1]["body"]["urlList"]) == 1


def test_c04_urls_of_two_hosts_are_one_post_per_host() -> None:
    t = FakeTransport()
    submitter(t).submit(["https://www.example.com/a", "https://blog.example.com/b", "https://www.example.com/c"])
    assert sorted(p["body"]["host"] for p in t.posts) == ["blog.example.com", "www.example.com"]


def test_c05_host_missing_from_the_hosts_map_is_dropped_with_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    t = FakeTransport()
    caplog.set_level(logging.DEBUG, "indexnowkit")
    cfg = config(key=None, hosts={"www.example.com": KEY})
    results = submitter(t, cfg).submit(["https://other.example.org/x"])
    assert t.posts == []
    assert "unmanaged host other.example.org" in messages(caplog, logging.WARNING)
    assert results[0].reason is Reason.NO_KEY


def test_c06_duplicates_in_one_call_are_one_url() -> None:
    t = FakeTransport()
    submitter(t).submit(["/a", "https://www.example.com/a", "/a#frag", "/A"])
    assert t.posts[0]["body"]["urlList"] == ["https://www.example.com/a", "https://www.example.com/A"]


def test_c07_c08_same_url_within_debounce_is_not_resent_and_after_the_ttl_is() -> None:
    t = FakeTransport()
    clock = FrozenClock()
    sub = submitter(t, config(debounce={"per_url": 600}), debounce=MemoryDebounceStore(clock))
    sub.submit(["/a"])
    clock.advance(100)
    debounced = sub.submit(["/a"])
    assert len(debounced) == 1 and debounced[0].status is ResultStatus.SKIPPED  # C07
    assert debounced[0].reason is Reason.DEBOUNCED and len(t.posts) == 1
    clock.advance(600)
    sub.submit(["/a"])
    assert len(t.posts) == 2  # C08


def test_c09_202_is_pending_treated_as_success_and_debounced() -> None:
    t = FakeTransport().will_respond(Response(202))
    sub = submitter(t, config(debounce={"per_url": 600}))
    results = sub.submit(["/a"])
    assert results[0].status is ResultStatus.PENDING and results[0].is_success
    sub.submit(["/a"])
    assert len(t.posts) == 1


def test_c10_403_is_failed_not_retryable_and_the_error_log_names_the_key_file(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, "indexnowkit")
    t = FakeTransport().will_respond(Response(403))
    results = submitter(t).submit(["/a"])
    assert results[0].status is ResultStatus.FAILED and results[0].retryable is False and results[0].http_code == 403
    assert results[0].reason is Reason.INVALID_KEY
    assert ".txt" in messages(caplog, logging.ERROR)
    assert KEY not in messages(caplog), "key must be masked in logs"


def test_c11_422_is_failed_not_retryable() -> None:
    results = submitter(FakeTransport().will_respond(Response(422))).submit(["/a"])
    assert results[0].status is ResultStatus.FAILED and results[0].retryable is False


def test_c12_429_in_sync_mode_is_failed_retryable_with_retry_after_and_no_retry() -> None:
    t = FakeTransport().will_respond(Response(429, b"slow", 30))
    results = submitter(t).submit(["/a"])
    assert len(t.posts) == 1 and results[0].retryable and results[0].retry_after == 30


def test_c13_429_with_retry_after_retried_in_process_ends_ok_after_sleeping_the_delay() -> None:
    t = FakeTransport().will_respond(Response(429, b"slow", 2), Response(200))
    sleeps: list[float] = []
    retrying = RetryingSubmitter(submitter(t), RetryPolicy(), sleeper=sleeps.append)
    results = retrying.submit(["/a"])
    assert len(t.posts) == 2 and sleeps == [2]
    assert len(results) == 1 and results[0].status is ResultStatus.OK
    assert all(not r.retryable for r in results)


def test_c14_transport_failure_is_failed_retryable_without_an_exception() -> None:
    results = submitter(FakeTransport().will_respond(FakeTransport.failing("timeout"))).submit(["/a"])
    assert results[0].status is ResultStatus.FAILED and results[0].retryable and results[0].http_code is None
    assert results[0].reason is Reason.TRANSPORT


def test_c15_invalid_key_is_a_configuration_error_at_construction() -> None:
    with pytest.raises(ConfigurationError):
        config(key="abc")


def test_c16_enabled_false_means_no_post() -> None:
    t = FakeTransport()
    results = submitter(t, config(enabled=False)).submit(["/a"])
    assert len(results) == 1 and results[0].status is ResultStatus.SKIPPED and results[0].reason is Reason.DISABLED
    assert t.posts == []


def test_c17_dry_run_means_no_post_and_an_info_line_with_the_body_key_masked(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, "indexnowkit")
    t = FakeTransport()
    results = submitter(t, config(dry_run=True)).submit(["/a"])
    assert t.posts == [] and results[0].status is ResultStatus.SKIPPED and results[0].reason is Reason.DRY_RUN
    info = messages(caplog, logging.INFO)
    assert "dry-run" in info and "https://www.example.com/a" in info and KEY not in info


def test_c18_engines_yandex_and_bing_are_two_posts_with_the_same_body() -> None:
    t = FakeTransport()
    submitter(t, config(engines=["yandex", "bing"])).submit(["/a"])
    assert [p["url"] for p in t.posts] == ["https://yandex.com/indexnow", "https://www.bing.com/indexnow"]
    assert t.posts[0]["json"] == t.posts[1]["json"]


def test_c19_fragment_stripped_idn_host_in_punycode_scheme_and_host_lower_cased() -> None:
    t = FakeTransport()
    submitter(t, config(key=None, hosts={"xn--80aswg.xn--p1ai": KEY})).submit(["HTTPS://Сайт.рф/Путь?q=1#top"])
    assert t.posts[0]["body"]["host"] == "xn--80aswg.xn--p1ai"
    assert t.posts[0]["body"]["urlList"] == ["https://xn--80aswg.xn--p1ai/Путь?q=1"]


def test_c20_empty_list_does_nothing() -> None:
    t = FakeTransport()
    assert submitter(t).submit([]) == [] and t.posts == []


def test_c21_key_generation_is_32_hex_characters_and_unique() -> None:
    a, b = generate_key(), generate_key()
    assert re.fullmatch(r"[a-f0-9]{32}", a) and a != b and len(generate_key(64)) == 64


def test_c22_throttle_2_per_minute_and_3_batches_makes_the_third_wait_for_the_next_token() -> None:
    t = FakeTransport()
    clock = FrozenClock()
    sleeps: list[float] = []

    def sleeper(seconds: float) -> None:
        sleeps.append(seconds)
        clock.advance(math.ceil(seconds))

    throttle = TokenBucket(2, clock, sleeper)
    submitter(t, config(engines=["api"], batch={"max_urls": 1}), throttle=throttle).submit(["/a", "/b", "/c"])
    assert len(t.posts) == 3 and len(sleeps) == 1 and sleeps[0] >= 29


def test_invalid_urls_are_dropped_with_a_warning_not_an_exception(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, "indexnowkit")
    t = FakeTransport()
    cfg = Config.from_mapping({"key": KEY, "debounce": {"per_url": 0}})  # no base_url
    submitter(t, cfg).submit(["/relative", "https://www.example.com/ok", ""])
    assert len(t.posts) == 1
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2
