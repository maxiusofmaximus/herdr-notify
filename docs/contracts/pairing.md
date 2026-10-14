# Contract: device identity, pairing, revocation

Authoritative code: `gateway/src/herdr_notify/api/auth/devices.py`,
`gateway/src/herdr_notify/cli.py` (`add-device`, `enroll`, `devices`),
`gateway/src/herdr_notify/pairing.py` (payload and QR),
`android/.../security/DeviceKeyStore.kt`, `android/.../pairing/`.

## Device identity — IMPLEMENTED

Each install generates a P-256 key **inside the Android Keystore**. The private
key never leaves the device, is never exportable, and is never sent anywhere. The
public key is transmitted in the encoding the gateway verifies:

- **P-256:** uncompressed SEC1 point, 65 bytes `0x04 || X(32) || Y(32)`, base64.
- The full curve and encoding rules are in [`auth.md`](auth.md).

The device id is a host-side label (`dev-<16 hex>` by default), not a secret.

## Pairing — IMPLEMENTED

Pairing has two implemented paths, and both land in the same trust store.

**Host-side CLI — IMPLEMENTED.** The operator runs a command on the machine that
runs the gateway. The app's pairing screen cannot submit anything; its whole job
is to present the command with the device's own public key pre-filled.

```
iOS/Android app                    operator's machine
──────────────                     ──────────────────
shows its public key      ──▶      runs:
+ suggested device id                herdr-notify add-device \
                                       --curve p256 \
                                       --public-key <SEC1 base64> \
                                       --label <name>
                                   trust store written atomically
app connects signed       ──▶      running gateway picks up the file
                                   change without a restart
```

```
herdr-notify add-device --curve p256 --public-key <b64> --label <name>
```

The running gateway notices a changed trust store (`reload_if_changed`) and
rebuilds its device list, so pairing a phone does not require restarting the
service.

**HTTP `POST /v1/pair` — IMPLEMENTED (Fase 2(c)).** The one unauthenticated
write, gated by a host-printed code, a per-device recovery code, or tailnet
ownership (see *Enrollment codes* below). It grants only the `READ_STATE`
pairing default. The wire contract — request body, resolution order, response
and errors — is in [`api.md`](api.md) and [`errors.md`](errors.md);
`gateway/src/herdr_notify/api/app.py` is authoritative.

## Enrollment codes — IMPLEMENTED (Fase 2(c))

Pairing has an HTTP path now: `POST /v1/pair` (see [`api.md`](api.md) and
[`errors.md`](errors.md) for the exact wire contract; `app.py` is
authoritative). It is the **only unauthenticated write**, and it is gated by one
of three proofs, never a static secret:

```
phone                                      host
─────                                      ────
POST /v1/pair {curve, public_key, label, code}
  │
  ├─ code is a live PAIRING code   ──▶  register a new device (code consumed)
  ├─ code is a live RECOVERY code  ──▶  re-key that device, rotate the code
  └─ no code, source IP is the host's own tailnet owner (tailscale whois)
                                    ──▶  register a new device
  ✗ anything else                   ──▶  403 pairing_rejected
```

An **empty pairing code is the exception, not the normal path.** It works only
when the caller's source IP belongs to the host's own tailnet owner; any other
address (a different account, a tagged node, an unavailable daemon, or a request
that arrived through a proxy) is refused with `403 pairing_rejected`. The normal
path is a **code from `herdr-notify enroll`**, which the operator reads off the
host and enters once on the phone.

- **Pairing code**: `DeviceStore.issue_enrollment_code` — 4 random bytes, base32,
  600 s TTL, **single use**. `herdr-notify enroll` prints it. The store validates
  the payload **before** spending the code, so a malformed request cannot deny
  the legitimate phone its pairing. The code is **persisted to the trust store**
  (as a SHA-256 digest, never in the clear), because `enroll` and the running
  `serve` gateway are separate processes: the gateway notices the changed file
  (`reload_if_changed`) and accepts the code. A spent or expired code is dropped
  from the file, so single use survives a restart.
- **Recovery code**: minted at pairing and returned exactly once; stored only as
  a SHA-256 hash. `herdr-notify devices --recovery <id>` mints a new one
  (rotating the old). It re-keys the device without manual approval and cannot
  be used for a revoked device.
- **Auto-approval**: with no code, `tailscale whois --json <source-ip>` must
  report the same `UserProfile.ID` as the host's own `Self.UserID`. A different
  account, a tagged node, or an unavailable daemon never auto-approves. A
  **local `tailscale serve` proxy** makes the request arrive from a loopback
  address, which has no tailnet owner, so it can never auto-approve: run
  `herdr-notify enroll` and use the code.
- A **supplied code** that fails answers the uniform
  `403 {"detail":"pairing_rejected"}` (updated: an empty code now answers a
  slightly clearer `403 {code, message}` naming `herdr-notify enroll`, since the
  caller already knows it sent no code and only the owner check could have
  failed; it still reveals no owner). The endpoint is rate-limited per source IP.

The host-side `add-device` CLI remains the manual path to the same result, and
is still the way to grant anything beyond the `READ_STATE` pairing default.

## QR payload — IMPLEMENTED

`herdr-notify enroll --qr` prints the pairing code and a QR the phone scans, so
the base URL and the code are entered in one step. The payload is a fixed text
URI (`gateway/src/herdr_notify/pairing.py` is authoritative):

```
herdr-notify://pair?u=<base URL>&c=<enrollment code>&v=1
```

- `u` — the gateway's public base URL, percent-encoded as one query value.
- `c` — the single-use enrollment code from `enroll`.
- `v` — the payload version, `1`.

The code inside the payload is the **same** enrollment code, with the same
600 s TTL and single use (`DeviceStore.issue_enrollment_code`). The QR carries
no secret beyond the code and opens no new path into the gateway; `POST /v1/pair`
resolves it exactly as it resolves a code typed by hand. The builder refuses a
base URL without a scheme or host, and an empty code.

The base URL for `--qr` is resolved from, in order: `--url`,
`HERDR_NOTIFY_PUBLIC_URL`, a `"public_url"` string in
`~/.config/herdr-notify/gateway.json`, then the host's own tailnet address
(`http://<tailnet-ip>:8787`). A malformed explicit or configured URL is an
error, not a silent fall-through. When no source answers, `enroll --qr` exits
`2` with guidance and mints no code. Without `--qr`, `enroll` is unchanged.

## Trust store — IMPLEMENTED

- Path: `~/.config/herdr-notify/devices.json` (override with `--devices`).
- Shape: `{ "version": 1, "devices": [ {device…} ], "codes": [ {code_hash…} ] }`,
  keys sorted, pretty JSON. `codes` holds the SHA-256 digest and the validity
  window of each **live** pairing code (`{code_hash, created_at, expires_at}`);
  spent and expired codes are not written. The plaintext of a code never appears
  in the file.
- **Fail closed:** a file that cannot be read or parsed leaves the store empty
  and trusts nobody. A corrupt store is never treated as "no devices, so allow
  all".
- **Atomic writes:** written to `*.tmp` then `os.replace`, so a half-written
  store cannot come up believing the wrong devices.
- `touch` (last-seen) writes at most once per device per 60 s; the in-memory
  stamp is always current.

A device record:

```json
{
  "device_id": "dev-…",
  "curve": "p256",
  "public_key": "<base64>",
  "label": "Pixel 9",
  "created_at": 1730000000.0,
  "last_seen_at": 1730000000.0,
  "revoked": false,
  "permissions": ["read_state"],
  "fcm_token": null,
  "owner_id": "12345",
  "recovery_code_hash": "<sha256 hex>",
  "persisted_at": 1730000000.0
}
```

`persisted_at` is internal bookkeeping and is never returned by `to_public()` /
the API. `recovery_code_hash` is a SHA-256 of the recovery code — the code
itself is never stored; `owner_id` is the `tailscale whois` owner (informational).

## Permissions (authorization) — IMPLEMENTED (READ_STATE default; APPROVE RESERVED)

A record carries an explicit grant set — the per-device permissions of
[`auth.md`](auth.md). Pairing grants `READ_STATE` and nothing else; the rest are
host-side grants, because widening access is an act performed by a person at
the machine that runs the gateway, the same reasoning that keeps enrollment
host-side.

```
herdr-notify add-device --curve p256 --public-key <b64> \
  --permission respond --permission send_key     # repeatable; READ_STATE always included
herdr-notify devices --grant <id> --permission respond
herdr-notify devices --revoke-permission <id> --permission respond
```

- A record without a `permissions` field (pre-M2) loads with the pairing
  default `[READ_STATE]` — no re-pairing needed.
- A permission id that is not one of the five is dropped on load: it grants
  nothing rather than guessing.
- An explicitly stored set is exact: an empty set stays empty, and a device
  whose `READ_STATE` was revoked stays refused on the read paths (`403`).
- `herdr-notify devices` lists each device's permissions.

## Revocation — IMPLEMENTED

```
herdr-notify devices                 # list, with REVOKED markers
herdr-notify devices --revoke <id>   # revoke one device
```

Since Fase 2(c), an `ADMIN`-granted device can also do this over HTTP:
`POST /v1/devices/{device_id}/revoke` (and `GET /v1/devices` to list).

- Revocation **marks**, it does not delete. A revoked device stays visible and
  refused, which is easier to audit than one that quietly becomes unknown and
  could be re-enrolled under the same id.
- Revoking clears the device's `fcm_token`.
- Effect is immediate: `RequireDevice` checks `revoked` before any cryptography,
  so the next request gets `401`.
- Revoking one device does not affect any other device's key.

## Implementation status

| Capability | Status |
|------------|--------|
| Device identity (P-256 / Ed25519 public key in the keystore) | IMPLEMENTED |
| Host-side `add-device` CLI pairing | IMPLEMENTED |
| `POST /v1/pair` (code / recovery / tailnet owner) | IMPLEMENTED (Fase 2(c)) |
| Pairing codes (4 bytes, 600 s, single use) | IMPLEMENTED |
| QR pairing payload (`enroll --qr`, `herdr-notify://pair`) | IMPLEMENTED |
| Recovery codes (re-key, rotate, SHA-256 hash only) | IMPLEMENTED |
| Tailnet auto-approval (`tailscale whois`, same owner) | IMPLEMENTED |
| Trust store (atomic writes, fail closed, live reload) | IMPLEMENTED |
| `READ_STATE` pairing default | IMPLEMENTED |
| Device management (`GET /v1/devices`, `POST /v1/devices/{id}/revoke`) behind `ADMIN` | IMPLEMENTED (Fase 2(c)) |
| Tailnet peer list (`GET /v1/peers`, `503` when unavailable) | IMPLEMENTED |
| HTTP grant endpoint | NOT IMPLEMENTED — widening access is a host-side CLI act by design |
| `APPROVE` permission endpoints | RESERVED — a valid grantable id with no endpoint in v1 |
