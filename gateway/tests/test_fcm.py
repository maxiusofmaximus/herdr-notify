"""Notification content, token lifecycle, and the FCM payload shape.

The payload is asserted without a Firebase app or a network on purpose. A
mis-shaped message is invisible until a phone receives it, and by then it is a
production incident rather than a test failure.
"""

from __future__ import annotations

import pytest

from herdr_notify.notify.fcm import (
    CREDENTIALS_ENV,
    DeviceRegistry,
    FcmSender,
    PushConfigurationError,
    build_message,
    build_notification,
    dumps,
    render_preview,
)
from herdr_notify.state.store import AgentChange, Transition


def change(**overrides: object) -> AgentChange:
    base: dict[str, object] = {
        "pane_id": "w1:p1",
        "workspace_id": "w1",
        "before": "working",
        "after": "blocked",
        "at": 1_700_000_000.0,
        "trigger": Transition.BECAME_BLOCKED,
        "synthetic": False,
    }
    base.update(overrides)
    return AgentChange(**base)  # type: ignore[arg-type]


# -- content ---------------------------------------------------------------


def test_blocked_notification_leads_with_the_ask() -> None:
    notification = build_notification(change(), project="herdr-notify", agent_name="opencode")
    assert notification.title == "opencode necesita tu atención"
    assert "herdr-notify" in notification.body
    assert notification.channel == "agents"
    assert notification.priority == "high"


def test_done_notification_is_distinct_from_blocked() -> None:
    notification = build_notification(
        change(after="done", trigger=Transition.BECAME_DONE), project="api", agent_name="codex"
    )
    assert notification.title == "codex terminó"
    assert notification.channel == "agents-review"
    assert notification.priority == "normal"


def test_notification_carries_the_herdr_ids_the_app_needs() -> None:
    """The tap handler must not have to parse a display string to know what to open."""
    notification = build_notification(change(), project="alpha", agent_name="opencode")
    assert notification.data["pane_id"] == "w1:p1"
    assert notification.data["workspace_id"] == "w1"
    assert notification.data["status"] == "blocked"
    assert notification.data["project"] == "alpha"


def test_notifications_collapse_per_agent() -> None:
    """Without this, a busy agent leaves a stack of tray entries."""
    first = build_notification(change())
    second = build_notification(change(after="done", trigger=Transition.BECAME_DONE))
    assert first.collapse_key == second.collapse_key == "agent-w1:p1"


def test_different_agents_do_not_share_a_collapse_key() -> None:
    a = build_notification(change(pane_id="w1:p1"))
    b = build_notification(change(pane_id="w2:p1"))
    assert a.collapse_key != b.collapse_key


def test_long_titles_are_truncated_rather_than_overflowing() -> None:
    notification = build_notification(change(), project="x" * 400, agent_name="opencode")
    assert len(notification.body) <= 160
    assert notification.body.endswith("…")


def test_notification_offers_open_and_mark_seen() -> None:
    notification = build_notification(change())
    ids = {action["id"] for action in notification.actions}
    assert ids == {"open", "seen"}


def test_payload_is_json_serialisable_for_logging_and_tests() -> None:
    import json

    payload = json.loads(dumps(build_notification(change())))
    assert payload["title"]
    assert "pane_id" in payload["data"]


def test_preview_is_readable() -> None:
    preview = render_preview(build_notification(change(), project="alpha", agent_name="opencode"))
    assert "opencode necesita tu atención" in preview


# -- payload shape ---------------------------------------------------------


class FakeMessaging:
    """Stands in for ``firebase_admin.messaging`` so the shape is assertable."""

    class Notification:
        def __init__(self, title: str, body: str) -> None:
            self.title = title
            self.body = body

    class AndroidNotification:
        def __init__(self, **kw: object) -> None:
            self.kw = kw

    class AndroidConfig:
        def __init__(self, **kw: object) -> None:
            self.kw = kw

    class Message:
        def __init__(self, **kw: object) -> None:
            self.kw = kw


def test_message_sets_both_the_notification_block_and_data() -> None:
    """A data-only message may not surface anything when the app is backgrounded."""
    notification = build_notification(change())
    message = build_message(FakeMessaging, notification, "device-abc")

    assert message.kw["token"] == "device-abc"  # noqa: S105 - a fixture, not a credential
    assert message.kw["notification"].title == notification.title
    assert message.kw["data"] == notification.data

    android = message.kw["android"]
    assert android.kw["priority"] == "high"
    assert android.kw["collapse_key"] == "agent-w1:p1"
    assert android.kw["ttl"] == 3_600
    inner = android.kw["notification"]
    assert inner.kw["channel_id"] == "agents"
    assert inner.kw["click_action"] == "OPEN_AGENT"
    assert inner.kw["tag"] == "agent-w1:p1"


def test_review_priority_is_normal_so_it_does_not_wake_the_phone() -> None:
    notification = build_notification(change(after="done", trigger=Transition.BECAME_DONE))
    message = build_message(FakeMessaging, notification, "device-abc")
    assert message.kw["android"].kw["priority"] == "normal"


# -- device registry -------------------------------------------------------


def test_registering_the_same_device_twice_is_idempotent() -> None:
    registry = DeviceRegistry()
    first = registry.register("pixel", "token-1", label="Pixel", now=100.0)
    second = registry.register("pixel", "token-1", now=200.0)
    assert len(registry) == 1
    assert first.registered_at == second.registered_at == 100.0
    assert second.label == "Pixel"


def test_a_rotated_token_replaces_the_old_one_in_place() -> None:
    """Tokens rotate on reinstall; appending would leak a dead one forever."""
    registry = DeviceRegistry()
    registry.register("pixel", "token-1", now=100.0)
    registry.register("pixel", "token-2", now=200.0)
    assert registry.tokens() == ["token-2"]


def test_dead_tokens_are_pruned() -> None:
    registry = DeviceRegistry()
    registry.register("pixel", "token-1")
    registry.register("pixel2", "token-2")
    assert registry.prune(["token-1"]) == 1
    assert registry.tokens() == ["token-2"]


def test_pruning_nothing_is_a_no_op() -> None:
    registry = DeviceRegistry()
    registry.register("pixel", "token-1")
    assert registry.prune([]) == 0
    assert len(registry) == 1


def test_success_resets_the_failure_counter() -> None:
    registry = DeviceRegistry()
    registry.register("pixel", "token-1", now=100.0)
    registry.note_failure("token-1")
    registry.note_failure("token-1")
    assert registry.all()[0].failures == 2
    registry.note_success("token-1", now=500.0)
    device = registry.all()[0]
    assert device.failures == 0
    assert device.last_success_at == 500.0


# -- credentials -----------------------------------------------------------


def test_sender_refuses_to_run_without_a_service_account() -> None:
    sender = FcmSender(DeviceRegistry())
    with pytest.raises(PushConfigurationError) as excinfo:
        sender.credential_file()
    assert CREDENTIALS_ENV in str(excinfo.value)


def test_sender_reports_a_missing_service_account_file(tmp_path: object) -> None:
    sender = FcmSender(DeviceRegistry(), credentials_path="does/not/exist.json")
    with pytest.raises(PushConfigurationError):
        sender.credential_file()


def test_sender_never_reads_the_credential_contents(tmp_path: object) -> None:
    """The key is referenced by path so it cannot reach a log or a traceback."""
    import json
    from pathlib import Path

    key = Path(tmp_path) / "service-account.json"  # type: ignore[operator]
    key.write_text(json.dumps({"private_key": "SECRET", "type": "service_account"}))
    sender = FcmSender(DeviceRegistry(), credentials_path=str(key))
    resolved = sender.credential_file()
    assert resolved == key
    assert "SECRET" not in str(resolved)


def test_sending_with_no_devices_is_a_no_op() -> None:
    """No devices must not touch credentials or the network."""
    sender = FcmSender(DeviceRegistry())
    assert sender.send(build_notification(change())) == 0
    assert sender.sent == 0


# -- send failures ---------------------------------------------------------


class _FcmError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sender_failing_with(monkeypatch: pytest.MonkeyPatch, code: str) -> FcmSender:
    from firebase_admin import messaging

    registry = DeviceRegistry()
    registry.register("pixel", "token-1")
    sender = FcmSender(registry)
    monkeypatch.setattr(sender, "_ensure_app", lambda: object())

    def fail(*_args: object, **_kwargs: object) -> None:
        raise _FcmError(code)

    monkeypatch.setattr(messaging, "send", fail)
    return sender


def _any_notification() -> object:
    return build_notification(change())


@pytest.mark.parametrize("code", ["UNREGISTERED", "NOT_FOUND", "SENDER_ID_MISMATCH"])
def test_a_genuinely_dead_token_is_pruned(monkeypatch: pytest.MonkeyPatch, code: str) -> None:
    sender = _sender_failing_with(monkeypatch, code)
    assert sender.send(_any_notification()) == 0  # type: ignore[arg-type]
    assert sender.registry.tokens() == []


def test_invalid_argument_does_not_prune_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed payload answers INVALID_ARGUMENT too; the token is innocent."""
    from herdr_notify.notify.fcm import PushSendError

    sender = _sender_failing_with(monkeypatch, "INVALID_ARGUMENT")
    with pytest.raises(PushSendError) as caught:
        sender.send(_any_notification())  # type: ignore[arg-type]
    assert caught.value.code == "INVALID_ARGUMENT"
    assert caught.value.retryable is False
    assert sender.registry.tokens() == ["token-1"]
