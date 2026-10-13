"""Registered devices: public keys, enrollment codes, grants, revocation.

The threat this answers: the gateway can drive any coding agent on the machine,
so a stolen bearer token is equivalent to handing an attacker your shell. There
is therefore no static secret here at all. A device is a public key, and proof
that the caller holds the matching private key — which never leaves the phone's
hardware keystore.

**Enrollment is itself an authenticated act.** If anything on the network could
register a device, key-based auth would be theatre: the attacker simply enrolls.
So enrollment requires a code that the host prints on the operator's own
machine, single use and short lived — the same pairing model as Bluetooth or a
Chromecast.

Persisted, unlike the FCM token registry: losing this file means re-enrolling
every phone, and an unpersisted registry would silently widen access across a
restart.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

#: Curves we can verify. P-256 is the default because Android Keystore has
#: supported it in hardware since API 23, while Ed25519 keystore support is
#: recent and inconsistent across devices. A device may present either; the
#: choice is per device and recorded, so Ed25519 can be adopted later without a
#: migration.
CURVE_P256: Final = "p256"
CURVE_ED25519: Final = "ed25519"
SUPPORTED_CURVES: Final = frozenset({CURVE_P256, CURVE_ED25519})

#: Bytes in an enrollment code. 32 bits of entropy is plenty for a 10-minute
#: single-use code, and a longer code is more awkward to read off a screen.
ENROLLMENT_CODE_BYTES: Final = 4
ENROLLMENT_TTL_SECONDS: Final = 600.0

#: Bytes behind a recovery code. 80 bits, printed once as four base32 groups
#: (``XXXX-XXXX-XXXX-XXXX``): long enough that guessing it is hopeless, short
#: enough to write down. Unlike the pairing code it never expires on its own —
#: it is rotated every time it re-pairs a device.
RECOVERY_CODE_BYTES: Final = 10

#: Minimum seconds between two ``last_seen_at`` writes for the same device.
#: Long enough to make a read-heavy client free, short enough that "when did this
#: phone last check in" stays roughly accurate for an operator reading the file.
TOUCH_PERSIST_INTERVAL: Final = 60.0

#: Permissions (authorization). The specification names five; READ_STATE is the
#: pairing default and the rest are explicit host-side grants — widening access
#: is a host-side act, the same reasoning that keeps enrollment host-side, so
#: there is no HTTP grant endpoint. APPROVE and ADMIN are RESERVED in v1: valid
#: grantable identifiers so a future endpoint can adopt them without a
#: migration, but no endpoint maps to them and they grant nothing, the same
#: pattern as the reserved key-id header.
PERMISSION_READ_STATE: Final = "read_state"
PERMISSION_RESPOND: Final = "respond"
PERMISSION_SEND_KEY: Final = "send_key"
PERMISSION_APPROVE: Final = "approve"
PERMISSION_ADMIN: Final = "admin"
SUPPORTED_PERMISSIONS: Final = frozenset(
    {
        PERMISSION_READ_STATE,
        PERMISSION_RESPOND,
        PERMISSION_SEND_KEY,
        PERMISSION_APPROVE,
        PERMISSION_ADMIN,
    }
)


class Curve(StrEnum):
    P256 = CURVE_P256
    ED25519 = CURVE_ED25519


class Permission(StrEnum):
    READ_STATE = PERMISSION_READ_STATE
    RESPOND = PERMISSION_RESPOND
    SEND_KEY = PERMISSION_SEND_KEY
    APPROVE = PERMISSION_APPROVE
    ADMIN = PERMISSION_ADMIN


@dataclass(slots=True)
class Device:
    """A registered phone. Public material only."""

    device_id: str
    curve: str
    public_key: str
    """Base64 of the raw public key: uncompressed SEC1 point for P-256, or the
    32 raw bytes for Ed25519. Never the private key — the gateway never has one."""

    label: str | None = None
    created_at: float = 0.0
    last_seen_at: float | None = None
    revoked: bool = False
    permissions: list[str] = field(default_factory=lambda: [PERMISSION_READ_STATE])
    """The explicit grant set: which operations this device may perform.

    The pairing default is READ_STATE and nothing else; the rest are host-side
    grants. A record loaded without this field receives the default, which is
    also the pre-M2 migration: those devices keep exactly the read behaviour M1
    verified, without re-pairing. An explicitly stored empty set stays empty —
    a device whose READ_STATE was revoked is refused on the read paths.
    """

    fcm_token: str | None = None
    owner_id: str = ""
    """The tailnet owner (``tailscale whois`` ``UserProfile.ID``) that paired
    this device, or ``""`` when unknown. Informational: it lets an operator see
    which account a device belongs to and is returned by ``GET /v1/devices``.
    It is never an authorization input."""

    recovery_code_hash: str | None = None
    """SHA-256 hex of this device's single-use recovery code, or ``None``.

    Only the hash is stored, so a leaked trust store does not reveal the code.
    Re-pairing rotates it; a revoked device's code stops working because the
    device itself is refused before the code is even considered.
    """

    persisted_at: float | None = None
    """When this record was last written to disk.

    In-memory bookkeeping for :meth:`DeviceStore.touch`, not part of the device's
    identity. Excluded from :meth:`to_public` so it never reaches a caller, and
    kept out of the comparison that matters by being a float rather than
    something a caller can act on.
    """

    def to_public(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "curve": self.curve,
            "label": self.label,
            "owner_id": self.owner_id,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "revoked": self.revoked,
            "permissions": sorted(self.permissions),
        }


@dataclass(slots=True)
class EnrollmentCode:
    code: str
    created_at: float
    expires_at: float
    used: bool = False

    def valid_at(self, now: float) -> bool:
        return not self.used and now < self.expires_at


class EnrollmentRejected(Exception):
    """The enrollment code was unknown, expired, or already used."""


def _new_recovery_code() -> str:
    """A recovery code in its display form: four base32 groups of four."""
    raw = base64.b32encode(os.urandom(RECOVERY_CODE_BYTES)).decode().rstrip("=")
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def _recovery_hash(code: str) -> str:
    """Hash a recovery code for storage.

    The canonical form drops separators and case so a code read off a screen and
    retyped with different spacing still matches, while the stored value is a
    hash rather than the secret itself.
    """
    canonical = "".join(code.split()).replace("-", "").upper()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _enrollment_hash(code: str) -> str:
    """Hash an enrollment code, both to store it and to look it up.

    The plaintext is never written to the trust store: the store keeps only this
    digest, so a leaked file does not hand out a live pairing code. The
    canonical form drops separators and case, so a code retyped from the screen
    still matches. A pairing code is only 32 bits, so this is defence in depth
    rather than a barrier against someone who already reads the host's files —
    such a code also expires in minutes and is single use.
    """
    canonical = "".join(code.split()).replace("-", "").upper()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def normalise_permissions(permissions: list[str] | None) -> list[str]:
    """The granted set for a freshly enrolled device.

    READ_STATE is the pairing default and always included; anything else is
    there only because the operator listed it. A permission outside the five
    supported ones is dropped rather than guessed: an unknown id grants
    nothing, and a stored set must never silently widen access.
    """
    granted = {PERMISSION_READ_STATE}
    granted.update(p for p in (permissions or ()) if p in SUPPORTED_PERMISSIONS)
    return sorted(granted)


class DeviceStore:
    """Registered devices, persisted as JSON.

    The file holds public keys, plus the hashes of any live pairing codes (never
    a code in the clear). Even a full compromise of this file grants nothing: an
    attacker learns which keys are trusted, not how to answer as any of them.
    Persisting the codes is what lets the ``enroll`` CLI and the running gateway
    — separate processes sharing one store — agree on a code.
    """

    def __init__(self, path: Path | None = None, *, clock: Any = time.time) -> None:
        self._path = Path(path) if path is not None else None
        self._clock = clock
        self._devices: dict[str, Device] = {}
        self._codes: dict[str, EnrollmentCode] = {}
        self._lock = threading.Lock()
        self._stamp: float | None = None
        if self._path is not None and self._path.is_file():
            self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        assert self._path is not None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Fail closed: a trust store we cannot read must not be treated as
            # an empty one that accepts anyone.
            return
        loaded: dict[str, Device] = {}
        for entry in raw.get("devices") or []:
            try:
                device = Device(**entry)
            except TypeError:
                continue
            if device.curve in SUPPORTED_CURVES and device.public_key:
                if not isinstance(device.permissions, list):
                    # A null or non-list field is a pre-M2 record in disguise.
                    device.permissions = [PERMISSION_READ_STATE]
                # An unknown permission id grants nothing rather than guessing:
                # a typo in a stored set must not silently widen access.
                device.permissions = [
                    p for p in device.permissions if p in SUPPORTED_PERMISSIONS
                ]
                loaded[device.device_id] = device
        # Enrollment codes live in the same file, hashed, so a code minted by
        # the `enroll` CLI is visible to the running gateway: it is a different
        # process, and without this the code would exist only in the CLI's
        # memory and every fresh code would be refused. Spent and expired codes
        # are dropped on load rather than resurrected.
        now = float(self._clock())
        loaded_codes: dict[str, EnrollmentCode] = {}
        for entry in raw.get("codes") or []:
            try:
                code_hash = str(entry["code_hash"])
                created_at = float(entry["created_at"])
                expires_at = float(entry["expires_at"])
            except (TypeError, KeyError, ValueError):
                continue
            code = EnrollmentCode(code=code_hash, created_at=created_at, expires_at=expires_at)
            if code.valid_at(now):
                loaded_codes[code_hash] = code
        with self._lock:
            self._devices = loaded
            self._codes = loaded_codes
        self._stamp = self._current_stamp()

    def _current_stamp(self) -> float | None:
        if self._path is None:
            return None
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None

    def reload_if_changed(self) -> bool:
        """Re-read the trust store when another process rewrote it.

        Enrollment is a host-side action: the operator adds a device with a CLI
        on the machine that runs the gateway, not over HTTP. That is why there
        is no unauthenticated enrollment endpoint — it would be the only write
        in the API reachable without a signature, and anything on the tailnet
        could call it.

        The consequence is that the file can change under a running server, so
        the store notices rather than serving a stale trust list until restart.
        """
        if self._path is None:
            return False
        stamp = self._current_stamp()
        if stamp is None or stamp == self._stamp:
            return False
        self._load()
        return True

    def _save(self) -> None:
        if self._path is None:
            return
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Only live codes are persisted: a spent or expired one is left off, so
        # single use survives a restart and the file is self-healing. The code
        # itself is never written — only its digest.
        now = float(self._clock())
        live_codes = [
            {
                "code_hash": code_hash,
                "created_at": entry.created_at,
                "expires_at": entry.expires_at,
            }
            for code_hash, entry in self._codes.items()
            if entry.valid_at(now)
        ]
        payload = {
            "version": 1,
            "devices": [asdict(d) for d in self._devices.values()],
            "codes": live_codes,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        # Atomic replace: a half-written trust store is a gateway that either
        # rejects everyone or, worse, comes up believing the wrong devices.
        os.replace(tmp, self._path)
        self._stamp = self._current_stamp()

    # -- host-side enrollment ---------------------------------------------

    def add_device(
        self,
        *,
        curve: str,
        public_key: str,
        label: str | None = None,
        fcm_token: str | None = None,
        device_id: str | None = None,
        permissions: list[str] | None = None,
        owner_id: str = "",
    ) -> Device:
        """Register a device without an enrollment code.

        The intended entry point. The code flow exists for a second, physical
        path to the same result — pairing a phone by reading a short string off
        this machine — but the authoritative act is a human running a command on
        the host, and this is it.
        """
        if curve not in SUPPORTED_CURVES:
            raise EnrollmentRejected(f"unsupported curve: {curve!r}")
        if not public_key:
            raise EnrollmentRejected("public_key is required")
        now = float(self._clock())
        with self._lock:
            identifier = device_id or f"dev-{secrets.token_hex(8)}"
            device = Device(
                device_id=identifier,
                curve=curve,
                public_key=public_key,
                label=label,
                fcm_token=fcm_token,
                permissions=normalise_permissions(permissions),
                owner_id=owner_id,
                created_at=now,
                # `_save` below writes the file, so this is the truthful
                # "last persisted" time. Without it the first authenticated
                # request from a freshly added device finds `persisted_at` unset,
                # concludes it is stale, and rewrites a file that was just
                # written a moment earlier.
                persisted_at=now,
            )
            self._devices[identifier] = device
            self._save()
            return device

    # -- enrollment --------------------------------------------------------

    def issue_enrollment_code(self, *, ttl: float = ENROLLMENT_TTL_SECONDS) -> EnrollmentCode:
        """Mint a single-use pairing code. The operator reads it off the host.

        The code is persisted to the trust store as a hash, so the process that
        prints it (``herdr-notify enroll``) and the process that validates it
        (the running ``serve`` gateway) can be the different processes they are:
        the gateway notices the file changed via :meth:`reload_if_changed` and
        accepts the code. Kept in memory alone, the code the CLI printed would
        never reach the gateway and every fresh code would be refused.
        """
        with self._lock:
            self._prune_codes()
            code = base64.b32encode(os.urandom(ENROLLMENT_CODE_BYTES)).decode().rstrip("=")
            now = float(self._clock())
            entry = EnrollmentCode(code=code, created_at=now, expires_at=now + ttl)
            self._codes[_enrollment_hash(code)] = entry
            self._save()
            return entry

    def enroll(
        self,
        *,
        code: str,
        curve: str,
        public_key: str,
        label: str | None = None,
        fcm_token: str | None = None,
        device_id: str | None = None,
        permissions: list[str] | None = None,
        owner_id: str = "",
    ) -> Device:
        """Register a device against a valid enrollment code.

        The code is validated first and consumed only once the request is known
        to be able to succeed. See the comment at the consumption point for why
        that ordering is the one that matters.
        """
        if not code:
            raise EnrollmentRejected("enrollment code is required")

        now = float(self._clock())
        with self._lock:
            entry = self._codes.get(_enrollment_hash(code))
            if entry is None or not entry.valid_at(now):
                self._prune_codes()
                raise EnrollmentRejected("enrollment code is unknown, expired, or used")

            # Validate before consuming. An enrollment code is a secret the
            # operator reads off this machine, and it has exactly one purpose:
            # to let one phone in, once. If a malformed request burned it, then
            # anyone who ever saw the code — in a terminal scrollback, a screen
            # share, a pasted log — could deny the legitimate phone its pairing
            # by sending a body that was never going to work. The operator would
            # see "invalid code" and have to reissue, with no way to tell a
            # network retry from an attempt.
            if curve not in SUPPORTED_CURVES:
                raise EnrollmentRejected(f"unsupported curve: {curve!r}")
            if not public_key:
                raise EnrollmentRejected("public_key is required")

            # Only now is the code spent. From here the request is guaranteed to
            # register a device, so a failure after this point is a bug rather
            # than a client's mistake.
            entry.used = True

            identifier = device_id or f"dev-{secrets.token_hex(8)}"
            device = Device(
                device_id=identifier,
                curve=curve,
                public_key=public_key,
                label=label,
                fcm_token=fcm_token,
                permissions=normalise_permissions(permissions),
                owner_id=owner_id,
                created_at=now,
                persisted_at=now,
            )
            self._devices[identifier] = device
            self._save()
            return device

    def _prune_codes(self) -> None:
        now = float(self._clock())
        for code in [c for c, e in self._codes.items() if e.used or now >= e.expires_at]:
            self._codes.pop(code, None)

    # -- recovery codes ----------------------------------------------------

    def issue_recovery_code(self, device_id: str) -> str | None:
        """Mint (and rotate) a device's recovery code. Returns it once, or None.

        The plaintext is returned to the caller and never stored: only its hash
        lives in the trust store. Any previous code stops working immediately,
        so "show a new recovery code" is also "revoke the old one".
        """
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return None
            code = _new_recovery_code()
            device.recovery_code_hash = _recovery_hash(code)
            self._save()
            return code

    def use_recovery_code(
        self,
        *,
        code: str,
        curve: str,
        public_key: str,
        label: str | None = None,
        owner_id: str = "",
    ) -> tuple[Device, str]:
        """Re-key the device that owns ``code`` and return (device, new code).

        Re-pairing keeps the device id and its grants, replaces the public key
        (a reinstall generates a fresh one), un-revokes nothing — a revoked
        device's code is refused, because revocation must be durable. The code
        is validated before any mutation, then rotated in the same lock.
        """
        if not code:
            raise EnrollmentRejected("recovery code is required")
        if curve not in SUPPORTED_CURVES:
            raise EnrollmentRejected(f"unsupported curve: {curve!r}")
        if not public_key:
            raise EnrollmentRejected("public_key is required")

        digest = _recovery_hash(code)
        with self._lock:
            device = next(
                (
                    d
                    for d in self._devices.values()
                    if d.recovery_code_hash == digest and not d.revoked
                ),
                None,
            )
            if device is None:
                raise EnrollmentRejected("recovery code is unknown or the device is revoked")

            device.curve = curve
            device.public_key = public_key
            if label is not None:
                device.label = label
            if owner_id:
                device.owner_id = owner_id
            rotated = _new_recovery_code()
            device.recovery_code_hash = _recovery_hash(rotated)
            self._save()
            return device, rotated

    # -- lookup ------------------------------------------------------------

    def get(self, device_id: str) -> Device | None:
        with self._lock:
            return self._devices.get(device_id)

    def get_trusted(self, device_id: str) -> Device | None:
        """Return the device only if it exists, is trusted, and is not revoked."""
        device = self.get(device_id)
        if device is None or device.revoked:
            return None
        return device

    def list(self) -> list[Device]:
        with self._lock:
            return sorted(self._devices.values(), key=lambda d: d.created_at)

    def touch(self, device_id: str) -> None:
        """Record that a device was just seen.

        The in-memory stamp is always updated — it is what the health endpoint
        and the CLI read — but the file is only rewritten when the previous write
        is older than :data:`TOUCH_PERSIST_INTERVAL`. Every authenticated request
        calls this, and a save is a ``write_text`` plus an ``os.replace``. An SSE
        stream alone is one long-lived request, but a phone reconnecting in a
        loop would otherwise turn reads into a stream of disk writes on the
        host's filesystem, which is an amplifier a buggy client should not have.
        """
        now = float(self._clock())
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return
            device.last_seen_at = now
            previous = device.persisted_at
            if previous is not None and now - previous < TOUCH_PERSIST_INTERVAL:
                return
            device.persisted_at = now
        self._save()

    def set_fcm_token(self, device_id: str, token: str) -> None:
        """Attach or replace this device's FCM token after a rotation."""
        with self._lock:
            device = self._devices.get(device_id)
            if device is not None:
                device.fcm_token = token
                self._save()

    def clear_fcm_token(self, device_id: str) -> None:
        """Drop this device's FCM token after the server reported it dead.

        The push sender's prune path: Google reports a token as permanently
        unregistered, and keeping it would make every later send retry a send
        that cannot succeed. Only the token goes — the device itself is
        untouched, and the app re-registers a fresh one on its next connection.
        """
        with self._lock:
            device = self._devices.get(device_id)
            if device is not None:
                device.fcm_token = None
                self._save()

    def revoke(self, device_id: str) -> bool:
        """Revoke instantly by marking rather than deleting.

        Deleting would free the id for re-enrolment, and a revoked device that
        quietly becomes unknown again is harder to audit than one that stays
        visible and refused.
        """
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return False
            device.revoked = True
            device.fcm_token = None
            self._save()
            return True

    def grant(self, device_id: str, permission: str) -> bool:
        """Add one permission to a device's grant set.

        Widening access is a host-side act — this is its entry point, the same
        reasoning as :meth:`add_device`: there is no HTTP grant endpoint, and
        an authenticated device granting itself permissions would be
        escalation. An unknown permission is refused rather than stored to
        grant nothing.
        """
        if permission not in SUPPORTED_PERMISSIONS:
            raise ValueError(f"unsupported permission: {permission!r}")
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return False
            if permission not in device.permissions:
                device.permissions = sorted([*device.permissions, permission])
                self._save()
            return True

    def revoke_permission(self, device_id: str, permission: str) -> bool:
        """Remove one permission from a device's grant set.

        The narrower version of :meth:`revoke`: the device stays trusted and
        visible, but this one operation stops being allowed. An explicitly
        stored empty set stays empty — a device whose READ_STATE was revoked
        is refused on the read paths, and answers 403 there rather than 401.
        """
        if permission not in SUPPORTED_PERMISSIONS:
            raise ValueError(f"unsupported permission: {permission!r}")
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return False
            if permission in device.permissions:
                device.permissions = sorted(
                    p for p in device.permissions if p != permission
                )
                self._save()
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._devices)

    @property
    def path(self) -> Path | None:
        return self._path


__all__ = [
    "CURVE_ED25519",
    "CURVE_P256",
    "ENROLLMENT_TTL_SECONDS",
    "PERMISSION_ADMIN",
    "PERMISSION_APPROVE",
    "PERMISSION_READ_STATE",
    "PERMISSION_RESPOND",
    "PERMISSION_SEND_KEY",
    "RECOVERY_CODE_BYTES",
    "SUPPORTED_CURVES",
    "SUPPORTED_PERMISSIONS",
    "Curve",
    "Device",
    "DeviceStore",
    "EnrollmentCode",
    "EnrollmentRejected",
    "Permission",
]
