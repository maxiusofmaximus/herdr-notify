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
| `POST` | `/v1/agents/{pane_id}/image` | signed | `RESPOND` | write | Store an image and prompt the agent with its path |
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

Body: `{ "text": "…" }` — non-empty, no control characters other than
newline/tab. There is **no length cap** (updated: the old 4000-character limit
and the `prompt_too_long` code are gone). Response: the summarised action result.

> **IMPLEMENTED.** The only remaining bound is the transport-signed-body cap of
> 256 KiB (`errors.md`), which is not a message-length rule; a longer message is
> only possible for the image route below, which raises its own cap.

### `POST /v1/agents/{pane_id}/keys`

Body: `{ "keys": ["enter"], "confirm": false }` — 1…8 keys.

- Allowed without `confirm`: `up down left right enter esc escape tab space
  backspace home end pgup pgdown y n` and the digits `0`–`9`.
- `ctrl+c` requires `confirm: true`.
- Anything else is refused. `escape` normalises to `esc`; keys are lower-cased
  and trimmed.

### `POST /v1/agents/{pane_id}/focus` / `.../seen`

No body. `focus` calls herdr's `agent.focus`. `seen` is an acknowledged no-op:
herdr 0.9.1 clears a "done" badge only through `agent.focus`, which would also
move the operator's terminal, so the phone marks the agent seen locally and the
gateway calls nothing (updated: this route no longer reaches herdr).

A pane that no longer exists answers `404` with `{"code": "agent_not_found"}`
on both (`errors.md`): `focus` gets that answer from herdr, `seen` from the
gateway's own mirror, since it makes no herdr call at all.

### `POST /v1/agents/{pane_id}/read`

Body: `{ "lines": 60 }` (optional). Clamped to 1…200, default 60. Response:

```json
{ "text": "…", "pane_id": "w1:p3" }
```

A pane herdr no longer knows is `404 agent_not_found`, and the visible-screen
fallback is not attempted for it. A working agent whose alternate screen
refuses the history source is still read through that fallback; if both
sources are refused the answer remains `409`.

### `POST /v1/agents/{pane_id}/image`

Body: `{ "mime": "image/png", "data": "<base64>" }`.

- `mime` is allowlisted: `image/png`, `image/jpeg` or `image/webp`.
- `data` is standard base64 of the image bytes, at most 5 MiB decoded.
- The bytes must actually be the declared container (PNG magic, JPEG `FF D8 FF`,
  or a `RIFF….WEBP` header). A renamed file is refused, not stored.
- The gateway writes the file under its data dir (`--images`, default
  `~/.config/herdr-notify/images`) and submits the **absolute path** to the agent
  as a prompt (`Imagen adjunta: <path>`), so the agent opens it with its own
  tools. The file is removed again if herdr refuses the prompt.

Response:

```json
{ "ok": true, "pane_id": "w1:p3",
  "path": "/home/me/.config/herdr-notify/images/w1_p3-1a2b3c4d5e6f7890.png",
  "result": { "pane_id": "w1:p3", "agent": "opencode", "agent_status": "idle" } }
```

Failures: `400` with an action code (`unsupported_type`, `invalid_image`,
`empty_image`, `image_too_large`, `type_mismatch`), `403` without `RESPOND`,
`404` with `agent_not_found` when the pane is gone (the stored file is removed,
as it is for a `409`), `409` if herdr refuses the prompt, `413` if the signed
body exceeds the image cap. Requires `RESPOND`: attaching a picture drives the
agent exactly as sending a prompt does.

> **IMPLEMENTED.** The Android side (`ImageAttachment`, `sendImage`) validates
> the same 5 MiB ceiling and the three types before sending.

### Action responses

Writes return `{"ok": true, "result": {…}}` where `result` is trimmed to what the
app needs (for a prompt: `pane_id`, `agent`, `agent_status`). herdr's own
refusal is a `409`, not a gateway fault (`errors.md`); a target pane that no
longer exists is a `404` with `{"code": "agent_not_found"}`, which the app
answers by saying the agent is gone and stopping its poll (`errors.md`).

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
[`pairing.md`](pairing.md).

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

The signed-body cap is 256 KiB, raised on the image route only to fit a base64
picture (`errors.md`).
