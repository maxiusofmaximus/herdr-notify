from __future__ import annotations

import pytest

from herdr_notify.tailnet import parse_status, parse_whois, whois

STATUS = {
    "BackendState": "Running",
    "Self": {
        "DNSName": "pc-ejemplo.tail1234.ts.net.",
        "TailscaleIPs": ["100.64.0.1", "fd7a::1"],
        "OS": "windows",
        "UserID": 1,
    },
    "Peer": {
        "nodeB": {
            "DNSName": "kevin.tail1234.ts.net.",
            "TailscaleIPs": ["100.1.1.2"],
            "Online": False,
            "UserID": 1,
        },
        "nodeA": {
            "DNSName": "tecno-spark-10-pro.tail1234.ts.net.",
            "TailscaleIPs": ["100.64.0.2"],
            "Online": True,
            "OS": "android",
            "UserID": 1,
        },
        "nodeC": {"DNSName": "", "HostName": "zeta", "TailscaleIPs": [], "Online": True},
    },
}


def test_self_is_separate_from_peers() -> None:
    view = parse_status(STATUS)
    assert view.self_peer is not None
    assert view.self_peer.name == "pc-ejemplo"
    assert all(p.name != "pc-ejemplo" for p in view.peers)


def test_peers_are_online_first_then_by_name() -> None:
    names = [p.name for p in parse_status(STATUS).peers]
    assert names == ["tecno-spark-10-pro", "zeta", "kevin"]


def test_missing_dns_name_falls_back_to_host_name() -> None:
    zeta = next(p for p in parse_status(STATUS).peers if p.name == "zeta")
    assert zeta.addresses == ()


def test_an_empty_status_is_not_an_error() -> None:
    view = parse_status({})
    assert view.self_peer is None
    assert view.peers == ()
    assert view.backend_state == ""


WHOIS = {
    "Node": {"Name": "tecno-spark-10-pro.tail1234.ts.net.", "UserID": 1},
    "UserProfile": {"ID": 1, "LoginName": "me@example.com", "DisplayName": "Me"},
}


def test_parse_whois_extracts_the_owner() -> None:
    """The owner id is what pairing auto-approval compares, nothing else."""
    who = parse_whois(WHOIS)
    assert who is not None
    assert who.owner_id == "1"
    assert who.login_name == "me@example.com"
    # DNSName carries a trailing dot; the node name is shown without it.
    assert who.node_name == "tecno-spark-10-pro.tail1234.ts.net"


def test_a_tagged_node_has_no_owner_to_compare() -> None:
    """No UserProfile means no owner: auto-approval must not fire."""
    assert parse_whois({"Node": {"Name": "tagged.tail.ts.net."}}) is None
    assert parse_whois({}) is None


def test_whois_returns_none_when_tailscale_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("herdr_notify.tailnet._binary", lambda: None)
    assert whois("100.64.0.2") is None


def test_whois_returns_none_for_an_empty_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("herdr_notify.tailnet._binary", lambda: "tailscale")
    assert whois("") is None
