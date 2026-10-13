"""Reducer behaviour: idempotence, rollups, and refusing untrusted event data."""

from __future__ import annotations

import pytest

from herdr_notify.state.models import Snapshot, coerce_status
from herdr_notify.state.store import Store, Transition, rollup_status
from tests.fake_herdr import agent_record, workspace_record


def _snapshot(*agents: dict) -> Snapshot:
    return Snapshot.model_validate(
        {
            "version": "0.9.1",
            "protocol": 22,
            "workspaces": [workspace_record(a["workspace_id"], a["workspace_id"]) for a in agents],
            "tabs": [],
            "panes": [dict(a) for a in agents],
            "agents": list(agents),
            "layouts": [],
        }
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "unknown"),
        (["working"], "working"),
        (["working", "blocked"], "blocked"),
        (["idle", "done"], "done"),
        (["idle", "unknown"], "idle"),
        (["unknown", "working", "idle"], "working"),
    ],
)
def test_rollup_takes_the_worst_state(statuses: list[str], expected: str) -> None:
    assert rollup_status(statuses) == expected  # type: ignore[arg-type]


def test_install_populates_every_collection() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1"), agent_record("w2:p1", "w2")))

    assert store.state.version == "0.9.1"
    assert len(store.state.agents) == 2
    assert store.state.pane_ids() == {"w1:p1", "w2:p1"}
    assert store.state.revision > 0


def test_workspace_rollup_follows_its_agents() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="working")))
    assert store.state.workspaces["w1"].agent_status == "working"

    # A single blocked agent must surface its whole workspace to the top.
    store.apply(
        "pane.agent_status_changed",
        {"pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "blocked"},
    )
    assert store.state.workspaces["w1"].agent_status == "blocked"


def test_status_event_reports_exactly_one_change() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="working")))

    outcome = store.apply(
        "pane.agent_status_changed",
        {"pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "blocked"},
    )

    assert len(outcome.changes) == 1
    change = outcome.changes[0]
    assert (change.before, change.after) == ("working", "blocked")
    assert change.trigger is Transition.BECAME_BLOCKED


def test_replaying_the_same_status_is_a_no_op() -> None:
    """A stream rotation can redeliver an event; it must not look like news."""
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="blocked")))
    revision = store.state.revision

    outcome = store.apply(
        "pane.agent_status_changed",
        {"pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "blocked"},
    )

    assert outcome.changes == []
    assert store.state.revision == revision


def test_unknown_status_is_rejected() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="working")))

    outcome = store.apply(
        "pane.agent_status_changed",
        {"pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "totally-invented"},
    )

    assert outcome.changes == []
    assert store.state.agents["w1:p1"].agent_status == "working"


def test_unknown_event_name_is_ignored_not_fatal() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="working")))

    outcome = store.apply("pane.some_future_event", {"pane_id": "w1:p1"})

    assert outcome.changes == []
    assert outcome.stream.value == "none"


def test_status_for_unknown_pane_asks_for_hydration() -> None:
    """A partial record would render an empty project name in the app."""
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="working")))

    outcome = store.apply(
        "pane.agent_status_changed",
        {"pane_id": "w9:p9", "workspace_id": "w9", "agent_status": "blocked"},
    )

    assert outcome.needs_hydration == {"w9:p9"}
    assert "w9:p9" not in store.state.agents


def test_pane_created_requests_hydration_and_rotation() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="working")))

    outcome = store.apply("pane.created", {"pane_id": "w1:p2", "workspace_id": "w1"})

    assert outcome.needs_hydration == {"w1:p2"}
    assert outcome.stream.value == "rotate"


def test_pane_closed_removes_the_agent_and_rotates() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="blocked")))
    store.apply(
        "pane.agent_status_changed",
        {"pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "working"},
    )

    outcome = store.apply("pane.closed", {"pane_id": "w1:p1"})

    assert "w1:p1" not in store.state.agents
    assert "w1:p1" not in store.state.panes
    assert outcome.stream.value == "rotate"
    assert [c.trigger for c in outcome.changes] == [Transition.REMOVED]


def test_workspace_closed_clears_its_whole_subtree() -> None:
    store = Store()
    store.install(
        _snapshot(
            agent_record("w1:p1", "w1", status="blocked"),
            agent_record("w2:p1", "w2", status="working"),
        )
    )

    store.apply("workspace.closed", {"workspace_id": "w1"})

    assert "w1" not in store.state.workspaces
    assert "w1:p1" not in store.state.agents
    assert "w2:p1" in store.state.agents


def test_reinstall_drops_agents_herdr_no_longer_reports() -> None:
    store = Store()
    store.install(
        _snapshot(
            agent_record("w1:p1", "w1", status="working"),
            agent_record("w2:p1", "w2", status="working"),
        )
    )

    changes = store.install(_snapshot(agent_record("w1:p1", "w1", status="working")))

    assert set(store.state.agents) == {"w1:p1"}
    removed = [c for c in changes if c.trigger is Transition.REMOVED]
    assert [c.pane_id for c in removed] == ["w2:p1"]


def test_view_reports_project_title_and_resumability() -> None:
    store = Store()
    store.install(_snapshot(agent_record("w1:p1", "w1", status="blocked")))

    view = store.state.view()
    entry = view["agents"][0]

    assert entry["project"] == "w1"
    assert entry["title"] == "OC | w1 task"
    assert entry["status"] == "blocked"
    assert entry["can_resume"] is True
    assert view["counts"] == {"workspaces": 1, "panes": 1, "agents": 1}


def test_view_falls_back_to_cwd_when_workspace_has_no_label() -> None:
    store = Store()
    store.install(
        Snapshot.model_validate({"version": "0.9.1", "agents": [agent_record("w1:p1", "w1")]})
    )

    assert store.state.view()["agents"][0]["project"] == "w1"


def test_coerce_status_only_accepts_known_states() -> None:
    assert coerce_status("blocked") == "blocked"
    assert coerce_status("BLOCKED") is None
    assert coerce_status(None) is None
    assert coerce_status(1) is None
