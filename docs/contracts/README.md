# Contracts

The agreement between the gateway (Python) and the app (Kotlin). Both sides must
consume exactly these shapes. When one side changes a contract, the other side
changes in the same commit, and the golden vectors change with them.

These documents describe **what the two sides must agree on**, not a wish list.
Each one names the code that is authoritative when the prose and the code
disagree — and they should not disagree.

## Index

| File | Contract |
|------|----------|
| [`auth.md`](auth.md) | Request signing, canonicalisation, anti-replay, curves |
| [`api.md`](api.md) | HTTP surface: endpoints, requests, responses |
| [`state.md`](state.md) | The state read model and triage ranking |
| [`pairing.md`](pairing.md) | Device identity, enrollment, trust store, revocation |
| [`push.md`](push.md) | Notification policy and the FCM token lifecycle |
| [`errors.md`](errors.md) | Status codes and error bodies |

## Implementation status

These documents are contracts, not a roadmap. Where the code does not yet
honour something, the contract says so with an explicit marker. The tokens
`IMPLEMENTED`, `NOT IMPLEMENTED`, `DEFERRED` and `RESERVED` are greppable on
purpose so no reader mistakes a defined shape for a working path.

| Concept | Status | Where |
|---------|--------|-------|
| Signed request auth (`p256`), anti-replay, trust store, revocation | IMPLEMENTED | [`auth.md`](auth.md), [`pairing.md`](pairing.md) |
| `GET /v1/health`, `/v1/state`, `/v1/events`, all `/v1/agents/{pane_id}/*` actions | IMPLEMENTED | [`api.md`](api.md), [`state.md`](state.md) |
| Image attachment (`POST /v1/agents/{pane_id}/image`: store + prompt the path) | IMPLEMENTED | [`api.md`](api.md) |
| Push policy (`blocked`/`done`, cooldown, budget, quiet hours) | IMPLEMENTED (host-side) | [`push.md`](push.md) |
| Per-device authorization (`READ_STATE`, `RESPOND`, …), endpoint matrix, uniform `403` | IMPLEMENTED (M2) | [`auth.md`](auth.md), [`api.md`](api.md) |
| HTTP pairing endpoint (`POST /v1/pair`), recovery codes, tailnet auto-approval | IMPLEMENTED (Fase 2(c)) | [`pairing.md`](pairing.md), [`api.md`](api.md) |
| Device management (`GET /v1/devices`, revoke) behind `ADMIN` | IMPLEMENTED (Fase 2(c)) | [`auth.md`](auth.md), [`api.md`](api.md) |
| Tailnet peer list (`GET /v1/peers`) for address probing | IMPLEMENTED (Fase 2(c)) | [`api.md`](api.md) |
| FCM token lifecycle (park → register → store) | IMPLEMENTED (unit-verified, 2026-10-04) | [`push.md`](push.md) |
| FCM end-to-end (`token → gateway → FCM → phone`, physical device) | **NOT IMPLEMENTED** (M3 open) | [`push.md`](push.md) |
| `ERROR` triage state | **DROPPED** (D2: herdr never reports it) | [`state.md`](state.md) |
| `X-HN-Key-Id` header | **RESERVED** — no effect in v1 | [`auth.md`](auth.md) |

## Rules

1. **One shape per concept.** A given concept is encoded one way. Two encodings
   of the same thing — the defect M0 fixed between `/v1/state` and the SSE
   opening frame — are a contract break, not a convenience.
2. **Additive changes only.** New fields may be added; existing fields may not
   change meaning or disappear without a version bump. Both parsers ignore what
   they do not know.
3. **Fail closed, degrade rather than crash.** An unknown enum value becomes
   `unknown`, never an exception. An unreadable trust store trusts nobody.
4. **The client names an action, never a method.** No herdr method name crosses
   the API boundary.
5. **No secret is a static bearer token.** A device is a public key.

## Source of truth

- Signing string: `gateway/src/herdr_notify/api/auth/canonical.py` and
  `android/.../net/RequestSigner.kt`. Pinned by the shared golden vectors.
- HTTP surface: `gateway/src/herdr_notify/api/app.py`.
- Typed actions and allowlists: `gateway/src/herdr_notify/api/actions.py`.
- State model: `gateway/src/herdr_notify/state/models.py` and
  `gateway/src/herdr_notify/notify/attention.py`.
- Trust store and enrollment: `gateway/src/herdr_notify/api/auth/devices.py`.
- Push policy: `gateway/src/herdr_notify/notify/policy.py`.

## Golden vectors

`gateway/tests/vectors/signing_vectors.json` is the shared fixture. The Python
suite (`tests/test_golden_vectors.py`) and the Kotlin suite
(`GoldenVectorTest`) both assert against the same file, so a change to the
canonical string breaks both suites if only one side is updated.

The vectors cover the signing string because that is where the two languages are
most likely to disagree by one byte (key order, newline termination, method
case). State and error shapes are covered by the API tests and the wire decoder
tests instead.
