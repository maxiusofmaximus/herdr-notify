"""Verifying a signed request.

Three checks, in this order, and the cheapest first:

**Is this device known, trusted and not revoked?** A revoked device is refused
before any cryptography runs, so revocation takes effect immediately even for a
device whose key is perfectly valid.

**Is this request fresh and unseen?** A timestamp inside the window and a nonce
never used before. Both are needed: a window alone still permits replay for its
whole duration, and a nonce alone permits an unbounded replay. The nonce cache
is bounded and pruned, so a long-running gateway does not accumulate them.

**Is the signature valid?** ECDSA P-256 or Ed25519, per the device's recorded
curve. The curve comes from the device record and never from the request — a
caller must not be able to pick the algorithm that verifies its own forged
signature.

Failures are reported as a reason string and never distinguish "no such device"
from "bad signature" to the caller, so the endpoint cannot be used to enumerate
registered devices. The distinction is kept for the server log.
"""

from __future__ import annotations

import base64
import binascii
import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from cryptography.exceptions import InvalidSignature

from .canonical import (
    DEFAULT_CLOCK_SKEW_SECONDS,
    HEADER_DEVICE,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MAX_BODY_BYTES,
    CanonicalizationError,
    build_signing_string,
)
from .devices import CURVE_ED25519, CURVE_P256, Device, DeviceStore

#: Nonces remembered per device. One hour is far longer than the skew window, so
#: a nonce cannot fall out of the cache while it would still be replayable.
log = logging.getLogger(__name__)

NONCE_CACHE_TTL_SECONDS: Final = 3600.0
NONCE_CACHE_MAX_PER_DEVICE: Final = 512
NONCE_CACHE_MAX_DEVICES: Final = 64


class Rejection(StrEnum):
    """Why a request was refused. Never sent verbatim to the caller."""

    NO_HEADERS = "no_headers"
    UNKNOWN_DEVICE = "unknown_device"
    REVOKED = "revoked"
    BAD_TIMESTAMP = "bad_timestamp"
    BAD_NONCE = "bad_nonce"
    BAD_SIGNATURE = "bad_signature"
    MALFORMED = "malformed"
    UNSUPPORTED_CURVE = "unsupported_curve"


class AuthError(Exception):
    """A signed request was refused."""

    def __init__(self, rejection: Rejection) -> None:
        super().__init__(rejection)
        self.rejection = rejection

    @property
    def public_message(self) -> str:
        """What the caller is told. Deliberately non-specific.

        Distinguishing "unknown device" from "bad signature" turns this endpoint
        into an oracle for which device ids exist.
        """
        return "unauthorized"


@dataclass(frozen=True, slots=True)
class VerifiedRequest:
    device: Device
    device_id: str
    timestamp: int
    nonce: str


class NonceCache:
    """Bounded set of used nonces, per device, with time-based expiry."""

    def __init__(
        self,
        *,
        ttl: float = NONCE_CACHE_TTL_SECONDS,
        max_per_device: int = NONCE_CACHE_MAX_PER_DEVICE,
        max_devices: int = NONCE_CACHE_MAX_DEVICES,
        clock: Any = time.time,
    ) -> None:
        self._seen: dict[str, dict[str, float]] = {}
        self._ttl = ttl
        self._max_per_device = max_per_device
        self._max_devices = max_devices
        self._clock = clock

    def check_and_add(self, device_id: str, nonce: str) -> bool:
        """True if the nonce is new. False if it has been used before."""
        now = float(self._clock())
        bucket = self._seen.setdefault(device_id, {})
        cutoff = now - self._ttl
        for old in [n for n, at in bucket.items() if at < cutoff]:
            bucket.pop(old, None)
        if nonce in bucket:
            return False
        # Bounded: an unauthenticated caller cannot grow this without limit
        # because the device must be known before we get here, but a compromised
        # device still should not be able to.
        if len(bucket) >= self._max_per_device:
            oldest = min(bucket.items(), key=lambda item: item[1])[0]
            bucket.pop(oldest, None)
        bucket[nonce] = now
        self._prune_devices(now)
        return True

    def _prune_devices(self, now: float) -> None:
        if len(self._seen) <= self._max_devices:
            return
        cutoff = now - self._ttl
        for device_id in [
            d for d, bucket in self._seen.items() if not any(at >= cutoff for at in bucket.values())
        ]:
            self._seen.pop(device_id, None)
        while len(self._seen) > self._max_devices:
            self._seen.pop(next(iter(self._seen)), None)

    def clear(self) -> None:
        self._seen.clear()


def _load_public_key(curve: str, encoded: str) -> Any:
    """Turn a stored public key into a verifier object."""
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("public key is not valid base64") from exc

    if curve == CURVE_P256:
        from cryptography.hazmat.primitives.asymmetric import ec

        # An Android Keystore P-256 public key is an uncompressed SEC1 point:
        # 0x04 followed by two 32-byte coordinates.
        if len(raw) != 65 or raw[0] != 0x04:
            raise ValueError("P-256 public key must be a 65-byte uncompressed point")
        return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)

    if curve == CURVE_ED25519:
        from cryptography.hazmat.primitives.asymmetric import ed25519

        if len(raw) != 32:
            raise ValueError("Ed25519 public key must be 32 raw bytes")
        return ed25519.Ed25519PublicKey.from_public_bytes(raw)

    raise ValueError(f"unsupported curve: {curve!r}")


def verify_signature(curve: str, encoded_public_key: str, signature: bytes, message: bytes) -> bool:
    """Verify a signature. Returns False for a bad signature, raises for a bug.

    Only the exceptions that mean "this signature is not valid" are caught.
    Catching broadly here would turn a programming error — a wrong arity, a
    misspelled attribute — into a silently uniform "invalid", which is
    indistinguishable from an attack and would hide a real defect until someone
    wondered why no request ever authenticated.

    Both curves expect the encodings Android actually produces: an uncompressed
    SEC1 point for P-256, and the DER-wrapped ECDSA signature that
    ``SHA256withECDSA`` emits. Accepting a second raw ``r||s`` form would mean
    guessing which one a caller meant, so a non-DER signature simply fails.
    """
    key = _load_public_key(curve, encoded_public_key)
    try:
        if curve == CURVE_P256:
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec

            # EC verify() takes the algorithm explicitly; Ed25519's does not.
            key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
        else:
            key.verify(signature, message)
    except InvalidSignature:
        return False
    except ValueError:
        # Malformed DER, wrong key size, and friends: still just a bad signature.
        return False
    return True


class RequestVerifier:
    """Authenticates a signed request against the device store."""

    def __init__(
        self,
        store: DeviceStore,
        *,
        clock: Any = time.time,
        skew_seconds: float = DEFAULT_CLOCK_SKEW_SECONDS,
        nonces: NonceCache | None = None,
    ) -> None:
        self._store = store
        self._clock = clock
        self._skew = skew_seconds
        self._nonces = nonces if nonces is not None else NonceCache(clock=clock)

    def verify(
        self,
        *,
        method: str,
        target: str,
        body: bytes,
        headers: dict[str, str],
        max_body_bytes: int | None = None,
    ) -> VerifiedRequest:
        """Authenticate, or raise :class:`AuthError`."""

        def header(name: str) -> str | None:
            value = headers.get(name)
            if value is None:
                # Header names are case-insensitive; a client that lowercases
                # them is not the attacker here, it is our own future self.
                for key, candidate in headers.items():
                    if key.lower() == name.lower():
                        value = candidate
                        break
            return value

        device_id = header(HEADER_DEVICE)
        timestamp_raw = header(HEADER_TIMESTAMP)
        nonce = header(HEADER_NONCE)
        signature_raw = header(HEADER_SIGNATURE)
        if not all((device_id, timestamp_raw, nonce, signature_raw)):
            raise AuthError(Rejection.NO_HEADERS)

        try:
            timestamp = int(timestamp_raw or "")
        except ValueError as exc:
            raise AuthError(Rejection.MALFORMED) from exc
        try:
            signature = base64.b64decode(signature_raw or "", validate=True)
        except (binascii.Error, ValueError) as exc:
            raise AuthError(Rejection.MALFORMED) from exc

        now = float(self._clock())
        if abs(now - timestamp) > self._skew:
            raise AuthError(Rejection.BAD_TIMESTAMP)

        device = self._store.get(device_id or "")
        if device is None:
            raise AuthError(Rejection.UNKNOWN_DEVICE)
        if device.revoked:
            raise AuthError(Rejection.REVOKED)

        # The nonce is consumed only after the device is known, so an
        # unauthenticated flood cannot evict legitimate nonces from the cache.
        if not self._nonces.check_and_add(device.device_id, nonce or ""):
            raise AuthError(Rejection.BAD_NONCE)

        if device.curve not in (CURVE_P256, CURVE_ED25519):
            raise AuthError(Rejection.UNSUPPORTED_CURVE)

        try:
            message = build_signing_string(
                method=method,
                target=target,
                body=body,
                timestamp=timestamp,
                nonce=nonce or "",
                max_body=max_body_bytes or MAX_BODY_BYTES,
            )
        except CanonicalizationError as exc:
            raise AuthError(Rejection.MALFORMED) from exc

        try:
            signature_ok = verify_signature(device.curve, device.public_key, signature, message)
        except ValueError as exc:
            # The key in our own trust store is unreadable. That is our bug, not
            # the caller's, but a corrupt store must not turn every request into
            # a 500: the phone would see a server fault instead of a refusal and
            # would keep retrying a request that can never succeed.
            log.error(
                "device %s has an unusable %s public key: %s",
                device.device_id,
                device.curve,
                exc,
            )
            raise AuthError(Rejection.MALFORMED) from exc
        if not signature_ok:
            raise AuthError(Rejection.BAD_SIGNATURE)

        return VerifiedRequest(
            device=device,
            device_id=device.device_id,
            timestamp=timestamp,
            nonce=nonce or "",
        )


__all__ = [
    "NONCE_CACHE_MAX_DEVICES",
    "NONCE_CACHE_MAX_PER_DEVICE",
    "NONCE_CACHE_TTL_SECONDS",
    "AuthError",
    "NonceCache",
    "Rejection",
    "RequestVerifier",
    "VerifiedRequest",
    "verify_signature",
]
