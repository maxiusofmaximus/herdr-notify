# Contract: device identity, pairing, revocation

Authoritative code: `gateway/src/herdr_notify/api/auth/devices.py`,
`gateway/src/herdr_notify/cli.py` (`add-device`, `enroll`, `devices`),
`android/.../security/DeviceKeyStore.kt`, `android/.../pairing/`.

## Device identity

Each install generates a P-256 key **inside the Android Keystore**. The private
key never leaves the device, is never exportable, and is never sent anywhere. The
public key is transmitted in the encoding the gateway verifies:

- **P-256:** uncompressed SEC1 point, 65 bytes `0x04 || X(32) || Y(32)`, base64.
- The full curve and encoding rules are in [`auth.md`](auth.md).

The device id is a host-side label (`dev-<16 hex>` by default), not a secret.

## How pairing actually works today

Pairing is a **host-side act**. There is no HTTP enrollment endpoint, and that
absence is a security decision, not an unfinished feature: an unauthenticated
write that registers devices would make key-based authentication pointless.

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

The app's pairing screen cannot submit anything; its whole job is to present a
correct, copyable command. The command is a single line

```
herdr-notify add-device --curve p256 --public-key <b64> --label <name>
```

The running gateway notices a changed trust store (`reload_if_changed`) and
rebuilds its device list, so pairing a phone does not require restarting the
service.

## Enrollment codes — IMPLEMENTED (Fase 2(c))

Pairing has an HTTP path now: `POST /v1/pair` (see `FASE2C.md` for the exact
wire contract). It is the **only unauthenticated write**, and it is gated by one
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
  ✗ anything else                   ──▶  403 {"detail":"pairing_rejected"}
```

- **Pairing code**: `DeviceStore.issue_enrollment_code` — 4 random bytes, base32,
  600 s TTL, **single use**. `herdr-notify enroll` prints it. The store validates
  the payload **before** spending the code, so a malformed request cannot deny
  the legitimate phone its pairing.
- **Recovery code**: minted at pairing and returned exactly once; stored only as
  a SHA-256 hash. `herdr-notify devices --recovery <id>` mints a new one
  (rotating the old). It re-keys the device without manual approval and cannot
  be used for a revoked device.
- **Auto-approval**: with no code, `tailscale whois --json <source-ip>` must
  report the same `UserProfile.ID` as the host's own `Self.UserID`. A different
  account, a tagged node, or an unavailable daemon never auto-approves.
- Every failure answers the uniform `403 {"detail":"pairing_rejected"}`; the
  endpoint is rate-limited per source IP.

The host-side `add-device` CLI remains the manual path to the same result, and
is still the way to grant anything beyond the `READ_STATE` pairing default.

## Trust store

- Path: `~/.config/herdr-notify/devices.json` (override with `--devices`).
- Shape: `{ "version": 1, "devices": [ {device…} ] }`, keys sorted, pretty JSON.
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

## Permissions (authorization)

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

## Revocation

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
