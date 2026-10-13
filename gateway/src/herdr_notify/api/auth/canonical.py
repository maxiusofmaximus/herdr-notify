"""The exact bytes both sides sign and verify.

Signing schemes fail at the canonicalisation step, not the cryptography. If the
phone signs one string and the gateway rebuilds a slightly different one — a
different query encoding, a body re-serialised with different key order, a path
with or without its trailing slash — every signature fails and the cause looks
like "crypto is broken" rather than "we disagreed about one byte".

So the rules are deliberately restrictive:

* **The body is hashed, never signed raw.** A hash of the exact received bytes
  removes every serialisation ambiguity, because there is no re-serialisation to
  disagree about.
* **The path is the raw request target**, taken from the request line and not
  reassembled from routing. Normalising it would be convenient and would create a
  second, differently-normalised copy on each side.
* **One field per line, LF-terminated, including the last.** No field can contain
  a newline (a query string can contain ``%0A`` but that is percent-encoded, and
  the raw target keeps it encoded), so no two distinct inputs can produce the
  same string.

Every one of those choices exists to make an ambiguity impossible rather than
unlikely.
"""

from __future__ import annotations

import hashlib
from typing import Final

#: Bound on what we will sign over, so a huge body cannot be hashed on every
#: request. Real requests here are a few hundred bytes.
MAX_BODY_BYTES: Final = 256 * 1024

#: Tolerance on the signed timestamp, in seconds. Wide enough to survive a phone
#: with a badly-set clock, narrow enough that a captured request cannot be
#: replayed tomorrow.
DEFAULT_CLOCK_SKEW_SECONDS: Final = 60.0


class CanonicalizationError(ValueError):
    """The request cannot produce a well-defined signing string."""


def body_digest(body: bytes) -> str:
    """SHA-256 of the raw body, lowercase hex."""
    return hashlib.sha256(body).hexdigest()


def build_signing_string(
    *,
    method: str,
    target: str,
    body: bytes,
    timestamp: int,
    nonce: str,
    max_body: int = MAX_BODY_BYTES,
) -> bytes:
    """Build the byte string that is signed.

    ``target`` is the raw HTTP request target, e.g. ``/v1/agents/w1:p1/respond``.
    It is not a parsed or normalised path. ``max_body`` lets an endpoint that
    legitimately carries a large body raise the bound the caller already
    enforced; the produced bytes do not depend on it.
    """
    if not method:
        raise CanonicalizationError("method is required")
    if not target.startswith("/"):
        raise CanonicalizationError(f"target must be an absolute path, got {target!r}")
    if "\n" in target or "\r" in target:
        raise CanonicalizationError("target must not contain a newline")
    if "\n" in nonce or "\r" in nonce:
        raise CanonicalizationError("nonce must not contain a newline")
    if not nonce:
        raise CanonicalizationError("nonce is required")
    if len(body) > max_body:
        raise CanonicalizationError(
            f"body of {len(body)} bytes exceeds the {max_body}-byte signing limit"
        )

    parts = (
        method.upper(),
        target,
        body_digest(body),
        str(int(timestamp)),
        nonce,
    )
    return ("\n".join(parts) + "\n").encode("utf-8")


#: Header names, in one place so the app, the CLI and the gateway cannot drift.
HEADER_DEVICE: Final = "X-HN-Device"
HEADER_TIMESTAMP: Final = "X-HN-Timestamp"
HEADER_NONCE: Final = "X-HN-Nonce"
HEADER_SIGNATURE: Final = "X-HN-Signature"
HEADER_KEY_ID: Final = "X-HN-Key-Id"

ALL_HEADERS: Final = (
    HEADER_DEVICE,
    HEADER_TIMESTAMP,
    HEADER_NONCE,
    HEADER_SIGNATURE,
    HEADER_KEY_ID,
)


__all__ = [
    "ALL_HEADERS",
    "DEFAULT_CLOCK_SKEW_SECONDS",
    "HEADER_DEVICE",
    "HEADER_KEY_ID",
    "HEADER_NONCE",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "MAX_BODY_BYTES",
    "CanonicalizationError",
    "body_digest",
    "build_signing_string",
]
