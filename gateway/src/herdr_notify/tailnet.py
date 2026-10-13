"""What the host can see of its tailnet, for the phone's peer list.

The phone holds no Tailscale token. It asks the gateway, and the gateway asks
the local Tailscale client (``tailscale status --json``). Nothing here talks to
the Tailscale control plane, and nothing here needs a credential.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Windows installs put the CLI under Program Files, which is often not on PATH
# for a service account. Checked after PATH so a PATH override still wins.
_FALLBACK_BINARIES = (
    r"C:\Program Files\Tailscale\tailscale.exe",
    "/usr/bin/tailscale",
    "/usr/local/bin/tailscale",
)
_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Peer:
    name: str
    addresses: tuple[str, ...]
    online: bool
    os: str = ""
    owner_id: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "addresses": list(self.addresses),
            "online": self.online,
            "os": self.os,
            "owner_id": self.owner_id,
        }


@dataclass(frozen=True)
class TailnetView:
    backend_state: str
    self_peer: Peer | None
    peers: tuple[Peer, ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, Any]:
        return {
            "backend_state": self.backend_state,
            "self": self.self_peer.to_json() if self.self_peer else None,
            "peers": [peer.to_json() for peer in self.peers],
        }


@dataclass(frozen=True)
class Whois:
    """``tailscale whois`` for one address: whose account owns that node.

    Only the owner id is load-bearing here — pairing auto-approval compares it
    with the host's own ``Self.UserID``. A node with no user profile (a tagged
    device) has an empty ``owner_id`` and never auto-approves.
    """

    owner_id: str
    login_name: str = ""
    node_name: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "login_name": self.login_name,
            "node_name": self.node_name,
        }


def _peer(raw: dict[str, Any]) -> Peer:
    # DNSName carries a trailing dot ("host.tailnet.ts.net.") — the phone shows
    # the short host name, so the dot and the tailnet suffix are dropped.
    dns = str(raw.get("DNSName") or "").rstrip(".")
    name = dns.split(".", 1)[0] or str(raw.get("HostName") or "")
    return Peer(
        name=name,
        addresses=tuple(str(ip) for ip in raw.get("TailscaleIPs") or ()),
        online=bool(raw.get("Online", False)),
        os=str(raw.get("OS") or ""),
        owner_id=str(raw.get("UserID") or ""),
    )


def parse_whois(data: dict[str, Any]) -> Whois | None:
    """Turn ``tailscale whois --json`` output into an owner lookup.

    The owner is ``UserProfile.ID`` from the control plane, paired with the
    ``Self.UserID`` of ``status --json``. A tagged node reports no user profile,
    so ``None`` here means "no owner to compare" rather than "unknown".
    """
    profile = data.get("UserProfile")
    if not isinstance(profile, dict):
        return None
    owner = profile.get("ID")
    if owner is None:
        return None
    node = data.get("Node")
    node_name = str(node.get("Name") or "") if isinstance(node, dict) else ""
    return Whois(
        owner_id=str(owner),
        login_name=str(profile.get("LoginName") or ""),
        node_name=node_name.rstrip("."),
    )


def parse_status(data: dict[str, Any]) -> TailnetView:
    """Turn ``tailscale status --json`` output into the peer list we publish.

    Peers are sorted online-first, then by name, so the phone's list is stable
    between polls. The host's own entry is returned separately, not as a peer.
    """
    own = data.get("Self")
    self_peer = _peer(own) if isinstance(own, dict) else None
    peers = [
        _peer(raw)
        for raw in (data.get("Peer") or {}).values()
        if isinstance(raw, dict)
    ]
    peers.sort(key=lambda p: (not p.online, p.name.lower()))
    return TailnetView(
        backend_state=str(data.get("BackendState") or ""),
        self_peer=self_peer,
        peers=tuple(peers),
    )


def _binary() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for candidate in _FALLBACK_BINARIES:
        if Path(candidate).is_file():
            return candidate
    return None


def read_status() -> TailnetView | None:
    """The current tailnet view, or ``None`` when Tailscale cannot be asked.

    ``None`` covers a missing binary, a stopped daemon and malformed output.
    The caller turns that into "unavailable"; the phone then falls back to the
    addresses it already knows.
    """
    binary = _binary()
    if binary is None:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [binary, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return parse_status(data)


def whois(ip: str) -> Whois | None:
    """Who owns the node at ``ip``, or ``None`` when Tailscale cannot say.

    ``None`` covers a missing binary, a stopped daemon, an address that is not a
    tailnet peer, and malformed output. Pairing auto-approval treats every one
    of those the same way: no owner match, so no auto-approval.
    """
    binary = _binary()
    if binary is None or not ip:
        return None
    try:
        completed = subprocess.run(  # noqa: S603
            [binary, "whois", "--json", ip],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return parse_whois(data)
