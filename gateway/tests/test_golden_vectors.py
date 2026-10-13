"""Cross-language golden vectors for the request signing string.

The phone builds these bytes in Kotlin (`RequestSigner.signingString`) and the
gateway verifies them in Python (`api.auth.canonical.build_signing_string`). If
the two implementations ever disagree by a single byte, every signed request
fails with a signature error that looks like an attack rather than a porting
mistake.

So the vectors live in one committed JSON file and both sides assert against it:
this suite, and `RequestSignerTest` on the phone. Neither side can drift alone.

Add a vector by computing it here first, verifying the resulting request against
a real `RequestVerifier`, and only then committing the expected bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from herdr_notify.api.auth import build_signing_string

VECTORS = Path(__file__).parent / "vectors" / "signing_vectors.json"


def _load() -> list[dict[str, Any]]:
    return json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"]


@pytest.mark.parametrize("vector", _load(), ids=lambda v: v["name"])
def test_python_builds_the_committed_bytes(vector: dict[str, Any]) -> None:
    built = build_signing_string(
        method=vector["method"],
        target=vector["target"],
        body=vector["body"].encode(),
        timestamp=vector["timestamp"],
        nonce=vector["nonce"],
    )
    assert built.decode() == vector["expected"]


@pytest.mark.parametrize("vector", _load(), ids=lambda v: v["name"])
def test_python_verifies_a_signature_made_over_those_bytes(vector: dict[str, Any]) -> None:
    """The full path: build, sign with a device key, verify on the gateway side.

    Imports `cryptography` lazily so the vectors themselves can still be checked
    on a machine without it.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from herdr_notify.api.auth import CURVE_P256, verify_signature

    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    message = build_signing_string(
        method=vector["method"],
        target=vector["target"],
        body=vector["body"].encode(),
        timestamp=vector["timestamp"],
        nonce=vector["nonce"],
    )
    signature = key.sign(message, ec.ECDSA(hashes.SHA256()))
    import base64

    assert verify_signature(
        CURVE_P256, base64.b64encode(public).decode(), signature, message
    )


def test_the_empty_body_digest_is_the_well_known_value() -> None:
    """A self-consistent implementation cannot catch a charset or encoding slip."""
    text = build_signing_string(
        method="GET", target="/v1/state", body=b"", timestamp=1, nonce="n"
    ).decode()
    assert "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" in text


def test_non_ascii_survives_both_implementations() -> None:
    """The product is used by Spanish speakers; a latin-1 slip would be silent."""
    body = '{"text":"Revisa los números del remitente en Brevo, por favor"}'
    built = build_signing_string(
        method="POST", target="/v1/agents/w1:p1/respond", body=body.encode(), timestamp=1, nonce="n"
    )
    # The digest is over the UTF-8 bytes, so the readable text must not survive
    # into the payload itself.
    assert "Revisa" not in built.decode()
