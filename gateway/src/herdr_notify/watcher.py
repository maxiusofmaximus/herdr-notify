"""Gap-free live mirror of a herdr session.

The bootstrap order is herdr's documented one and is not interchangeable:

1. Open a subscription stream for the *unscoped* events and wait for its
   acknowledgement. Subscriptions do not replay history, so anything emitted
   before this point is unrecoverable from the stream.
2. While that stream is already buffering, fetch ``session.snapshot`` and
   install it.
3. Rotate the stream to include a per-pane ``pane.agent_status_changed``
   subscription for every pane the snapshot revealed.

Step 3 is a rotation rather than an update because ``stream_subscriptions`` in
herdr's server takes ownership of its connection: the subscription set is
frozen at subscribe time. The old stream stays open and draining until the
replacement is acknowledged, so nothing is lost across the swap, and every
rotation is followed by a fresh snapshot so a replayed or reordered event cannot
leave the mirror wrong.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .herdr.client import HerdrClient, HerdrError, HerdrStream, StreamFactory
from .herdr.paths import Endpoint
from .state.models import AgentRecord, PaneRecord, Snapshot
from .state.store import AgentChange, Store, StreamAction

log = logging.getLogger(__name__)

ChangeHandler = Callable[[list[AgentChange]], Awaitable[None] | None]

# The server may be restarting or the pipe transiently unavailable. Back off
# rather than hot-looping against an endpoint that accepts instantly.
RECONNECT_DELAYS = (0.5, 1.0, 2.0, 5.0, 10.0, 30.0)


class Watcher:
    """Keeps a :class:`Store` in sync with a running herdr server."""

    def __init__(
        self,
        *,
        session: str | None = None,
        endpoint: Endpoint | None = None,
        store: Store | None = None,
        on_changes: ChangeHandler | None = None,
        request_timeout: float = 5.0,
        stream_factory: StreamFactory | None = None,
    ) -> None:
        self.endpoint = endpoint if endpoint is not None else Endpoint.resolve(session)
        self.client = HerdrClient(
            self.endpoint, timeout=request_timeout, stream_factory=stream_factory
        )
        self.store = store or Store()
        self._on_changes = on_changes
        self._stream: HerdrStream | None = None
        self._stop = asyncio.Event()
        self._booted = asyncio.Event()
        self.rotations = 0
        self.resyncs = 0

    @property
    def booted(self) -> asyncio.Event:
        return self._booted

    @property
    def stream(self) -> HerdrStream | None:
        return self._stream

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Connect, bootstrap, then consume events until cancelled."""
        delay_index = 0
        while not self._stop.is_set():
            try:
                await self._session()
                delay_index = 0
            except asyncio.CancelledError:
                raise
            except HerdrError as exc:
                if self._stop.is_set():
                    break
                delay = RECONNECT_DELAYS[min(delay_index, len(RECONNECT_DELAYS) - 1)]
                delay_index += 1
                log.warning("herdr connection lost (%s); retrying in %.1fs", exc, delay)
                self._booted.clear()
                await self._teardown()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), delay)
            else:
                # The stream ended without an error worth backoff-ing on.
                if self._stop.is_set():
                    break
                log.info("herdr event stream ended; resubscribing")
                self._booted.clear()
                await self._teardown()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), 0.5)

    async def stop(self) -> None:
        self._stop.set()
        await self._teardown()

    async def _teardown(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.close()

    # -- one connected session --------------------------------------------

    async def _session(self) -> None:
        await self._bootstrap()
        self._booted.set()
        state = self.store.state
        log.info(
            "watching herdr %s: %d workspaces, %d panes, %d agents",
            state.version,
            len(state.workspaces),
            len(state.panes),
            len(state.agents),
        )
        await self._consume()

    async def _bootstrap(self) -> None:
        # 1. Unscoped stream first: subscriptions never replay, so it must be
        #    acknowledged before the snapshot is requested.
        bootstrap_stream = self.client.open_stream(name="stream-bootstrap")
        await bootstrap_stream.start(())
        self._stream = bootstrap_stream

        # 2. Snapshot while the stream is already buffering.
        await self.install_snapshot()

        # 3. Rotate to cover every pane the snapshot revealed. The bootstrap
        #    stream keeps draining until _rotate_stream closes it.
        await self._rotate()
        log.debug("bootstrap complete, watching %d panes", len(self.store.state.pane_ids()))

    async def install_snapshot(self) -> None:
        """Fetch and install a fresh snapshot, emitting whatever it changed.

        Public because every recovery path needs it: a stream overflow, a
        rotation, an explicit resync from the API. It is the only operation
        allowed to *remove* records, because it is the only one that sees
        everything herdr currently holds.
        """
        payload = await self.client.snapshot()
        changes = self.store.install(Snapshot.model_validate(payload))
        await self._emit(changes)

    async def _rotate(self) -> None:
        """Replace the stream with one covering every known pane.

        The old stream stays open and draining until the new one is
        acknowledged, so events in the swap window are applied rather than lost.
        Duplicates are harmless: the store is idempotent and the snapshot that
        follows every rotation is authoritative.
        """
        pane_ids = self.store.state.pane_ids()
        old = self._stream
        fresh = self.client.open_stream(name="stream")
        try:
            await fresh.start(pane_ids)
        except HerdrError:
            fresh.close()
            raise
        self._stream = fresh
        if old is not None and old is not fresh:
            old.close()
        self.rotations += 1
        # A rotation can straddle a state change, and the snapshot is the only
        # authoritative view of what herdr holds right now.
        await self.install_snapshot()
        log.debug("stream rotated to %d panes", len(pane_ids))

    async def _consume(self) -> None:
        """Apply events until the stream dies or a stop is requested."""
        while not self._stop.is_set():
            stream = self._stream
            if stream is None or stream.closed:
                return

            next_event = asyncio.ensure_future(stream.events().__anext__())
            stop_wait = asyncio.ensure_future(self._stop.wait())
            done, pending = await asyncio.wait(
                {next_event, stop_wait}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            if stop_wait in done:
                next_event.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await next_event
                return

            try:
                message = next_event.result()
            except StopAsyncIteration:
                return
            await self._handle(message)

    async def _handle(self, message: dict[str, Any]) -> None:
        name = message.get("event")
        data = message.get("data")
        if not isinstance(name, str) or not isinstance(data, dict):
            return

        outcome = self.store.apply(name, data)

        if outcome.needs_hydration:
            await self._hydrate(outcome.needs_hydration)

        if outcome.changes:
            await self._emit(outcome.changes)

        if self._stop.is_set():
            return

        # A dropped event leaves the mirror behind; only a snapshot can fix it.
        if self._stream is not None and self._stream.resync_needed:
            log.warning("event queue overflowed; forcing a resync")
            self._stream.resync_needed = False
            with contextlib.suppress(HerdrError):
                await self.install_snapshot()
                self.resyncs += 1
            return

        if outcome.stream is StreamAction.ROTATE or (
            self._stream is not None and self._stream.closed
        ):
            with contextlib.suppress(HerdrError):
                await self._rotate()

    async def _hydrate(self, pane_ids: set[str]) -> None:
        """Fetch records for panes we only know by id.

        A status event for an unknown pane carries no cwd, title or session
        reference, so a partial record would render an empty project name in the
        app. A failed hydration is logged and skipped rather than fatal: the
        next rotation's snapshot picks the pane up.
        """
        for pane_id in sorted(pane_ids):
            if self._stop.is_set():
                return
            try:
                pane = PaneRecord.model_validate(await self.client.pane_get(pane_id))
            except HerdrError as exc:
                log.debug("could not hydrate pane %s: %s", pane_id, exc)
                continue
            agent: AgentRecord | None = None
            with contextlib.suppress(HerdrError):
                agent = AgentRecord.model_validate(await self.client.agent_get(pane_id))
            self.store.hydrate(pane, agent)

    async def _emit(self, changes: list[AgentChange]) -> None:
        if not changes or self._on_changes is None:
            return
        result = self._on_changes(changes)
        if asyncio.iscoroutine(result):
            await result


__all__ = ["ChangeHandler", "Watcher"]
