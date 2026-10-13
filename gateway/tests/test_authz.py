"""Per-device authorization: the endpoint matrix and the 403 contract.

Authentication is tested in ``test_auth.py`` — who you are. This file tests
what you may do. The properties under test are the ones a compromised or
mis-paired device would attack: an implicit allowance, an endpoint that starts
life authorized, a grant that disappears when it should not, and a 403 that
leaks which check failed. A control plane that can drive coding agents is the
highest-value target in the project; "authenticated, therefore all-powerful" is
exactly the gap this closes.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from herdr_notify.api.auth import (
    PERMISSION_ADMIN,
    PERMISSION_APPROVE,
    PERMISSION_READ_STATE,
    PERMISSION_RESPOND,
    PERMISSION_SEND_KEY,
    SUPPORTED_PERMISSIONS,
    AuthError,
    DeviceStore,
    Permission,
    Rejection,
    RequestVerifier,
    build_signing_string,
)
from herdr_notify.api.auth.authz import (
    AuthorizationError,
    AuthzRejection,
    UnknownEndpoint,
    authorize,
    required_permission,
)

BODY = json.dumps({"text": "sí, hazlo"}).encode()
TARGET = "/v1/agents/w1:p1/respond"


class Clock:
    def __init__(self, start: float | None = None) -> None:
        self.now = time.time() if start is None else start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def p256_keypair() -> tuple[Any, bytes]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return key, public


class Enrolled:
    """A device that has been through the real enrollment flow."""

    def __init__(
        self,
        store: DeviceStore | None = None,
        *,
        permissions: list[str] | None = None,
    ) -> None:
        self.clock = Clock()
        self.store = store if store is not None else DeviceStore(clock=self.clock)
        self.key, public = p256_keypair()
        code = self.store.issue_enrollment_code().code
        self.device = self.store.enroll(
            code=code,
            curve="p256",
            public_key=base64.b64encode(public).decode(),
            permissions=permissions,
        )

    def headers(
        self, *, method: str = "POST", target: str = TARGET, body: bytes = BODY
    ) -> dict[str, str]:
        moment = int(self.clock.now)
        nonce = base64.b64encode(secrets.token_bytes(16)).decode()
        message = build_signing_string(
            method=method, target=target, body=body, timestamp=moment, nonce=nonce
        )
        return {
            "X-HN-Device": self.device.device_id,
            "X-HN-Timestamp": str(moment),
            "X-HN-Nonce": nonce,
            "X-HN-Signature": base64.b64encode(
                self.key.sign(message, ec.ECDSA(hashes.SHA256()))
            ).decode(),
        }

    def verify(self, headers: dict[str, str], **kwargs: Any) -> Any:
        return RequestVerifier(self.store, clock=self.clock).verify(
            method=kwargs.pop("method", "POST"),
            target=kwargs.pop("target", TARGET),
            body=kwargs.pop("body", BODY),
            headers=headers,
        )


# -- the pairing default ----------------------------------------------------


def test_the_pairing_default_is_read_state_only() -> None:
    """The specification: a newly paired device may observe and nothing more."""
    device = Enrolled()
    assert device.device.permissions == [PERMISSION_READ_STATE]


def test_an_authorized_device_passes_its_granted_endpoints() -> None:
    device = Enrolled(permissions=[PERMISSION_RESPOND, PERMISSION_SEND_KEY])
    authorize(device.device, method="POST", target=TARGET)
    authorize(device.device, method="POST", target="/v1/agents/w1:p1/keys")
    # READ_STATE is the pairing default and is always granted at enrollment.
    authorize(device.device, method="GET", target="/v1/state")
    authorize(device.device, method="GET", target="/v1/events")


def test_the_endpoint_matrix_is_exact() -> None:
    """Every endpoint's required permission, derived from the real surface.

    This table is the contract in ``docs/contracts/auth.md``. The matrix is
    load-bearing: a rule added to the code without being added here — or the
    other way round — is a contract break.
    """
    cases = [
        ("GET", "/v1/health", None),
        ("GET", "/v1/state", Permission.READ_STATE),
        ("GET", "/v1/state?rev=4", Permission.READ_STATE),
        ("GET", "/v1/events", Permission.READ_STATE),
        ("POST", "/v1/agents/w1:p1/respond", Permission.RESPOND),
        ("POST", "/v1/agents/w1:p1/keys", Permission.SEND_KEY),
        ("POST", "/v1/agents/w1:p1/focus", Permission.RESPOND),
        ("POST", "/v1/agents/w1:p1/seen", Permission.READ_STATE),
        ("POST", "/v1/agents/w1:p1/read", Permission.READ_STATE),
        ("POST", "/v1/agents/w1:p1/image", Permission.RESPOND),
        ("POST", "/v1/me/fcm-token", None),
        ("post", "/v1/me/fcm-token", None),
        ("get", "/v1/health", None),
    ]
    for method, target, expected in cases:
        assert required_permission(method, target) == expected, (method, target)


def test_a_method_no_rule_covers_fails_closed() -> None:
    """GET on a POST endpoint, or DELETE on anything, has no rule."""
    with pytest.raises(UnknownEndpoint):
        required_permission("GET", "/v1/agents/w1:p1/respond")
    with pytest.raises(UnknownEndpoint):
        required_permission("DELETE", "/v1/state")
    with pytest.raises(UnknownEndpoint):
        required_permission("PUT", "/v1/state")


def test_an_endpoint_without_a_matrix_rule_is_refused() -> None:
    """A new endpoint cannot start life authorized by accident.

    The matrix is load-bearing: an endpoint added without a rule fails closed
    even for a device granted every permission, because an implicit allowance
    is exactly the failure mode M2 exists to close.
    """
    device = Enrolled(permissions=list(SUPPORTED_PERMISSIONS))
    with pytest.raises(AuthorizationError) as excinfo:
        authorize(device.device, method="POST", target="/v1/agents/w1:p1/restart")
    assert excinfo.value.rejection is AuthzRejection.UNKNOWN_ENDPOINT


def test_an_authenticated_device_without_the_grant_is_refused() -> None:
    """A valid signature says who you are, not what you may do."""
    device = Enrolled()
    with pytest.raises(AuthorizationError) as excinfo:
        authorize(device.device, method="POST", target=TARGET)
    assert excinfo.value.rejection is AuthzRejection.NOT_PERMITTED
    assert excinfo.value.required is Permission.RESPOND
    assert excinfo.value.public_message == "forbidden"


def test_the_caller_is_not_told_which_grant_failed() -> None:
    """The same oracle reasoning as the uniform 401."""
    device = Enrolled()
    with pytest.raises(AuthorizationError) as respond:
        authorize(device.device, method="POST", target=TARGET)
    with pytest.raises(AuthorizationError) as keys:
        authorize(device.device, method="POST", target="/v1/agents/w1:p1/keys")
    assert respond.value.public_message == keys.value.public_message == "forbidden"


def test_authorization_never_widens_authentication() -> None:
    """Unknown and revoked are authentication failures, whatever the grants."""
    device = Enrolled(permissions=list(SUPPORTED_PERMISSIONS))
    device.store.revoke(device.device.device_id)
    with pytest.raises(AuthError) as excinfo:
        device.verify(device.headers())
    assert excinfo.value.rejection is Rejection.REVOKED


def test_a_revoked_device_is_401_not_403() -> None:
    """Revocation is an authentication failure; under-granting is not.

    The client must be able to tell "re-pair" from "you lack a grant", so a
    revoked device is refused by the verifier even for an endpoint it was never
    granted — the order of checks decides which answer it gets.
    """
    device = Enrolled(permissions=[PERMISSION_RESPOND])
    device.store.revoke(device.device.device_id)
    with pytest.raises(AuthError) as excinfo:
        device.verify(device.headers())
    assert excinfo.value.rejection is Rejection.REVOKED


# -- the store's grant set --------------------------------------------------


def test_grant_adds_one_permission(tmp_path: Any) -> None:
    devices = DeviceStore(tmp_path / "devices.json")
    device = Enrolled(devices)
    assert devices.grant(device.device.device_id, PERMISSION_RESPOND) is True
    loaded = devices.get(device.device.device_id)
    assert loaded is not None
    assert loaded.permissions == sorted([PERMISSION_READ_STATE, PERMISSION_RESPOND])
    # Granting the same permission twice does not duplicate it.
    devices.grant(device.device.device_id, PERMISSION_RESPOND)
    reloaded = devices.get(device.device.device_id)
    assert reloaded is not None
    assert len(reloaded.permissions) == 2


def test_revoke_permission_removes_one(tmp_path: Any) -> None:
    devices = DeviceStore(tmp_path / "devices.json")
    device = Enrolled(devices, permissions=[PERMISSION_RESPOND, PERMISSION_SEND_KEY])
    assert devices.revoke_permission(device.device.device_id, PERMISSION_RESPOND) is True
    loaded = devices.get(device.device.device_id)
    assert loaded is not None
    assert PERMISSION_RESPOND not in loaded.permissions
    assert PERMISSION_SEND_KEY in loaded.permissions


def test_grant_refuses_an_unknown_permission(tmp_path: Any) -> None:
    """An unknown id is refused, not stored to grant nothing."""
    devices = DeviceStore(tmp_path / "devices.json")
    device = Enrolled(devices)
    with pytest.raises(ValueError):
        devices.grant(device.device.device_id, "root")
    with pytest.raises(ValueError):
        devices.revoke_permission(device.device.device_id, "root")


def test_grant_on_an_unknown_device_returns_false(tmp_path: Any) -> None:
    devices = DeviceStore(tmp_path / "devices.json")
    assert devices.grant("dev-nope", PERMISSION_RESPOND) is False
    assert devices.revoke_permission("dev-nope", PERMISSION_RESPOND) is False


def test_revoking_read_state_closes_the_read_paths(tmp_path: Any) -> None:
    """The narrower version of revoke: still trusted, this one operation stops."""
    devices = DeviceStore(tmp_path / "devices.json")
    device = Enrolled(devices)
    devices.revoke_permission(device.device.device_id, PERMISSION_READ_STATE)
    loaded = devices.get(device.device.device_id)
    assert loaded is not None
    with pytest.raises(AuthorizationError):
        authorize(loaded, method="GET", target="/v1/state")
    with pytest.raises(AuthorizationError):
        authorize(loaded, method="GET", target="/v1/events")
    # The device is still authenticated — 403, never 401 — and not revoked.
    assert loaded.revoked is False


def test_a_grant_survives_a_restart(tmp_path: Any) -> None:
    path = tmp_path / "devices.json"
    device = Enrolled(DeviceStore(path), permissions=[PERMISSION_RESPOND])
    reopened = DeviceStore(path)
    loaded = reopened.get(device.device.device_id)
    assert loaded is not None
    assert loaded.permissions == sorted([PERMISSION_READ_STATE, PERMISSION_RESPOND])


def test_approve_is_reserved_and_admin_guards_device_management() -> None:
    """ADMIN was activated in Fase 2(c); APPROVE stays reserved.

    M2 reserved both with no endpoint. Fase 2(c) gives ADMIN the device
    management surface (``/v1/devices``); APPROVE still maps to nothing.
    Granting APPROVE therefore changes no answer, while ADMIN now allows the
    device roster — and only that.
    """
    device = Enrolled(permissions=[PERMISSION_APPROVE, PERMISSION_ADMIN])
    loaded = device.device
    assert PERMISSION_APPROVE in loaded.permissions
    assert PERMISSION_ADMIN in loaded.permissions
    # Holding APPROVE does not widen access to the action endpoints.
    with pytest.raises(AuthorizationError):
        authorize(loaded, method="POST", target=TARGET)
    # ADMIN is the grant behind device management.
    assert required_permission("GET", "/v1/devices") is Permission.ADMIN
    assert required_permission("POST", "/v1/devices/dev-x/revoke") is Permission.ADMIN


# -- migration --------------------------------------------------------------


def test_a_pre_m2_record_loads_with_the_pairing_default(tmp_path: Any) -> None:
    """Records written before M2 have no permissions field.

    The migration gives them READ_STATE, which preserves exactly the behaviour
    M1 verified — read paths only — without re-pairing.
    """
    path = tmp_path / "devices.json"
    _, public = p256_keypair()
    legacy = {
        "device_id": "dev-legacy",
        "curve": "p256",
        "public_key": base64.b64encode(public).decode(),
        "label": "pixel",
        "created_at": 1730000000.0,
        "last_seen_at": None,
        "revoked": False,
        "fcm_token": None,
        "persisted_at": 1730000000.0,
    }
    path.write_text(json.dumps({"version": 1, "devices": [legacy]}), encoding="utf-8")
    loaded = DeviceStore(path).get("dev-legacy")
    assert loaded is not None
    assert loaded.permissions == [PERMISSION_READ_STATE]


def test_an_unknown_permission_id_grants_nothing_on_load(tmp_path: Any) -> None:
    """A typo in a stored set grants nothing rather than guessing."""
    path = tmp_path / "devices.json"
    _, public = p256_keypair()
    record = {
        "device_id": "dev-legacy",
        "curve": "p256",
        "public_key": base64.b64encode(public).decode(),
        "revoked": False,
        "permissions": ["respond", "resp0nd", "root"],
    }
    path.write_text(json.dumps({"version": 1, "devices": [record]}), encoding="utf-8")
    loaded = DeviceStore(path).get("dev-legacy")
    assert loaded is not None
    assert loaded.permissions == [PERMISSION_RESPOND]


def test_an_explicitly_empty_grant_set_stays_empty(tmp_path: Any) -> None:
    """Fail closed: a stored empty set is a device that may do nothing."""
    path = tmp_path / "devices.json"
    _, public = p256_keypair()
    record = {
        "device_id": "dev-empty",
        "curve": "p256",
        "public_key": base64.b64encode(public).decode(),
        "revoked": False,
        "permissions": [],
    }
    path.write_text(json.dumps({"version": 1, "devices": [record]}), encoding="utf-8")
    loaded = DeviceStore(path).get("dev-empty")
    assert loaded is not None
    assert loaded.permissions == []
    with pytest.raises(AuthorizationError):
        authorize(loaded, method="GET", target="/v1/state")
    with pytest.raises(AuthorizationError):
        authorize(loaded, method="POST", target=TARGET)


# -- /seen needs READ_STATE only --------------------------------------------

SEEN = "/v1/agents/w1:p1/seen"


def test_a_read_only_device_can_mark_seen_but_not_respond() -> None:
    """Marking seen is non-destructive; answering an agent is not."""
    device = Enrolled()
    assert device.device.permissions == [PERMISSION_READ_STATE]
    authorize(device.device, method="POST", target=SEEN)
    with pytest.raises(AuthorizationError) as excinfo:
        authorize(device.device, method="POST", target=TARGET)
    assert excinfo.value.rejection is AuthzRejection.NOT_PERMITTED
    assert excinfo.value.required is Permission.RESPOND


def test_a_responder_can_still_do_both() -> None:
    device = Enrolled(permissions=[PERMISSION_RESPOND])
    authorize(device.device, method="POST", target=SEEN)
    authorize(device.device, method="POST", target=TARGET)


def test_a_device_with_no_permissions_cannot_mark_seen() -> None:
    device = Enrolled()
    device.device.permissions = []
    with pytest.raises(AuthorizationError) as excinfo:
        authorize(device.device, method="POST", target=SEEN)
    assert excinfo.value.rejection is AuthzRejection.NOT_PERMITTED
    assert excinfo.value.required is Permission.READ_STATE
    assert excinfo.value.public_message == "forbidden"
