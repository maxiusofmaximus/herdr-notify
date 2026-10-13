"""Push eligibility, dedup, cooldown, escalation and budget.

These tests are the anti-spam contract. A notification system that sends too
often is functionally identical to one that does not exist, and it is much
harder to notice: the bugs only show up as a user quietly muting the channel.
"""

from __future__ import annotations

import time

import pytest

from herdr_notify.notify.attention import Attention, attention_for, counts, is_notifiable, triage
from herdr_notify.notify.policy import DAY_SECONDS, PushPolicy, Verdict
from herdr_notify.state.store import AgentChange, Transition


class Clock:
    """A hand-cranked clock, so no test ever sleeps.

    Defaults to the real current time. Quiet hours are evaluated against local
    wall-clock, so a test that builds a window from the real hour while the
    clock sits on a fixed 2023 epoch is comparing two different days.
    """

    def __init__(self, start: float | None = None) -> None:
        self.now = time.time() if start is None else start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def change(
    pane_id: str = "w1:p1",
    before: str | None = "working",
    after: str | None = "blocked",
    *,
    synthetic: bool = False,
    workspace: str = "w1",
) -> AgentChange:
    if after is None:
        trigger = Transition.REMOVED
    elif after == "blocked":
        trigger = Transition.BECAME_BLOCKED
    elif after == "done":
        trigger = Transition.BECAME_DONE
    else:
        trigger = Transition.RESYNC
    return AgentChange(
        pane_id=pane_id,
        workspace_id=workspace,
        before=before,  # type: ignore[arg-type]
        after=after,  # type: ignore[arg-type]
        at=time.time(),
        trigger=trigger,
        synthetic=synthetic,
    )


# -- eligibility -----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("blocked", Attention.URGENT),
        ("done", Attention.REVIEW),
        ("working", Attention.INFO),
        ("unknown", Attention.INFO),
        ("idle", Attention.NONE),
    ],
)
def test_attention_maps_herdr_semantics(status: str, expected: Attention) -> None:
    assert attention_for(status) == expected  # type: ignore[arg-type]


def test_working_and_idle_are_never_notifiable() -> None:
    """Pinging someone because their agent is still working is how channels die."""
    assert is_notifiable("blocked") is True
    assert is_notifiable("done") is True
    assert is_notifiable("working") is False
    assert is_notifiable("idle") is False
    assert is_notifiable("unknown") is False


def test_synthetic_bootstrap_changes_are_never_pushed() -> None:
    """Without this, every gateway restart pushes one notification per agent."""
    clock = Clock()
    policy = PushPolicy(clock=clock)
    decision = policy.decide(change(after="blocked", synthetic=True))
    assert decision.verdict is Verdict.SUPPRESS
    assert decision.reason == "synthetic"
    assert policy.sent_count() == 0


def test_working_transition_is_suppressed() -> None:
    policy = PushPolicy(clock=Clock())
    decision = policy.decide(change(after="working"))
    assert decision.verdict is Verdict.SUPPRESS
    assert policy.sent_count() == 0


def test_blocked_is_allowed_and_recorded() -> None:
    clock = Clock()
    policy = PushPolicy(clock=clock)
    decision = policy.decide(change(after="blocked"))
    assert decision.verdict is Verdict.ALLOW
    assert decision.priority == "high"
    assert policy.sent_count() == 1


def test_removed_agent_is_suppressed() -> None:
    policy = PushPolicy(clock=Clock())
    decision = policy.decide(change(before="blocked", after=None))
    assert decision.verdict is Verdict.SUPPRESS
    assert decision.reason == "removed"


# -- cooldown --------------------------------------------------------------


def test_repeat_inside_the_cooldown_is_suppressed() -> None:
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=120)
    assert policy.decide(change()).verdict is Verdict.ALLOW

    clock.advance(30)
    second = policy.decide(change())
    assert second.verdict is Verdict.SUPPRESS
    assert second.reason == "cooldown"
    assert second.wake_at == clock.now + 90


def test_repeat_after_the_cooldown_is_allowed() -> None:
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=120, escalate_after_seconds=120)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW
    clock.advance(121)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW


def test_urgent_uses_the_escalation_interval_not_the_short_cooldown() -> None:
    """The two intervals are independent, and blocked deliberately gets the longer one."""
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=10, escalate_after_seconds=900)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW
    clock.advance(60)
    assert policy.decide(change(after="blocked")).verdict is Verdict.SUPPRESS
    clock.advance(841)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW


def test_review_uses_the_plain_cooldown() -> None:
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=120, escalate_after_seconds=900)
    assert policy.decide(change(after="done")).verdict is Verdict.ALLOW
    clock.advance(121)
    assert policy.decide(change(after="done")).verdict is Verdict.ALLOW


def test_blocked_uses_the_longer_escalation_interval() -> None:
    """A still-blocked agent gets one more nudge much later, not on the short cooldown."""
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=120, escalate_after_seconds=900)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW

    clock.advance(300)
    assert policy.decide(change(after="blocked")).verdict is Verdict.SUPPRESS

    clock.advance(601)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW


def test_escalation_can_be_disabled() -> None:
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=120, escalate_after_seconds=None)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW
    clock.advance(300)
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW


def test_cooldown_is_per_pane() -> None:
    """One agent's cooldown must not silence a different agent."""
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=300)
    assert policy.decide(change(pane_id="w1:p1")).verdict is Verdict.ALLOW
    assert policy.decide(change(pane_id="w2:p1")).verdict is Verdict.ALLOW
    assert policy.decide(change(pane_id="w1:p1")).verdict is Verdict.SUPPRESS


# -- budget ----------------------------------------------------------------


def test_hourly_budget_stops_a_flapping_agent() -> None:
    """A state flapping between two values must not be able to spend quota."""
    clock = Clock()
    policy = PushPolicy(
        clock=clock,
        cooldown_seconds=0,
        escalate_after_seconds=0,
        max_per_agent_per_hour=3,
        max_per_hour=100,
    )
    verdicts = [policy.decide(change()).verdict for _ in range(5)]
    assert verdicts.count(Verdict.ALLOW) == 3
    assert verdicts[-1] is Verdict.SUPPRESS


def test_global_hourly_budget_applies_across_agents() -> None:
    clock = Clock()
    policy = PushPolicy(
        clock=clock,
        cooldown_seconds=0,
        escalate_after_seconds=0,
        max_per_agent_per_hour=100,
        max_per_hour=4,
    )
    for index in range(6):
        policy.decide(change(pane_id=f"w{index}:p1"))
    assert policy.sent_count() == 4


def test_daily_budget_applies() -> None:
    clock = Clock()
    policy = PushPolicy(
        clock=clock,
        cooldown_seconds=0,
        escalate_after_seconds=0,
        max_per_agent_per_hour=0,
        max_per_hour=0,
        max_per_day=3,
    )
    for index in range(6):
        policy.decide(change(pane_id=f"w{index}:p1"))
    assert policy.sent_count() == 3


def test_history_is_pruned_after_a_day() -> None:
    clock = Clock()
    policy = PushPolicy(clock=clock, cooldown_seconds=0, escalate_after_seconds=0, max_per_day=0)
    for index in range(3):
        policy.decide(change(pane_id=f"w{index}:p1"))
    assert policy.sent_count() == 3

    clock.advance(DAY_SECONDS + 60)
    assert policy.decide(change(pane_id="w9:p1")).verdict is Verdict.ALLOW
    assert policy.sent_count() == 1


# -- quiet hours -----------------------------------------------------------


def _quiet_window_containing_now() -> tuple[int, int]:
    """A quiet-hours window guaranteed to contain the current local hour.

    Building it relative to "now" is the only way this is deterministic at any
    hour of the day; a hard-coded (22, 6) asserts nothing at 09:00.
    """
    hour = time.localtime().tm_hour
    return ((hour - 1) % 24, (hour + 2) % 24)


def test_quiet_hours_defer_review_but_not_urgent() -> None:
    clock = Clock()
    policy = PushPolicy(
        clock=clock,
        cooldown_seconds=0,
        quiet_hours=_quiet_window_containing_now(),
    )
    assert policy.decide(change(after="done")).verdict is Verdict.DEFER
    # A blocked agent is someone waiting on a decision; morning is too late.
    assert policy.decide(change(after="blocked")).verdict is Verdict.ALLOW


def test_deferred_push_reports_when_to_wake() -> None:
    clock = Clock()
    policy = PushPolicy(
        clock=clock,
        cooldown_seconds=0,
        quiet_hours=_quiet_window_containing_now(),
    )
    decision = policy.decide(change(after="done"))
    assert decision.verdict is Verdict.DEFER
    assert decision.wake_at is not None
    assert decision.wake_at > clock.now


def test_quiet_hours_wrapping_past_midnight_are_handled() -> None:
    """A 22:00-06:00 window must include 23:30 and 02:00, and exclude 12:00."""

    def at_local_hour(hour: int, minute: int = 0) -> float:
        local = time.localtime()
        return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))

    for hour, minute, expected in (
        (21, 0, Verdict.ALLOW),
        (22, 0, Verdict.DEFER),
        (23, 30, Verdict.DEFER),
        (2, 0, Verdict.DEFER),
        (5, 59, Verdict.DEFER),
        (6, 0, Verdict.ALLOW),
        (12, 0, Verdict.ALLOW),
    ):
        clock = Clock(at_local_hour(hour, minute))
        policy = PushPolicy(clock=clock, cooldown_seconds=0, quiet_hours=(22, 6))
        decision = policy.decide(change(after="done"))
        assert decision.verdict is expected, f"{hour:02d}:{minute:02d} expected {expected}"


# -- triage ----------------------------------------------------------------


def test_triage_ranks_blocked_first_then_done_then_working() -> None:
    view = {
        "agents": [
            {
                "pane_id": "w1:p1",
                "workspace_id": "w1",
                "project": "alpha",
                "agent": "opencode",
                "status": "working",
            },
            {
                "pane_id": "w2:p1",
                "workspace_id": "w2",
                "project": "beta",
                "agent": "opencode",
                "status": "done",
            },
            {
                "pane_id": "w3:p1",
                "workspace_id": "w3",
                "project": "gamma",
                "agent": "opencode",
                "status": "blocked",
            },
            {
                "pane_id": "w4:p1",
                "workspace_id": "w4",
                "project": "delta",
                "agent": "opencode",
                "status": "idle",
            },
        ]
    }
    rows = triage(view)
    assert [r.status for r in rows] == ["blocked", "done", "working", "idle"]
    assert counts(rows) == {"blocked": 1, "done": 1, "working": 1, "idle": 1}


def test_focused_pane_is_a_tiebreaker_not_a_promotion() -> None:
    """herdr focus is whichever client moved last; it must not outrank a block."""
    view = {
        "agents": [
            {
                "pane_id": "w1:p1",
                "workspace_id": "w1",
                "project": "alpha",
                "agent": "opencode",
                "status": "working",
                "focused": True,
            },
            {
                "pane_id": "w2:p1",
                "workspace_id": "w2",
                "project": "beta",
                "agent": "opencode",
                "status": "blocked",
            },
        ]
    }
    rows = triage(view)
    assert rows[0].pane_id == "w2:p1"


def test_unknown_status_degrades_to_info_rather_than_crashing() -> None:
    view = {
        "agents": [
            {
                "pane_id": "w1:p1",
                "workspace_id": "w1",
                "project": "a",
                "agent": "opencode",
                "status": "totally-new",
            }
        ]
    }
    rows = triage(view)
    assert rows[0].status == "unknown"
    assert rows[0].attention is Attention.INFO
