"""The status command's pure helpers: trust-store totals and the port probe."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from herdr_notify.cli import _cmd_status, _device_totals, _port_listening, build_parser


def test_totals_split_active_from_revoked() -> None:
    devices = [
        SimpleNamespace(revoked=False),
        SimpleNamespace(revoked=False),
        SimpleNamespace(revoked=True),
    ]
    assert _device_totals(devices) == (3, 2, 1)


def test_totals_on_an_empty_store() -> None:
    assert _device_totals([]) == (0, 0, 0)


def test_a_listening_socket_is_reported_listening() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert _port_listening("127.0.0.1", port) is True
    finally:
        server.close()


def test_a_free_port_is_reported_not_listening() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    assert _port_listening("127.0.0.1", port) is False


def test_status_is_wired_with_a_default_port() -> None:
    args = build_parser().parse_args(["status"])
    assert args.func is _cmd_status
    assert args.port == 8787


@pytest.mark.parametrize("port", ["9", "65535"])
def test_status_accepts_a_port_override(port: str) -> None:
    args = build_parser().parse_args(["status", "--port", port])
    assert args.port == int(port)
