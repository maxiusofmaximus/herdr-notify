"""Triage ranking: which agents deserve attention, and in what order.

The ordering is the product. An agent that is *waiting for a human decision* is
categorically different from one that is quietly working, and a notification
system that treats them alike gets muted within a day. herdr already models the
distinction — ``blocked`` means an approval or question UI is up, ``done`` means
finished and not yet seen — so this ranks its semantics rather than inventing new
ones.

``done`` is the second tier rather than the first on purpose. Being blocked means
someone is waiting on you; being done means there is something to look at. Mixing
them trains the user to dismiss the blocked ones too.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from ..state.models import AgentStatus, coerce_status


class Attention(IntEnum):
    """How loudly an agent should be surfaced. Higher sorts first."""

    NONE = 0
    """Idle and already seen. Nothing to say."""

    INFO = 1
    """Working, or in a state we could not classify. In the app, never pushed."""

    REVIEW = 2
    """Finished and unseen. Worth a notification, not an interruption."""

    URGENT = 3
    """Waiting for a human decision. Push, and act on it from the lock screen."""


_STATUS_ATTENTION: dict[AgentStatus, Attention] = {
    "blocked": Attention.URGENT,
    "done": Attention.REVIEW,
    "working": Attention.INFO,
    "unknown": Attention.INFO,
    "idle": Attention.NONE,
}

#: States a push may be sent for. ``working`` and ``idle`` are excluded on
#: purpose: pinging someone because their agent is still working is how a
#: notification channel dies.
NOTIFIABLE: frozenset[Attention] = frozenset({Attention.URGENT, Attention.REVIEW})


def attention_for(status: AgentStatus) -> Attention:
    return _STATUS_ATTENTION.get(status, Attention.INFO)


def is_notifiable(status: AgentStatus) -> bool:
    return attention_for(status) in NOTIFIABLE


@dataclass(frozen=True, slots=True)
class TriageRow:
    """One agent, ranked and ready to render."""

    pane_id: str
    workspace_id: str
    project: str
    agent: str
    status: AgentStatus
    attention: Attention
    title: str | None
    cwd: str | None
    focused: bool
    can_resume: bool

    @classmethod
    def from_view_entry(cls, entry: dict[str, Any]) -> TriageRow:
        # An unrecognised status degrades to "unknown" rather than raising. The
        # read model comes off the wire, and a herdr version that adds a state
        # must not be able to break the app's triage list.
        status = coerce_status(entry.get("status")) or "unknown"
        return cls(
            pane_id=str(entry.get("pane_id") or ""),
            workspace_id=str(entry.get("workspace_id") or ""),
            project=str(entry.get("project") or entry.get("workspace_id") or "?"),
            agent=str(entry.get("agent") or "agent"),
            status=status,
            attention=attention_for(status),
            title=entry.get("title"),
            cwd=entry.get("cwd"),
            focused=bool(entry.get("focused")),
            can_resume=bool(entry.get("can_resume")),
        )

    def sort_key(self) -> tuple[int, int, str, str]:
        """Urgency first, then the focused pane, then stable name order.

        The focused pane is a tiebreaker rather than a promotion: herdr's focus
        reflects whichever client moved last, and it must not outrank a genuine
        ``blocked`` agent elsewhere in the session.
        """
        return (
            -int(self.attention),
            0 if self.focused else 1,
            self.project.lower(),
            self.pane_id,
        )

    def to_public(self) -> dict[str, Any]:
        return {
            "pane_id": self.pane_id,
            "workspace_id": self.workspace_id,
            "project": self.project,
            "agent": self.agent,
            "status": self.status,
            "attention": int(self.attention),
            "title": self.title,
            "cwd": self.cwd,
            "focused": self.focused,
            "can_resume": self.can_resume,
        }


def triage(view: dict[str, Any]) -> list[TriageRow]:
    """Rank a read model into the order the app should display it."""
    rows = [TriageRow.from_view_entry(entry) for entry in view.get("agents") or []]
    rows.sort(key=TriageRow.sort_key)
    return rows


def counts(rows: list[TriageRow]) -> dict[str, int]:
    """Per-status tallies, for the app's summary row."""
    tally: dict[str, int] = {}
    for row in rows:
        tally[row.status] = tally.get(row.status, 0) + 1
    return tally


__all__ = [
    "NOTIFIABLE",
    "Attention",
    "TriageRow",
    "attention_for",
    "counts",
    "is_notifiable",
    "triage",
]
