"""The protocol client: groups already-normalized URLs by host, chunks them, throttles and POSTs one batch per
endpoint. Never raises on HTTP status codes or network errors, only on programming errors."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from indexnowkit._log import log
from indexnowkit.config import Config
from indexnowkit.engine import Engine
from indexnowkit.exceptions import InvalidArgumentError, TransportError
from indexnowkit.http import Transport
from indexnowkit.key import KeyProvider, KeyValidator, StaticKeyProvider
from indexnowkit.result import Reason, Result
from indexnowkit.retry import ForbiddenCounter
from indexnowkit.throttle import NullThrottle, Throttle
from indexnowkit.url import UrlNormalizerProtocol, normalizer_from_config

__all__ = ["Client", "ClientProtocol"]
_logger = logging.getLogger("indexnowkit.client")


@runtime_checkable
class ClientProtocol(Protocol):
    """The HTTP-facing half of the pipeline: normalized URLs in, one :class:`Result` per engine × host × batch out.
    :class:`Client` is the shipped implementation; decorate it for per-host policy (engines, throttling, metrics)."""

    def submit_all(self, normalized_urls: Iterable[str]) -> list[Result]: ...

    def submit_batch(self, endpoint: str, host: str, key: str, urls: Iterable[str]) -> Result:
        """One POST of a batch that belongs to ``host``, under ``key``, to ``endpoint``.

        :raises InvalidArgumentError: on an empty list
        """


class Client:
    """The 403 escalation (:class:`ForbiddenCounter`) counts consecutive rejections per host: in the process by
    default, in the cache the adapter shares between web workers and queue workers when one is given
    (``failure_cache``), so the one ``critical`` line is written once per fleet, not once per worker."""

    #: Default of ``failure_cache_ttl``: a 403 streak older than an hour without a new 403 is forgotten.
    FAILURE_CACHE_TTL = ForbiddenCounter.TTL

    def __init__(
        self,
        transport: Transport,
        keys: KeyProvider,
        config: Config,
        logger: logging.Logger | None = None,
        throttle: Throttle | None = None,
        normalizer: UrlNormalizerProtocol | None = None,
        failure_cache: Any | None = None,
        failure_cache_ttl: int = FAILURE_CACHE_TTL,
    ) -> None:
        self._transport = transport
        self._keys = keys
        self._config = config
        self._logger = logger or _logger
        self._throttle: Throttle = throttle or NullThrottle()
        self._normalizer = normalizer or normalizer_from_config(config)
        self.counter = ForbiddenCounter(
            failure_cache,
            config.debounce_key_prefix,
            config.logging_forbidden_escalation,
            failure_cache_ttl,
            self._logger,
        )

    def submit_all(self, normalized_urls: Iterable[str]) -> list[Result]:
        results: list[Result] = []
        for host, urls in self._group_by_host(normalized_urls).items():
            key = self._keys.key_for(host)
            if key is None:
                log(
                    self._logger,
                    self._config.logging_level("no_key"),
                    'skipping {count} URL(s) for unmanaged host {host}: no key configured (add it to "hosts" or set base_url)',  # noqa: E501 — a text of the family, one to one with PHP
                    count=len(urls),
                    host=host,
                    urls=self._config.log_sample(urls),
                )
                results.append(
                    Result.skipped(host, urls, Reason.NO_KEY, f'No IndexNow key configured for host "{host}".')
                )
                continue
            size = max(1, self._config.batch_max_urls)
            for start in range(0, len(urls), size):
                chunk = urls[start : start + size]
                for endpoint in self._config.endpoints_for(host):
                    results.append(self.submit_batch(endpoint, host, key, chunk))
        return results

    def submit_batch(self, endpoint: str, host: str, key: str, urls: Iterable[str]) -> Result:
        """One POST. Throttled unless dry-run."""
        batch = list(urls)
        if not batch:
            raise InvalidArgumentError("Cannot submit an empty URL list.")
        engine = Engine.label_for(endpoint)
        payload: dict[str, Any] = {"host": host, "key": key}
        location = self._keys.key_location_for(host)
        if location is not None:
            payload["keyLocation"] = location
        payload["urlList"] = batch
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError) as error:
            log(
                self._logger,
                logging.ERROR,
                "cannot encode {count} URL(s) for {host} as JSON: {error}",
                count=len(batch),
                host=host,
                error=str(error),
            )
            return Result.failed(
                engine, host, batch, Reason.UNEXPECTED, f"Cannot encode URL list as JSON: {error}", endpoint=endpoint
            )
        if self._config.dry_run:
            log(
                self._logger,
                self._config.logging_level("dry_run"),
                "dry-run POST {endpoint} {body}",
                endpoint=endpoint,
                body=self._mask(body, host, key),
            )
            return Result.skipped(host, batch, Reason.DRY_RUN, engine=engine, endpoint=endpoint)
        try:
            self._throttle.acquire()
        except Exception as error:
            log(
                self._logger,
                logging.ERROR,
                "throttle failed, sending without rate limiting: {error}",
                error=str(error),
                exc=error,
            )
        try:
            response = self._transport.post(endpoint, body, {"User-Agent": self._config.user_agent()})
        except TransportError as error:
            message = self._mask(str(error), host, key)
            log(
                self._logger,
                self._config.logging_level("transport"),
                "{engine} transport error for {host}: {error}",
                engine=engine,
                host=host,
                error=message,
            )
            return Result.failed(engine, host, batch, Reason.TRANSPORT, message, retryable=True, endpoint=endpoint)
        except Exception as error:
            message = self._mask(f"{type(error).__name__}: {error}", host, key)
            log(
                self._logger,
                logging.ERROR,
                "{engine} HTTP client failure for {host}: {error}",
                engine=engine,
                host=host,
                error=message,
                cls=type(error).__name__,
            )
            return Result.failed(engine, host, batch, Reason.UNEXPECTED, message, retryable=True, endpoint=endpoint)
        return self._interpret(endpoint, engine, host, batch, response.status, response.text, response.retry_after, key)

    def _interpret(
        self,
        endpoint: str,
        engine: str,
        host: str,
        urls: list[str],
        status: int,
        body: str,
        retry_after: int | None,
        key: str,
    ) -> Result:
        config = self._config
        ctx = {
            "engine": engine,
            "host": host,
            "count": len(urls),
            "status": status,
            "body": self._mask(body[: config.logging_max_body], host, key),
        }

        def failed(
            reason: Reason, error: str | None = None, retryable: bool = False, after: int | None = None
        ) -> Result:
            return Result.failed(engine, host, urls, reason, error, status, retryable, after, endpoint)

        if status != 403:
            self.counter.reset(host)
        if status == 200:
            log(self._logger, config.logging_level("ok"), "{engine} accepted {count} URL(s) for {host}", **ctx)
            return Result.ok(engine, host, urls, 200, endpoint)
        if status == 202:
            log(
                self._logger,
                config.logging_level("pending"),
                "{engine} accepted {count} URL(s) for {host}, key verification pending (202)",
                **ctx,
            )
            return Result.ok(engine, host, urls, 202, endpoint)
        if status == 400:
            log(
                self._logger,
                config.logging_level("invalid_request"),
                "{engine} rejected the request as malformed (400): {body}",
                **ctx,
            )
            return failed(Reason.INVALID_REQUEST)
        if status == 403:
            return self._forbidden(host, key, ctx, failed(Reason.INVALID_KEY))
        if status == 422:
            log(
                self._logger,
                config.logging_level("unprocessable"),
                "{engine} could not process URLs for {host} (422): URLs do not belong to the host or keyLocation is invalid",  # noqa: E501 — a text of the family, one to one with PHP
                **ctx,
            )
            return failed(Reason.UNPROCESSABLE)
        if status == 429:
            log(
                self._logger,
                config.logging_level("rate_limited"),
                "{engine} rate limited (429) for {host}, retry after {retry_after}s",
                retry_after=retry_after if retry_after is not None else "?",
                **ctx,
            )
            return failed(Reason.RATE_LIMITED, None, True, retry_after)
        if status >= 500:
            log(self._logger, config.logging_level("server_error"), "{engine} server error {status} for {host}", **ctx)
            return failed(Reason.SERVER_ERROR, f"Server error ({status})", True, retry_after)
        log(
            self._logger,
            config.logging_level("unexpected"),
            "{engine} unexpected status {status} for {host}: {body}",
            **ctx,
        )
        return failed(Reason.UNEXPECTED, f"Unexpected status ({status})")

    def _forbidden(self, host: str, key: str, ctx: Mapping[str, Any], result: Result) -> Result:
        count, escalate = self.counter.hit(host)
        message = (
            "{engine} rejected the key for {host} (403). Check that https://{host}/{key}.txt is reachable and contains "
            "the key (run the check command of your adapter, e.g. indexnowkit check)."
        )
        if escalate:
            level = logging.CRITICAL
            message += " {consecutive} consecutive failures: submissions for this host are not being indexed."
        elif count >= self._config.logging_forbidden_escalation:
            level = logging.WARNING
        else:
            level = logging.ERROR
        log(self._logger, level, message, key=KeyValidator.mask(key), consecutive=count, **ctx)
        return result

    def _group_by_host(self, urls: Iterable[str]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for url in urls:
            groups.setdefault(self._normalizer.host_of(url), []).append(url)
        return groups

    def _mask(self, text: str, host: str, key: str) -> str:
        """Every key the host has (the current one, the previous one during a rotation) masked in a log excerpt."""
        keys = [key]
        if isinstance(self._keys, StaticKeyProvider):
            previous = self._keys.previous_key_for(host)
            if previous is not None:
                keys.append(previous)
        for known in keys:
            text = text.replace(known, KeyValidator.mask(known))
        return text
