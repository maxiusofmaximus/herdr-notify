"""Image attachments a phone sends to an agent.

The phone picks a picture and posts it to the gateway; the gateway writes it
under its own data directory and submits the absolute path to the agent as a
prompt. The image never leaves the host's filesystem, so the agent can open it
with the tools it already has.

Only three container types are accepted and the bytes must actually be one of
them: a declared content type is a claim by the caller, and a renamed archive is
exactly the kind of thing a type check exists to catch.
"""

from __future__ import annotations

import base64
import binascii
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

MAX_IMAGE_BYTES: Final = 5 * 1024 * 1024

MAX_IMAGE_BODY_BYTES: Final = (MAX_IMAGE_BYTES * 4 // 3) + 64 * 1024

_EXTENSIONS: Final = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}

ALLOWED_IMAGE_TYPES: Final = frozenset(_EXTENSIONS)

_UNSAFE_FILENAME: Final = re.compile(r"[^A-Za-z0-9._-]+")


class ImageError(Exception):
    """An image was refused. ``code`` is safe to return to the caller."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_image_type(data: bytes) -> str | None:
    """The container type from the bytes themselves, or None if unrecognised."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_image(mime: str, data: str) -> tuple[bytes, str]:
    """Decode and validate an image, returning (bytes, canonical mime).

    Type is checked before size so a mislabeled file is reported as the wrong
    kind rather than as too large: the person fixes the first by picking another
    picture and the second only by shrinking it.
    """
    declared = (mime or "").strip().lower()
    if declared not in ALLOWED_IMAGE_TYPES:
        raise ImageError("unsupported_type", f"{mime!r} is not an allowed image type")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageError("invalid_image", "data is not valid base64") from exc
    if not raw:
        raise ImageError("empty_image", "image data is empty")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ImageError(
            "image_too_large",
            f"image is {len(raw)} bytes, limit is {MAX_IMAGE_BYTES}",
        )
    detected = detect_image_type(raw)
    if detected is None:
        raise ImageError("unsupported_type", "data is not a png, jpeg or webp image")
    if detected != declared:
        raise ImageError(
            "type_mismatch",
            f"declared {declared} but the bytes are {detected}",
        )
    return raw, declared


def _safe_stem(pane_id: str) -> str:
    return _UNSAFE_FILENAME.sub("_", pane_id).strip("_") or "pane"


@dataclass(frozen=True, slots=True)
class StoredImage:
    path: Path
    mime: str
    size: int


def store_image(directory: Path, pane_id: str, mime: str, data: str) -> StoredImage:
    """Validate an image and write it under ``directory``.

    The filename carries a random suffix so two attachments for one pane cannot
    overwrite each other and a caller cannot guess a path it was not given.
    """
    raw, declared = decode_image(mime, data)
    directory.mkdir(parents=True, exist_ok=True)
    extension = _EXTENSIONS[declared]
    target = directory / f"{_safe_stem(pane_id)}-{secrets.token_hex(8)}.{extension}"
    target.write_bytes(raw)
    return StoredImage(path=target.resolve(), mime=declared, size=len(raw))


def image_prompt(path: Path) -> str:
    """The prompt that hands an agent the stored image's path."""
    return f"Imagen adjunta: {path}"


__all__ = [
    "ALLOWED_IMAGE_TYPES",
    "MAX_IMAGE_BODY_BYTES",
    "MAX_IMAGE_BYTES",
    "ImageError",
    "StoredImage",
    "decode_image",
    "detect_image_type",
    "image_prompt",
    "store_image",
]
