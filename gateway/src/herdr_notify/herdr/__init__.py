"""Read-only and streaming access to a running herdr server."""

from __future__ import annotations

from .client import (
    AGENT_STATUS_EVENT,
    UNSCOPED_EVENTS,
    HerdrClient,
    HerdrConnectionClosed,
    HerdrError,
    HerdrRemoteError,
    HerdrStream,
    HerdrTimeoutError,
    build_subscriptions,
)
from .paths import Endpoint, SocketPathError, is_pid_lock_file, resolve_socket_path

__all__ = [
    "AGENT_STATUS_EVENT",
    "UNSCOPED_EVENTS",
    "Endpoint",
    "HerdrClient",
    "HerdrConnectionClosed",
    "HerdrError",
    "HerdrRemoteError",
    "HerdrStream",
    "HerdrTimeoutError",
    "SocketPathError",
    "build_subscriptions",
    "is_pid_lock_file",
    "resolve_socket_path",
]
