# Contract: notifications and the FCM token

FCM's responsibility is narrow and fixed:

> **Notify, do not authorize.**

A push wakes the app and tells it something changed. It never carries the
authority to act: the app must consult `GET /v1/state` and issue a signed request
before anything happens. Authoritative code:
`gateway/src/herdr_notify/notify/{policy,attention,fcm}.py`,
`gateway/src/herdr_notify/api/app.py` (`/v1/me/fcm-token`),
`android/.../push/HerdrMessagingService.kt`.

## When a change becomes a push

Three independent brakes, in order. A `SUPPRESS` is not an error; it is the
normal outcome for most changes.

**Eligibility**
- Only `blocked` and `done` are ever pushed (`working`, `idle`, `unknown` never).
- A change whose `synthetic` flag is set (it came from a snapshot on startup or
  recovery, not a live event) is never pushed. Without this, restarting the
  gateway would notify once per agent.
- A removed agent is never pushed.

**Cooldown** (defaults)
- One push per pane per 120 s.
- A still-`blocked`, still-unseen agent is repeated after 900 s at most, not
  every cooldown.

**Budget** (defaults)
- Per agent: 6 per hour.
- Global: 60 per hour, 400 per day.

**Quiet hours** (optional, local `START-END`)
- `REVIEW` (`done`) pushes are deferred to the next end hour.
- `URGENT` (`blocked`) pushes ignore quiet hours: an approval dialog waiting
  until morning is an agent burning tokens and wall-clock.

Verdicts: `ALLOW` (send), `DEFER` (revisit at `wake_at`), `SUPPRESS` (never).

## What the phone receives

A notification block (so the tray entry appears even for a killed app) plus the
same values in `data`:

| `data` key | Value |
|------------|-------|
| `pane_id` | The pane id |
| `workspace_id` | Workspace id |
| `status` | `blocked` or `done` |
| `trigger` | The transition name |
| `project` | Workspace label / project name |

- Collapse key: `agent-<pane_id>` — a newer state replaces the older tray entry
  instead of stacking.
- Channel: `agents` (blocked, `priority: high`, may wake the screen) or
  `agents-review` (done, `priority: normal`).
- TTL: 3600 s.

The app treats every field as untrusted. It drops a push whose `pane_id` does not
match the pane-id shape or whose `status` is not `blocked`/`done`, before
building any notification.

## FCM token registration

Endpoint: `POST /v1/me/fcm-token`, body `{ "fcm_token": "…" }`. The token is
stored on the **device record** (so it is associated with `device_id`, never with
"a user"), ≤512 characters. Rotating replaces the old value; revoking a device
clears it.

### Required lifecycle — IMPLEMENTED (2026-10-04, unit-verified)

```
Firebase issues/rotates token
        │
        ▼
onNewToken()  ── writes a PERSISTENT pending token
        │
        ▼
     paired & gateway reachable?
        ├── no  → keep pending, retry
        └── yes → POST /v1/me/fcm-token (signed)
                    │
                    ▼
              server associates token ↔ device_id
```

### The gap is closed in code (2026-10-04)

`onNewToken()` now parks the token **persistently** (`TokenRelay.park`, a
`SharedPreferences` `commit()`, plus an in-memory mirror), and both that
callback and the next `connect()` flush it through `GatewayClient.fcmToken()`
— which now has a production caller. On the gateway side the push sender reads
the trust store at send time (`StoreBackedRegistry`) and prunes tokens that
Google reported dead back into the store (`DeviceStore.clear_fcm_token`).
Unit-verified by `GatewayTriageRepositoryTest` (parked token registered on
connect, failed registration keeps it parked) and `tests/test_push_wiring.py`.

What is still not claimed:

- The full `token → gateway → FCM → phone` path has not been exercised on a
  physical device yet; M3 stays open until it has.

This is the exact class of defect `replanteamiento.md` §16 names: a client
method and a server endpoint can both exist, compile and be tested, and still
not form a working path.

## Sending identity: decided (D1, 2026-10-01)

See [`../roadmap.md`](../roadmap.md) D1. The sending identity must hold only
`firebase.messaging`, have no long-lived private key on the laptop, use
short-lived access tokens and be revocable.

**Resolved 2026-10-01**: a dedicated Google identity logged in with
`gcloud auth application-default login --scopes=https://www.googleapis.com/auth/firebase.messaging`
— the refresh token mints only messaging-scoped access tokens (short-lived,
revocable) and carries none of the operator's own project permissions. It lives
in the Windows Credential Manager via `notify/dpapi.py`: no plaintext file, no
private key JSON, no cloud component. The hybrid architecture is confirmed: the
SSE stream stays the primary path; FCM is the fallback for an asleep, off-LAN
or killed app.
