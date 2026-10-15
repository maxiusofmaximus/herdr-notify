"""The pairing payload builder and public-URL resolution.

The QR renderer shares this module; its tests live below the payload ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from herdr_notify.pairing import (
    DEFAULT_GATEWAY_PORT,
    PAIRING_URI_VERSION,
    PUBLIC_URL_ENV,
    PairingPayloadError,
    _render_matrix,
    build_pairing_payload,
    normalise_base_url,
    render_qr_ascii,
    resolve_public_url,
)
from herdr_notify.tailnet import Peer, TailnetView


def _tailnet_with(*addresses: str) -> TailnetView:
    return TailnetView(
        backend_state="Running",
        self_peer=Peer(name="pc", addresses=addresses, online=True),
    )


def test_payload_is_the_agreed_uri() -> None:
    payload = build_pairing_payload("https://pc.tailnet.ts.net", "ABCDEF")
    assert payload == "herdr-notify://pair?u=https%3A%2F%2Fpc.tailnet.ts.net&c=ABCDEF&v=1"


def test_payload_round_trips_through_url_parsing() -> None:
    payload = build_pairing_payload("https://pc.tailnet.ts.net", "ABCDEF")
    parts = urlsplit(payload)
    assert parts.scheme == "herdr-notify"
    assert parts.netloc == "pair"
    query = parse_qs(parts.query)
    assert query == {"u": ["https://pc.tailnet.ts.net"], "c": ["ABCDEF"], "v": ["1"]}


def test_payload_carries_version_one() -> None:
    payload = build_pairing_payload("https://pc.tailnet.ts.net", "X")
    assert parse_qs(urlsplit(payload).query)["v"] == [str(PAIRING_URI_VERSION)]


def test_the_base_url_query_survives_encoding() -> None:
    url = "https://pc.tailnet.ts.net:8788/gw?mode=qr&x=1"
    payload = build_pairing_payload(url, "CODE")
    assert parse_qs(urlsplit(payload).query)["u"] == [url]


def test_the_code_is_trimmed_but_kept() -> None:
    payload = build_pairing_payload("https://pc.tailnet.ts.net", "  CODE  ")
    assert parse_qs(urlsplit(payload).query)["c"] == ["CODE"]


@pytest.mark.parametrize(
    "url",
    ["", "   ", "pc.tailnet.ts.net", "https://", "http:///path", "ftp://host/path"],
)
def test_a_url_without_scheme_or_host_is_refused(url: str) -> None:
    with pytest.raises(PairingPayloadError):
        build_pairing_payload(url, "CODE")


@pytest.mark.parametrize("code", ["", "   ", None])
def test_an_empty_code_is_refused(code: str | None) -> None:
    with pytest.raises(PairingPayloadError):
        build_pairing_payload("https://pc.tailnet.ts.net", code)  # type: ignore[arg-type]


def test_normalise_accepts_http_and_https() -> None:
    assert normalise_base_url("http://100.64.0.1:8787/") == "http://100.64.0.1:8787/"


def test_resolve_prefers_the_explicit_url() -> None:
    resolved = resolve_public_url(
        "https://pc.tailnet.ts.net",
        environ={PUBLIC_URL_ENV: "https://env.ts.net"},
        tailnet=_tailnet_with("100.64.0.1"),
    )
    assert resolved == "https://pc.tailnet.ts.net"


def test_resolve_uses_the_environment() -> None:
    resolved = resolve_public_url(
        None,
        environ={PUBLIC_URL_ENV: "https://env.ts.net"},
        tailnet=_tailnet_with("100.64.0.1"),
    )
    assert resolved == "https://env.ts.net"


def test_resolve_uses_the_config_file(tmp_path: Path) -> None:
    config = tmp_path / "gateway.json"
    config.write_text(json.dumps({"public_url": "https://cfg.ts.net"}), encoding="utf-8")
    resolved = resolve_public_url(
        None, environ={}, config_path=config, tailnet=_tailnet_with("100.64.0.1")
    )
    assert resolved == "https://cfg.ts.net"


def test_resolve_falls_back_to_the_tailnet_address(tmp_path: Path) -> None:
    resolved = resolve_public_url(
        None,
        environ={},
        config_path=tmp_path / "absent.json",
        tailnet=_tailnet_with("fe80::1", "100.64.0.1"),
    )
    assert resolved == f"http://100.64.0.1:{DEFAULT_GATEWAY_PORT}"


def test_resolve_returns_none_when_nothing_knows(tmp_path: Path) -> None:
    assert resolve_public_url(None, environ={}, config_path=tmp_path / "absent.json") is None


def test_resolve_refuses_a_malformed_explicit_url() -> None:
    with pytest.raises(PairingPayloadError):
        resolve_public_url("not-a-url", environ={})


def test_resolve_refuses_a_malformed_environment_url(tmp_path: Path) -> None:
    with pytest.raises(PairingPayloadError):
        resolve_public_url(
            None, environ={PUBLIC_URL_ENV: "pc.tailnet.ts.net"}, config_path=tmp_path / "x.json"
        )


def test_resolve_ignores_a_config_without_public_url(tmp_path: Path) -> None:
    config = tmp_path / "gateway.json"
    config.write_text(json.dumps({"port": 8787}), encoding="utf-8")
    assert resolve_public_url(None, environ={}, config_path=config) is None


def test_matrix_maps_dark_to_a_block_and_light_to_a_space() -> None:
    assert _render_matrix([[1]], border=0) == "\u2588\u2588"
    assert _render_matrix([[0]], border=0) == "  "


def test_matrix_rows_are_rendered_top_to_bottom() -> None:
    rendered = _render_matrix([[1], [0]], border=0)
    assert rendered.split("\n") == ["\u2588\u2588", "  "]


def test_matrix_border_wraps_every_side() -> None:
    rendered = _render_matrix([[1]], border=1)
    lines = rendered.split("\n")
    assert len(lines) == 3
    assert lines[0] == "  " * 3
    assert lines[2] == "  " * 3
    assert lines[1] == "  " + "\u2588\u2588" + "  "
    assert len({len(line) for line in lines}) == 1


def test_every_rendered_line_is_the_same_width() -> None:
    rendered = render_qr_ascii("herdr-notify://pair?u=x&c=y&v=1")
    lines = rendered.split("\n")
    assert len(lines) > 8
    assert len({len(line) for line in lines}) == 1


def test_rendered_symbol_uses_blocks_on_a_light_background() -> None:
    rendered = render_qr_ascii("herdr-notify://pair?u=https%3A%2F%2Fpc.tailnet.ts.net&c=AB&v=1")
    assert "\u2588" in rendered
    assert set(rendered) <= {"\u2588", " ", "\n"}


def test_the_renderer_accepts_a_larger_quiet_zone() -> None:
    small = render_qr_ascii("payload", border=2)
    large = render_qr_ascii("payload", border=4)
    assert len(large.split("\n")) > len(small.split("\n"))
