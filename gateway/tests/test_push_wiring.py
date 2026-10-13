"""The push sender's delivery view: the trust store is where tokens live.

push.md pins the token's home to the device record. The sender reads it at send
time, so a registration the HTTP plane wrote, a rotation the host CLI wrote and
a revocation all reach the next send without a second copy of the truth — and
none of them can be dropped silently by a bridge that was never written. The
in-memory ledger this replaces failed in exactly that way: a registered token
never reached the sender at all, and a revoked one kept receiving until a
restart.
"""

from __future__ import annotations

from typing import Any

from herdr_notify.api.auth.devices import DeviceStore
from herdr_notify.cli import StoreBackedRegistry

CURVE = "p256"
PUBLIC_KEY = "BMz7dV1PKO1fO6Zhf9nWKRoRLCbIJFysqCXVSVZ4WWoB"


def _store(path: Any) -> DeviceStore:
    return DeviceStore(path)


def test_a_registered_token_reaches_the_sender(tmp_path: Any) -> None:
    devices = _store(tmp_path / "devices.json")
    registration = "tok-1"
    devices.add_device(curve=CURVE, public_key=PUBLIC_KEY, fcm_token=registration)
    registry = StoreBackedRegistry(devices)

    targets = registry.all()

    assert len(targets) == 1
    assert targets[0].device_id.startswith("hn-") or targets[0].device_id
    assert targets[0].token == registration


def test_a_device_without_a_token_is_skipped(tmp_path: Any) -> None:
    devices = _store(tmp_path / "devices.json")
    devices.add_device(curve=CURVE, public_key=PUBLIC_KEY)
    registry = StoreBackedRegistry(devices)

    assert registry.all() == []


def test_a_registration_written_behind_the_senders_back_reaches_the_next_send(
    tmp_path: Any,
) -> None:
    """The HTTP plane writes the store file; the sender reloads and sees it."""
    path = tmp_path / "devices.json"
    devices = _store(path)
    device = devices.add_device(curve=CURVE, public_key=PUBLIC_KEY)
    registry = StoreBackedRegistry(devices)
    assert registry.all() == []

    # A second process — the CLI, or a fresh store instance — writes the token.
    elsewhere = DeviceStore(path)
    elsewhere.set_fcm_token(device.device_id, "tok-2")

    assert [d.token for d in registry.all()] == ["tok-2"]


def test_a_revoked_device_stops_receiving_push(tmp_path: Any) -> None:
    devices = _store(tmp_path / "devices.json")
    registration = "tok-3"
    device = devices.add_device(curve=CURVE, public_key=PUBLIC_KEY, fcm_token=registration)
    registry = StoreBackedRegistry(devices)
    assert [d.token for d in registry.all()] == [registration]

    devices.revoke(device.device_id)

    # revoke clears the token at the source, so the very next send cannot
    # target a device that is no longer trusted — no restart needed.
    assert registry.all() == []


def test_a_pruned_token_is_cleared_from_the_store(tmp_path: Any) -> None:
    """Google reported the token dead; keeping it would retry a dead send."""
    path = tmp_path / "devices.json"
    devices = _store(path)
    registration = "tok-4"
    device = devices.add_device(curve=CURVE, public_key=PUBLIC_KEY, fcm_token=registration)
    registry = StoreBackedRegistry(devices)
    assert registry.prune([]) == 0

    assert registry.prune([registration]) == 1

    loaded = devices.get(device.device_id)
    assert loaded is not None and loaded.fcm_token is None
    assert registry.all() == []
    # Pruning an already-cleared token is a no-op, not an error.
    assert registry.prune([registration]) == 0
