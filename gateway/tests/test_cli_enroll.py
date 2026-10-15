"""The enroll command's --qr path: URL resolution, output and failure."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from herdr_notify import pairing, tailnet
from herdr_notify.cli import _cmd_enroll, build_parser
from herdr_notify.tailnet import Peer, TailnetView


def _args(*extra: str) -> argparse.Namespace:
    return build_parser().parse_args(["enroll", *extra])


def _isolate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    view: TailnetView | None = None,
) -> None:
    """No tailnet, no env, no config: only an explicit --url can resolve."""
    monkeypatch.setattr(tailnet, "read_status", lambda: view)
    monkeypatch.setattr(pairing, "gateway_config_path", lambda: tmp_path / "absent.json")
    monkeypatch.delenv(pairing.PUBLIC_URL_ENV, raising=False)


def _printed(out: str, label: str) -> str:
    line = next(line for line in out.splitlines() if line.startswith(label))
    return line.split(":", 1)[1].strip()


def test_enroll_parser_has_qr_off_by_default() -> None:
    args = build_parser().parse_args(["enroll"])
    assert args.qr is False
    assert args.url is None


def test_enroll_parser_accepts_url_and_qr() -> None:
    args = build_parser().parse_args(["enroll", "--url", "https://pc.tailnet.ts.net", "--qr"])
    assert args.qr is True
    assert args.url == "https://pc.tailnet.ts.net"


def test_enroll_qr_prints_a_payload_the_code_round_trips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate(monkeypatch, tmp_path)
    args = _args(
        "--qr",
        "--url",
        "https://pc.tailnet.ts.net",
        "--devices",
        str(tmp_path / "devices.json"),
    )
    assert _cmd_enroll(args) == 0

    out = capsys.readouterr().out
    code = _printed(out, "pairing code")
    payload = _printed(out, "pairing uri")

    parts = urlsplit(payload)
    assert parts.scheme == "herdr-notify"
    assert parts.netloc == "pair"
    query = parse_qs(parts.query)
    assert query == {"u": ["https://pc.tailnet.ts.net"], "c": [code], "v": ["1"]}
    assert "\u2588" in out


def test_enroll_qr_without_a_url_refuses_and_mints_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate(monkeypatch, tmp_path)
    path = tmp_path / "devices.json"
    args = _args("--qr", "--devices", str(path))
    assert _cmd_enroll(args) == 2
    assert "error: --qr needs" in capsys.readouterr().err
    assert not path.exists()


def test_enroll_qr_with_a_malformed_url_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate(monkeypatch, tmp_path)
    args = _args(
        "--qr", "--url", "pc.tailnet.ts.net", "--devices", str(tmp_path / "devices.json")
    )
    assert _cmd_enroll(args) == 2
    assert "not an absolute http(s) URL" in capsys.readouterr().err


def test_enroll_qr_uses_the_environment_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv(pairing.PUBLIC_URL_ENV, "https://env.ts.net")
    args = _args("--qr", "--devices", str(tmp_path / "devices.json"))
    assert _cmd_enroll(args) == 0
    assert "u=https%3A%2F%2Fenv.ts.net" in capsys.readouterr().out


def test_enroll_qr_falls_back_to_the_tailnet_address(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    view = TailnetView(
        backend_state="Running",
        self_peer=Peer(name="pc", addresses=("100.64.0.1",), online=True),
    )
    _isolate(monkeypatch, tmp_path, view=view)
    args = _args("--qr", "--devices", str(tmp_path / "devices.json"))
    assert _cmd_enroll(args) == 0
    assert "u=http%3A%2F%2F100.64.0.1%3A8787" in capsys.readouterr().out


def test_enroll_without_qr_does_not_print_a_qr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _isolate(monkeypatch, tmp_path)
    args = _args("--devices", str(tmp_path / "devices.json"))
    assert _cmd_enroll(args) == 0
    out = capsys.readouterr().out
    assert "pairing code : " in out
    assert "herdr-notify://pair" not in out
    assert "\u2588" not in out
