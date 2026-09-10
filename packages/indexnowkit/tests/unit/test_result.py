from __future__ import annotations

import dataclasses

import pytest

from indexnowkit.result import NO_ENGINE, Reason, Result, ResultStatus, all_urls, retryable_urls, urls_where


def test_reason_has_sixteen_members_split_into_skips_and_failures() -> None:
    assert len(Reason) == 17
    skips = [reason for reason in Reason if reason.is_skip]
    assert len(skips) == 10
    assert Reason.INVALID_KEY.is_skip is False
    assert {reason for reason in Reason if reason.is_retryable} == {
        Reason.RATE_LIMITED,
        Reason.SERVER_ERROR,
        Reason.TRANSPORT,
        Reason.ORIGIN_ERROR,
    }
    assert Reason.DEBOUNCED.translation_key == "indexnowkit.reason.debounced"
    assert Reason.INVALID_KEY.message == "Invalid key (403): key file not found or does not match."


def test_ok_and_pending() -> None:
    ok = Result.ok("api", "www.example.com", ["https://www.example.com/a"], 200, "https://api.indexnow.org/indexnow")
    pending = Result.ok("api", "www.example.com", ["https://www.example.com/a"], 202, "")
    assert ok.status is ResultStatus.OK and ok.is_success and ok.reason is None
    assert pending.status is ResultStatus.PENDING and pending.is_success
    assert ok.urls == ("https://www.example.com/a",)
    assert ok.url_count == 1


def test_skipped_and_failed_carry_the_reason_sentence() -> None:
    skipped = Result.skipped("www.example.com", ["https://www.example.com/a"], Reason.DRY_RUN)
    assert skipped.engine == NO_ENGINE
    assert skipped.status is ResultStatus.SKIPPED
    assert skipped.error == Reason.DRY_RUN.message
    failed = Result.failed(
        "api", "www.example.com", ["u"], Reason.RATE_LIMITED, http_code=429, retryable=True, retry_after=30
    )
    assert failed.status is ResultStatus.FAILED
    assert failed.retryable and failed.retry_after == 30 and failed.http_code == 429
    assert failed.metric_labels() == {
        "status": "failed",
        "engine": "api",
        "reason": "rate_limited",
        "http_code": "429",
        "retryable": "true",
    }
    assert skipped.metric_labels()["http_code"] == ""


def test_result_is_frozen() -> None:
    result = Result.ok("api", "h", ["u"], 200, "e")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.host = "x"  # type: ignore[misc]


def test_url_helpers_deduplicate_in_order() -> None:
    results = [
        Result.failed("api", "h", ["a", "b"], Reason.SERVER_ERROR, retryable=True),
        Result.ok("api", "h", ["b", "c"], 200, ""),
        Result.failed("yandex", "h", ["a"], Reason.INVALID_KEY),
    ]
    assert retryable_urls(results) == ["a", "b"]
    assert all_urls(results) == ["a", "b", "c"]
    assert urls_where(results, lambda r: r.status is ResultStatus.OK) == ["b", "c"]
