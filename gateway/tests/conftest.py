"""Shared test configuration."""

from __future__ import annotations

import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

GATEWAY_ROOT = Path(__file__).resolve().parent.parent
SRC = GATEWAY_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolate_herdr_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Keep a developer's real herdr environment out of the unit tests.

    The endpoint validator reads the ambient environment, and a real
    HERDR_SOCKET_PATH or herdr config dir on the host would make resolution tests
    assert against the machine instead of the code.

    Integration tests are exempt from the *directory* redirect: their whole
    purpose is to talk to the actual server, and pointing them at a temp dir
    would just make them fail for the wrong reason. They still get the
    environment-variable scrub, so a developer's session override cannot
    silently redirect them.
    """
    monkeypatch.delenv("HERDR_SOCKET_PATH", raising=False)
    monkeypatch.delenv("HERDR_SESSION", raising=False)

    if request.node.get_closest_marker("integration") is not None:
        yield
        return

    root = Path(tempfile.mkdtemp(prefix="herdr-notify-test-"))
    # Windows resolves the config dir from APPDATA, POSIX from XDG_CONFIG_HOME.
    monkeypatch.setenv("APPDATA", str(root))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(root))
    try:
        yield
    finally:
        shutil.rmtree(root, ignore_errors=True)
