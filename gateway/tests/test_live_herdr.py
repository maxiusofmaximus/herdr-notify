"""Smoke tests against a real herdr server.

Deselected by default. They are read-only: nothing here mutates a session,
because a developer's live coding agents are not a test fixture.

    pytest -m integration            # run them
    pytest -m "not integration"      # the default
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from herdr_notify.herdr.client import HerdrClient
from herdr_notify.herdr.paths import Endpoint
from herdr_notify.state.models import Snapshot
from herdr_notify.state.store import Store
from herdr_notify.watcher import Watcher

pytestmark = pytest.mark.integration


async def test_live_ping_reports_capabilities() -> None:
    endpoint = Endpoint.resolve()
    client = HerdrClient(endpoint, timeout=5.0)
    result = await client.ping()
    assert result["type"] == "pong"
    assert result["version"]
    # These two gate the saved-machine federation path this project relies on.
    capabilities = result.get("capabilities") or {}
    assert capabilities.get("surface_interest") is True
    assert capabilities.get("health_check") is True


async def test_live_snapshot_parses_into_our_models() -> None:
    client = HerdrClient(Endpoint.resolve(), timeout=10.0)
    payload = await client.snapshot()
    snapshot = Snapshot.model_validate(payload)

    assert snapshot.version
    assert snapshot.protocol is not None
    # Workspaces and panes must agree, or the app would render a pane with no
    # project and a workspace with no agents.
    for agent in snapshot.agents:
        assert agent.pane_id in {p.pane_id for p in snapshot.panes}


async def test_live_bootstrap_then_stream_rotates() -> None:
    """The real gap-free sequence, end to end, without touching agent state."""
    store = Store()
    watcher = Watcher(store=store, request_timeout=10.0)
    task = asyncio.create_task(watcher.start())
    try:
        await asyncio.wait_for(watcher.booted.wait(), 30)
        assert watcher.rotations >= 1
        assert watcher.stream is not None
        assert not watcher.stream.closed
        assert store.state.pane_ids() <= watcher.stream.pane_ids
        assert store.state.version
    finally:
        await watcher.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
