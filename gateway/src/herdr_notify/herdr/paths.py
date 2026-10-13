"""Resolution and validation of herdr's local IPC endpoint.

herdr exposes a single socket per session. The documented resolution order is:

1. explicit ``--session <name>``
2. ``HERDR_SOCKET_PATH``
3. ``HERDR_SESSION=<name>``
4. the default session socket

On Unix that endpoint is a filesystem socket. On Windows it is a named pipe
whose *name* is the absolute filesystem path herdr reports, addressed through
the ``\\\\.\\pipe\\`` namespace. Both are reachable only by the user who owns
the herdr server: herdr sets a restrictive DACL on the pipe at creation time
(``src/ipc.rs``), so local privilege separation is herdr's job, not ours.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_SOCKET_PATH = "HERDR_SOCKET_PATH"
ENV_SESSION = "HERDR_SESSION"

PIPE_NAMESPACE = r"\\.\pipe"


class SocketPathError(RuntimeError):
    """Raised when the herdr endpoint cannot be resolved or fails validation."""


def herdr_config_dir() -> Path:
    """Return the directory holding herdr's session state for this platform."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if not base:
            raise SocketPathError("APPDATA is not set; cannot locate the herdr config dir")
        return Path(base) / "herdr"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = xdg if xdg else str(Path.home() / ".config")
    return Path(base) / "herdr"


def default_socket_path() -> Path:
    return herdr_config_dir() / "herdr.sock"


def session_socket_path(session: str) -> Path:
    if not session or any(sep in session for sep in ("/", "\\")) or session in {".", ".."}:
        raise SocketPathError(f"invalid session name: {session!r}")
    return herdr_config_dir() / "sessions" / session / "herdr.sock"


def _validate_within_config_dir(candidate: Path) -> Path:
    """Refuse any endpoint that is not a herdr session socket we own.

    ``HERDR_SOCKET_PATH`` is attacker-influenceable in a shared-host threat
    model, and the gateway would happily send it every API method it is capable
    of. Pinning resolution to the herdr config dir keeps a tampered environment
    variable from redirecting the control plane at another process.
    """
    resolved = candidate.expanduser().resolve(strict=False)
    root = herdr_config_dir().resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise SocketPathError(f"refusing endpoint {resolved} outside the herdr config dir {root}")
    if resolved.name != "herdr.sock":
        raise SocketPathError(f"refusing endpoint {resolved}: not a herdr session socket")
    return resolved


def resolve_socket_path(session: str | None = None) -> Path:
    """Resolve the herdr endpoint, honouring the documented precedence."""
    if session:
        return _validate_within_config_dir(session_socket_path(session))

    override = os.environ.get(ENV_SOCKET_PATH)
    if override:
        return _validate_within_config_dir(Path(override))

    env_session = os.environ.get(ENV_SESSION)
    if env_session:
        return _validate_within_config_dir(session_socket_path(env_session))

    return _validate_within_config_dir(default_socket_path())


def transport_address(path: Path) -> str:
    """Return the string to hand to the OS connect call."""
    text = str(path)
    if sys.platform == "win32":
        return f"{PIPE_NAMESPACE}\\{text}"
    return text


@dataclass(frozen=True, slots=True)
class Endpoint:
    """A resolved, connectable herdr endpoint."""

    path: Path
    address: str

    @property
    def is_named_pipe(self) -> bool:
        return sys.platform == "win32"

    @classmethod
    def resolve(cls, session: str | None = None) -> Endpoint:
        path = resolve_socket_path(session)
        return cls(path=path, address=transport_address(path))

    def exists(self) -> bool:
        """Best-effort presence probe.

        On Windows a named pipe shows up in the ``\\\\.\\pipe`` namespace but is
        not a filesystem entry at ``path``, so a plain ``exists()`` is only
        meaningful on Unix. Callers should treat False as advisory and let the
        connect attempt be the real test.
        """
        if self.is_named_pipe:
            return True
        return self.path.exists()

    def describe(self) -> str:
        """Human-facing diagnosis for the CLI and the health endpoint."""
        if is_pid_lock_file(self.path):
            return (
                f"{self.path} is herdr's PID lock file, not a live endpoint. "
                f"The real endpoint is the named pipe {self.address} — a connect "
                f"attempt is the only reliable test."
            )
        if not self.exists():
            return f"no herdr endpoint at {self.path} — is the server running?"
        return f"herdr endpoint {self.address}"


def is_pid_lock_file(path: Path) -> bool:
    """True when ``path`` is herdr's PID lock file rather than a live endpoint.

    On Windows ``herdr.sock`` is a 26-byte ``<pid>:<created_ns>`` file while the
    real endpoint is a named pipe registered under that same path string in the
    ``\\\\.\\pipe`` namespace. Confusing the two produces a baffling "connection
    refused on a file that clearly exists", so name the distinction once.
    """
    try:
        if not path.is_file():
            return False
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return False
    pid, _, stamp = content.partition(":")
    return pid.isdigit() and stamp.isdigit()
