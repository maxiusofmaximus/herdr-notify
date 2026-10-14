# Contract: error model

Authoritative code: `gateway/src/herdr_notify/api/{app,actions,ratelimit}.py`.

## Status codes

| Status | `detail` | When |
|--------|----------|------|
| `400` | `invalid_body`, or `{code, message}` from an action | Body is not JSON / missing field; or an action failed validation |
| `401` | `"unauthorized"` | Any authentication rejection (uniform — see below) |
| `403` | `"forbidden"` | Any authorization rejection (uniform — see below) |
| `404` | `{ "code": "agent_not_found", "message": … }` | The addressed pane no longer exists (see below) |
| `409` | herdr's own message | herdr declined the action (legitimate answer, not a fault) |
| `413` | `"body too large"` | Body exceeds the cap (8 KB enroll/pair, 256 KB signed, image route's own larger cap) |
| `422` | `{ "code": "invalid_body", "errors": [...] }` | A signed body failed model validation |
| `429` | `"slow down"` / `"too many open streams"` | Rate limit, or per-device stream cap |

`429` responses carry `Retry-After` (integer seconds).

## `agent_not_found` (404)

herdr answers `agent_not_found` ("agent target wQ:pG not found") when a request
addresses a pane that was closed on the PC — the everyday case of a chat left
open for an agent that is gone. That is a state of the world, not a refusal:
a `409` told the phone to keep waiting for a state that could never come back,
and it rendered as the generic red "could not read the agent's output" while
the poll retried forever.

| Routes | Where the answer comes from |
|--------|-----------------------------|
| `respond`, `keys`, `focus`, `read`, `image` | herdr's error code, mapped once in `perform()` |
| `seen` | the gateway's own mirror (`store.state.agents`) — this route never reaches herdr |

Body: `{ "code": "agent_not_found", "message": … }`. The **code** is the
contract; the message is herdr's wording and may change. The app branches on
the status and the code: it shows "Este agente ya no existe", stops the output
poll, and the next `/v1/state` refresh drops the agent from the list.

`read` does not try its visible-screen fallback on a `404`: herdr has already
said there is no pane to read. Every other herdr refusal stays `409`,
including the alternate-screen refusal of a working agent, which is a
transient state the app renders as "the agent is working".

## Pairing (Fase 2(c))

`POST /v1/pair` is the one unauthenticated write. Its failures are:

| Status | `detail` | When |
|--------|----------|------|
| `400` | `"invalid_body"` | not JSON, missing `curve`/`public_key`, unsupported curve |
| `403` | `"pairing_rejected"` (string) | a supplied code/recovery code is unknown, expired, used, or the device is revoked |
| `403` | `{ "code": "pairing_rejected", "message": … }` | no code was supplied and the source IP is not the host's tailnet owner; Tailscale unavailable |
| `413` | `"body too large"` | body > 8 KiB |
| `429` | `"slow down"` | per-source-IP limit (`Retry-After`) |

For a **supplied code**, `pairing_rejected` is **uniform**: the caller is never
told which code or which check failed, the same oracle reasoning as the uniform
`401`/`403`. When **no code** was supplied there is only the tailnet-owner check
to fail, and the caller already knows it sent no code, so the refusal is a
`{code, message}` object whose message names the working path
(`herdr-notify enroll`) and, for a loopback source, the local-proxy cause. It
never reports whose account owns an address.

## Order of checks

A request is evaluated in this order, cheapest and most security-relevant first:

1. Signature and freshness → `401` (`auth.md`).
2. Authorization against the endpoint matrix → `403` (`auth.md`).
3. Read rate limit → `429`.
4. For writes, write rate limit → `429`.
5. Body size → `413`; body parse → `400`/`422`.
6. Action validation → `400` with an action code.
7. herdr → `409` if it refuses, `404` (`agent_not_found`) if the target pane is
   gone.

An authorization failure happens before the rate limit and before `last_seen`
is updated: an unauthorized request consumes no budget and leaves no trace.

## The uniform 401

Every authentication rejection — no headers, unknown device, revoked, bad
timestamp, bad nonce, bad signature, malformed, unsupported curve — returns the
same `401` with `{"detail": "unauthorized"}`. The specific reason is logged
server-side only. Distinguishing "unknown device" from "bad signature" would turn
the endpoint into an oracle for which device ids exist.

## The uniform 403

Every authorization rejection — a granted permission missing (`not_permitted`),
an endpoint with no matrix rule (`unknown_endpoint`) — returns the same `403`
with `{"detail": "forbidden"}`. The reason, the device id and the required
permission are logged server-side only: the log is the audit trail.

`401` and `403` are different answers and the client must not conflate them:

- `401` — this device is no longer trusted. Terminal: stop retrying, re-pair.
- `403` — this device is trusted but not allowed to do this. Terminal **for
  that action**: stop retrying it, do **not** re-pair (the pairing is intact),
  do **not** treat it as a transport error. The fix is a host-side grant, never
  a client-side retry.

An authorization error is also **not** a triage status: a triage status is an
agent's own state (`state.md`), not an HTTP outcome. herdr's vocabulary has no
`ERROR` (D2 resolved it: herdr cannot produce one, the contract drops it), so
there is no triage `ERROR` state for an authorization error to be confused with.
The concepts are distinct and never share a representation.

## Action error codes

Returned in the `400` body as `{ "code": "...", "message": "..." }`.

| `code` | Meaning |
|--------|---------|
| `bad_pane` | The target is not a pane id |
| `no_keys` | An empty key list |
| `too_many_keys` | More than 8 keys |
| `empty_key` | A blank key in the list |
| `confirmation_required` | A guarded key (`ctrl+c`) without `confirm: true` |
| `key_not_allowed` | A key outside the allowlist |
| `empty_prompt` | A blank prompt |
| `control_characters` | A prompt with terminal control characters |
| `unsupported_type` | An image whose declared type is not png/jpeg/webp, or whose bytes are none of them |
| `invalid_image` | Image `data` is not valid base64 |
| `empty_image` | Image `data` decodes to zero bytes |
| `image_too_large` | Decoded image over 5 MiB |
| `type_mismatch` | Declared image type does not match the bytes |

There is no `prompt_too_long` code any more: prompts have no length cap
(2026-10-13).

These codes are stable identifiers the app may branch on. They are not
localised; the app renders its own text.

## Deliberately not distinguished

- A malformed body is a client error (`400`/`422`), never a `500`. A phone that
  cannot tell a refusal from a server fault would keep retrying a request that
  can never succeed.
- herdr's refusal (`409`) is a normal outcome. An agent that is no longer blocked,
  or a prompt herdr declined, is information, not a gateway failure.
