"""Fase 2(c): pairing, tailnet auto-approval, peers, devices, recovery.

The properties under test are the ones an attacker would attack: a pairing code
that survives its single use, a recovery code that survives its rotation, an
auto-approval that fires for the wrong account, a revoke that leaves the old key
working, and a device roster that leaks a secret. The gateway can drive real
coding agents, so each of these is a way in if it is wrong.
"""

from __future__ import annotations

import base64
import secrets
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from herdr_notify.api.app import ApiConfig, AppContext, _empty_code_detail, create_app
from herdr_notify.api.auth import (
    CURVE_P256,
    HEADER_DEVICE,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    PERMISSION_ADMIN,
    PERMISSION_READ_STATE,
    DeviceStore,
    RequestVerifier,
    build_signing_string,
)
from herdr_notify.api.ratelimit import RateLimiter, StreamRegistry
from herdr_notify.state.store import Store
from herdr_notify.tailnet import Whois, parse_status


def signed(key: Any, method: str, path: str, device_id: str, body: bytes = b"") -> dict[str, str]:
    """A valid signature from an arbitrary P-256 key, for one request."""
    moment = int(time.time())
    nonce = base64.b64encode(secrets.token_bytes(16)).decode()
    message = build_signing_string(
        method=method, target=path, body=body, timestamp=moment, nonce=nonce
    )
    return {
        HEADER_DEVICE: device_id,
        HEADER_TIMESTAMP: str(moment),
        HEADER_NONCE: nonce,
        HEADER_SIGNATURE: base64.b64encode(
            key.sign(message, ec.ECDSA(hashes.SHA256()))
        ).decode(),
    }


class Phone:
    """A handset: its signing key, its device id, and its recovery code."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.device_id = ""
        self.recovery_code = ""

    def public_key(self) -> str:
        return base64.b64encode(
            self.key.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        ).decode()

    def pair(
        self,
        client: TestClient,
        *,
        code: str | None = None,
        public_key: str | None = None,
        curve: str = CURVE_P256,
    ) -> Any:
        body: dict[str, Any] = {
            "curve": curve,
            "public_key": public_key or self.public_key(),
            "label": self.label,
        }
        if code is not None:
            body["code"] = code
        return client.post("/v1/pair", json=body)

    def remember(self, response: Any) -> None:
        payload = response.json()
        self.device_id = payload["device_id"]
        self.recovery_code = payload["recovery_code"]

    def sign(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        return signed(self.key, method, path, self.device_id, body)


class Harness:
    def __init__(self, tmp_path: Any) -> None:
        self.devices = DeviceStore(tmp_path / "devices.json")
        self.context = AppContext(
            store=Store(),
            devices=self.devices,
            verifier=RequestVerifier(self.devices),
            limiter=RateLimiter(read_per_minute=1000, write_per_minute=1000),
            streams=StreamRegistry(per_device=4),
            client=None,  # type: ignore[arg-type]  # unused by these endpoints
            subscribers=set(),
        )
        self.app = create_app(self.context, ApiConfig(device_store_path=tmp_path / "d.json"))
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def pair(self, label: str = "pixel") -> Phone:
        """Pair a phone with a freshly minted host code."""
        phone = Phone(label)
        response = phone.pair(self.client, code=self.devices.issue_enrollment_code().code)
        assert response.status_code == 200, response.text
        phone.remember(response)
        return phone

    def pair_admin(self, label: str = "admin-phone") -> Phone:
        phone = self.pair(label)
        assert self.devices.grant(phone.device_id, PERMISSION_ADMIN) is True
        return phone


@pytest.fixture
def harness(tmp_path: Any) -> Harness:
    return Harness(tmp_path)


def host_view(owner: str = "12345") -> Any:
    return parse_status(
        {
            "BackendState": "Running",
            "Self": {
                "DNSName": "desktop.tail.ts.net.",
                "TailscaleIPs": ["100.64.0.1"],
                "UserID": int(owner),
            },
        }
    )


# -- (1) pairing by code ----------------------------------------------------


def test_pair_with_a_code_registers_a_usable_device(harness: Harness) -> None:
    phone = Phone("pixel")
    response = phone.pair(harness.client, code=harness.devices.issue_enrollment_code().code)
    assert response.status_code == 200
    phone.remember(response)
    assert response.json()["permissions"] == [PERMISSION_READ_STATE]
    assert response.json()["recovery_code"]

    # The registered key authenticates against a normal signed read.
    state = harness.client.get("/v1/state", headers=phone.sign("GET", "/v1/state"))
    assert state.status_code == 200


def test_a_pairing_code_is_single_use(harness: Harness) -> None:
    code = harness.devices.issue_enrollment_code().code
    assert Phone("a").pair(harness.client, code=code).status_code == 200
    second = Phone("b").pair(harness.client, code=code)
    assert second.status_code == 403
    assert second.json() == {"detail": "pairing_rejected"}


def test_an_expired_pairing_code_is_refused(harness: Harness) -> None:
    code = harness.devices.issue_enrollment_code(ttl=0).code
    response = Phone("a").pair(harness.client, code=code)
    assert response.status_code == 403


def test_an_unknown_code_is_refused_uniformly(harness: Harness) -> None:
    response = Phone("a").pair(harness.client, code="ZZZZZZZZ")
    assert response.status_code == 403
    assert response.json() == {"detail": "pairing_rejected"}


def test_a_malformed_pairing_body_is_refused(harness: Harness) -> None:
    assert harness.client.post("/v1/pair", content=b"not json").status_code == 400
    assert (
        harness.client.post("/v1/pair", json={"curve": "rsa", "public_key": "x"}).status_code == 400
    )
    assert harness.client.post("/v1/pair", json={"curve": CURVE_P256}).status_code == 400


def test_a_pairing_body_over_the_cap_is_refused(harness: Harness) -> None:
    response = harness.client.post("/v1/pair", content=b"x" * (8 * 1024 + 1))
    assert response.status_code == 413
    assert response.json() == {"detail": "body too large"}


def test_pairing_by_code_records_the_creation_time(harness: Harness) -> None:
    phone = harness.pair("pixel")
    device = harness.devices.get(phone.device_id)
    assert device is not None
    assert device.created_at > 0.0


def test_pairing_by_code_works_when_tailscale_is_unavailable(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The code path is the host's own proof; it must not need the tailnet."""
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: None)
    monkeypatch.setattr("herdr_notify.api.app.tailnet_whois", lambda ip: None)
    code = harness.devices.issue_enrollment_code().code
    assert Phone("pixel").pair(harness.client, code=code).status_code == 200


def test_a_code_minted_by_the_enroll_cli_pairs_with_a_running_gateway(tmp_path: Any) -> None:
    """The gateway and ``herdr-notify enroll`` are different processes.

    Regression: enrollment codes were kept only in the minting process's memory,
    so a code the CLI printed was invisible to the running gateway and every
    fresh code answered ``403 pairing_rejected`` (the app's "código no válido,
    ya se usó o ha caducado"). The gateway's store and the CLI's store are
    separate instances over one file, which is the real setup.
    """
    path = tmp_path / "devices.json"
    gateway = DeviceStore(path)
    context = AppContext(
        store=Store(),
        devices=gateway,
        verifier=RequestVerifier(gateway),
        limiter=RateLimiter(read_per_minute=1000, write_per_minute=1000),
        streams=StreamRegistry(per_device=4),
        client=None,  # type: ignore[arg-type]  # unused by these endpoints
        subscribers=set(),
    )
    client = TestClient(
        create_app(context, ApiConfig(device_store_path=path)), raise_server_exceptions=False
    )

    first = DeviceStore(path).issue_enrollment_code().code  # the enroll CLI
    assert Phone("pixel").pair(client, code=first).status_code == 200

    # A second, later CLI invocation still pairs: the gateway reloads the store.
    second = DeviceStore(path).issue_enrollment_code().code
    assert Phone("second").pair(client, code=second).status_code == 200

    # And the spent code is refused, so single use survives the process split.
    assert Phone("thief").pair(client, code=first).status_code == 403


# -- (2) tailnet auto-approval ----------------------------------------------


def test_auto_approval_when_whois_matches_the_host_owner(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: host_view())
    monkeypatch.setattr("herdr_notify.api.app.tailnet_whois", lambda ip: Whois(owner_id="12345"))
    response = Phone("pixel").pair(harness.client)
    assert response.status_code == 200
    assert response.json()["owner_id"] == "12345"


def test_auto_approval_is_refused_for_a_different_owner(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: host_view("12345"))
    monkeypatch.setattr("herdr_notify.api.app.tailnet_whois", lambda ip: Whois(owner_id="999"))
    assert Phone("pixel").pair(harness.client).status_code == 403


def test_auto_approval_is_refused_when_tailscale_is_unavailable(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: None)
    monkeypatch.setattr("herdr_notify.api.app.tailnet_whois", lambda ip: None)
    assert Phone("pixel").pair(harness.client).status_code == 403


def test_auto_approval_is_refused_for_a_tagged_node(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tagged node reports no owner, so it must never auto-approve."""
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: host_view())
    monkeypatch.setattr("herdr_notify.api.app.tailnet_whois", lambda ip: None)
    assert Phone("pixel").pair(harness.client).status_code == 403


def test_a_code_less_pairing_is_refused_with_guidance(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a code the owner check is the only proof, so say so.

    The caller already knows it sent no code, so naming that and the working
    path (`herdr-notify enroll`) leaks nothing while turning a baffling refusal
    into an instruction. It must not report the tailnet owner either side.
    """
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: host_view("12345"))
    monkeypatch.setattr("herdr_notify.api.app.tailnet_whois", lambda ip: Whois(owner_id="999"))
    response = Phone("pixel").pair(harness.client)
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "pairing_rejected"
    assert "enroll" in detail["message"]
    assert "12345" not in detail["message"]
    assert "999" not in detail["message"]


def test_the_empty_code_hint_calls_out_a_local_proxy() -> None:
    local = _empty_code_detail("127.0.0.1")
    remote = _empty_code_detail("100.64.0.2")
    assert local["code"] == remote["code"] == "pairing_rejected"
    assert "proxy" in local["message"]
    assert local["message"] != remote["message"]


def test_auto_approval_records_the_creation_time(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: host_view())
    monkeypatch.setattr("herdr_notify.api.app.tailnet_whois", lambda ip: Whois(owner_id="12345"))
    response = Phone("pixel").pair(harness.client)
    assert response.status_code == 200
    device = harness.devices.get(response.json()["device_id"])
    assert device is not None
    assert device.created_at > 0.0


# -- (3) the peer list the phone probes -------------------------------------


def test_peers_lists_addresses_for_a_paired_device(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    phone = harness.pair("watch-only")
    view = parse_status(
        {
            "BackendState": "Running",
            "Self": {"DNSName": "desktop.tail.ts.net.", "TailscaleIPs": ["100.64.0.1"]},
            "Peer": {
                "k": {
                    "DNSName": "tecno.tail.ts.net.",
                    "TailscaleIPs": ["100.64.0.2"],
                    "Online": True,
                }
            },
        }
    )
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: view)
    response = harness.client.get("/v1/peers", headers=phone.sign("GET", "/v1/peers"))
    assert response.status_code == 200
    body = response.json()
    assert body["self"]["addresses"] == ["100.64.0.1"]
    assert body["peers"][0]["addresses"] == ["100.64.0.2"]


def test_peers_requires_a_signature(harness: Harness) -> None:
    assert harness.client.get("/v1/peers").status_code == 401


def test_peers_is_503_when_tailscale_is_unavailable(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    phone = harness.pair("pixel")
    monkeypatch.setattr("herdr_notify.api.app.read_tailnet_status", lambda: None)
    response = harness.client.get("/v1/peers", headers=phone.sign("GET", "/v1/peers"))
    assert response.status_code == 503
    assert response.json() == {"detail": "tailscale unavailable"}


# -- (4) my devices: list and revoke ----------------------------------------


def test_listing_devices_requires_a_signature(harness: Harness) -> None:
    assert harness.client.get("/v1/devices").status_code == 401


def test_listing_devices_requires_admin(harness: Harness) -> None:
    phone = harness.pair("read-only")
    assert phone.sign  # the phone is real; it just lacks the grant
    response = harness.client.get("/v1/devices", headers=phone.sign("GET", "/v1/devices"))
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


def test_an_admin_lists_every_paired_device_without_secrets(harness: Harness) -> None:
    admin = harness.pair_admin()
    other = harness.pair("other")
    response = harness.client.get("/v1/devices", headers=admin.sign("GET", "/v1/devices"))
    assert response.status_code == 200
    devices = response.json()["devices"]
    assert {d["device_id"] for d in devices} == {admin.device_id, other.device_id}
    assert all("public_key" not in d and "fcm_token" not in d for d in devices)
    assert all("owner_id" in d for d in devices)


def test_an_admin_can_revoke_a_device_and_its_token_dies(harness: Harness) -> None:
    admin = harness.pair_admin()
    victim = harness.pair("victim")
    path = f"/v1/devices/{victim.device_id}/revoke"
    before = harness.client.get("/v1/state", headers=victim.sign("GET", "/v1/state"))
    assert before.status_code == 200

    response = harness.client.post(path, headers=admin.sign("POST", path))
    assert response.status_code == 200
    assert response.json() == {"ok": True, "device_id": victim.device_id, "revoked": True}

    after = harness.client.get("/v1/state", headers=victim.sign("GET", "/v1/state"))
    assert after.status_code == 401


def test_revoking_requires_admin(harness: Harness) -> None:
    phone = harness.pair("read-only")
    path = f"/v1/devices/{phone.device_id}/revoke"
    response = harness.client.post(path, headers=phone.sign("POST", path))
    assert response.status_code == 403


def test_revoking_an_unknown_device_is_404(harness: Harness) -> None:
    admin = harness.pair_admin()
    path = "/v1/devices/dev-nope/revoke"
    response = harness.client.post(path, headers=admin.sign("POST", path))
    assert response.status_code == 404
    assert response.json() == {"detail": "no such device"}


# -- (5) recovery codes -----------------------------------------------------


def test_recovery_code_re_pairs_without_approval_and_rotates(harness: Harness) -> None:
    phone = harness.pair("pixel")
    assert phone.recovery_code

    # A reinstall generates a fresh key; recovery re-keys the same device.
    reinstall = Phone("pixel")
    response = reinstall.pair(harness.client, code=phone.recovery_code)
    assert response.status_code == 200
    reinstall.remember(response)
    rotated = response.json()
    assert rotated["device_id"] == phone.device_id, "recovery keeps the device id"
    assert rotated["recovery_code"] and rotated["recovery_code"] != phone.recovery_code

    # The old code is spent, and the device is on the new key.
    stale = Phone("pixel").pair(harness.client, code=phone.recovery_code)
    assert stale.status_code == 403
    assert (
        harness.client.get("/v1/state", headers=reinstall.sign("GET", "/v1/state")).status_code
        == 200
    )
    old = signed(phone.key, "GET", "/v1/state", phone.device_id)
    assert harness.client.get("/v1/state", headers=old).status_code == 401


def test_a_revoked_device_cannot_use_its_recovery_code(harness: Harness) -> None:
    phone = harness.pair("pixel")
    assert harness.devices.revoke(phone.device_id) is True
    response = Phone("pixel").pair(harness.client, code=phone.recovery_code)
    assert response.status_code == 403


def test_issuing_a_new_recovery_code_rotates_the_old_one(harness: Harness) -> None:
    phone = harness.pair("pixel")
    first = phone.recovery_code
    second = harness.devices.issue_recovery_code(phone.device_id)
    assert second is not None and second != first
    # The rotated-out code no longer re-pairs.
    assert Phone("pixel").pair(harness.client, code=first).status_code == 403
    assert Phone("pixel").pair(harness.client, code=second).status_code == 200
