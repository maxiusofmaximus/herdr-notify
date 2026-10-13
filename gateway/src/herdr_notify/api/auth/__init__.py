"""Per-device public-key authentication for the control plane.

There is no static secret in this package. A device is a public key, and a
request is accepted only when the caller proves possession of the matching
private key — which never leaves the phone's hardware keystore. A stolen log, a
captured proxy request or a phone backup therefore yields nothing usable.

The pieces:

* :mod:`.canonical` — the exact bytes both sides sign. Signing schemes fail here,
  not in the cryptography.
* :mod:`.devices` — the trust store, enrollment codes, per-device grants,
  revocation.
* :mod:`.verify` — freshness, replay rejection, and signature verification
  (authentication).
* :mod:`.authz` — the endpoint matrix and per-device authorization, a separate
  question from authentication: a valid signature says who the caller is, not
  what it may do.
"""

from __future__ import annotations

from .authz import (
    AuthorizationError,
    AuthzRejection,
    UnknownEndpoint,
    authorize,
    required_permission,
)
from .canonical import (
    ALL_HEADERS,
    DEFAULT_CLOCK_SKEW_SECONDS,
    HEADER_DEVICE,
    HEADER_KEY_ID,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    MAX_BODY_BYTES,
    CanonicalizationError,
    body_digest,
    build_signing_string,
)
from .devices import (
    CURVE_ED25519,
    CURVE_P256,
    ENROLLMENT_TTL_SECONDS,
    PERMISSION_ADMIN,
    PERMISSION_APPROVE,
    PERMISSION_READ_STATE,
    PERMISSION_RESPOND,
    PERMISSION_SEND_KEY,
    SUPPORTED_CURVES,
    SUPPORTED_PERMISSIONS,
    TOUCH_PERSIST_INTERVAL,
    Curve,
    Device,
    DeviceStore,
    EnrollmentCode,
    EnrollmentRejected,
    Permission,
)
from .verify import (
    AuthError,
    NonceCache,
    Rejection,
    RequestVerifier,
    VerifiedRequest,
    verify_signature,
)

__all__ = [
    "ALL_HEADERS",
    "CURVE_ED25519",
    "CURVE_P256",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "ENROLLMENT_TTL_SECONDS",
    "HEADER_DEVICE",
    "HEADER_KEY_ID",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "MAX_BODY_BYTES",
    "PERMISSION_ADMIN",
    "PERMISSION_APPROVE",
    "PERMISSION_READ_STATE",
    "PERMISSION_RESPOND",
    "PERMISSION_SEND_KEY",
    "SUPPORTED_CURVES",
    "SUPPORTED_PERMISSIONS",
    "TOUCH_PERSIST_INTERVAL",
    "AuthError",
    "AuthorizationError",
    "AuthzRejection",
    "CanonicalizationError",
    "Curve",
    "Device",
    "DeviceStore",
    "EnrollmentCode",
    "EnrollmentRejected",
    "NonceCache",
    "Permission",
    "Rejection",
    "RequestVerifier",
    "UnknownEndpoint",
    "VerifiedRequest",
    "authorize",
    "body_digest",
    "build_signing_string",
    "required_permission",
    "verify_signature",
]
