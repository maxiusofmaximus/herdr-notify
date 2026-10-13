"""Authoritative mirror of a herdr session, reduced from snapshot plus events.

The store is the single source of truth for everything downstream: the push
policy, the API read model and the SSE stream. Two properties matter and are
tested directly:

**Idempotence.** ``events.subscribe`` sets can be rotated (see
``watcher.py``), and a rotation can replay an event the previous stream already
delivered. Re-applying a status change must be a no-op, not a duplicate
notification.

**Rollup ownership.** herdr reports ``agent_status`` on workspace and tab
records, but a status event for one pane invalidates its workspace's and tab's
rollup too. Recomputing rollups locally from the pane set keeps the view
self-consistent even if a ``workspace.updated`` event is missed.

Every mutation bumps ``revision``. The Android client uses it to detect a gap in
the SSE stream and re-fetch the full view instead of trusting a partial delta.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .models import (
    AgentRecord,
    AgentStatus,
    PaneRecord,
    Snapshot,
    TabRecord,
    WorkspaceRecord,
)

# Worst-first. A rollup takes the maximum attention present in its subtree, so
# one blocked agent surfaces its whole workspace to the top of the triage list.
ROLLS_UP_ORDER: tuple[AgentStatus, ...] = ("blocked", "working", "done", "idle", "unknown")

_REVISION = itertools.count(1)


def rollup_status(statuses: list[AgentStatus]) -> AgentStatus:
    """Combine agent statuses into one status for a tab or workspace."""
    if not statuses:
        return "unknown"
    present = set(statuses)
    for candidate in ROLLS_UP_ORDER:
        if candidate in present:
            return candidate
    return "unknown"


class StreamAction(StrEnum):
    """What the watcher must do with the subscription stream after an event."""

    NONE = "none"
    ROTATE = "rotate"


class Transition(StrEnum):
    """Semantic change worth reacting to."""

    BECAME_BLOCKED = "became_blocked"
    BECAME_DONE = "became_done"
    BECAME_WORKING = "became_working"
    BECAME_IDLE = "became_idle"
    BECAME_UNKNOWN = "became_unknown"
    REMOVED = "removed"
    APPEARED = "appeared"
    RESYNC = "resync"


@dataclass(frozen=True, slots=True)
class AgentChange:
    """One agent's before/after state, produced by an event or a resync."""

    pane_id: str
    workspace_id: str
    before: AgentStatus | None
    after: AgentStatus | None
    at: float
    trigger: Transition
    synthetic: bool = False
    """True when the change came from a snapshot rather than a live event.

    A snapshot reports *everything* as a change on the way in, because there is
    no prior state to diff against. Treating those as news would fire a push for
    every agent in the session each time the gateway starts or recovers — the
    single most obvious way to make a notification system get uninstalled. The
    push policy skips synthetic changes; the API still surfaces them so the app
    can render the initial view.
    """

    @property
    def changed(self) -> bool:
        return self.before != self.after


@dataclass(slots=True)
class EventOutcome:
    """Everything the watcher learns from one event."""

    event: str
    changes: list[AgentChange] = field(default_factory=list)
    stream: StreamAction = StreamAction.NONE
    needs_hydration: set[str] = field(default_factory=set)


class SessionState:
    """The reduced session. Mutate only through :class:`Store`."""

    def __init__(self) -> None:
        self.version: str | None = None
        self.protocol: int | None = None
        self.focused_workspace_id: str | None = None
        self.focused_tab_id: str | None = None
        self.focused_pane_id: str | None = None
        self.workspaces: dict[str, WorkspaceRecord] = {}
        self.tabs: dict[str, TabRecord] = {}
        self.panes: dict[str, PaneRecord] = {}
        self.agents: dict[str, AgentRecord] = {}
        self.revision: int = 0
        self.installed_at: float = 0.0
        self.updated_at: float = 0.0

    # -- collections -------------------------------------------------------

    def pane_ids(self) -> set[str]:
        """Every live pane id that needs a status subscription."""
        return set(self.panes) | set(self.agents)

    def agent_records(self) -> list[AgentRecord]:
        return sorted(self.agents.values(), key=lambda a: a.pane_id)

    def workspace_label(self, workspace_id: str) -> str:
        record = self.workspaces.get(workspace_id)
        if record is not None and record.label:
            return record.label
        for agent in self.agents.values():
            if agent.workspace_id == workspace_id and agent.project_name:
                return agent.project_name
        return workspace_id

    # -- view --------------------------------------------------------------

    def view(self) -> dict[str, Any]:
        """The read model served over the API and rendered by the app."""
        agents: list[dict[str, Any]] = []
        for record in self.agent_records():
            agents.append(
                {
                    "pane_id": record.pane_id,
                    "workspace_id": record.workspace_id,
                    "tab_id": record.tab_id,
                    "project": self.workspace_label(record.workspace_id),
                    "agent": record.display_name,
                    "status": record.agent_status,
                    "title": record.task_title,
                    "cwd": record.cwd,
                    "focused": record.focused,
                    "state_change_seq": record.state_change_seq,
                    "can_resume": record.agent_session is not None,
                    "session_kind": (record.agent_session.kind if record.agent_session else None),
                }
            )
        return {
            "revision": self.revision,
            "herdr_version": self.version,
            "protocol": self.protocol,
            "installed_at": self.installed_at,
            "updated_at": self.updated_at,
            "focused": {
                "workspace_id": self.focused_workspace_id,
                "tab_id": self.focused_tab_id,
                "pane_id": self.focused_pane_id,
            },
            "counts": {
                "workspaces": len(self.workspaces),
                "panes": len(self.panes),
                "agents": len(self.agents),
            },
            "agents": agents,
        }


class Store:
    """Reduces herdr snapshots and events into a :class:`SessionState`."""

    def __init__(self) -> None:
        self.state = SessionState()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Register a change listener; returns an unsubscribe callable."""
        self._subscribers.append(callback)

        def _remove() -> None:
            with_suppress = self._subscribers
            if callback in with_suppress:
                with_suppress.remove(callback)

        return _remove

    # -- bootstrap ---------------------------------------------------------

    def install(self, snapshot: Snapshot) -> list[AgentChange]:
        """Replace all state with a fresh snapshot.

        Installing is a resync, not a merge: it is the only correct way to
        recover from a rotated stream, a restarted server or dropped events, and
        it is the only path allowed to clear records that herdr no longer
        reports.
        """
        now = time.time()
        changes: list[AgentChange] = []
        previous: dict[str, AgentStatus] = {
            pane_id: rec.agent_status for pane_id, rec in self.state.agents.items()
        }

        state = SessionState()
        state.version = snapshot.version
        state.protocol = snapshot.protocol
        state.focused_workspace_id = snapshot.focused_workspace_id
        state.focused_tab_id = snapshot.focused_tab_id
        state.focused_pane_id = snapshot.focused_pane_id
        state.workspaces = {w.workspace_id: w for w in snapshot.workspaces}
        state.tabs = {t.tab_id: t for t in snapshot.tabs}
        state.panes = {p.pane_id: p for p in snapshot.panes}
        state.agents = {a.pane_id: a for a in snapshot.agents}
        state.revision = next(_REVISION)
        state.installed_at = now
        state.updated_at = now

        self._recompute_rollups(state)
        self.state = state

        for pane_id, record in state.agents.items():
            before = previous.get(pane_id)
            if before != record.agent_status:
                changes.append(
                    AgentChange(
                        pane_id=pane_id,
                        workspace_id=record.workspace_id,
                        before=before,
                        after=record.agent_status,
                        at=now,
                        trigger=_transition(before, record.agent_status),
                        synthetic=True,
                    )
                )
        for pane_id, before in previous.items():
            if pane_id not in state.agents:
                changes.append(
                    AgentChange(
                        pane_id=pane_id,
                        workspace_id=state.panes.get(
                            pane_id, PaneRecord(pane_id=pane_id, workspace_id="")
                        ).workspace_id,
                        before=before,
                        after=None,
                        at=now,
                        trigger=Transition.REMOVED,
                        synthetic=True,
                    )
                )
        return changes

    # -- events ------------------------------------------------------------

    def apply(self, event: str, data: dict[str, Any]) -> EventOutcome:
        """Apply one subscription event.

        Unknown events are ignored rather than treated as errors: herdr adds
        event types over time and an unknown name must not tear down the stream.
        """
        outcome = EventOutcome(event=event)
        state = self.state
        now = time.time()
        handler = _HANDLERS.get(event)
        if handler is None:
            return outcome

        handler(self, data, outcome, now)
        if outcome.changes or outcome.stream is not StreamAction.NONE:
            state.revision = next(_REVISION)
            state.updated_at = now
        return outcome

    # -- handlers ----------------------------------------------------------

    def _on_agent_status_changed(
        self, data: dict[str, Any], outcome: EventOutcome, now: float
    ) -> None:
        pane_id = data.get("pane_id")
        workspace_id = data.get("workspace_id")
        raw_status = data.get("agent_status")
        if not isinstance(pane_id, str) or not isinstance(workspace_id, str):
            return
        if raw_status not in ("idle", "working", "blocked", "done", "unknown"):
            return

        record = self.state.agents.get(pane_id)
        if record is None:
            # The status event for a pane we have no record for. The event
            # carries no cwd, title or session reference, so a partial record
            # would show an empty project name in the app. Ask the watcher to
            # hydrate it from the server instead of guessing.
            outcome.needs_hydration.add(pane_id)
            return

        before = record.agent_status
        if before == raw_status and not _has_presentation_delta(record, data):
            return

        record.agent_status = raw_status
        for field_name in ("agent", "title", "display_agent"):
            value = data.get(field_name)
            if isinstance(value, str) and value:
                if field_name == "display_agent":
                    record.display_agent = value
                elif field_name == "title":
                    record.terminal_title = value
                    record.terminal_title_stripped = value
                else:
                    record.agent = value

        self._recompute_rollups(self.state)
        outcome.changes.append(
            AgentChange(
                pane_id=pane_id,
                workspace_id=workspace_id,
                before=before,
                after=record.agent_status,
                at=now,
                trigger=_transition(before, record.agent_status),
            )
        )

    def _on_pane_created(self, data: dict[str, Any], outcome: EventOutcome, now: float) -> None:
        pane_id = data.get("pane_id")
        if not isinstance(pane_id, str):
            return
        outcome.needs_hydration.add(pane_id)
        outcome.stream = StreamAction.ROTATE

    def _on_pane_agent_detected(
        self, data: dict[str, Any], outcome: EventOutcome, now: float
    ) -> None:
        pane_id = data.get("pane_id")
        if not isinstance(pane_id, str):
            return
        outcome.needs_hydration.add(pane_id)
        if pane_id not in self.state.agents:
            outcome.changes.append(
                AgentChange(
                    pane_id=pane_id,
                    workspace_id=data.get("workspace_id") or "",
                    before=None,
                    after=None,
                    at=now,
                    trigger=Transition.APPEARED,
                )
            )

    def _on_pane_closed(self, data: dict[str, Any], outcome: EventOutcome, now: float) -> None:
        pane_id = data.get("pane_id")
        if not isinstance(pane_id, str):
            return
        record = self.state.agents.pop(pane_id, None)
        self.state.panes.pop(pane_id, None)
        self._recompute_rollups(self.state)
        outcome.stream = StreamAction.ROTATE
        if record is not None:
            outcome.changes.append(
                AgentChange(
                    pane_id=pane_id,
                    workspace_id=record.workspace_id,
                    before=record.agent_status,
                    after=None,
                    at=now,
                    trigger=Transition.REMOVED,
                )
            )

    def _on_pane_exited(self, data: dict[str, Any], outcome: EventOutcome, now: float) -> None:
        self._on_pane_closed(data, outcome, now)

    def _on_workspace_closed(self, data: dict[str, Any], outcome: EventOutcome, now: float) -> None:
        workspace_id = data.get("workspace_id")
        if not isinstance(workspace_id, str):
            return
        doomed_panes = {
            pane_id
            for pane_id, pane in self.state.panes.items()
            if pane.workspace_id == workspace_id
        }
        self.state.workspaces.pop(workspace_id, None)
        for tab_id in [t for t, tab in self.state.tabs.items() if tab.workspace_id == workspace_id]:
            self.state.tabs.pop(tab_id, None)
        for pane_id in list(doomed_panes):
            record = self.state.agents.pop(pane_id, None)
            self.state.panes.pop(pane_id, None)
            if record is not None:
                outcome.changes.append(
                    AgentChange(
                        pane_id=pane_id,
                        workspace_id=workspace_id,
                        before=record.agent_status,
                        after=None,
                        at=now,
                        trigger=Transition.REMOVED,
                    )
                )
        self._recompute_rollups(self.state)
        outcome.stream = StreamAction.ROTATE

    def _on_pane_focused(self, data: dict[str, Any], outcome: EventOutcome, now: float) -> None:
        """Server-wide pane focus moved.

        herdr reports this for selection changes from *any* attached client, so
        it reflects what the operator is looking at, not what we asked for.
        """
        pane_id = data.get("pane_id")
        if not isinstance(pane_id, str):
            return
        self.state.focused_pane_id = pane_id
        for record in self.state.panes.values():
            record.focused = record.pane_id == pane_id
        for agent in self.state.agents.values():
            agent.focused = agent.pane_id == pane_id
        pane = self.state.panes.get(pane_id)
        if pane is not None:
            self.state.focused_tab_id = pane.tab_id
            self.state.focused_workspace_id = pane.workspace_id

    def _on_tab_focused(self, data: dict[str, Any], outcome: EventOutcome, now: float) -> None:
        tab_id = data.get("tab_id")
        if not isinstance(tab_id, str):
            return
        self.state.focused_tab_id = tab_id
        for record in self.state.tabs.values():
            record.focused = record.tab_id == tab_id
        tab = self.state.tabs.get(tab_id)
        if tab is not None:
            self.state.focused_workspace_id = tab.workspace_id

    def _on_workspace_focused(
        self, data: dict[str, Any], outcome: EventOutcome, now: float
    ) -> None:
        workspace_id = data.get("workspace_id")
        if not isinstance(workspace_id, str):
            return
        self.state.focused_workspace_id = workspace_id
        for record in self.state.workspaces.values():
            record.focused = record.workspace_id == workspace_id

    def _on_workspace_updated(
        self, data: dict[str, Any], outcome: EventOutcome, now: float
    ) -> None:
        record = self.state.workspaces.get(data.get("workspace_id", ""))
        if record is None:
            return
        label = data.get("label")
        if isinstance(label, str) and label:
            record.label = label
        if isinstance(data.get("focused"), bool):
            record.focused = data["focused"]

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _recompute_rollups(state: SessionState) -> None:
        """Recompute tab and workspace status from the agents inside them."""
        by_tab: dict[str, list[AgentStatus]] = {}
        by_workspace: dict[str, list[AgentStatus]] = {}
        for agent in state.agents.values():
            if agent.tab_id:
                by_tab.setdefault(agent.tab_id, []).append(agent.agent_status)
            by_workspace.setdefault(agent.workspace_id, []).append(agent.agent_status)

        for tab in state.tabs.values():
            tab.agent_status = rollup_status(by_tab.get(tab.tab_id, []))

        for workspace in state.workspaces.values():
            workspace.agent_status = rollup_status(by_workspace.get(workspace.workspace_id, []))

    def hydrate(self, pane: PaneRecord, agent: AgentRecord | None) -> None:
        """Insert or replace a pane/agent record fetched on demand.

        Marked synthetic for the same reason snapshot changes are: a pane we had
        not seen is not news the operator needs pushed.
        """
        self.state.panes[pane.pane_id] = pane
        if agent is not None:
            self.state.agents[pane.pane_id] = agent
        self.state.revision = next(_REVISION)
        self.state.updated_at = time.time()
        self._recompute_rollups(self.state)

    def snapshot_stream(self) -> Iterator[dict[str, Any]]:
        yield {"event": "state", "revision": self.state.revision, "state": self.state.view()}


def _has_presentation_delta(record: AgentRecord, data: dict[str, Any]) -> bool:
    """True when an event carries display text our record does not already have."""
    for field_name in ("agent", "title", "display_agent"):
        value = data.get(field_name)
        if not isinstance(value, str) or not value:
            continue
        if field_name == "agent" and record.agent != value:
            return True
        if field_name == "title" and record.terminal_title_stripped != value:
            return True
    return False


def _transition(before: AgentStatus | None, after: AgentStatus | None) -> Transition:
    if after is None:
        return Transition.REMOVED
    if before == after:
        return Transition.RESYNC
    match after:
        case "blocked":
            return Transition.BECAME_BLOCKED
        case "done":
            return Transition.BECAME_DONE
        case "working":
            return Transition.BECAME_WORKING
        case "idle":
            return Transition.BECAME_IDLE
        case _:
            return Transition.BECAME_UNKNOWN


_HANDLERS: dict[str, Callable[[Store, dict[str, Any], EventOutcome, float], None]] = {
    "pane.agent_status_changed": Store._on_agent_status_changed,
    "pane.created": Store._on_pane_created,
    "pane.agent_detected": Store._on_pane_agent_detected,
    "pane.closed": Store._on_pane_closed,
    "pane.exited": Store._on_pane_exited,
    "workspace.closed": Store._on_workspace_closed,
    "workspace.updated": Store._on_workspace_updated,
    "pane.focused": Store._on_pane_focused,
    "tab.focused": Store._on_tab_focused,
    "workspace.focused": Store._on_workspace_focused,
}
