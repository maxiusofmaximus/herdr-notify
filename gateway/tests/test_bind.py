"""The bind-address rules: explicit addresses only, never a wildcard."""

from __future__ import annotations

import pytest

from herdr_notify.cli import bind_sockets, parse_bind_hosts


def test_a_comma_separated_list_names_each_address() -> None:
    assert parse_bind_hosts("127.0.0.1, 100.64.0.1,127.0.0.1") == ["127.0.0.1", "100.64.0.1"]


@pytest.mark.parametrize("raw", ["0.0.0.0", "::", "", "*", "127.0.0.1,0.0.0.0"])  # noqa: S104
def test_a_wildcard_is_refused(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_bind_hosts(raw)


def test_one_socket_is_opened_per_host() -> None:
    sockets = bind_sockets(["127.0.0.1"], 0)
    try:
        assert len(sockets) == 1
        assert sockets[0].getsockname()[0] == "127.0.0.1"
    finally:
        for sock in sockets:
            sock.close()
