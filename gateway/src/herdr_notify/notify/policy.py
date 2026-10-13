"""When a state change is allowed to become a phone notification.

Getting this wrong is the only way this project can really fail. Too eager and
the user mutes the channel, after which the one agent that actually needed them
stays silent forever. Three independent brakes, checked in this order:

**Eligibility.** Only ``blocked`` and ``done`` are ever pushed, and a change that
came from a snapshot rather than a live event never is. Without that last part,
restarting the gateway or recovering from a dropped event would produce one
notification per agent in the session.

**Cooldown.** One push per agent per window, with a longer repeat interval for an
agent that is *still* blocked. An agent blocked for ten minutes is either still
stuck or was never really blocked, and the user deserves one more nudge — not one
every thirty seconds.

**Budget.** Hard caps per agent, per hour and per day. These are not only about
experience: FCM is a metered third-party service, and an agent flapping between
two states must not be able to exhaust a quota or spend money unattended.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from ..state.store import AgentChange, Transition
from .attention import Attention, attention_for

DAY_SECONDS = 86400.0


class Verdict(StrEnum):
    ALLOW = "allow"
    DEFER = "defer"
    SUPPRESS = "suppress"


@dataclass(frozen=True, slots=True)
class Decision:
    verdict: Verdict
    reason: str
    priority: str = "normal"
    wake_at: float | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


@dataclass(slots=True)
class PushPolicy:
    """Decides whether a change becomes a notification."""

    cooldown_seconds: float = 120.0
    """Minimum gap between two pushes for the same pane."""

    escalate_after_seconds: float | None = 900.0
    """Repeat interval for an agent still blocked and still unseen.

    ``None`` disables the repeat entirely.
    """

    max_per_agent_per_hour: int = 6
    max_per_hour: int = 60
    max_per_day: int = 400

    quiet_hours: tuple[int, int] | None = None
    """Local ``(start_hour, end_hour)`` in 0-23, wrapping past midnight.

    ``None`` disables it. ``URGENT`` still sends during quiet hours: an approval
    dialog that waits until morning is an agent burning tokens and wall-clock.
    """

    clock: Callable[[], float] = time.time

    _last_sent: dict[str, float] = field(default_factory=dict, repr=False)
    _history: deque[tuple[float, str]] = field(default_factory=deque, repr=False)

    # -- entry point -------------------------------------------------------

    def decide(self, change: AgentChange) -> Decision:
        """Decide one change, recording it only if the decision is ALLOW."""
        if change.synthetic:
            return Decision(Verdict.SUPPRESS, "synthetic")
        if change.trigger is Transition.REMOVED:
            return Decision(Verdict.SUPPRESS, "removed")

        attention = attention_for(change.after or "unknown")
        if attention not in (Attention.URGENT, Attention.REVIEW):
            return Decision(Verdict.SUPPRESS, f"status={change.after}")

        now = self.clock()

        quiet = self._quiet_hours(now, attention)
        if quiet is not None:
            return quiet

        if not self._within_cooldown(change.pane_id, attention, now):
            return Decision(
                Verdict.SUPPRESS,
                "cooldown",
                wake_at=self._next_allowed(change.pane_id),
            )

        if not self._within_budget(change.pane_id, now):
            return Decision(Verdict.SUPPRESS, "budget")

        self._record(change.pane_id, now)
        return Decision(Verdict.ALLOW, "eligible", priority="high")

    # -- brakes ------------------------------------------------------------

    def _quiet_hours(self, now: float, attention: Attention) -> Decision | None:
        if self.quiet_hours is None or attention is Attention.URGENT:
            return None
        start, end = self.quiet_hours
        hour = time.localtime(now).tm_hour
        inside = start <= hour < end if start < end else (hour >= start or hour < end)
        if not inside:
            return None
        return Decision(Verdict.DEFER, "quiet_hours", wake_at=_next_hour_boundary(end, now))

    def _within_cooldown(self, pane_id: str, attention: Attention, now: float) -> bool:
        last = self._last_sent.get(pane_id)
        if last is None:
            return True
        window = self.cooldown_seconds
        if attention is Attention.URGENT and self.escalate_after_seconds is not None:
            window = self.escalate_after_seconds
        return (now - last) >= window

    def _next_allowed(self, pane_id: str) -> float | None:
        last = self._last_sent.get(pane_id)
        return None if last is None else last + self.cooldown_seconds

    def _within_budget(self, pane_id: str, now: float) -> bool:
        self._prune(now)
        if self.max_per_hour and len(self._history) >= self.max_per_hour:
            return False
        if self.max_per_agent_per_hour:
            recent = sum(1 for at, pane in self._history if pane == pane_id)
            if recent >= self.max_per_agent_per_hour:
                return False
        if self.max_per_day:
            today = sum(1 for at, _ in self._history if at >= now - DAY_SECONDS)
            if today >= self.max_per_day:
                return False
        return True

    def _prune(self, now: float) -> None:
        cutoff = now - DAY_SECONDS
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

    def _record(self, pane_id: str, now: float) -> None:
        self._last_sent[pane_id] = now
        self._history.append((now, pane_id))

    # -- introspection -----------------------------------------------------

    def sent_count(self) -> int:
        return len(self._history)

    def sent_for(self, pane_id: str) -> int:
        return sum(1 for _, pane in self._history if pane == pane_id)

    def reset(self) -> None:
        self._last_sent.clear()
        self._history.clear()


def _next_hour_boundary(hour: int, now: float) -> float:
    """The next occurrence of a given local hour, at least one minute away.

    Quiet hours end at a wall-clock hour, so the deferral is released when that
    hour next comes round rather than a fixed number of seconds later.
    """
    local = time.localtime(now)
    midnight = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))
    target = midnight + hour * 3600
    if target <= now:
        target += DAY_SECONDS
    return target


__all__ = ["DAY_SECONDS", "Decision", "PushPolicy", "Verdict"]
