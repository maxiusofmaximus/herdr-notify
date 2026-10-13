# Contract: HTTP surface

The gateway binds loopback only. Reaching it from a phone is the transport's job
(Tailscale), not this process's. Authoritative code:
`gateway/src/herdr_notify/api/app.py`, `.../api/actions.py`.

## Rules

- The client names an **action**, never a herdr method. There is no passthrough.
- Every endpoint except `/v1/health` and `POST /v1/pair` requires a valid signature.
- **`POST /v1/pair` is the only unauthenticated write.** It is gated by a
  host-printed single-use code, a per-device recovery code, or the same-tailnet
  owner check — never a static secret (Fase 2(c), `pairing.md`).

## Endpoints

| Method | Path | Auth | Grant | Rate | Purpose |
|--------|------|------|-------|------|---------|
| `GET` | `/v1/health` | none | — | — | Liveness, no operator data |
| `POST` | `/v1/pair` | none (code/owner) | — | write (per IP) | Pair or re-key a device |
| `GET` | `/v1/state` | signed | `READ_STATE` | read | The full state read model |
| `GET` | `/v1/events` | signed | `READ_STATE` | read | SSE stream (see `state.md`) |
| `GET` | `/v1/peers` | signed | `READ_STATE` | read | Tailnet peers + host addresses to probe |
| `GET` | `/v1/devices` | signed | `ADMIN` | read | List paired devices ("My devices") |
| `POST` | `/v1/devices/{device_id}/revoke` | signed | `ADMIN` | write | Revoke one device |
| `POST` | `/v1/agents/{pane_id}/respond` | signed | `RESPOND` | write | Submit a prompt |
| `POST` | `/v1/agents/{pane_id}/keys` | signed | `SEND_KEY` | write | Send allowlisted keys |
| `POST` | `/v1/agents/{pane_id}/focus` | signed | `RESPOND` | write | Focus the pane |
| `POST` | `/v1/agents/{pane_id}/seen` | signed | `READ_STATE` | write | Clear the "done" badge |
| `POST` | `/v1/agents/{pane_id}/read` | signed | `READ_STATE` | **write** | Read recent pane output |
| `POST` | `/v1/me/fcm-token` | signed | — (self-service) | write | Attach/replace this device's FCM token |
| `POST` | `/v1/workspaces` | signed | `RESPOND` | write | Create a workspace and start a new opencode agent in it |

`Grant` is the per-device permission from [`auth.md`](auth.md). A new device is
paired with the `READ_STATE` default; the rest are explicit host-side grants. An
authenticated device without the grant receives `403`, not `401`. An endpoint
added later without a matrix rule fails closed (`403`).

`read` is counted against the write budget on purpose: it drives work on the
host (a herdr round trip and a pane read) even though it mutates nothing.

`pane_id` must match `^[A-Za-z0-9]{1,32}:p[0-9A-Za-z]{1,32}$` (for example
`w1:p3`). A bare agent name is refused — targets are resolved only to panes the
gateway already mirrors.

## Request and response shapes

### `GET /v1/health` (no auth)

```json
{ "ok": true, "revision": 42, "devices": 2, "streams": 1 }
```

Nothing identifying: no herdr version, no pane names, no agent count.

### `GET /v1/state` → `state.md`

### `POST /v1/agents/{pane_id}/respond`

Body: `{ "text": "…" }` — 1…4000 characters, no control characters other than
newline/tab. Response: the summarised action result.

### `POST /v1/agents/{pane_id}/keys`

Body: `{ "keys": ["enter"], "confirm": false }` — 1…8 keys.

- Allowed without `confirm`: `up down left right enter esc escape tab space
  backspace home end pgup pgdown y n` and the digits `0`–`9`.
- `ctrl+c` requires `confirm: true`.
- Anything else is refused. `escape` normalises to `esc`; keys are lower-cased
  and trimmed.

### `POST /v1/agents/{pane_id}/focus` / `.../seen`

No body. `seen` is implemented as herdr's `agent.focus`, so the phone and the
terminal can never disagree about what has been read.

### `POST /v1/agents/{pane_id}/read`

Body: `{ "lines": 60 }` (optional). Clamped to 1…200, default 60. Response:

```json
{ "text": "…", "pane_id": "w1:p3" }
```

### Action responses

Writes return `{"ok": true, "result": {…}}` where `result` is trimmed to what the
app needs (for a prompt: `pane_id`, `agent`, `agent_status`). herdr's own
refusal is a `409`, not a gateway fault (`errors.md`).

### `POST /v1/me/fcm-token`

Body: `{ "fcm_token": "…" }`, ≤512 chars, non-empty. Response: `{"ok": true}`.

> **IMPLEMENTED (producer + sender, 2026-10-04; real-device E2E pending in M3).**
> The Android build calls it from `GatewayTriageRepository.flushPendingToken()`
> on every connect and on token rotation; the gateway's push sender reads the
> token from the trust store at send time. See [`push.md`](push.md).

### `POST /v1/pair` (no auth)

Body: `{ "curve": "p256", "public_key": "<b64>", "label": "Pixel 9", "code": "HJKQ2ZP4" }`.
`code` is optional; `label` is optional. Response:

```json
{
  "ok": true,
  "device_id": "dev-…",
  "curve": "p256",
  "label": "Pixel 9",
  "permissions": ["read_state"],
  "owner_id": "12345",
  "recovery_code": "7QK3-M2XP-9B7C-D4HF"
}
```

`recovery_code` is shown **once**; only a hash is stored. Failures answer
`403 {"detail":"pairing_rejected"}` (uniform), `400 {"detail":"invalid_body"}`,
`413`, or `429`. The exact resolution order (code → recovery → same-owner) is in
[`pairing.md`](pairing.md) and `FASE2C.md`.

### `GET /v1/devices` (signed, `ADMIN`)

```json
{"ok": true, "devices": [
  {"device_id":"dev-…","curve":"p256","label":"Pixel 9","owner_id":"12345",
   "created_at":1730000000.0,"last_seen_at":1730000000.0,"revoked":false,
   "permissions":["read_state"]}
]}
```

Public material only: never a `public_key` or an `fcm_token`.

### `POST /v1/devices/{device_id}/revoke` (signed, `ADMIN`)

No body. Response `{"ok": true, "device_id": "dev-…", "revoked": true}`, or
`404 {"detail":"no such device"}`. After a revoke the device's signed requests
answer `401` and its live stream closes within one keepalive.

## Request bodies and signatures

The body used for the signature hash is the **exact received bytes**, not a
re-serialised model. Consequently the server does not require
`Content-Type: application/json`; the bytes are parsed directly as JSON by the
signed-body parser. A correctly signed body with a missing or wrong content type
is still valid.
