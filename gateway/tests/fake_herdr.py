"""A scriptable stand-in for herdr's API server.

The gateway's hardest behaviour is timing: subscribe before snapshot, rotate
without losing an event, and stay idempotent when a rotation replays one. None of
that can be proven against a live server without mutating somebody's real coding
session, so the tests drive this fake instead. It speaks the same NDJSON dialect
over a loopback TCP pair, which keeps the tests runnable on a Windows Python
that has no AF_UNIX.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Iterator
from typing import Any

Handler = Callable[[str, dict[str, Any]], dict[str, Any] | None]


class FakeHerdr:
    """Loopback NDJSON server implementing the subset of herdr we rely on."""

    def __init__(self) -> None:
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self.port: int = self._listener.getsockname()[1]

        self.snapshot_payload: dict[str, Any] = {}
        self.panes: dict[str, dict[str, Any]] = {}
        self.agents: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.subscriptions: list[list[dict[str, Any]]] = []
        self.connections_opened = 0

        self._handlers: dict[str, Handler] = {}
        self._running = threading.Event()
        self._running.set()
        self._threads: list[threading.Thread] = []
        self._streams: list[_StreamSession] = []
        self._lock = threading.Lock()
        self._accept = threading.Thread(target=self._accept_loop, name="fake-herdr", daemon=True)
        self._accept.start()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        self._running.clear()
        for session in list(self._streams):
            session.stop()
        with self._lock:
            self._listener.close()

    def __enter__(self) -> FakeHerdr:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- scripting ---------------------------------------------------------

    def on(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    def stream_factory(self):
        """A HerdrClient/HerdrStream factory pointed at this fake."""
        from herdr_notify.herdr.transport import LocalStream

        def _factory() -> LocalStream:
            sock = socket.create_connection(("127.0.0.1", self.port), timeout=5.0)
            return LocalStream.from_socket(sock)

        return _factory

    def set_snapshot(
        self,
        *,
        agents: list[dict[str, Any]],
        panes: list[dict[str, Any]] | None = None,
        workspaces: list[dict[str, Any]] | None = None,
        version: str = "0.9.1",
    ) -> None:
        self.snapshot_payload = {
            "version": version,
            "protocol": 22,
            "focused_workspace_id": None,
            "focused_tab_id": None,
            "focused_pane_id": None,
            "workspaces": workspaces or [],
            "tabs": [],
            "panes": panes if panes is not None else [dict(a) for a in agents],
            "agents": agents,
            "layouts": [],
        }
        self.agents = {a["pane_id"]: a for a in agents}
        self.panes = {p["pane_id"]: p for p in (panes if panes is not None else agents)}

    def set_agent(self, pane_id: str, **changes: Any) -> None:
        """Update a pane/agent everywhere the fake reports it.

        All three views have to move together. A fake whose ``agent.get`` says
        ``blocked`` while its ``session.snapshot`` still says ``working`` makes
        every stream rotation look like a state change, which is exactly the
        class of bug these tests exist to catch.
        """
        with self._lock:
            existing = self.agents.get(pane_id)
            if existing is None:
                workspace_id = str(changes.get("workspace_id") or pane_id.split(":")[0])
                existing = agent_record(pane_id, workspace_id)
            existing.update(changes)
            self.agents[pane_id] = existing
            self.panes[pane_id] = dict(existing)
            self._rewrite_snapshot()
            if workspace_record_for(existing) not in self.snapshot_payload["workspaces"]:
                self.snapshot_payload["workspaces"].append(workspace_record_for(existing))

    def _rewrite_snapshot(self) -> None:
        self.snapshot_payload["agents"] = [dict(a) for a in self.agents.values()]
        self.snapshot_payload["panes"] = [dict(p) for p in self.panes.values()]

    def emit(self, event: str, data: dict[str, Any]) -> None:
        """Push one event to every open subscription stream."""
        for session in list(self._streams):
            session.send({"event": event, "data": data})

    def emit_to_all(self, events: Iterator[tuple[str, dict[str, Any]]]) -> None:
        for event, data in events:
            self.emit(event, data)

    @property
    def subscription_sets(self) -> list[list[dict[str, Any]]]:
        return list(self.subscriptions)

    def request_over_socket(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """One request/response over a fresh connection, as herdr actually does.

        herdr answers a single request and closes, so the fake offers the same
        shape rather than a persistent-session shortcut. Anything that depends
        on that detail — retry behaviour, connection reuse, timeouts — is then
        exercised rather than assumed away.
        """
        client = socket.create_connection(("127.0.0.1", self.port), timeout=5.0)
        try:
            with self._lock:
                self.connections_opened += 1
            payload = json.dumps({"id": "t1", "method": method, "params": params or {}})
            client.sendall(payload.encode() + b"\n")
            buffer = bytearray()
            while b"\n" not in buffer:
                chunk = client.recv(65536)
                if not chunk:
                    raise OSError("fake closed without answering")
                buffer += chunk
            line = bytes(buffer[: buffer.index(b"\n")])
        finally:
            client.close()
        response = json.loads(line)
        if "error" in response:
            raise KeyError(response["error"].get("code", "error"))
        result = response.get("result")
        return result if isinstance(result, dict) else {}

    def subscribed_panes(self, index: int = -1) -> set[str]:
        if not self.subscriptions:
            return set()
        return {
            s["pane_id"]
            for s in self.subscriptions[index]
            if s.get("type") == "pane.agent_status_changed"
        }

    # -- server ------------------------------------------------------------

    def _accept_loop(self) -> None:
        while self._running.is_set():
            try:
                client, _ = self._listener.accept()
            except OSError:
                return
            with self._lock:
                self.connections_opened += 1
            threading.Thread(
                target=self._serve, args=(client,), name="fake-herdr-conn", daemon=True
            ).start()

    def _serve(self, client: socket.socket) -> None:
        buffer = bytearray()
        session: _StreamSession | None = None
        try:
            while self._running.is_set():
                try:
                    chunk = client.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    index = buffer.index(b"\n")
                    line = bytes(buffer[:index])
                    del buffer[: index + 1]
                    if not line.strip():
                        continue
                    request = json.loads(line)
                    if request.get("method") == "events.subscribe":
                        session = _StreamSession(client)
                        with self._lock:
                            self._streams.append(session)
                            self.subscriptions.append(
                                list(request.get("params", {}).get("subscriptions", []))
                            )
                        client.sendall(
                            json.dumps(
                                {
                                    "id": request["id"],
                                    "result": {"type": "subscription_started"},
                                }
                            ).encode()
                            + b"\n"
                        )
                        continue
                    self._dispatch(client, request)
        finally:
            if session is not None:
                session.stop()
            try:
                client.close()
            except OSError:
                pass

    def _dispatch(self, client: socket.socket, request: dict[str, Any]) -> None:
        method = str(request.get("method") or "")
        params = request.get("params") or {}
        with self._lock:
            self.requests.append((method, params))
        handler = self._handlers.get(method)
        if handler is not None:
            result = handler(method, params)
            if result is not None:
                self._reply(client, request["id"], result)
                return
        self._default(client, request, method, params)

    def _default(
        self,
        client: socket.socket,
        request: dict[str, Any],
        method: str | None,
        params: dict[str, Any],
    ) -> None:
        match method:
            case "ping":
                self._reply(
                    client,
                    request["id"],
                    {"type": "pong", "version": "0.9.1", "protocol": 22, "capabilities": {}},
                )
            case "session.snapshot":
                with self._lock:
                    payload = json.loads(json.dumps(self.snapshot_payload))
                self._reply(
                    client, request["id"], {"type": "session_snapshot", "snapshot": payload}
                )
            case "pane.get":
                pane_id = str(params.get("pane_id") or "")
                with self._lock:
                    pane = self.panes.get(pane_id)
                if pane is None:
                    self._error(client, request["id"], "not_found", f"pane {pane_id} not found")
                else:
                    self._reply(client, request["id"], {"type": "pane_info", "pane": dict(pane)})
            case "agent.get":
                target = str(params.get("target") or "")
                with self._lock:
                    agent = self.agents.get(target)
                if agent is None:
                    self._error(client, request["id"], "not_found", f"agent {target} not found")
                else:
                    self._reply(client, request["id"], {"type": "agent_info", "agent": dict(agent)})
            case "workspace.create":
                label = str(params.get("label") or "untitled")
                workspace_id = f"w{len(self.snapshot_payload['workspaces']) + 10:X}"
                pane_id = f"{workspace_id}:p1"
                pane = {
                    "pane_id": pane_id,
                    "workspace_id": workspace_id,
                    "agent_status": "unknown",
                    "cwd": params.get("cwd") or ".",
                    "focused": False,
                    "revision": 0,
                    "tab_id": f"{workspace_id}:t1",
                }
                workspace = {
                    "workspace_id": workspace_id,
                    "label": label,
                    "pane_count": 1,
                    "tab_count": 1,
                    "agent_status": "unknown",
                    "focused": False,
                    "number": len(self.snapshot_payload["workspaces"]) + 10,
                    "active_tab_id": f"{workspace_id}:t1",
                }
                with self._lock:
                    self.panes[pane_id] = pane
                    self.snapshot_payload["workspaces"].append(workspace)
                self._reply(
                    client,
                    request["id"],
                    {"type": "workspace_created", "workspace": workspace, "root_pane": pane},
                )
            case "agent.start":
                pane_id = str(params.get("pane") or "")
                name = str(params.get("name") or "agent")
                kind = str(params.get("kind") or "opencode")
                with self._lock:
                    pane = self.panes.get(pane_id)
                if pane is None:
                    self._error(client, request["id"], "not_found", f"pane {pane_id} not found")
                else:
                    agent = agent_record(
                        pane_id=pane_id, status="idle", workspace_id=pane_id.split(":")[0]
                    )
                    agent["name"] = name
                    agent["agent"] = kind
                    with self._lock:
                        self.agents[pane_id] = agent
                    self._reply(client, request["id"], {"type": "agent_started", "agent": agent})
            case _:
                self._error(client, request["id"], "method_not_found", f"unknown method {method}")

    @staticmethod
    def _reply(client: socket.socket, request_id: str, result: dict[str, Any]) -> None:
        client.sendall(json.dumps({"id": request_id, "result": result}).encode() + b"\n")

    @staticmethod
    def _error(client: socket.socket, request_id: str, code: str, message: str) -> None:
        client.sendall(
            json.dumps({"id": request_id, "error": {"code": code, "message": message}}).encode()
            + b"\n"
        )


class _StreamSession:
    def __init__(self, client: socket.socket) -> None:
        self._client = client
        self._closed = False

    def send(self, message: dict[str, Any]) -> None:
        if self._closed:
            return
        try:
            self._client.sendall(json.dumps(message).encode() + b"\n")
        except OSError:
            self._closed = True

    def stop(self) -> None:
        self._closed = True


def agent_record(
    pane_id: str,
    workspace_id: str,
    status: str = "working",
    **overrides: Any,
) -> dict[str, Any]:
    """Build an agent record shaped like herdr's real snapshot output."""
    record: dict[str, Any] = {
        "pane_id": pane_id,
        "workspace_id": workspace_id,
        "tab_id": f"{workspace_id}:t1",
        "agent": "opencode",
        "agent_status": status,
        "cwd": f"C:\\dev\\{workspace_id}",
        "terminal_id": f"term_{pane_id}",
        "terminal_title": f"OC | {workspace_id} task",
        "terminal_title_stripped": f"OC | {workspace_id} task",
        "state_change_seq": 1,
        "revision": 1,
        "focused": False,
        "agent_session": {
            "source": "herdr:opencode",
            "agent": "opencode",
            "kind": "id",
            "value": f"ses_{pane_id}",
        },
    }
    record.update(overrides)
    return record


def workspace_record(workspace_id: str, label: str) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "number": 1,
        "label": label,
        "focused": False,
        "pane_count": 1,
        "tab_count": 1,
        "active_tab_id": f"{workspace_id}:t1",
        "agent_status": None,
    }


def workspace_record_for(agent: dict[str, Any]) -> dict[str, Any]:
    workspace_id = str(agent.get("workspace_id") or "")
    return workspace_record(workspace_id, workspace_id)
