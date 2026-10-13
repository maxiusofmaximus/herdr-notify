"""Public-key request authentication.

The properties under test are the ones an attacker would attack: replay, curve
confusion, enumeration, and revocation lag. If any of these pass by accident the
control plane is driveable by anyone who can reach it, because the gateway can
send prompts and keystrokes to real coding agents on the host.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from herdr_notify.api.auth import (
    CURVE_ED25519,
    CURVE_P256,
    HEADER_DEVICE,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    TOUCH_PERSIST_INTERVAL,
    AuthError,
    CanonicalizationError,
    DeviceStore,
    EnrollmentRejected,
    NonceCache,
    Rejection,
    RequestVerifier,
    build_signing_string,
    verify_signature,
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


def ed25519_keypair() -> tuple[Any, bytes]:
    key = ed25519.Ed25519PrivateKey.generate()
    return key, key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )


def sign_p256(key: Any, message: bytes) -> bytes:
    # Android's SHA256withECDSA emits DER; match it exactly.
    return key.sign(message, ec.ECDSA(hashes.SHA256()))


def sign_ed25519(key: Any, message: bytes) -> bytes:
    return key.sign(message)


class Enrolled:
    """A device that has been through enrollment, plus its signing key."""

    def __init__(self, curve: str = CURVE_P256, store: DeviceStore | None = None) -> None:
        self.clock = Clock()
        self.store = store if store is not None else DeviceStore(clock=self.clock)
        self.curve = curve
        self.key, public = p256_keypair() if curve == CURVE_P256 else ed25519_keypair()
        code = self.store.issue_enrollment_code().code
        self.device = self.store.enroll(
            code=code,
            curve=curve,
            public_key=base64.b64encode(public).decode(),
            label="pixel",
        )
        self.verifier = RequestVerifier(self.store, clock=self.clock)

    def headers(
        self,
        *,
        method: str = "POST",
        target: str = TARGET,
        body: bytes = BODY,
        nonce: str | None = None,
        timestamp: int | None = None,
        sign: bool = True,
        sign_with: Any = None,
    ) -> dict[str, str]:
        moment = int(self.clock.now) if timestamp is None else timestamp
        unique = nonce if nonce is not None else base64.b64encode(secrets.token_bytes(16)).decode()
        message = build_signing_string(
            method=method, target=target, body=body, timestamp=moment, nonce=unique
        )
        key = sign_with if sign_with is not None else self.key
        signature = (
            sign_p256(key, message) if self.curve == CURVE_P256 else sign_ed25519(key, message)
        )
        headers = {
            HEADER_DEVICE: self.device.device_id,
            HEADER_TIMESTAMP: str(moment),
            HEADER_NONCE: unique,
            HEADER_SIGNATURE: base64.b64encode(signature).decode(),
        }
        if not sign:
            headers[HEADER_SIGNATURE] = base64.b64encode(b"not-a-signature").decode()
        return headers

    def verify(self, headers: dict[str, str], **kwargs: Any) -> Any:
        return self.verifier.verify(
            method=kwargs.pop("method", "POST"),
            target=kwargs.pop("target", TARGET),
            body=kwargs.pop("body", BODY),
            headers=headers,
        )


# -- canonicalization ------------------------------------------------------


def test_signing_string_is_field_separated_and_lf_terminated() -> None:
    message = build_signing_string(
        method="post", target="/v1/x", body=b"{}", timestamp=123, nonce="n1"
    )
    assert message.endswith(b"\n")
    assert message.count(b"\n") == 5
    # Method is upper-cased so "post" and "POST" cannot sign differently.
    assert message.startswith(b"POST\n/v1/x\n")


def test_signing_string_hashes_the_body_not_the_body_text() -> None:
    import hashlib

    a = build_signing_string(method="GET", target="/x", body=b'{"a":1}', timestamp=1, nonce="n")
    b = build_signing_string(method="GET", target="/x", body=b'{"a": 1}', timestamp=1, nonce="n")
    # Different bytes, so different digest, so different signature. This is the
    # property that makes a re-serialised body detectable rather than ambiguous.
    assert a != b
    assert hashlib.sha256(b'{"a":1}').hexdigest() in a.decode()


def test_signing_string_rejects_a_relative_target() -> None:
    with pytest.raises(CanonicalizationError):
        build_signing_string(method="GET", target="v1/x", body=b"", timestamp=1, nonce="n")


def test_signing_string_rejects_a_newline_in_the_nonce() -> None:
    """Otherwise a nonce could impersonate a field boundary."""
    with pytest.raises(CanonicalizationError):
        build_signing_string(method="GET", target="/x", body=b"", timestamp=1, nonce="a\nb")


def test_signing_string_refuses_an_oversized_body() -> None:
    with pytest.raises(CanonicalizationError):
        build_signing_string(
            method="POST", target="/x", body=b"a" * (256 * 1024 + 1), timestamp=1, nonce="n"
        )


# -- happy path ------------------------------------------------------------


def test_a_correctly_signed_request_is_accepted() -> None:
    device = Enrolled()
    verified = device.verify(device.headers())
    assert verified.device_id == device.device.device_id
    assert verified.device.label == "pixel"


def test_ed25519_devices_are_accepted_too() -> None:
    device = Enrolled(curve=CURVE_ED25519)
    assert device.verify(device.headers()).device_id == device.device.device_id


def test_header_lookup_is_case_insensitive() -> None:
    device = Enrolled()
    headers = {k.lower(): v for k, v in device.headers().items()}
    assert device.verify(headers).device_id == device.device.device_id


# -- the attacks -----------------------------------------------------------


def test_a_signature_over_a_different_body_is_rejected() -> None:
    """The exact attack a body-hash prevents: tamper with the payload in flight."""
    device = Enrolled()
    headers = device.headers(body=b'{"text":"original"}')
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers, body=b'{"text":"rm -rf /"}')
    assert excinfo.value.rejection is Rejection.BAD_SIGNATURE


def test_a_signature_over_a_different_path_is_rejected() -> None:
    """Path confusion: an approve action must not replay as a send-keys action."""
    device = Enrolled()
    headers = device.headers(target="/v1/agents/w1:p1/approve")
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers, target="/v1/agents/w2:p1/approve")
    assert excinfo.value.rejection is Rejection.BAD_SIGNATURE


def test_a_signature_over_a_different_method_is_rejected() -> None:
    device = Enrolled()
    headers = device.headers(method="DELETE")
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers, method="GET")
    assert excinfo.value.rejection is Rejection.BAD_SIGNATURE


def test_replaying_an_exact_request_is_rejected() -> None:
    """A timestamp alone is not enough; the nonce is what makes this one-shot."""
    device = Enrolled()
    headers = device.headers()
    assert device.verify(headers) is not None
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.BAD_NONCE


def test_a_request_from_outside_the_clock_window_is_rejected() -> None:
    device = Enrolled()
    headers = device.headers()
    device.clock.advance(3600)
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.BAD_TIMESTAMP


def test_a_request_from_before_the_window_is_rejected() -> None:
    device = Enrolled()
    headers = device.headers()
    device.clock.advance(-3600)
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.BAD_TIMESTAMP


def test_a_signature_from_a_different_key_is_rejected() -> None:
    device = Enrolled()
    other, _ = p256_keypair()
    headers = device.headers(sign_with=other)
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.BAD_SIGNATURE


def test_an_unknown_device_is_rejected() -> None:
    device = Enrolled()
    headers = device.headers()
    headers[HEADER_DEVICE] = "dev-does-not-exist"
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.UNKNOWN_DEVICE


def test_missing_headers_are_rejected() -> None:
    device = Enrolled()
    for header in (HEADER_DEVICE, HEADER_TIMESTAMP, HEADER_NONCE, HEADER_SIGNATURE):
        headers = device.headers()
        headers.pop(header)
        with pytest.raises(AuthError) as excinfo:
            device.verify(headers)
        assert excinfo.value.rejection is Rejection.NO_HEADERS


def test_a_garbage_signature_is_rejected_without_raising() -> None:
    """A verifier that raises is a DoS primitive, not a check."""
    device = Enrolled()
    headers = device.headers()
    headers[HEADER_SIGNATURE] = "!!!not base64!!!"
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.MALFORMED

    headers = device.headers(sign=False)
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.BAD_SIGNATURE


def test_the_curve_comes_from_the_device_not_the_request() -> None:
    """A caller must not pick the algorithm that verifies its own signature."""
    store = DeviceStore()
    # Register a P-256 device, then present an Ed25519 public key for it.
    key, public = p256_keypair()
    ed_key, ed_public = ed25519_keypair()
    code = store.issue_enrollment_code().code
    device = store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(public).decode())
    assert device.curve == CURVE_P256

    # Even with the record's own curve, an Ed25519 signature over the message
    # cannot verify as P-256.
    message = build_signing_string(method="POST", target=TARGET, body=BODY, timestamp=1, nonce="n")
    assert (
        verify_signature(device.curve, device.public_key, sign_ed25519(ed_key, message), message)
        is False
    )
    assert (
        verify_signature(device.curve, device.public_key, sign_p256(key, message), message) is True
    )
    del ed_public


def test_a_malformed_public_key_fails_cleanly() -> None:
    """A bad signature is a refusal; a bad stored key is our bug.

    verify_signature is honest about the difference so a defect surfaces. The
    verifier is not, because a corrupt trust store must not turn every request
    into a 500 that the phone retries forever.
    """
    message = b"message"
    for bad in (
        "not-base64!!",
        base64.b64encode(b"short").decode(),
        base64.b64encode(b"x" * 31).decode(),
    ):
        with pytest.raises(ValueError):
            verify_signature(CURVE_P256, bad, b"sig", message)

    device = Enrolled()
    # Swap in a corrupt key and confirm the request is refused, not crashed.
    stored = device.store.get(device.device.device_id)
    assert stored is not None
    stored.public_key = "not-base64!!"
    with pytest.raises(AuthError) as excinfo:
        device.verify(device.headers())
    assert excinfo.value.rejection is Rejection.MALFORMED


def test_an_unsupported_curve_in_the_store_is_refused() -> None:
    device = Enrolled()
    stored = device.store.get(device.device.device_id)
    assert stored is not None
    stored.curve = "dsa"
    with pytest.raises(AuthError) as excinfo:
        device.verify(device.headers())
    assert excinfo.value.rejection is Rejection.UNSUPPORTED_CURVE


# -- revocation ------------------------------------------------------------


def test_revocation_takes_effect_immediately() -> None:
    device = Enrolled()
    assert device.verify(device.headers()) is not None
    assert device.store.revoke(device.device.device_id) is True
    with pytest.raises(AuthError) as excinfo:
        device.verify(device.headers())
    assert excinfo.value.rejection is Rejection.REVOKED


def test_revocation_precedes_cryptography() -> None:
    """A revoked device is refused before its signature is even checked."""
    device = Enrolled()
    device.store.revoke(device.device.device_id)
    headers = device.headers()
    with pytest.raises(AuthError) as excinfo:
        device.verify(headers)
    assert excinfo.value.rejection is Rejection.REVOKED


def test_a_revoked_device_loses_its_fcm_token() -> None:
    device = Enrolled()
    device.store.set_fcm_token(device.device.device_id, "fake-fcm-token")
    device.store.revoke(device.device.device_id)
    revoked = device.store.get(device.device.device_id)
    assert revoked is not None and revoked.fcm_token is None


# -- enumeration -----------------------------------------------------------


def test_the_caller_is_not_told_which_check_failed() -> None:
    """Otherwise this endpoint enumerates registered device ids."""
    device = Enrolled()
    unknown = device.headers()
    unknown[HEADER_DEVICE] = "dev-nope"
    with pytest.raises(AuthError) as a:
        device.verify(unknown)
    with pytest.raises(AuthError) as b:
        device.verify(device.headers(sign=False))
    assert a.value.public_message == b.value.public_message == "unauthorized"


# -- enrollment ------------------------------------------------------------


def test_enrollment_requires_a_valid_code() -> None:
    store = DeviceStore()
    with pytest.raises(EnrollmentRejected):
        store.enroll(code="WRONG", curve=CURVE_P256, public_key="x")


def test_an_enrollment_code_is_single_use() -> None:
    store = DeviceStore()
    code = store.issue_enrollment_code().code
    store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode())
    with pytest.raises(EnrollmentRejected):
        store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode())


def test_an_enrollment_code_expires() -> None:
    clock = Clock()
    store = DeviceStore(clock=clock)
    code = store.issue_enrollment_code(ttl=600).code
    clock.advance(601)
    with pytest.raises(EnrollmentRejected):
        store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode())


def test_enrollment_rejects_an_unsupported_curve() -> None:
    store = DeviceStore()
    code = store.issue_enrollment_code().code
    with pytest.raises(EnrollmentRejected):
        store.enroll(code=code, curve="rsa", public_key=base64.b64encode(b"k").decode())


def test_a_rejected_payload_does_not_consume_the_code() -> None:
    """A malformed request must not deny the legitimate phone its pairing.

    The code is a secret the operator reads off this machine and it has one
    purpose: let one phone in, once. If a bad curve burned it, then anyone who
    ever saw the code — terminal scrollback, a screen share, a pasted log —
    could deny the real phone its pairing by sending a body that was never going
    to work. The operator would see "invalid code" with no way to tell a typo
    from an attack.
    """
    store = DeviceStore()
    code = store.issue_enrollment_code().code

    with pytest.raises(EnrollmentRejected):
        store.enroll(code=code, curve="rsa", public_key=base64.b64encode(b"k").decode())
    with pytest.raises(EnrollmentRejected):
        store.enroll(code=code, curve=CURVE_P256, public_key="")

    # The code still works for a request that can actually succeed.
    device = store.enroll(
        code=code,
        curve=CURVE_P256,
        public_key=base64.b64encode(b"k").decode(),
    )
    assert device.curve == CURVE_P256


def test_a_successful_enrollment_still_consumes_the_code() -> None:
    """The single-use property is not weakened by validating first.

    This is the half that matters for a leaked code: consuming late would be
    pointless if a spent code could still be replayed.
    """
    store = DeviceStore()
    code = store.issue_enrollment_code().code
    store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode())

    with pytest.raises(EnrollmentRejected):
        store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode())


def test_touch_persists_at_most_once_per_interval(tmp_path: Any) -> None:
    """Reads must not become a stream of disk writes.

    Every authenticated request calls ``touch``, and a save is a write plus an
    atomic replace. A phone reconnecting in a loop would otherwise turn reads
    into writes on the host's filesystem, which is an amplifier a buggy client
    should not have.
    """
    now = [1000.0]
    path = tmp_path / "devices.json"
    store = DeviceStore(path, clock=lambda: now[0])
    key, public = p256_keypair()
    device = store.add_device(
        curve=CURVE_P256, public_key=base64.b64encode(public).decode(), label="pixel"
    )
    del key

    # `add_device` already wrote the file, and that is the baseline. Asserting
    # against a timestamp taken before it would fail for a reason unrelated to
    # `touch` — the first request legitimately has nothing to do if the record
    # was just persisted.
    mtime = path.stat().st_mtime_ns

    now[0] += 1.0
    store.touch(device.device_id)
    assert path.stat().st_mtime_ns == mtime, "a touch inside the interval must not write"
    # The in-memory stamp is still exact even though the file was not rewritten:
    # it is what /v1/health and the CLI read.
    assert store.get(device.device_id).last_seen_at == pytest.approx(1001.0)  # type: ignore[union-attr]

    now[0] += TOUCH_PERSIST_INTERVAL
    store.touch(device.device_id)
    assert store.get(device.device_id).last_seen_at == pytest.approx(now[0])  # type: ignore[union-attr]


def test_touch_on_an_unknown_device_does_nothing(tmp_path: Any) -> None:
    path = tmp_path / "devices.json"
    store = DeviceStore(path)
    store.touch("dev-does-not-exist")
    assert not path.exists()


# -- persistence -----------------------------------------------------------


def test_devices_survive_a_restart(tmp_path: Any) -> None:
    path = tmp_path / "devices.json"
    store = DeviceStore(path)
    key, public = p256_keypair()
    code = store.issue_enrollment_code().code
    original = store.enroll(
        code=code, curve=CURVE_P256, public_key=base64.b64encode(public).decode(), label="pixel"
    )

    reopened = DeviceStore(path)
    assert len(reopened) == 1
    reloaded = reopened.get(original.device_id)
    assert reloaded is not None and reloaded.label == "pixel"

    verifier = RequestVerifier(reopened)
    headers = {
        HEADER_DEVICE: original.device_id,
        HEADER_TIMESTAMP: str(int(time.time())),
        HEADER_NONCE: base64.b64encode(secrets.token_bytes(16)).decode(),
    }
    message = build_signing_string(
        method="GET",
        target="/v1/state",
        body=b"",
        timestamp=int(headers[HEADER_TIMESTAMP]),
        nonce=headers[HEADER_NONCE],
    )
    headers[HEADER_SIGNATURE] = base64.b64encode(sign_p256(key, message)).decode()
    assert verifier.verify(method="GET", target="/v1/state", body=b"", headers=headers)


def test_a_revocation_survives_a_restart(tmp_path: Any) -> None:
    path = tmp_path / "devices.json"
    store = DeviceStore(path)
    code = store.issue_enrollment_code().code
    device = store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode())
    store.revoke(device.device_id)

    reopened = DeviceStore(path)
    restored = reopened.get(device.device_id)
    assert restored is not None and restored.revoked is True
    assert reopened.get_trusted(device.device_id) is None


def test_a_corrupt_trust_store_registers_nobody_rather_than_everybody(tmp_path: Any) -> None:
    """Failing open here would trust every device; failing closed costs a re-enrol."""
    path = tmp_path / "devices.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(DeviceStore(path)) == 0


def test_the_trust_store_holds_no_private_material(tmp_path: Any) -> None:
    path = tmp_path / "devices.json"
    store = DeviceStore(path)
    key, public = p256_keypair()
    code = store.issue_enrollment_code().code
    store.enroll(code=code, curve=CURVE_P256, public_key=base64.b64encode(public).decode())
    raw = path.read_text(encoding="utf-8")
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    assert "PRIVATE" not in raw
    assert private_pem.decode().strip() not in raw


def test_an_enrollment_code_minted_by_another_process_is_usable(tmp_path: Any) -> None:
    """The `enroll` CLI and the gateway are separate processes over one file.

    Regression: an enrollment code used to live only in the minting process's
    memory, so a code printed by ``herdr-notify enroll`` was never visible to
    the running gateway and every fresh code was refused with 403.
    """
    path = tmp_path / "devices.json"
    gateway = DeviceStore(path)  # the long-lived server, no code yet
    cli_code = DeviceStore(path).issue_enrollment_code().code  # a separate process

    assert gateway.reload_if_changed() is True
    device = gateway.enroll(
        code=cli_code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode()
    )
    assert device.curve == CURVE_P256


def test_an_enrollment_code_is_single_use_across_processes(tmp_path: Any) -> None:
    path = tmp_path / "devices.json"
    code = DeviceStore(path).issue_enrollment_code().code
    DeviceStore(path).enroll(
        code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode()
    )
    with pytest.raises(EnrollmentRejected):
        DeviceStore(path).enroll(
            code=code, curve=CURVE_P256, public_key=base64.b64encode(b"k").decode()
        )


def test_a_live_enrollment_code_is_stored_hashed_not_in_the_clear(tmp_path: Any) -> None:
    path = tmp_path / "devices.json"
    code = DeviceStore(path).issue_enrollment_code().code
    raw = path.read_text(encoding="utf-8")
    assert code not in raw, "the plaintext code must never be written to disk"


# -- nonce cache -----------------------------------------------------------


def test_the_nonce_cache_is_bounded_per_device() -> None:
    cache = NonceCache(max_per_device=4, clock=Clock())
    for index in range(10):
        assert cache.check_and_add("dev-1", f"n{index}") is True
    # Ten distinct nonces were accepted, but only the most recent few are
    # retained, so the cache cannot be grown without bound by a known device.
    assert len(cache._seen["dev-1"]) == 4


def test_the_nonce_cache_is_bounded_across_devices() -> None:
    cache = NonceCache(max_devices=3, clock=Clock())
    for index in range(10):
        cache.check_and_add(f"dev-{index}", "n")
    assert len(cache._seen) <= 3


def test_nonces_expire_with_their_device() -> None:
    clock = Clock()
    cache = NonceCache(ttl=100, clock=clock)
    assert cache.check_and_add("dev-1", "n") is True
    assert cache.check_and_add("dev-1", "n") is False
    clock.advance(101)
    assert cache.check_and_add("dev-1", "n") is True


def test_nonce_cache_keeps_devices_isolated() -> None:
    cache = NonceCache(clock=Clock())
    assert cache.check_and_add("dev-1", "shared") is True
    assert cache.check_and_add("dev-2", "shared") is True
