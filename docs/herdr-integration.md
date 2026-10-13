# Integrating with herdr

Everything here was verified against **herdr 0.9.1** — against the source in
`herdrdev/herdr` and against a live server. Several of these are not in the prose
docs and would each cost an afternoon to rediscover.

## Where the endpoint actually is

`herdr status` reports:

```
socket: %APPDATA%\herdr\herdr.sock
```

That path is **not** the socket. On Windows it is a 26-byte lock file whose
contents are `<pid>:<created_nanos>`. The real endpoint is a **named pipe**
registered under that same path string in the `\\.\pipe\` namespace, so it is
reached as:

```
\\.\pipe\%APPDATA%\herdr\herdr.sock
```

On POSIX the same path *is* a real `AF_UNIX` socket. Resolution order, per herdr's
own documentation: explicit `--session`, then `HERDR_SOCKET_PATH`, then
`HERDR_SESSION`, then the default session socket.

herdr sets a restrictive DACL on the pipe at creation time, so local access is
already restricted to the owning user. Do not widen it when opening the handle.

## One request per connection

`handle_connection_with_stop` (`src/api/server.rs`) calls
`read_initial_request_line`, answers it, and returns — closing the stream. A
second write on the same handle fails with `ERROR_NO_DATA` (winerror 232).

So: **open a fresh connection per request.** This is the protocol, not a
workaround, and it is what the `herdr` CLI does implicitly by being one-shot.

`events.subscribe` is the single exception: `stream_subscriptions` takes over the
connection and writes events forever.

## Subscriptions are frozen at subscribe time

Because `stream_subscriptions` owns its stream, the subscription set cannot be
extended later. And `pane.agent_status_changed` **requires an explicit
`pane_id`** — herdr's schema has no wildcard form:

```json
{"type": "pane.agent_status_changed", "required": ["type", "pane_id"]}
```

`pane.created`, `pane.agent_detected`, `pane.closed`, `workspace.*`, `tab.*` and
`layout.updated` are unscoped and *can* be subscribed once for the whole session.

Therefore, to follow every agent:

1. Subscribe to the unscoped events.
2. `session.snapshot`, learn the pane set.
3. Rotate to a new stream with a per-pane subscription for each pane.
4. On `pane.created` / `pane.closed`, rotate again.

The old stream should keep draining until the replacement is acknowledged, and
every rotation should be followed by a fresh snapshot. Both are what
`watcher.py` does.

## The bootstrap order is not interchangeable

herdr's documented gap-free procedure, and the reason for each step:

| Step | Why it cannot move |
|------|--------------------|
| 1. Subscribe, wait for ack | Subscriptions do not replay history. Anything before this point is unrecoverable. |
| 2. `session.snapshot` while the stream buffers | This is the authoritative initial state. |
| 3. Rotate to cover every pane | Per-pane status events are the point of the exercise. |

## `session.snapshot` nests everything

```jsonc
{ "id": "...", "result": { "type": "session_snapshot",
                          "snapshot": { "workspaces": [...], "agents": [...] } } }
```

Collections live under `result.snapshot`, not at the response root. Looking at
the root yields an empty session with no error.

## The event contract

`pane.agent_status_changed` carries **only**:

```json
{ "pane_id": "w1:p1", "workspace_id": "w1", "agent_status": "blocked",
  "agent": "opencode", "title": "...", "display_agent": "...", "state_labels": {} }
```

Notably **absent**: `cwd`, `terminal_title`, `state_change_seq`, and the native
session reference. Those only appear in `session.snapshot` and `pane.get`. So a
status event for a pane you have not seen cannot be rendered usefully — the app
would show an empty project name. Fetch the record instead of guessing.

`agent_status` is one of `idle`, `working`, `blocked`, `done`, `unknown`.
`idle` and `done` both mean "ready for input"; `done` additionally means "not yet
seen by the operator", which is what makes it worth a notification.

## Reading a useful title

`terminal_title_stripped` is the field to display. herdr already removes a
leading spinner or activity glyph from it, and `terminal_title` keeps the raw
form. The project name is `workspace.label`, falling back to the last segment of
the agent's `cwd`.

## Windows transport notes

Two Windows behaviours shaped `transport.py`, and both fail in confusing ways:

**The CRT shares one file position between reads and writes.** Opening the pipe
with `open(path, "r+b", buffering=0)` and then reading *before* writing leaves
the write at a non-zero offset, which the pipe rejects with `EINVAL`. Using the
Win32 API directly (`ReadFile`/`WriteFile`) removes the shared position entirely.

**`CloseHandle` deadlocks against a pending read.** A reader thread blocked in
`ReadFile` will not return when another thread closes the handle, and the close
waits on the read. herdr solves this by peeking before reading
(`poll_local_stream_read_count` in `src/ipc.rs`): ask how many bytes are
available, and only read a count that is already there. The read then returns
immediately, so the reader is never parked in the kernel and a close is always
safe. `LocalStream` does the same, which also yields real read timeouts.

## Never block in `ctypes` without prototypes

`ctypes` defaults every integer argument and return value to `c_int`, which
truncates a 64-bit `HANDLE` to 32 bits. The result is `ERROR_INVALID_HANDLE` on
the first write, with no hint that the handle was the problem.
`transport.py` declares `restype`/`argtypes` for every call for that reason.
