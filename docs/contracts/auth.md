# Contract: request authentication and authorization

Every request except `GET /v1/health` must carry a signature over the exact
request. There is no bearer token and no shared secret to leak: a device is a
public key, and proving possession of the matching private key is the whole
authentication.

Authentication and authorization are **two different questions**, checked in
this order:

- **Authentication** — *was this request signed by a device whose identity can
  be verified?* Answered by the signature, freshness and revocation checks.
  Failure → `401`.
- **Authorization** — *even though the device is authenticated, is it allowed to
  perform this operation?* Answered by the per-device permission grant against
  the endpoint matrix below. Failure → `403`.

A valid signature never implies authorization. Authentication answers *who you
are*; authorization answers *what you may do*.

Authoritative code: `gateway/src/herdr_notify/api/auth/canonical.py`,
`.../verify.py`, `.../devices.py`, `.../authz.py`;
`android/.../net/RequestSigner.kt`; `android/.../security/DeviceKeyStore.kt`.

## Headers

| Header | Meaning |
|--------|---------|
| `X-HN-Device` | The device id from the trust store |
| `X-HN-Timestamp` | Unix seconds, integer, **not** milliseconds |
| `X-HN-Nonce` | Base64 of 16 random bytes, unique per request |
| `X-HN-Signature` | Base64 of the signature (see below) |

`X-HN-Key-Id` is reserved and **not used in v1**. A client must not send it; a
server must ignore it. It exists as a name so key rotation can be added later
without a second header name.

## The signing string

```
METHOD \n
TARGET \n
sha256(body) \n
TIMESTAMP \n
NONCE \n
```

- `METHOD` is upper-cased (`GET`, `POST`).
- `TARGET` is the raw HTTP request target, query string included, exactly as it
  appears on the wire. It is **not** a path reassembled from routing. It must
  start with `/` and contain no `\n` or `\r`.
- `sha256(body)` is lowercase hex of the SHA-256 of the **exact received body
  bytes**, never a re-serialisation. An empty body hashes to
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
- `TIMESTAMP` is the decimal integer from the header.
- `NONCE` is the header value verbatim (base64, may contain `=`).
- Every field is LF-terminated, **including the last**. The result is UTF-8.
- No field may contain a newline, so two distinct requests cannot produce one
  string.

This exact byte string is what the golden vectors in
`gateway/tests/vectors/signing_vectors.json` pin.

## Signing algorithms

| Curve id | Key encoding | Signature |
|----------|--------------|-----------|
| `p256` | Uncompressed SEC1 point, 65 bytes: `0x04 \|\| X(32) \|\| Y(32)`, base64 | ECDSA P-256 + SHA-256, **DER** (`SHA256withECDSA`) |
| `ed25519` | 32 raw bytes, base64 | Ed25519, raw |

`p256` is the default and the only curve the current app produces. The curve is
taken from the **device record**, never from the request: a caller must not be
able to choose the algorithm that verifies its own forged signature.

A signature that is not valid DER is simply invalid — the verifier does not try
to guess a raw `r||s` form.

## Freshness and replay

Two independent checks, both required:

- **Clock skew.** `abs(server_now - timestamp) <= 60 s`. Wider tolerates a phone
  with a wrong clock; narrower closes replay sooner.
- **Nonce.** A nonce is accepted once per device, remembered for 1 hour. The
  cache is bounded (512 nonces per device, 64 devices) and pruned.

The nonce is consumed only **after** the device is known, so an unauthenticated
flood cannot evict a legitimate device's nonces. The device is checked before the
signature so a revoked device is refused before any cryptography runs.

## Rejections

All rejections return **one** response: `401` with body
`{"detail": "unauthorized"}`. The specific reason (`no_headers`, `unknown_device`,
`revoked`, `bad_timestamp`, `bad_nonce`, `bad_signature`, `malformed`,
`unsupported_curve`) is written to the server log only.

This is deliberate: distinguishing "unknown device" from "bad signature" turns
the endpoint into an oracle for which device ids exist. The client treats a
`401` as "this device is no longer trusted — re-pair", and stops retrying.
(`403` is a different answer — see the authorization section below.)

## Authorization

### Permissions

The specification (§24–25) names five permissions. A device's grant set is an
explicit list on its trust-store record; nothing is implied by pairing beyond
the default below.

| Permission | id | Default at pairing | Meaning |
|------------|----|--------------------|---------|
| `READ_STATE` | `read_state` | **granted** | Observe: `/v1/state`, `/v1/events` (SSE), `/v1/peers`, pane output reads, mark an agent seen |
| `RESPOND` | `respond` | not granted | Act: submit a prompt, focus a pane, attach an image to a pane |
| `SEND_KEY` | `send_key` | not granted | Act: send allowlisted keys |
| `APPROVE` | `approve` | not granted | **RESERVED in v1** — no endpoint maps to it; dialog answering is done through `respond`/`keys` |
| `ADMIN` | `admin` | not granted | Manage devices: `GET /v1/devices`, `POST /v1/devices/{id}/revoke` (activated in Fase 2(c)) |

`APPROVE` remains a valid grantable identifier so a future endpoint can adopt it
without a migration, but it grants nothing in v1 — the same pattern as the
reserved `X-HN-Key-Id` header. `ADMIN` was reserved the same way in M2 and is
now the grant behind device management (Fase 2(c)).

`focus` sits behind `RESPOND` because it drives herdr (`agent.focus` on the
session): a device granted only `READ_STATE` observes but never drives. `seen`
sits behind `READ_STATE` (decision 2026-10-09): marking an agent seen is
non-destructive and reversible, and `RESPOND` stays reserved for approving,
denying and sending. `read` (pane output) sits behind `READ_STATE` because it
mutates nothing, and the write-budget rate limit already prices the herdr round
trip it costs. `image` sits behind `RESPOND` because it submits a prompt (with
the picture's path) to the agent.

`/v1/me/fcm-token` requires no permission: it is self-service on the caller's
own device record. The device id comes from the signature, never from the body,
so a device cannot touch another device's token. A revoked device never reaches
it (rejected at authentication).

### Endpoint matrix

The authoritative mapping. The matrix is **load-bearing**: an endpoint added
later without a rule here fails closed (`403`) until one is written, so a new
endpoint cannot start life implicitly authorized.

| Method | Path | Without auth | Authenticated, not granted | Granted |
|--------|------|--------------|----------------------------|---------|
| `GET` | `/v1/health` | `200` | `200` | `200` |
| `POST` | `/v1/pair` | `200`/`403` | — | — |
| `GET` | `/v1/state` | `401` | `403` | `200` |
| `GET` | `/v1/events` | `401` | `403` | `200` |
| `GET` | `/v1/peers` | `401` | `403` | `200` |
| `GET` | `/v1/devices` | `401` | `403` | `200` (`ADMIN`) |
| `POST` | `/v1/devices/{device_id}/revoke` | `401` | `403` | `200` (`ADMIN`) |
| `POST` | `/v1/agents/{pane_id}/respond` | `401` | `403` | `200` |
| `POST` | `/v1/agents/{pane_id}/keys` | `401` | `403` | `200` |
| `POST` | `/v1/agents/{pane_id}/focus` | `401` | `403` | `200` |
| `POST` | `/v1/agents/{pane_id}/seen` | `401` | `200` | `200` |
| `POST` | `/v1/agents/{pane_id}/read` | `401` | `200` | `200` |
| `POST` | `/v1/agents/{pane_id}/image` | `401` | `403` | `200` |
| `POST` | `/v1/me/fcm-token` | `401` | `200` | `200` |
| any | endpoint with no rule | `401`/`404` | `403` | `403` |

`POST /v1/pair` is the **only unauthenticated write** (Fase 2(c)): the pairing
code, a recovery code, or the tailnet-owner check is the authorisation, never a
static secret. It is rate-limited per source IP and answers a uniform
`403 {"detail":"pairing_rejected"}` on any failure. See
[`pairing.md`](pairing.md).

The query string is not part of the match: the permission is derived from the
method and the path exactly as signed (`raw_path`), with anything after `?`
ignored.

### The 403 response

Every authorization rejection returns **one** response: `403` with body
`{"detail": "forbidden"}`. The specific reason (`not_permitted`,
`unknown_endpoint`) is written to the server log only, together with the
device id and the required permission — the log is the audit trail.

This mirrors the uniform `401`: the reason is not sent to the caller because a
permission- or endpoint-shaped oracle has no legitimate client. `401` and `403`
mean different things and a client must not conflate them:

- `401` — this device is no longer trusted. Terminal: stop retrying, re-pair.
- `403` — this device is trusted but not allowed to do this. Terminal **for
  that action**: stop retrying it, do **not** re-pair (the pairing is intact),
  do **not** treat it as a transport error. The fix is a host-side grant, never
  a client-side retry.

### Order of checks

1. Signature and freshness → `401` (`auth.md`).
2. Authorization against the endpoint matrix → `403`.
3. Read rate limit → `429`.
4. For writes, write rate limit → `429`.
5. Body size → `413`; body parse → `400`/`422`.
6. Action validation → `400` with an action code.
7. herdr → `409` if it refuses.

An authorization failure happens **before** the rate limit and before
`last_seen` is updated: an unauthorized request consumes no rate budget and
leaves no last-seen trace, the same way a revoked device never reaches either.

### Fail-closed properties

- No grants (beyond the pairing default) → `403` on every protected endpoint.
- An endpoint with no matrix rule → `403` (the matrix is load-bearing).
- A permission id in a trust-store record that is not one of the five above is
  dropped on load: it grants nothing rather than guessing.
- A trust store that cannot be read trusts nobody (`401` on everything).
- There is no HTTP grant endpoint: widening access is a host-side CLI act. (Since
  Fase 2(c), *pairing* has an HTTP path — `POST /v1/pair` — but it is gated by a
  host-printed code or the tailnet-owner check, and it only ever grants the
  `READ_STATE` default; grants stay host-side.)
- **Revocation reaches established streams.** The stream is the one long-lived
  request, so revocation that only refused *new* requests would leave a revoked
  phone receiving live state until the stream happened to break. The stream
  checks the device's trust before every frame it yields — state frames and
  keepalive comments alike — so after a revocation nothing at all flows to the
  device it revoked, and the stream closes within one keepalive interval
  (20 s). The check re-reads the trust store first (`reload_if_changed`): a
  stream's keepalives never pass through the request path that would otherwise
  pick the change up, so without it the check would read a stale trust list
  until some other authenticated request happened to reload.

### Device lifecycle

```
unknown
  ↓  host-side CLI (add-device) or HTTP POST /v1/pair (code | recovery | same-owner)
paired (default grant: READ_STATE)
  ↓  host-side CLI (devices --grant)
authorized (for exactly the granted operations)
  ↓  host-side CLI (devices --revoke / --revoke-permission) or HTTP POST /v1/devices/{id}/revoke (ADMIN)
revoked (marked, never deleted: the device stays visible and refused)
```

"Disabled" is not a separate state: `revoked` is the disabling mechanism, and
revoking a permission is the narrower version of the same act. A revoked device
answers `401` before any cryptography runs; a merely under-granted device
answers `403` after authentication succeeds.

### Migration from pre-M2 records

Trust-store records written before M2 have no `permissions` field. On load such
a record receives the pairing default (`[READ_STATE]`), which preserves exactly
the behaviour M1 verified (read paths only) without re-pairing. Records that
carry a `permissions` field get exactly the listed set, minus any unknown ids —
an explicitly stored empty set stays empty.

## What is not yet implemented

**APPROVE endpoints.** The permission model, the endpoint matrix and the
`403` contract are IMPLEMENTED (M2); `ADMIN` was activated in Fase 2(c) for
device management. `APPROVE` is a RESERVED grant identifier with no endpoint in
v1: dialog answering is done through `respond`/`keys`. No endpoint maps to it,
so granting it has no effect until one adopts it — recorded here so the
reservation is not mistaken for a working surface.

**Pairing wire flow.** IMPLEMENTED in Fase 2(c): `POST /v1/pair` consumes a
host-printed single-use code, a per-device recovery code, or the tailnet-owner
auto-approval (`tailscale whois`). See [`pairing.md`](pairing.md) and
[`api.md`](api.md).
