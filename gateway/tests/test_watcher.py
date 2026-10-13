"""Bootstrap ordering, stream rotation and gap-freedom.

These are the properties that decide whether a phone notification is ever
wrong. A missed ``blocked`` transition means a silent agent; a duplicated one
means notification spam. Both are timing bugs, so they are driven against a
scriptable fake rather than a live session — mutating a real coding session to
run a test is not an acceptable trade.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from herdr_notify.herdr.client import HerdrClient, HerdrRemoteError
from herdr_notify.herdr.paths import Endpoint, SocketPathError, resolve_socket_path
from herdr_notify.state.models import Snapshot
from herdr_notify.state.store import AgentChange, Store, Transition
from herdr_notify.watcher import Watcher
from tests.fake_herdr import FakeHerdr, agent_record, workspace_record

UNUSED_ENDPOINT = Endpoint(path=Path("unused/herdr.sock"), address="unused")


async def _run(fake: FakeHerdr, store: Store) -> tuple[Watcher, asyncio.Task[None]]:
    """Start a watcher on the fake and wait for its first snapshot."""
    watcher = Watcher(
        endpoint=UNUSED_ENDPOINT,
        store=store,
        stream_factory=fake.stream_factory(),
        request_timeout=5.0,
    )
    task = asyncio.create_task(watcher.start())
    await asyncio.wait_for(watcher.booted.wait(), 10)
    return watcher, task


async def _stop(watcher: Watcher, task: asyncio.Task[None]) -> None:
    await watcher.stop()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _settle(predicate, attempts: int = 200) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.fixture
def fake() -> Iterator[FakeHerdr]:
    server = FakeHerdr()
    server.set_snapshot(
        agents=[
            agent_record("w1:p1", "w1", status="working"),
            agent_record("w2:p1", "w2", status="idle"),
        ],
        workspaces=[workspace_record("w1", "alpha"), workspace_record("w2", "beta")],
    )
    try:
        yield server
    finally:
        server.close()


async def test_bootstrap_subscribes_before_snapshot(fake: FakeHerdr) -> None:
    """herdr subscriptions never replay, so a stream must exist before the read."""
    store = Store()
    watcher, task = await _run(fake, store)
    try:
        assert len(fake.subscription_sets) == 2, "expected a bootstrap stream then a rotation"
        assert fake.subscribed_panes(0) == set(), "bootstrap stream must be unscoped"
        assert fake.subscribed_panes(1) == {"w1:p1", "w2:p1"}
        assert [m for m, _ in fake.requests][:1] == ["session.snapshot"]
    finally:
        await _stop(watcher, task)


async def test_bootstrap_installs_the_snapshot(fake: FakeHerdr) -> None:
    store = Store()
    watcher, task = await _run(fake, store)
    try:
        assert set(store.state.agents) == {"w1:p1", "w2:p1"}
        assert store.state.version == "0.9.1"
        assert watcher.rotations == 1
    finally:
        await _stop(watcher, task)


async def test_status_change_flows_through_as_one_change(fake: FakeHerdr) -> None:
    store = Store()
    changes: list[AgentChange] = []
    watcher = Watcher(
        endpoint=UNUSED_ENDPOINT,
        store=store,
        on_changes=changes.extend,
        stream_factory=fake.stream_factory(),
    )
    task = asyncio.create_task(watcher.start())
    await asyncio.wait_for(watcher.booted.wait(), 10)
    try:
        live = [c for c in changes if not c.synthetic]
        assert live == [], "bootstrap must not look like live news"

        fake.set_agent("w1:p1", agent_status="blocked")
        fake.emit(
            "pane.agent_status_changed",
            {"pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "blocked"},
        )
        assert await _settle(lambda: any(not c.synthetic for c in changes))

        assert store.state.agents["w1:p1"].agent_status == "blocked"
        first = next(c for c in changes if not c.synthetic)
        assert first.trigger is Transition.BECAME_BLOCKED
        assert first.before == "working"
        assert first.synthetic is False
    finally:
        await _stop(watcher, task)


async def test_rotation_subscribes_to_a_pane_created_later(fake: FakeHerdr) -> None:
    """Subscription sets are frozen at subscribe time, so a pane needs a new stream."""
    store = Store()
    watcher, task = await _run(fake, store)
    try:
        fake.set_agent("w1:p2", workspace_id="w1", agent="opencode", agent_status="working")
        fake.emit("pane.created", {"pane_id": "w1:p2", "workspace_id": "w1"})

        # Both conditions, not just the subscription: the fake records the new
        # set the moment it sees events.subscribe, which is a moment before the
        # watcher finishes its rotation and bumps the counter.
        assert await _settle(
            lambda: watcher.rotations >= 2 and "w1:p2" in fake.subscribed_panes(-1)
        )
        assert "w1:p2" in store.state.agents
    finally:
        await _stop(watcher, task)


async def test_late_pane_is_hydrated_with_its_real_fields(fake: FakeHerdr) -> None:
    store = Store()
    watcher, task = await _run(fake, store)
    try:
        fake.set_agent("w3:p1", workspace_id="w3", agent="opencode", agent_status="working")
        fake.emit("pane.created", {"pane_id": "w3:p1", "workspace_id": "w3"})

        assert await _settle(lambda: "w3:p1" in store.state.agents)
        assert store.state.agents["w3:p1"].cwd == "C:\\dev\\w3"
    finally:
        await _stop(watcher, task)


async def test_replayed_status_after_rotation_is_idempotent(fake: FakeHerdr) -> None:
    store = Store()
    changes: list[AgentChange] = []
    watcher = Watcher(
        endpoint=UNUSED_ENDPOINT,
        store=store,
        on_changes=changes.extend,
        stream_factory=fake.stream_factory(),
    )
    task = asyncio.create_task(watcher.start())
    await asyncio.wait_for(watcher.booted.wait(), 10)
    try:
        fake.set_agent("w1:p1", agent_status="blocked")
        for _ in range(3):
            fake.emit(
                "pane.agent_status_changed",
                {"pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "blocked"},
            )
        assert await _settle(lambda: any(not c.synthetic for c in changes))
        await asyncio.sleep(0.2)

        live = [c for c in changes if not c.synthetic]
        assert len(live) == 1, "a replayed status must not look like news"
    finally:
        await _stop(watcher, task)


async def test_reinstall_never_mirrors_agents_herdr_stopped_reporting(fake: FakeHerdr) -> None:
    store = Store()
    watcher, task = await _run(fake, store)
    try:
        fake.set_snapshot(agents=[agent_record("w1:p1", "w1", status="idle")], workspaces=[])
        await watcher.install_snapshot()
        assert set(store.state.agents) == {"w1:p1"}
    finally:
        await _stop(watcher, task)


async def test_remote_error_carries_herdr_code(fake: FakeHerdr) -> None:
    client = HerdrClient(UNUSED_ENDPOINT, timeout=5.0, stream_factory=fake.stream_factory())
    with pytest.raises(HerdrRemoteError) as excinfo:
        await client.request("pane.get", {"pane_id": "does-not-exist"})
    assert excinfo.value.code == "not_found"


async def test_snapshot_is_read_from_result_snapshot_not_the_root(fake: FakeHerdr) -> None:
    """Regression: herdr nests every collection under result.snapshot."""
    client = HerdrClient(UNUSED_ENDPOINT, timeout=5.0, stream_factory=fake.stream_factory())
    payload = await client.snapshot()
    assert "agents" in payload
    assert Snapshot.model_validate(payload).agents


def test_endpoint_outside_the_herdr_config_dir_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tampered HERDR_SOCKET_PATH must not redirect the control plane."""
    monkeypatch.setenv("HERDR_SOCKET_PATH", r"C:\Windows\System32\evil.sock")
    with pytest.raises(SocketPathError):
        resolve_socket_path()


def test_session_names_cannot_escape_the_config_dir() -> None:
    with pytest.raises(SocketPathError):
        resolve_socket_path("..\\..\\escape")


async def test_unknown_method_is_reported_as_a_remote_error(fake: FakeHerdr) -> None:
    client = HerdrClient(UNUSED_ENDPOINT, timeout=5.0, stream_factory=fake.stream_factory())
    with pytest.raises(HerdrRemoteError) as excinfo:
        await client.request("totally.unknown.method")
    assert excinfo.value.code == "method_not_found"
