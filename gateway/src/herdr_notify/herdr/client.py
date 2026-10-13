"""Async client for herdr's local socket API.

The protocol is shaped by two facts in herdr's server, both verified against
0.9.1 source and a live server:

**One request per connection.** ``handle_connection_with_stop`` reads
``read_initial_request_line``, answers it and returns, closing the stream
(``src/api/server.rs``). Reusing a request/response connection fails with
``ERROR_NO_DATA`` on the second write, so a fresh connection per request *is*
the protocol.

**Subscriptions own their connection.** ``events.subscribe`` is handed to
``stream_subscriptions``, which loops writing events and never reads another
request. The subscription set is frozen at subscribe time, and herdr's schema
requires an explicit ``pane_id`` for ``pane.agent_status_changed`` with no
wildcard form — so a pane created later needs a new stream, not an update to
the existing one.

See :mod:`.transport` for why reads are polled rather than blocked.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any, Final

from .paths import Endpoint
from .transport import LocalStream, TransportClosed, TransportError

log = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT: Final = 5.0
STREAM_ACK_TIMEOUT: Final = 5.0

StreamFactory = Callable[[], LocalStream]
"""Builds one already-open transport. Overridden in tests; production opens
herdr's endpoint directly."""

# Bounded so a stalled consumer cannot grow the queue without limit. Overflow
# sets resync_needed so the caller reconciles against a fresh snapshot instead
# of trusting a gap-riddled stream.
EVENT_QUEUE_SIZE: Final = 4096

# Event names herdr's subscription schema accepts, verified against
# `herdr api schema --json`. Anything else is rejected at subscribe time, which
# closes the stream.
UNSCOPED_EVENTS: Final = (
    "workspace.created",
    "workspace.updated",
    "workspace.closed",
    "workspace.focused",
    "tab.created",
    "tab.closed",
    "tab.focused",
    "pane.created",
    "pane.closed",
    "pane.moved",
    "pane.exited",
    "pane.agent_detected",
    "pane.focused",
    "layout.updated",
)

AGENT_STATUS_EVENT: Final = "pane.agent_status_changed"

# States herdr itself treats as "ready for input".
READY_FOR_INPUT: frozenset[str] = frozenset({"idle", "done"})


class HerdrError(RuntimeError):
    """Base error for the herdr client."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class HerdrRemoteError(HerdrError):
    """The server answered with a structured error response."""


class HerdrConnectionClosed(HerdrError):
    """The stream ended or was closed underneath us."""


class HerdrTimeoutError(HerdrError):
    """A request or the subscribe acknowledgement did not arrive in time."""


def agent_status_subscription(pane_id: str) -> dict[str, Any]:
    """The per-pane subscription herdr requires for status changes."""
    return {"type": AGENT_STATUS_EVENT, "pane_id": pane_id}


def build_subscriptions(pane_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Full subscription set: every unscoped event plus one per known pane."""
    subs: list[dict[str, Any]] = [{"type": name} for name in UNSCOPED_EVENTS]
    subs.extend(agent_status_subscription(pane_id) for pane_id in sorted(set(pane_ids)))
    return subs


class HerdrClient:
    """Request/response access to herdr. One connection per request."""

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._stream_factory = stream_factory
        self._counter = 0
        self._lock = threading.Lock()

    def _open(self) -> LocalStream:
        """Build the transport for one request.

        ``stream_factory`` is the test seam; production always opens herdr's own
        endpoint. It exists because a Windows Python without AF_UNIX cannot host
        a duplex stream anywhere except a real named pipe, and the tests must
        not depend on a running herdr to be meaningful.
        """
        if self._stream_factory is not None:
            return self._stream_factory()
        return LocalStream(str(self.endpoint.path), is_named_pipe=self.endpoint.is_named_pipe)

    def _next_id(self, method: str) -> str:
        with self._lock:
            self._counter += 1
            return f"hn-{method}-{self._counter}"

    def _request_blocking(
        self, request_id: str, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        stream = self._open()
        with stream:
            stream.write_line(
                json.dumps(
                    {"id": request_id, "method": method, "params": params},
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
            line = stream.read_line(timeout=self.timeout)
        if line is None:
            raise HerdrConnectionClosed(f"{method}: herdr closed the stream without answering")
        try:
            decoded = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HerdrError(f"{method}: malformed response: {exc}") from exc
        if not isinstance(decoded, dict):
            raise HerdrError(f"{method}: response was not a JSON object")
        return decoded

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,  # noqa: ASYNC109 - see note below
    ) -> dict[str, Any]:
        """Send one request on a fresh connection and return its result object.

        The ``timeout`` keyword is deliberate rather than an oversight. Every
        caller picks its own bound: a snapshot on a loaded machine deserves
        longer than a pane lookup, and the deadline is also forwarded to the
        transport so a stalled read unblocks rather than leaking a thread. A
        caller-supplied deadline cannot be expressed as a wrapping
        ``asyncio.timeout()`` because it is chosen per call site.
        """
        request_id = self._next_id(method)
        payload = params or {}
        # Trace every herdr call the gateway makes, with the pane it addresses.
        # Focus is a side effect of *some* herdr methods (agent.focus moves the
        # operator's terminal); a phone opening a chat must never cause one, so
        # this is the line an investigation reads to prove which method, if any,
        # was sent. ``target``/``pane_id`` cover the action and watcher methods.
        log.info(
            "herdr -> %s pane=%s",
            method,
            payload.get("target") or payload.get("pane_id") or "-",
        )
        try:
            message = await asyncio.to_thread(
                self._request_blocking, request_id, method, payload
            )
        except TransportClosed as exc:
            raise HerdrConnectionClosed(f"{method}: {exc}") from exc
        except TransportError as exc:
            raise HerdrError(f"{method}: {exc}") from exc

        if "error" in message:
            error = message.get("error") or {}
            code = error.get("code")
            raise HerdrRemoteError(
                f"{method}: {error.get('message', 'unknown error')}",
                code=code if isinstance(code, str) else None,
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise HerdrError(f"{method}: response carried no result object")
        return result

    async def ping(self) -> dict[str, Any]:
        return await self.request("ping")

    async def snapshot(self) -> dict[str, Any]:
        """Return the raw ``session.snapshot`` payload.

        herdr nests everything under ``result.snapshot``; callers must not look
        for collections at the response root.
        """
        result = await self.request("session.snapshot")
        snapshot = result.get("snapshot")
        if not isinstance(snapshot, dict):
            raise HerdrError("session.snapshot returned no snapshot object")
        return snapshot

    async def pane_get(self, pane_id: str) -> dict[str, Any]:
        result = await self.request("pane.get", {"pane_id": pane_id})
        pane = result.get("pane")
        if not isinstance(pane, dict):
            raise HerdrError(f"pane.get {pane_id} returned no pane object")
        return pane

    async def agent_get(self, target: str) -> dict[str, Any]:
        result = await self.request("agent.get", {"target": target})
        agent = result.get("agent")
        if not isinstance(agent, dict):
            raise HerdrRemoteError(f"agent.get {target} returned no agent object", code="not_found")
        return agent

    def open_stream(self, *, name: str = "stream") -> HerdrStream:
        """Create a subscription stream. Call ``await stream.start(pane_ids)``."""
        stream = HerdrStream(self.endpoint, name=name)
        if self._stream_factory is not None:
            stream.bind_factory(self._stream_factory)
        return stream


class HerdrStream:
    """A long-lived subscription connection.

    herdr writes the acknowledgement and then only ever writes events, so this
    class never sends anything after ``start``.
    """

    def __init__(self, endpoint: Endpoint, *, name: str = "stream") -> None:
        self._endpoint = endpoint
        self._name = name
        self._transport: LocalStream | None = None
        self._events: asyncio.Queue[dict[str, Any] | None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._reader: threading.Thread | None = None
        self._subscribed_panes: set[str] = set()
        self.dropped_events = 0
        self.resync_needed = False
        self._stream_factory: StreamFactory | None = None

    def bind_factory(self, factory: StreamFactory) -> None:
        """Install the transport factory before :meth:`start`. Test seam."""
        self._stream_factory = factory

    @property
    def closed(self) -> bool:
        return self._transport is None or self._transport.closed

    @property
    def pane_ids(self) -> set[str]:
        """Panes this stream is subscribed to, for logging and assertions."""
        return set(self._subscribed_panes)

    async def start(self, pane_ids: Iterable[str] = ()) -> None:
        """Open the endpoint, subscribe, and wait for herdr's acknowledgement."""
        self._loop = asyncio.get_running_loop()
        self._events = asyncio.Queue(maxsize=EVENT_QUEUE_SIZE)
        self._subscribed_panes = set(pane_ids)
        log.info("herdr -> events.subscribe panes=%d", len(self._subscribed_panes))

        if self._stream_factory is not None:
            transport = self._stream_factory()
        else:
            transport = LocalStream(
                str(self._endpoint.path), is_named_pipe=self._endpoint.is_named_pipe
            )
        self._transport = transport
        try:
            await asyncio.to_thread(transport.open)

            await asyncio.to_thread(
                transport.write_line,
                json.dumps(
                    {
                        "id": f"{self._name}-sub",
                        "method": "events.subscribe",
                        "params": {"subscriptions": build_subscriptions(self._subscribed_panes)},
                    },
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
        except (TransportError, TransportClosed) as exc:
            self.close()
            raise HerdrConnectionClosed(f"{self._name}: subscribe failed: {exc}") from exc

        # The reader thread starts only after the request is on the wire. Reads
        # are polled rather than blocked (see transport), so this cannot race
        # with the write, and the ack is simply the first queued message.
        self._reader = threading.Thread(
            target=self._read_loop, name=f"herdr-{self._name}", daemon=True
        )
        self._reader.start()

        consumer = asyncio.ensure_future(self._events.get())
        try:
            first = await asyncio.wait_for(consumer, STREAM_ACK_TIMEOUT)
        except TimeoutError as exc:
            consumer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer
            self.close()
            raise HerdrTimeoutError(f"{self._name}: subscribe ack timed out") from exc

        if first is None:
            self.close()
            raise HerdrConnectionClosed(f"{self._name}: stream closed before acknowledging")
        if "error" in first:
            self.close()
            error = first.get("error") or {}
            code = error.get("code")
            raise HerdrRemoteError(
                f"events.subscribe: {error.get('message', 'unknown error')}",
                code=code if isinstance(code, str) else None,
            )
        if first.get("result", {}).get("type") != "subscription_started":
            self.close()
            raise HerdrError(f"{self._name}: unexpected subscribe result")

    def _read_loop(self) -> None:
        transport = self._transport
        if transport is None:
            return
        for line in transport.iter_lines():
            try:
                self._push(json.loads(line))
            except json.JSONDecodeError:
                self.dropped_events += 1
                self.resync_needed = True
        self._deliver_sentinel()

    def _push(self, message: dict[str, Any]) -> None:
        loop, events = self._loop, self._events
        if loop is None or events is None or loop.is_closed():
            return

        def _offer() -> None:
            if events.full():
                # Losing events silently would leave the app showing a state herdr
                # no longer holds. Force snapshot reconciliation instead.
                self.dropped_events += 1
                self.resync_needed = True
                with contextlib.suppress(asyncio.QueueFull):
                    events.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                events.put_nowait(message)

        loop.call_soon_threadsafe(_offer)

    def _deliver_sentinel(self) -> None:
        loop, events = self._loop, self._events
        if loop is None or events is None or loop.is_closed():
            return

        def _put() -> None:
            with contextlib.suppress(asyncio.QueueFull):
                events.put_nowait(None)

        loop.call_soon_threadsafe(_put)

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Yield pushed events until the stream ends."""
        if self._events is None:
            raise HerdrError(f"{self._name}: stream is not started")
        while True:
            message = await self._events.get()
            if message is None:
                return
            yield message

    def close(self) -> None:
        """Stop the stream. Safe from any thread and safe to repeat.

        Closing the transport makes the reader's poll loop exit within one poll
        interval, so the handle is never released while a read is pending.
        """
        transport, self._transport = self._transport, None
        if transport is None:
            return
        transport.close()
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=1.0)
        self._reader = None
        self._deliver_sentinel()


__all__ = [
    "AGENT_STATUS_EVENT",
    "DEFAULT_REQUEST_TIMEOUT",
    "READY_FOR_INPUT",
    "UNSCOPED_EVENTS",
    "HerdrClient",
    "HerdrConnectionClosed",
    "HerdrError",
    "HerdrRemoteError",
    "HerdrStream",
    "HerdrTimeoutError",
    "build_subscriptions",
]
