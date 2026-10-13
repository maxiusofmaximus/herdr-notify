"""FCM HTTP v1 sender and the device token registry.

Two things about push worth stating plainly, because both are easy to get wrong
and both fail silently in production:

**The legacy FCM HTTP API is dead.** Google retired ``fcm.googleapis.com/fcm/send``
with server keys in mid-2024. The only current API is HTTP v1, authenticated with
an OAuth 2.0 token derived from a service account. ``firebase-admin`` is Google's
own SDK and speaks v1, which is why this module does not hand-roll the request.

**Tokens are not stable.** They rotate on reinstall, on some app updates, and
when Google decides to. A registry that only ever appends accumulates dead
tokens, every send to them fails, and the failure mode looks like "push stopped
working". So a token is replaced in place when it rotates, and pruned when the
server reports it unregistered.

Credential handling: the service account is referenced by path from the
environment, never read into a variable that could be logged, and the initialising
app is a module-level singleton so a second ``initialize_app`` cannot raise in the
middle of a send.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from ..state.store import AgentChange

log = logging.getLogger(__name__)

CREDENTIALS_ENV: Final = "GOOGLE_APPLICATION_CREDENTIALS"
FCM_SCOPE: Final = "https://www.googleapis.com/auth/firebase.messaging"


def _fcm_project_id() -> str | None:
    """The Firebase project the gateway sends into.

    ADC refresh tokens carry no project, and ``firebase-admin`` cannot talk to
    FCM without one. The single source of truth is the app's own
    ``google-services.json``, which ships in the same repo; the env var
    overrides it when the gateway runs against a different app.
    """
    env = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("FCM_PROJECT_ID")
    if env:
        return env
    try:
        repo_root = Path(__file__).resolve().parents[4]
        services = repo_root / "android" / "app" / "google-services.json"
        if services.is_file():
            data = json.loads(services.read_text(encoding="utf-8"))
            project = data.get("project_info", {}).get("project_id")
            if isinstance(project, str) and project:
                return project
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    return None


class PushConfigurationError(RuntimeError):
    """The gateway cannot send push at all."""


class PushSendError(RuntimeError):
    """A send failed. Carries whether retrying could possibly help."""

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


# Tokens Google reports as permanently dead. Retrying them wastes quota forever.
# INVALID_ARGUMENT is deliberately absent: FCM answers it for a malformed
# *message* as well as a bad token, so pruning on it deletes good tokens when
# the payload is at fault (a wrong TTL did exactly that).
UNRECOVERABLE = frozenset(
    {
        "NOT_FOUND",
        "UNREGISTERED",
        "SENDER_ID_MISMATCH",
        "THIRD_PARTY_AUTH_ERROR",
    }
)


@dataclass(slots=True)
class Device:
    """A registered phone.

    Mutable on purpose: the registry stamps delivery outcomes onto the record
    rather than rebuilding it, so a failed send does not lose ``registered_at``.
    """

    device_id: str
    token: str
    label: str | None = None
    registered_at: float = 0.0
    last_success_at: float | None = None
    failures: int = 0


class DeviceRegistry:
    """In-memory token registry, keyed by device then by token.

    Deliberately not persisted yet. A restart re-registers the app's token on its
    first connection, so a lost registry costs one missed push rather than a
    migration; persisting it before the API surface is settled would be
    speculative. A restart is also a fresh start for the cooldown counters, which
    is the conservative direction.
    """

    def __init__(self) -> None:
        self._devices: dict[str, Device] = {}
        self._lock = threading.Lock()

    def register(
        self, device_id: str, token: str, label: str | None = None, now: float | None = None
    ) -> Device:
        """Register or refresh a device. A rotated token replaces the old one."""
        stamp = time.time() if now is None else now
        with self._lock:
            existing = self._devices.get(device_id)
            if existing is not None and existing.token != token:
                log.info("device %s rotated its FCM token", device_id)
            device = Device(
                device_id=device_id,
                token=token,
                label=label if label is not None else (existing.label if existing else None),
                registered_at=existing.registered_at if existing else stamp,
                last_success_at=existing.last_success_at if existing else None,
                failures=existing.failures if existing else 0,
            )
            self._devices[device_id] = device
            return device

    def all(self) -> list[Device]:
        with self._lock:
            return list(self._devices.values())

    def tokens(self) -> list[str]:
        return [device.token for device in self.all()]

    def __len__(self) -> int:
        with self._lock:
            return len(self._devices)

    def note_success(self, token: str, now: float | None = None) -> None:
        stamp = time.time() if now is None else now
        with self._lock:
            for device in self._devices.values():
                if device.token == token:
                    device.last_success_at = stamp
                    device.failures = 0
                    return

    def prune(self, tokens: Iterable[str]) -> int:
        """Drop devices whose token the server reported as permanently dead."""
        dead = set(tokens)
        if not dead:
            return 0
        with self._lock:
            doomed = [d for d in self._devices.values() if d.token in dead]
            for device in doomed:
                log.info("pruning device %s with a dead FCM token", device.device_id)
                self._devices.pop(device.device_id, None)
        return len(doomed)

    def note_failure(self, token: str) -> None:
        with self._lock:
            for device in self._devices.values():
                if device.token == token:
                    device.failures += 1
                    return


# -- message construction --------------------------------------------------


@dataclass(frozen=True, slots=True)
class Notification:
    """The data actually put on the wire, kept separate from the SDK call.

    Rendering the title and body here rather than on the device means the same
    text is logged, asserted on in tests, and shown in the notification tray, so
    a wording regression is visible without a phone in the loop.
    """

    title: str
    body: str
    data: dict[str, str]
    collapse_key: str
    channel: str
    priority: str = "normal"
    ttl_seconds: int = 3600
    actions: list[dict[str, str]] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "collapse_key": self.collapse_key,
            "channel": self.channel,
            "priority": self.priority,
            "ttl_seconds": self.ttl_seconds,
            "actions": self.actions,
        }


def build_notification(
    change: AgentChange,
    *,
    project: str | None = None,
    agent_name: str | None = None,
    title: str | None = None,
    max_body: int = 160,
) -> Notification:
    """Compose the user-visible notification for one change.

    FCM's own notification block is filled in as well as ``data``: with a
    backgrounded or killed app, a data-only message is delivered but Android may
    not surface anything, whereas a notification block guarantees the tray entry
    the user is relying on. The app reads the same values from ``data`` so the
    tap handler never has to parse a display string.
    """
    label = project or change.workspace_id
    who = agent_name or "agent"
    blocked = change.after == "blocked"
    headline = f"{who} necesita tu atención" if blocked else f"{who} terminó"
    if title:
        detail = title
    elif blocked:
        detail = f"{label} está esperando una respuesta"
    else:
        detail = f"{label} terminó la tarea"
    body = detail if len(detail) <= max_body else detail[: max_body - 1].rstrip() + "…"

    return Notification(
        title=headline,
        body=body,
        data={
            "pane_id": change.pane_id,
            "workspace_id": change.workspace_id,
            "status": change.after or "unknown",
            "trigger": str(change.trigger),
            "project": label,
        },
        # One notification per pane: a newer state for the same agent replaces the
        # old one instead of stacking a second copy in the tray.
        collapse_key=f"agent-{change.pane_id}",
        # A blocked agent is waiting on a person, so it may wake the screen. A
        # finished task should be visible without hijacking whatever the phone is
        # doing — that asymmetry is the whole reason the two tiers exist.
        channel="agents" if blocked else "agents-review",
        priority="high" if blocked else "normal",
        ttl_seconds=3600,
        actions=[
            {"id": "open", "title": "Abrir"},
            {"id": "seen", "title": "Marcar visto"},
        ],
    )


# -- sender ----------------------------------------------------------------


#: The scope the gateway requests for push.
#:
#: The sending identity is a dedicated Google account narrowed to exactly this
#: scope (roadmap D1, resolved 2026-10-01): the refresh token in the Credential
#: Manager can only mint messaging-scoped access tokens, so the scope requested
#: here is the one the grant actually has. Refreshing with a scope the grant
#: does not include fails with ``invalid_scope`` — and it fails from a
#: background send, long after startup, with the gateway otherwise looking
#: healthy. That is the worst place for a credential error to surface, so the
#: scope requested here is the one the D1 decision minted.
#:
#: ``firebase.messaging`` is what the FCM HTTP v1 API accepts (with its
#: superset ``cloud-platform``). A token minted with a different grant fails
#: here, loudly, with Google's own message.
PUSH_SCOPES: Final = ("https://www.googleapis.com/auth/firebase.messaging",)


class _RefreshTokenCredential:
    """Factory for a ``firebase_admin`` credential backed by an in-memory token.

    ``firebase_admin.credentials.RefreshToken`` does this job but always requests
    its own scope list, which a default gcloud grant cannot satisfy. This builds
    one against the scope the token really has, keeping the SDK's public
    interface intact.

    It is a factory rather than a module-level class because ``firebase-admin``
    is an optional dependency: subclassing ``credentials.Base`` at import time
    would make this module unimportable without the ``push`` extra installed,
    which is the opposite of how the rest of the file is written.
    """

    _cached: type[Any] | None = None

    @classmethod
    def build(cls, info: dict[str, Any]) -> Any:
        from firebase_admin import credentials as fb_credentials
        from google.oauth2.credentials import Credentials as GoogleCredentials

        if cls._cached is None:

            # Subclassing a symbol that is `Any` at type-check time, because the
            # import is deliberately lazy. The runtime relationship is what
            # `initialize_app` checks, and it is real.
            class _Impl(fb_credentials.Base):  # type: ignore[misc]
                def __init__(self, data: dict[str, Any], scopes: list[str]) -> None:
                    # Untyped in google-auth's stubs; the call is correct and
                    # the alternative is casting the module rather than this.
                    self._google = GoogleCredentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
                        data, scopes
                    )

                def get_credential(self) -> Any:
                    return self._google

            cls._cached = _Impl

        return cls._cached(info, list(PUSH_SCOPES))


class FcmSender:
    """Thin wrapper over ``firebase-admin``'s messaging API."""

    def __init__(
        self,
        registry: DeviceRegistry,
        *,
        credentials_path: str | os.PathLike[str] | None = None,
        refresh_token: Mapping[str, Any] | None = None,
    ) -> None:
        self.registry = registry
        self.credentials_path = credentials_path
        #: An ADC-shaped dict held in memory, not read from a file. See
        #: :mod:`herdr_notify.notify.dpapi` for why it is not persisted.
        self._refresh_token = refresh_token
        self._app: Any = None
        self._lock = threading.Lock()
        self.sent = 0
        self.failures = 0
        self.dead_tokens: set[str] = set()

    # -- credential handling ----------------------------------------------

    def credential_file(self) -> Path:
        """Locate a service account key, failing loudly if it is unusable.

        Only used on the service-account path. Referenced by path only: the JSON
        is never read here, so it cannot end up in a log line, an exception
        message, or a traceback.
        """
        raw = self.credentials_path or os.environ.get(CREDENTIALS_ENV)
        if not raw:
            raise PushConfigurationError(
                f"no FCM credentials: expected a refresh token in the Windows "
                f"Credential Manager, or {CREDENTIALS_ENV} pointing at a "
                f"service account key"
            )
        path = Path(raw).expanduser()
        if not path.is_file():
            raise PushConfigurationError(f"FCM service account not found at {path}")
        return path

    def _build_credential(self, credentials: Any) -> Any:
        """Pick the credential, in the order Google documents for a workstation.

        Google's own guidance for local development names user credentials as the
        best option and a service account key as the last resort, "if you cannot
        use a user account or service account impersonation for local
        development". So the order here is the same, and it is a decision about
        which credential kind is available, not a preference.

        1. A refresh token supplied in memory. Nothing is read from disk; the
           token came from the Windows Credential Manager, which means DPAPI
           encrypted it and bound it to the Windows account.
        2. Application Default Credentials, so ``gcloud auth application-default
           login`` works with no configuration at all.
        3. A service account key, which is what ``credentials_path`` is for.
        """
        if self._refresh_token:
            return _RefreshTokenCredential.build(dict(self._refresh_token))
        if self.credentials_path or os.environ.get(CREDENTIALS_ENV):
            return credentials.Certificate(str(self.credential_file()))
        return credentials.ApplicationDefault()

    def _ensure_app(self) -> Any:
        """Initialise the Firebase app once, lazily.

        ``initialize_app`` raises if called twice with a different app name, and
        this runs from a background task that may be re-entry after a reconnect,
        so the singleton is guarded rather than assumed.
        """
        with self._lock:
            if self._app is not None:
                return self._app
            try:
                import firebase_admin
                from firebase_admin import credentials
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise PushConfigurationError(
                    "firebase-admin is not installed; install the 'push' extra"
                ) from exc
            cred = self._build_credential(credentials)
            self._app = firebase_admin.initialize_app(
                cred, {"projectId": _fcm_project_id()}
            )
            log.info("FCM sender initialised")
            return self._app

    # -- sending -----------------------------------------------------------

    def send(self, notification: Notification) -> int:
        """Send to every registered device. Returns the number accepted."""
        devices = self.registry.all()
        if not devices:
            return 0
        app = self._ensure_app()
        from firebase_admin import messaging

        accepted = 0
        dead: list[str] = []
        for device in devices:
            try:
                messaging.send(build_message(messaging, notification, device.token), app=app)
            except Exception as exc:
                self.failures += 1
                self.registry.note_failure(device.token)
                code = _error_code(exc)
                if code in UNRECOVERABLE:
                    dead.append(device.token)
                    self.dead_tokens.add(device.token)
                    log.warning("device %s has a dead token (%s); pruning", device.device_id, code)
                    continue
                raise PushSendError(
                    f"FCM send failed for {device.device_id}: {exc}",
                    code=code,
                    retryable=code != "INVALID_ARGUMENT",
                ) from exc
            self.sent += 1
            accepted += 1
            self.registry.note_success(device.token)
        if dead:
            self.registry.prune(dead)
        return accepted


def build_message(messaging: Any, notification: Notification, token: str) -> Any:
    """Assemble the SDK message.

    Kept separate and module-level so the payload shape is testable without a
    Firebase app or a network.
    """
    return messaging.Message(
        token=token,
        notification=messaging.Notification(title=notification.title, body=notification.body),
        data=notification.data,
        android=messaging.AndroidConfig(
            priority="high" if notification.priority == "high" else "normal",
            # Collapse per agent: without it, every state change for a busy agent
            # leaves its own tray entry.
            collapse_key=notification.collapse_key,
            ttl=notification.ttl_seconds,
            notification=messaging.AndroidNotification(
                channel_id=notification.channel,
                # Tapping opens the app rather than launching some fallback.
                click_action="OPEN_AGENT",
                tag=notification.collapse_key,
            ),
        ),
    )


def _error_code(exc: BaseException) -> str | None:
    for attribute in ("code", "grpc_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str):
            return value.rsplit("/", 1)[-1]
    return None


def render_preview(notification: Notification) -> str:
    """Human-readable form, used by the CLI and by tests."""
    return f"[{notification.channel}] {notification.title} — {notification.body}"


def dumps(notification: Notification) -> str:
    return json.dumps(notification.to_payload(), ensure_ascii=False, sort_keys=True)


__all__ = [
    "CREDENTIALS_ENV",
    "FCM_SCOPE",
    "UNRECOVERABLE",
    "Device",
    "DeviceRegistry",
    "FcmSender",
    "Notification",
    "PushConfigurationError",
    "PushSendError",
    "build_message",
    "build_notification",
    "dumps",
    "render_preview",
]
