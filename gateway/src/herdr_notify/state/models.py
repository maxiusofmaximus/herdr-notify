"""Typed view of herdr's session state.

Field names and optionality mirror what ``session.snapshot`` actually returns
from herdr 0.9.x, captured live rather than inferred from prose. Every model
allows extra fields on purpose: herdr's own API guidance tells clients to ignore
unknown fields so a server upgrade never breaks an existing client.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

AgentStatus = Literal["idle", "working", "blocked", "done", "unknown"]

AGENT_STATUSES: tuple[AgentStatus, ...] = ("idle", "working", "blocked", "done", "unknown")

_STATUS_SET: frozenset[str] = frozenset(AGENT_STATUSES)

# herdr treats idle and done as "ready for input"; done additionally means "not
# yet seen by the operator". That distinction is what makes a notification
# worth sending, so it is modelled rather than collapsed.
NEEDS_INPUT: frozenset[str] = frozenset({"idle", "done"})

# States that mean the agent is actively doing something. Never notify on these.
BUSY: frozenset[str] = frozenset({"working"})


def coerce_status(value: object) -> AgentStatus | None:
    """Narrow an untrusted JSON value to a known agent status.

    Event payloads are untrusted input: an unknown or missing status must be
    dropped rather than stored, or the app would render a state herdr never
    reported and the push policy would act on garbage.
    """
    if isinstance(value, str) and value in _STATUS_SET:
        return cast("AgentStatus", value)
    return None


class _Base(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class Rect(_Base):
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


class ScrollInfo(_Base):
    offset_from_bottom: int | None = None
    max_offset_from_bottom: int | None = None
    viewport_rows: int | None = None


class AgentSessionRef(_Base):
    """Native resume reference reported by an official herdr integration."""

    source: str
    agent: str
    kind: str
    value: str


class AgentRecord(_Base):
    """One recognised coding agent occupying a pane."""

    pane_id: str
    workspace_id: str
    tab_id: str | None = None
    agent: str | None = None
    display_agent: str | None = None
    agent_status: AgentStatus = "unknown"
    agent_session: AgentSessionRef | None = None
    cwd: str | None = None
    terminal_id: str | None = None
    terminal_title: str | None = None
    terminal_title_stripped: str | None = None
    screen_detection_skipped: bool | None = None
    state_change_seq: int = 0
    revision: int = 0
    focused: bool = False

    @property
    def display_name(self) -> str:
        """What the operator sees. herdr's `display_agent` overrides the kind."""
        return self.display_agent or self.agent or "agent"

    @property
    def task_title(self) -> str | None:
        """Best available human label for what the agent is doing.

        ``terminal_title_stripped`` is preferred over ``terminal_title`` because
        herdr already strips a leading spinner/activity glyph from it.
        """
        for candidate in (self.terminal_title_stripped, self.terminal_title):
            if candidate and candidate.strip():
                return candidate.strip()
        return None

    @property
    def project_name(self) -> str | None:
        """Last path segment of cwd — the project a developer would name."""
        if not self.cwd:
            return None
            # Herdr runs on Windows, macOS and Linux; cwd is a native path.
        normalised = self.cwd.replace("\\", "/").rstrip("/")
        if not normalised:
            return None
        tail = normalised.rsplit("/", 1)[-1]
        return tail or None


class PaneRecord(_Base):
    pane_id: str
    workspace_id: str
    tab_id: str | None = None
    cwd: str | None = None
    agent: str | None = None
    agent_status: AgentStatus | None = None
    agent_session: AgentSessionRef | None = None
    terminal_id: str | None = None
    terminal_title: str | None = None
    terminal_title_stripped: str | None = None
    scroll: ScrollInfo | None = None
    revision: int = 0
    focused: bool = False


class TabRecord(_Base):
    tab_id: str
    workspace_id: str
    number: int | None = None
    label: str | None = None
    focused: bool = False
    pane_count: int = 0
    agent_status: AgentStatus | None = None


class WorkspaceRecord(_Base):
    workspace_id: str
    number: int | None = None
    label: str | None = None
    focused: bool = False
    pane_count: int = 0
    tab_count: int = 0
    active_tab_id: str | None = None
    agent_status: AgentStatus | None = None

    @property
    def display_name(self) -> str:
        return self.label or self.workspace_id


class SnapshotMeta(_Base):
    version: str | None = None
    protocol: int | None = None
    focused_workspace_id: str | None = None
    focused_tab_id: str | None = None
    focused_pane_id: str | None = None


class Snapshot(_Base):
    """The one-time bootstrap payload from ``session.snapshot``.

    herdr wraps this in ``result.snapshot``; callers must not look for the
    collections at the response root.
    """

    workspaces: list[WorkspaceRecord] = Field(default_factory=list)
    tabs: list[TabRecord] = Field(default_factory=list)
    panes: list[PaneRecord] = Field(default_factory=list)
    agents: list[AgentRecord] = Field(default_factory=list)
    layouts: list[dict[str, Any]] = Field(default_factory=list)
    version: str | None = None
    protocol: int | None = None
    focused_workspace_id: str | None = None
    focused_tab_id: str | None = None
    focused_pane_id: str | None = None

    @property
    def meta(self) -> SnapshotMeta:
        return SnapshotMeta(
            version=self.version,
            protocol=self.protocol,
            focused_workspace_id=self.focused_workspace_id,
            focused_tab_id=self.focused_tab_id,
            focused_pane_id=self.focused_pane_id,
        )
