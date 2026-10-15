"""The pairing payload a phone scans, and how it is rendered.

A pairing code is only useful if the phone can reach the gateway with it. Typing
a base URL and a code by hand is two chances to mistype the one thing that has to
be exact, so the host can instead encode both into a single URI the phone scans:

    herdr-notify://pair?u=<base URL>&c=<enrollment code>&v=1

``u`` is the gateway's public base URL, ``c`` the single-use enrollment code
``herdr-notify enroll`` mints, and ``v`` the payload version. The payload is
plain text and carries no secret beyond the code itself, which keeps the fixed
TTL and single use of the existing enrollment path: nothing here is a second
way in, only a shorter way to type the first one.

Everything in this module is pure. Building the payload and rendering the QR
never touch the network, the clock, or the disk; the one impure helper,
:func:`resolve_public_url`, takes the tailnet view as an argument rather than
fetching it, so a test can drive every branch without a daemon.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from .tailnet import TailnetView

PAIRING_URI_SCHEME = "herdr-notify"
PAIRING_URI_HOST = "pair"
PAIRING_URI_VERSION = 1

PUBLIC_URL_ENV = "HERDR_NOTIFY_PUBLIC_URL"
DEFAULT_GATEWAY_PORT = 8787

# Two full blocks per dark module, two spaces per light one. A terminal cell is
# about twice as tall as it is wide, so doubling the width keeps the symbol
# square — a QR a scanner will accept. Full blocks (U+2588) are in every console
# font a Windows host ships, which half-blocks and ANSI reverse video are not.
_DARK = "\u2588\u2588"
_LIGHT = "  "


class PairingPayloadError(ValueError):
    """The base URL or the code cannot form a payload a phone could use."""


def normalise_base_url(url: str | None) -> str:
    """Return an absolute http(s) base URL, or refuse to guess.

    A phone cannot open a hostless or schemeless string, and a relative one would
    resolve against whatever it happened to be scanning from. Refusing here means
    the operator sees the problem on the host, where the fix is a flag, rather
    than on the phone, where it is a silent failure.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise PairingPayloadError("the gateway URL is empty")
    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise PairingPayloadError(
            f"not an absolute http(s) URL with a host: {candidate!r}"
        )
    return candidate


def build_pairing_payload(
    url: str, code: str, *, version: int = PAIRING_URI_VERSION
) -> str:
    """Build the ``herdr-notify://pair`` URI a phone scans.

    The base URL is percent-encoded as a single query value, so a port, a path or
    a query string in it survives the round trip intact. The code is trimmed (a
    code pasted with surrounding whitespace is still the code) but an empty one
    is an error: a payload without a code would enrol nothing.
    """
    base = normalise_base_url(url)
    cleaned_code = (code or "").strip()
    if not cleaned_code:
        raise PairingPayloadError("the enrollment code is empty")
    query = urlencode({"u": base, "c": cleaned_code, "v": version})
    return f"{PAIRING_URI_SCHEME}://{PAIRING_URI_HOST}?{query}"


def gateway_config_path() -> Path:
    """Where the host may pin the gateway's public URL, if it wants to."""
    return Path.home() / ".config" / "herdr-notify" / "gateway.json"


def _public_url_from_config(path: Path) -> str | None:
    """``{"public_url": "..."}`` from the optional gateway config, or ``None``.

    A missing or unreadable file is not an error: the config is one of several
    fallbacks, and a host that never wrote one is the normal case.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("public_url")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _first_ipv4(addresses: tuple[str, ...]) -> str | None:
    for address in addresses:
        if ":" not in address:
            return address
    return None


def resolve_public_url(
    explicit: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    config_path: Path | None = None,
    tailnet: TailnetView | None = None,
    port: int = DEFAULT_GATEWAY_PORT,
) -> str | None:
    """Pick the gateway's public base URL from the sources, most explicit first.

    Order: an explicit ``--url``, then ``HERDR_NOTIFY_PUBLIC_URL``, then the
    ``public_url`` key of ``gateway.json``, then the host's own tailnet address
    (``http://<tailnet-ip>:<port>``). The first three are validated; a malformed
    explicit or configured URL raises rather than silently falling through, so a
    typo is reported instead of masked. ``None`` means no source had an answer.
    """
    if explicit and explicit.strip():
        return normalise_base_url(explicit)

    env = environ if environ is not None else os.environ
    from_env = env.get(PUBLIC_URL_ENV)
    if from_env and from_env.strip():
        return normalise_base_url(from_env)

    path = config_path if config_path is not None else gateway_config_path()
    from_config = _public_url_from_config(path)
    if from_config:
        return normalise_base_url(from_config)

    if tailnet is not None and tailnet.self_peer is not None:
        address = _first_ipv4(tailnet.self_peer.addresses)
        if address:
            return f"http://{address}:{port}"
    return None


def _render_matrix(matrix: tuple[bytearray, ...] | list[list[int]], *, border: int) -> str:
    """Render a QR module matrix as Unicode blocks.

    A pure string transform, kept separate from segno so the mapping from module
    to character is testable without building a symbol. ``border`` is the quiet
    zone in modules; the QR spec asks for four.
    """
    width = len(matrix[0]) if matrix else 0
    blank = _LIGHT * (width + 2 * border)
    lines = [blank] * border
    for row in matrix:
        cells = "".join(_DARK if cell else _LIGHT for cell in row)
        lines.append(_LIGHT * border + cells + _LIGHT * border)
    lines.extend([blank] * border)
    return "\n".join(lines)


def render_qr_ascii(payload: str, *, border: int = 4, error: str = "m") -> str:
    """The payload as a scannable QR, in Unicode blocks.

    segno computes the module matrix — a pure-Python, Pillow-free symbol builder
    — and this module does the terminal rendering, which keeps the output a plain
    string a test can assert on and the encoder a dependency with one job.
    """
    import segno

    qr = segno.make(payload, error=error, micro=False)
    return _render_matrix(qr.matrix, border=border)
