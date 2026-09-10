"""Dispatchers hand a batch of URLs to the delivery mechanism (spec 20 §3.8): ``sync`` (inline), ``none``,
``thread`` (one worker thread), ``asyncio`` (a task on the running loop), ``callable`` (any queue), and the batching
shape every queue dispatcher of the family has. None of them raises into user code."""

from __future__ import annotations

import asyncio
import atexit
import logging
import queue
import secrets
import threading
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from indexnowkit._log import log
from indexnowkit.config import Config
from indexnowkit.exceptions import ConfigurationError

if TYPE_CHECKING:
    from indexnowkit.submitter import SubmitterProtocol

__all__ = [
    "ASYNCIO",
    "NONE",
    "SYNC",
    "THREAD",
    "AsyncTaskDispatcher",
    "BatchingDispatcher",
    "CallableDispatcher",
    "Dispatcher",
    "NullDispatcher",
    "SyncDispatcher",
    "ThreadDispatcher",
    "dispatcher_from_config",
    "new_job_id",
]
_logger = logging.getLogger("indexnowkit.dispatch")
SYNC = "sync"
NONE = "none"
THREAD = "thread"
ASYNCIO = "asyncio"


@runtime_checkable
class Dispatcher(Protocol):
    def dispatch(self, urls: Iterable[str]) -> None:
        """Hands a batch of URLs to the delivery mechanism. Must never raise into user code."""


def new_job_id() -> str:
    """A fresh correlation id (12 hex characters) the dispatch log line and the worker's log line share."""
    return secrets.token_hex(6)


class NullDispatcher:
    """Drops everything (``dispatch: none``). Keeps collection hooks active while delivery is off."""

    __slots__ = ()

    def dispatch(self, urls: Iterable[str]) -> None:
        return None


class SyncDispatcher:
    """Sends inline. Any exception is logged, never re-raised into the caller."""

    def __init__(self, submitter: SubmitterProtocol, logger: logging.Logger | None = None, log_urls: int = 20) -> None:
        self._submitter = submitter
        self._logger = logger or _logger
        self._log_urls = log_urls

    def dispatch(self, urls: Iterable[str]) -> None:
        batch = list(urls)
        try:
            self._submitter.submit(batch)
        except Exception as error:
            log(
                self._logger,
                logging.ERROR,
                "sync dispatch of {count} URL(s) failed, they are lost: {error}",
                count=len(batch),
                error=str(error),
                exc=error,
                urls=batch[: self._log_urls],
            )


class CallableDispatcher:
    """Adapter for any queue: the callable receives the URL list and enqueues it (``task.delay(urls)``,
    ``queue.enqueue(fn, urls)``, ``task.enqueue(urls)``)."""

    def __init__(
        self, fn: Callable[[list[str]], object], logger: logging.Logger | None = None, log_urls: int = 20
    ) -> None:
        self._fn = fn
        self._logger = logger or _logger
        self._log_urls = log_urls

    def dispatch(self, urls: Iterable[str]) -> None:
        batch = list(urls)
        try:
            self._fn(batch)
        except Exception as error:
            log(
                self._logger,
                logging.ERROR,
                "dispatch of {count} URL(s) failed, they are lost: {error}",
                count=len(batch),
                error=str(error),
                exc=error,
                urls=batch[: self._log_urls],
            )


class BatchingDispatcher:
    """The shape of every queue dispatcher of the family: one unit of work per ``batch.max_urls`` URLs, a correlation
    id per unit, and a push that may raise — logged as lost, never re-raised into the request."""

    def __init__(
        self,
        enqueue: Callable[[list[str], str], object],
        config: Config,
        logger: logging.Logger | None = None,
        noun: str = "job",
    ) -> None:
        """:param enqueue: the framework's push of one batch under its id; raises on failure
        :param noun: what the log calls one unit: ``job``, ``message``, ``task``
        """
        self._enqueue = enqueue
        self._config = config
        self._logger = logger or _logger
        self._noun = noun

    def dispatch(self, urls: Iterable[str]) -> None:
        batch = list(urls)
        size = max(1, self._config.batch_max_urls)
        for start in range(0, len(batch), size):
            chunk = batch[start : start + size]
            job_id = new_job_id()
            try:
                self._enqueue(chunk, job_id)
                log(
                    self._logger,
                    logging.DEBUG,
                    "{count} URL(s) queued as {noun} {id}",
                    count=len(chunk),
                    noun=self._noun,
                    id=job_id,
                    urls=self._config.log_sample(chunk),
                )
            except Exception as error:
                log(
                    self._logger,
                    logging.ERROR,
                    "cannot queue {count} URL(s) ({noun} {id}), they are lost: {error}",
                    count=len(chunk),
                    noun=self._noun,
                    id=job_id,
                    error=str(error),
                    exc=error,
                    urls=self._config.log_sample(chunk),
                )


class ThreadDispatcher:
    """One daemon worker thread with a queue, started lazily on the first dispatch (after a fork: gunicorn
    ``--preload`` is safe). At interpreter exit the worker gets ``join_timeout`` seconds to drain; what is left is
    one warning with the count. For environments without a queue where the sync delay is unacceptable."""

    def __init__(
        self, submitter: SubmitterProtocol, logger: logging.Logger | None = None, join_timeout: float = 5.0
    ) -> None:
        self._submitter = submitter
        self._logger = logger or _logger
        self._join_timeout = join_timeout
        self._queue: queue.Queue[list[str] | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def dispatch(self, urls: Iterable[str]) -> None:
        self._queue.put(list(urls))
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="indexnowkit-dispatch", daemon=True)
            self._thread.start()
            atexit.register(self.shutdown)

    def _run(self) -> None:
        while True:
            batch = self._queue.get()
            if batch is None:
                return
            try:
                self._submitter.submit(batch)
            except Exception as error:
                log(
                    self._logger,
                    logging.ERROR,
                    "dispatch of {count} URL(s) failed, they are lost: {error}",
                    count=len(batch),
                    error=str(error),
                    exc=error,
                )
            finally:
                self._queue.task_done()

    def shutdown(self) -> None:
        """Stop the worker after the queued batches, waiting at most ``join_timeout`` seconds."""
        thread = self._thread
        if thread is None or not thread.is_alive():
            return
        self._queue.put(None)
        thread.join(self._join_timeout)
        lost = sum(len(item) for item in list(self._queue.queue) if item)
        if thread.is_alive() or lost:
            log(
                self._logger,
                logging.WARNING,
                "{count} URL(s) still queued when the process ended (dispatch: thread); use a queue for durable delivery",  # noqa: E501 — a text of the family, one to one with PHP
                count=lost,
            )


class AsyncTaskDispatcher:
    """``loop.create_task(asubmit(urls))`` on the running loop, with a strong reference kept until the task is done
    (the loop holds weak references only). Opt-in for ASGI without a queue: tasks still running when the server
    stops are cancelled — ``check`` warns (``dispatch.asyncio``)."""

    def __init__(self, asubmit: Callable[[list[str]], Awaitable[object]], logger: logging.Logger | None = None) -> None:
        self._asubmit = asubmit
        self._logger = logger or _logger
        self._tasks: set[asyncio.Task[Any]] = set()

    def dispatch(self, urls: Iterable[str]) -> None:
        batch = list(urls)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log(
                self._logger,
                logging.ERROR,
                "dispatch of {count} URL(s) failed, they are lost: no running event loop (dispatch: asyncio needs one)",
                count=len(batch),
            )
            return
        task: asyncio.Task[Any] = loop.create_task(_await(self._asubmit(batch)))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @property
    def pending(self) -> int:
        return sum(1 for task in self._tasks if not task.done())


async def _await(awaitable: Awaitable[object]) -> object:
    return await awaitable


def dispatcher_from_config(
    config: Config,
    submitter: SubmitterProtocol,
    logger: logging.Logger | None = None,
    queue_factory: Callable[[], Dispatcher] | None = None,
    asubmit: Callable[[list[str]], Awaitable[object]] | None = None,
) -> Dispatcher:
    """The dispatcher an adapter wires from ``dispatch``: nothing when IndexNow is disabled or the mode is ``none``,
    inline delivery for ``sync``, a worker thread for ``thread``, a loop task for ``asyncio`` (``asubmit`` of the kit),
    the adapter's queue for anything else.

    :raises ConfigurationError: when the mode needs a queue and the adapter gave none
    """
    if not config.enabled or config.dispatch == NONE:
        return NullDispatcher()
    if config.dispatch == SYNC:
        return SyncDispatcher(submitter, logger, config.logging_max_urls)
    if config.dispatch == THREAD:
        return ThreadDispatcher(submitter, logger)
    if config.dispatch == ASYNCIO:
        if asubmit is None:
            raise ConfigurationError(
                '"dispatch" "asyncio" needs an async submitter (IndexNowKit.asubmit); use "sync", "thread" or "none".'
            )
        return AsyncTaskDispatcher(asubmit, logger)
    if queue_factory is None:
        raise ConfigurationError(
            f'"dispatch" "{config.dispatch}" needs a queue dispatcher, which this adapter does not provide; use "sync", "thread" or "none".'  # noqa: E501 — a text of the family, one to one with PHP
        )
    return queue_factory()
