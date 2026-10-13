# Contract: state model and triage

`herdr` events are reduced on the host into a read model. The app renders that
model; it does not re-derive it. Authoritative code:
`gateway/src/herdr_notify/state/{models,store}.py`,
`gateway/src/herdr_notify/notify/attention.py`,
`gateway/src/herdr_notify/api/app.py` (`state_payload`),
`android/.../net/Wire.kt`, `android/.../domain/SessionState.kt`.

## One shape, two transports

`GET /v1/state` and the **opening frame** of `GET /v1/events` return the exact
same object, built by one function (`state_payload`). This was not always true:
the stream used to return the raw reduced view, which has no `attention` and a
different `counts`, so a phone that joined the stream ranked from a payload the
gateway never ranked. That divergence is fixed and pinned by a test.

## The state object

```json
{
  "revision": 42,
  "herdr_version": "0.9.3",
  "focused": { "workspace_id": "w1", "tab_id": "t1", "pane_id": "w1:p1" },
  "counts": { "blocked": 1, "working": 2, "idle": 3 },
  "agents": [ /* TriageRow, ranked */ ]
}
```

- `revision` is monotonic over the reduced state. An older revision arriving
  after a newer one is discarded by the client.
- `counts` is a **tally per status**, containing only statuses that are present.
- `agents` is ordered by the ranking below, not by pane id.

### Agent entry (TriageRow)

```json
{
  "pane_id": "w1:p1",
  "workspace_id": "w1",
  "project": "herdr-notify",
  "agent": "opencode",
  "status": "blocked",
  "attention": 3,
  "title": "Add the pairing screen",
  "cwd": "<ruta-del-repo>",
  "focused": false,
  "can_resume": true
}
```

| Field | Notes |
|-------|-------|
| `pane_id` | The key every action is addressed by. An entry without one is dropped by the client. |
| `project` | Workspace label, falling back to a project name, then `?`. |
| `agent` | Display name; `display_agent` overrides the agent kind. |
| `status` | One of the statuses below. |
| `attention` | Ranking 0–3, computed on the host. |
| `title` | Best available human label; may be `null`. |
| `focused` | herdr's focus flag; a tiebreaker, never a promotion. |
| `can_resume` | Whether the agent reported a native resume reference. |

## Statuses

`idle` · `working` · `blocked` · `done` · `unknown`

This is herdr's own vocabulary, forwarded unchanged. An unrecognised value
degrades to `unknown`; it is never stored as-is and never raises.

## Attention and ranking

| Status | Attention | Value | Pushed? |
|--------|-----------|-------|---------|
| `blocked` | `URGENT` | 3 | yes, high priority |
| `done` | `REVIEW` | 2 | yes, configurable |
| `working` | `INFO` | 1 | no |
| `unknown` | `INFO` | 1 | no |
| `idle` | `NONE` | 0 | no |

Sort key, ascending: `(-attention, focused ? 0 : 1, project.lower(), pane_id)`.
Urgency first; the focused pane breaks ties but never outranks a `blocked` agent
elsewhere; then stable name order.

## The SSE stream

`GET /v1/events`, authenticated once at connect. The signature covers the
connect request only; a long-lived stream is not re-verified per frame. A
reconnect is a **new signed request with a fresh nonce**, never a resumption.

Frame format:

```
event: state
data: {"event":"state","revision":42,"state":{ …the state object… }}

```

- **First frame** is always `event: state` carrying the full state object, so a
  client that connects while changes are queued still converges without a second
  round trip. This is the app's revision baseline.
- **Change frames** carry `event: <name>` and a JSON body containing at least
  `revision`. The app does not patch locally; it re-reads `/v1/state`, so the
  phone and the terminal cannot drift.
- **Keepalive** is the comment frame `: keepalive` every 20 seconds, so
  intermediaries do not time the connection out.
- Response headers: `Cache-Control: no-store`, `X-Accel-Buffering: no`.
- Per-device stream cap; exceeding it is `429` (`errors.md`).

The server drops from the queue of a client that stops reading rather than
growing memory; that client re-syncs from `/v1/state` on reconnect.

## Client decoding

The app decodes leniently (`ignoreUnknownKeys`, `isCoerceInputValues`): a newer
gateway adding a field must not stop an older phone. A malformed body falls back
to the last good state and shows it as stale, rather than emptying the screen.

## `ERROR` — dropped by D2 (herdr never reports it)

The specification (§10) lists `ERROR` among the minimum states. herdr cannot
produce one: in herdr 0.9.1 (`src/api/schema/common.rs`) `AgentStatus` is
`idle | working | blocked | done | unknown` — no `Error` arm — and
`PaneAgentState`, the raw detection state, has none either; `parse_agent_status`
(`src/cli.rs`) accepts only those five strings. The gateway forwards herdr's
status untouched and degrades an unrecognised value to `unknown`, so an `ERROR`
state is unreachable by construction and no `ERROR` was added to the model
(decision D2 in [`../roadmap.md`](../roadmap.md)). If a future herdr adds an
error-like state, this contract extends — additive changes only.
