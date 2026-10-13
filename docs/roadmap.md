# Roadmap v2

Governing specification: [`replanteamiento.md`](../replanteamiento.md).
This file turns it into an ordered, checkable plan and records what is actually
verified at each step.

The rule that orders everything here:

> A feature is done when it has been **executed in its real environment**, not
> when the code exists. "Código presente" ≠ "funcionalidad implementada".

## Milestones

| # | Milestone | Result | Status |
|---|-----------|--------|--------|
| M0 | Baseline clean | Repo clean, tests green, no credentials, no temp sessions | **done** |
| M1 | Secure local monitoring | herdr → gateway → pairing → Android → real-time state | **host + device verified; all 13 items observed** |
| M2 | Authenticated/authorized actions | Per-device permissions, not just authentication | **done — host + device verified; all 10 items observed; the two device-level observations below are recorded, not open defects** |
| M3 | FCM E2E real | token → gateway → FCM → phone, on a physical device | wiring implemented + unit-verified (commit `262ac61`, 2026-10-04); FCM project id resolved from google-services.json (`0ce30bd`, 2026-10-05); D1 credential minted + migrated to the Windows Credential Manager 2026-10-05; remaining: physical-device E2E run |
| M4 | Remote access | Tailscale + TLS, verified off-LAN | not started |
| M5 | Offline/reconnect/errors | Forced disconnects and recovery measured on-device | not started |
| M6 | Release hardening | Release APK, R8, signing, no debug flags, clean install | not started |
| M7 | Final audit | Security audit across the whole surface | not started |
| M8 | Release candidate | Signed artefact attached to a GitHub release | not started |

## Security first, then contracts, then correctness

The priority order is fixed: **security → contracts → correctness → real
integration → recovery → observability → UX → extras.** No milestone may pull a
later item forward past an unfinished earlier one.

## M0 — Baseline (done)

Verified 2026-09-29 on this machine, from a clean tree:

| Check | Command | Result |
|-------|---------|--------|
| Gateway unit tests | `python -m pytest` in `gateway/` | 189 passed, 3 deselected |
| Gateway lint | `python -m ruff check src tests` | clean |
| Gateway types | `python -m mypy src` | clean, 23 files |
| Android unit tests | `:app:testDebugUnitTest --rerun-tasks` | 94 passed, 0 failed |
| Secrets in tracked files | pattern scan of `git ls-files` | none |
| Temp sessions | `session-*.md` ignored, prior export archived out of the tree | none |

Re-run for the Fase 1 close (2026-09-29, same tree): gateway `189 passed, 3
deselected`; `ruff check src tests` clean; `mypy src` clean (23 files); Android
`:app:testDebugUnitTest :app:assembleDebug --no-daemon --rerun-tasks` → `94
tests, 0 failures/skipped`, `BUILD SUCCESSFUL in 59s`. Integration marker against
the live server: `pytest -m integration` → `3 passed`.

Baseline defects found and fixed while establishing M0 (both were real, both were
invisible to a green suite before the fix):

1. **`/v1/state` and the SSE opening frame disagreed.** The poll returned ranked
   triage rows with `attention` and a per-status `counts`; the stream's first
   frame returned the raw reduced view, whose agents carry no `attention` and
   whose `counts` tallies collections. A phone joining the stream ranked from a
   payload the gateway never ranked. Now both come from a single `state_payload`.
2. **`GatewayTriageRepository.disconnect()` cancelled its own scope.**
   `disconnect()` called `scope.cancel()` on the repository's scope, so every
   later `connect()` launched into a dead scope and the stream never reopened.
   Now only the connection's `Job` is cancelled.

## M1 — Secure local monitoring (host + device verified)

The deliberately small first target. Exactly this path, nothing else:

```
herdr → gateway → secure pairing → Android → real-time state
```

Explicitly **out of scope for M1**: FCM, dangerous actions, cloud relay, and any
secondary feature.

Executed 2026-09-29 on this machine. Re-executed and closed 2026-09-30 with a
real gateway kill/restart cycle and a natural live transition. Three proof
levels, labelled so a test double is never mistaken for a device run:

- **REAL GATEWAY VERIFIED** — real gateway process, real herdr 0.9.1, real P-256
  key, real HTTP + SSE over loopback (`/v1/state`, `/v1/events`); no TestClient.
- **REAL DEVICE VERIFIED** — physical **TECNO KI7, Android 13 (SDK 33)**, app
  `dev.herdrnotify.app.debug` installed over adb, reaching the host gateway via
  `adb reverse tcp:8787` (no Tailscale on the device).
- **VERIFIED BY TEST** — JVM/unit only.

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| 1 | Gateway starts and mirrors live herdr | REAL GATEWAY VERIFIED | `serve` bound `:8787`; `watching herdr 0.9.1: 9 workspaces, 9 panes, 9 agents`; `/v1/health` `revision 2` |
| 2 | Device pairs via the contractual flow | REAL DEVICE VERIFIED | app produced `herdr-notify add-device --curve p256 --public-key BMz7… `; host ran it with the phone's key; store `devices:1` |
| 3 | Auth/signing with a real key | REAL GATEWAY + REAL DEVICE | unsigned `/v1/state` → 401; signed → 200; the phone's keystore key was accepted |
| 4 | Device reads `/v1/state` | REAL DEVICE VERIFIED | phone rendered the 9 real agents |
| 5 | Device establishes SSE | REAL DEVICE VERIFIED | `/v1/health` `streams:1` while the app was open |
| 6 | Opening frame == `/v1/state` | REAL GATEWAY VERIFIED | opening frame `== state_payload` (identical dict) |
| 7 | A real herdr change arrives | REAL DEVICE VERIFIED | 2026-09-30: natural transition observed on-device — `graphify-rust` went `terminado` → `trabajando` on its own (no agent mutated), health `revision` 2→4, and the phone showed the new state; earlier 2026-09-29 window had no transition in 120 s (agents stable, left untouched) |
| 8 | Android updates displayed state | REAL DEVICE VERIFIED | 2026-09-30: in-place update over the live stream — same gateway process alive (PID unchanged), `streams:1` at both sample points, the row re-ranked (moved from 1st to 4th, consistent with triage ranking) and re-rendered with the new state |
| 9 | Disconnect detected | REAL DEVICE VERIFIED | 2026-09-29: gateway killed → header subtitle `Sin conexión`, list kept as last-known. 2026-09-30 re-run with a real server-side kill: gateway process (PID 188748, `python -m herdr_notify.cli serve` on `127.0.0.1:8787`) killed → 45 s later the header showed `Sin conexión` (UI dump observed); the earlier `adb reverse --remove` attempt proved nothing and is not counted |
| 10 | Reconnect | REAL DEVICE VERIFIED | 2026-09-29: bridge restored → subtitle back to `9 agentes`, `streams:1`. 2026-09-30 re-run: gateway restarted detached (`Invoke-CimMethod Win32_Process Create` + the real `run-gateway.cmd`) → health `streams:1` within ~60 s, header back to `9 agentes`, real state and agents re-rendered (UI dump observed) |
| 11 | `disconnect()`→`connect()` keeps repo usable | VERIFIED BY TEST + DEVICE | `GatewayTriageRepositoryTest`; the device reconnected after a real gateway restart on 2026-09-29 and again after a real detached restart on 2026-09-30 |
| 12 | No FCM needed | REAL GATEWAY VERIFIED | ran with `push credential: none stored in the Credential Manager` |
| 13 | No dangerous actions enabled | REAL DEVICE VERIFIED | M1 exercised only `/v1/state` + `/v1/events` (read paths) |

### Item 7/8 closed (2026-09-30) — natural transition, no agent mutated

The 2026-09-29 window found no transition (the nine real agents were stable for
120 s) and the operator's session was left untouched, so 7/8 stayed open. On
2026-09-30 a connected-window watch caught a natural one: between two UI dumps
(~5 min apart, device connected the whole time, same gateway process alive) the
`graphify-rust` agent resumed work on its own — `terminado` → `trabajando`,
health `revision` 2→4, and the phone re-rendered the row with the new state and
the new ranking position. Nothing was mutated, restarted or fabricated to
produce it: the operator's opencode session simply resumed. The changed state
reached the device over the established SSE stream, which is exactly what 7/8
required.

### Observation recorded during M1 (not changed now)

The pairing screen suggests a **random device id per launch** until it is saved,
so the id inside the copied `add-device` command can differ from the one the app
finally stores if the app is relaunched before saving. Pairing succeeds when the
operator runs the command from the same session it is saved in. Recorded, not
"fixed" — it is a UX decision, not this milestone's scope.

### Known gap that blocked M1 sign-off (behavioural) — RESOLVED by M2

**Per-device permissions did not exist.** Every paired device could do every action;
§24–25 require `READ_STATE` by default and explicit grants for the rest. Contract
in [`contracts/auth.md`](contracts/auth.md); implementation is M2. M1 was honest
that a newly paired device is currently all-powerful.

M2 (2026-09-30) closes it: the endpoint matrix, the `READ_STATE` default at
pairing, the host-side grant path, the uniform `403`, and the fail-closed
properties are implemented and verified (see the M2 section). The phone's real
pre-M2 record migrated to `READ_STATE` without re-pairing and the M1-verified
behaviour (state + SSE) still works on the device.

### 2026-09-30 execution record (M1 close)

Timeline of the real kill/restart cycle plus the natural transition, all
observed (UI dumps via `uiautomator dump`, health via `/v1/health`):

| Time (local) | Event | Observed evidence |
|--------------|-------|-------------------|
| 02:51 | Gateway killed | `Stop-Process` on PID 188748 (the exact `python -m herdr_notify.cli serve --host 127.0.0.1 --port 8787` process); `8787: no listener` |
| 02:53 | Disconnect detected | UI dump: header `9 agentes` → `Sin conexión`, list kept as last-known |
| ~02:55 | First detached start attempt died | `Invoke-CimMethod` without `PYTHONPATH` → `ModuleNotFoundError: herdr_notify`; the real `run-gateway.cmd` sets it — diagnosed, not hidden |
| 02:59 | Gateway restarted detached | `Invoke-CimMethod Win32_Process Create` running the real `run-gateway.cmd` (venv python + `PYTHONPATH` + real devices store); listener PID 172316 on `127.0.0.1:8787` |
| 03:00 | Client reconnected | health `{"ok":true,"revision":2,"devices":2,"streams":1}`; serve log `watching herdr 0.9.1: 9 workspaces, 9 panes, 9 agents`, `push credential: none` |
| 03:02 | Reconnect shown in UI | UI dump: `Sin conexión` gone, header back to `9 agentes`, real state and agents re-rendered |
| 03:16 | Watch t0 | UI dump: `graphify-rust` `terminado`, `herdr-notify` `trabajando`; health `revision:2, streams:1` |
| 03:21 | Watch t1 — transition | UI dump: `graphify-rust` `trabajando`, row re-ranked (bounds y 324→927); health `revision:4, streams:1`; same gateway process alive (PID 172316, started 02:59) |

- No agent was mutated, stopped or created to force the transition —
  `graphify-rust` resumed on its own.
- `/v1/events` unsigned → `401` (fail closed still holds); `/v1/state` could not
  be read from the host (the signing key lives in the phone keystore, by
  design), so state↔UI consistency was checked against the observed transition
  (revision 2→4 in the gateway, `terminado`→`trabajando` in the UI) rather than
  a host-side poll.
- Store now holds `devices:2` (the phone `hn-aaaaaaaa`, last seen during this
  run, plus an earlier pairing `hn-bbbbbbbb`, never seen); not a defect.
- Tests re-run after the documentation update (2026-09-30, same tree): gateway
  `pytest` → `189 passed, 3 deselected`; `ruff check src tests` clean; `mypy src`
  clean (23 files); `pytest -m integration` → `3 passed` (live server); Android
  `:app:testDebugUnitTest :app:assembleDebug --no-daemon --rerun-tasks` →
  `BUILD SUCCESSFUL in 1m 11s`, `94 tests, 0 failures, 0 skipped` (13 suites).

## M2 — Authenticated/authorized actions (done)

The gap that blocked M1 sign-off: **per-device permissions do not exist** —
every paired device could do every action. M2 closes it.

### Model (derived, documented in `contracts/auth.md`)

Five permissions, the ones the specification (§24–25) names: `READ_STATE`
(default at pairing: observe only), `RESPOND` (act: prompts, focus, seen),
`SEND_KEY` (act: allowlisted keys), `APPROVE` and `ADMIN` (**RESERVED in v1** —
grantable identifiers with no endpoint; device management is a host-side CLI
action by design). Authorization is a separate question from authentication,
checked after it and before the rate limit; a refusal is a uniform `403`
`{"detail": "forbidden"}` with the reason logged server-side only. The
endpoint→permission matrix is load-bearing: an endpoint without a rule fails
closed. `401` and `403` are different answers (re-pair vs. host-side grant) and
the Android client maps them to distinct error types so the UI never asks for a
re-pair when the pairing is intact.

Two security properties beyond the original gap, found while auditing:

1. **Revocation reaches established streams.** The stream is the one long-lived
   request; revocation that only refused *new* requests would leave a revoked
   phone receiving live state until the stream broke. The stream now checks the
   device's trust before every frame — keepalives included — so nothing at all
   flows after a revocation, and the stream closes within one keepalive (20 s).
2. **An unauthorized request leaves no trace.** The authorization check runs
   before the rate limit and before `last_seen`, so a refused request consumes
   no rate budget and writes nothing.

### Implementation

| Area | File | Change |
|------|------|--------|
| Endpoint matrix + authorization | `gateway/src/herdr_notify/api/auth/authz.py` | NEW: `Permission`, `required_permission()`, `authorize()`, uniform `403` |
| Grant set on the device record | `.../api/auth/devices.py` | `permissions` field (default `[read_state]`), `grant()`, `revoke_permission()`, unknown ids dropped on load |
| 403 handler + check order | `.../api/app.py` | `authorize()` in `require_device` (after auth, before rate limit); stream trust check per frame; `STREAM_KEEPALIVE_SECONDS` |
| Host-side grants | `.../cli.py` | `add-device --permission`, `devices --grant/--revoke-permission`, permissions in the listing |
| Client 403 ≠ 401 | `android/.../net/GatewayClient.kt` | `GatewayError.NotPermitted` (new type) for 403; 401 stays Unauthorised |
| Stream 403 stops retrying | `android/.../net/LiveStream.kt` | 403 → NotPermitted → Failed without re-pair message, no retry |
| Repository | `android/.../pairing/GatewayTriageRepository.kt` | NotPermitted: no connection-state change (pairing intact) |

### Evidence (2026-09-30)

Proof levels labelled as in M1, so a test double is never mistaken for a device
run:

- **REAL GATEWAY VERIFIED** — real gateway process (`python -m herdr_notify.cli
  -v serve` on `127.0.0.1:8787`, restarted with the M2 code; the first detached
  start without `PYTHONPATH` died with `ModuleNotFoundError`, diagnosed and
  re-run with the wrapper script — the same M1 lesson), real trust store, real
  P-256 signature from a host-side enrolled key, real HTTP. No TestClient.
- **REAL DEVICE VERIFIED** — physical **TECNO KI7, Android 13**, app
  `dev.herdrnotify.app.debug` (M2 build, installed over adb), reaching the host
  via `adb reverse tcp:8787`.
- **VERIFIED BY TEST** — JVM/unit only.

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| 1 | Authorization model defined + contract | REAL GATEWAY VERIFIED | `contracts/auth.md` authorization sections; matrix pinned by `tests/test_authz.py::test_the_endpoint_matrix_is_exact` |
| 2 | Fail closed: no grant → refused | REAL GATEWAY VERIFIED | synthetic device (READ_STATE only): `POST /v1/agents/w1:p1/respond` → `403 {"detail":"forbidden"}`; serve log `refused an authorized request from dev-…: not_permitted (required: respond)` |
| 3 | Default grant: READ_STATE | REAL GATEWAY VERIFIED | same device: `GET /v1/state` → `200`; act endpoints → `403` |
| 4 | Grant path works | REAL GATEWAY VERIFIED | `devices --grant <id> --permission respond` (CLI choice-validated) → respond → `409` (authorization passed; herdr's own refusal for a non-live pane — a legitimate answer, not a fault) |
| 5 | Revocation immediate, 401 ≠ 403 | REAL GATEWAY VERIFIED | `devices --revoke <id>` → `GET /v1/state` → `401 {"detail":"unauthorized"}`; serve log `refused a signed request: revoked` |
| 6 | Revocation reaches established streams | VERIFIED BY TEST (real HTTP) | `test_a_revoked_device_loses_its_live_stream`: real uvicorn on an ephemeral loopback port, real SSE over a real socket; revoked mid-stream → the stream closes within one keepalive and nothing (not even a keepalive comment) is delivered after. The TestClient cannot drive this — it buffers the whole response body, which is why no other test opens `/v1/events` through it. **Gap found during the real device run** (below): the check read the stale in-memory store because stream keepalives do not trigger the reload — fixed (`reload_if_changed()` before every frame check); the running gateway picks it up on its next restart |
| 7 | Unauthorized request leaves no trace | VERIFIED BY TEST | `test_an_unauthorized_request_leaves_no_trace`: 403 before the rate limit and before `last_seen` |
| 8 | Migration: pre-M2 records keep working | REAL DEVICE VERIFIED | the phone's real record (no `permissions` field, paired during M1) loaded with `[read_state]`; the phone connected, authenticated with its keystore key, received state and SSE — `streams:1`, real agents rendered (UI dump: `graphify-rust`, `herdr-notify`, …) — without re-pairing |
| 9 | Client 403 ≠ 401 (no false re-pair) | VERIFIED BY TEST + DEVICE | `GatewayClientTest` (403 → NotPermitted, not Unauthorised); `LiveStreamTest` (403 stops retrying, message never says "emparej"); the M2 APK installed and the live path working end to end |
| 10 | Uniform 401 preserved (M1) | REAL GATEWAY VERIFIED | unsigned `/v1/state` → 401; revoked → 401; the golden vectors unchanged |

### Honest observations recorded during M2 (not changed now)

1. **The phone's markSeen tap never fires the request chain.** Four attempts
   with fresh UI dumps tapped inside the first row's bounds; no request from
   `hn-aaaaaaaa` ever reached the gateway (its 403 would be logged, as the
   synthetic device's was). A TCP watch during two taps never saw a second
   connection to the gateway open, and the request path cannot drop silently
   (it either sends or throws) — so the chain never starts: the tap does not
   reach `onOpenAgent`. The tap path was never exercised in M1 either — item 13
   covered read paths only. Diagnosing further needs app-level instrumentation
   (e.g. a debug log in `onOpenAgent`); recorded as an observation, not a claim
   either way.
2. **The app's reaction to a real revocation, observed on-device.** After a
   real `devices --revoke` with the app connected, the phone's stream stopped
   and the app entered the error UI without retrying (`streams:1` → `0`; the
   gateway log shows the 401 for the phone's reconnect:
   `refused a signed request: revoked`). The UI renders fixed error strings for
   any failed state — the repository's own message ("Este teléfono ya no está
   emparejado") is carried in the state but not rendered, so the UI cannot
   tell a revocation from a transient failure. Recorded: a UX decision for a
   later milestone, not this one's scope.
3. **The stream-revocation gap (found and fixed during the device run).** The
   first device attempt showed a revoked phone's stream still open after 42 s:
   the stream's trust check read the *in-memory* store, and stream keepalives
   do not go through the request path that triggers the reload — so the check
   read a stale trust list until some other authenticated request came along.
   Fixed in `app.py` (`reload_if_changed()` before every frame check) and
   covered by the stream test. Note the running gateway imports the code as of
   its own start: a gateway restarted before this fix keeps the gap until the
   next restart.
4. `replanteamiento.md` is not in the tree (never committed; archived out
   during M0). The §24–25 constraints are known only as quoted in
   `contracts/auth.md`. Recorded so the gap is visible, not hidden.

### 2026-10-01 device window (M2 second pass)

Wireless debugging re-established (the adb pairing dialog rotates its code and
port on every re-open; the mDNS connect service reconnected on its own, no
`adb pair` needed). Sequence observed:

| Step | Event | Observed evidence |
|------|-------|-------------------|
| 1 | Phone reconnects after restore | `streams:1`, `devices:2` (the gateway reloaded the clean store) |
| 2 | Revoke with the stream established | `devices --revoke hn-aaaaaaaa` → the stream stayed open 42 s on a gateway started before the stream-reload fix (gap 3, above) |
| 3 | Gateway restarted with the fix | fresh process; the phone's reconnect → `401` (`refused a signed request: revoked` in the serve log) |
| 4 | Phone restored again | `add-device` with the same key and id → the record is overwritten, un-revoked, `[read_state]` |
| 5 | App restarted, reconnects | `streams:1`, `devices:2`, real agents rendered (UI dump: live revision 19, `ArkASA-Servidor-Dedicado` `Terminó`, `atlas-os` `· en foco`) |

The store ends clean: two real pairings, neither revoked. The operator's phone
ends working, on the live path, under the M2 default grant.

### M2 close (2026-10-01)

Closed by commit `633a8f8` (`feat(authz): close M2 authorization enforcement`)
after the evidence above demonstrated every acceptance criterion: all 10 items
in the table observed, gateway `pytest tests/test_api.py tests/test_authz.py`
→ `83 passed`, Android `:app:testDebugUnitTest` (GatewayClientTest,
LiveStreamTest, GatewayTriageRepositoryTest) → `26 tests, 0 failed, 0 skipped`.
Re-run 2026-10-01 on the same tree before this record: gateway `83 passed, 1
warning`. The two honest observations (markSeen/tap chain, fixed error strings)
remain recorded as observations — they are not open M2 defects and are handled
by later decisions (D2/roadmap), not by reopening M2.

## Fase 1 — Contracts (done)

Written before the code that depends on them and kept honest about what the code
does not yet do. Each file names the authoritative source. Status tokens
(`IMPLEMENTED` / `NOT IMPLEMENTED` / `DEFERRED` / `RESERVED`) are greppable.

| Document | Contract | Marked `NOT IMPLEMENTED` / `RESERVED` |
|----------|----------|--------------------------------------|
| [`contracts/README.md`](contracts/README.md) | Index, rules, status table | central status table |
| [`contracts/auth.md`](contracts/auth.md) | Signing string, anti-replay, curves, uniform 401 | per-device **authorization** (M2); `X-HN-Key-Id` **RESERVED**, no effect |
| [`contracts/api.md`](contracts/api.md) | HTTP surface | no HTTP **enrollment endpoint** (by design) |
| [`contracts/state.md`](contracts/state.md) | Read model + triage ranking | `ERROR` status **DROPPED** (D2: herdr never reports it) |
| [`contracts/pairing.md`](contracts/pairing.md) | Identity, trust store, revocation | enrollment-code **wire** flow **NOT IMPLEMENTED** (store only) |
| [`contracts/push.md`](contracts/push.md) | Notify-don't-authorize policy, token lifecycle | FCM **end-to-end on a physical device** **NOT IMPLEMENTED** (M3 open) |
| [`contracts/errors.md`](contracts/errors.md) | Status codes, uniform 401, action codes | — |

Golden vectors (`gateway/tests/vectors/signing_vectors.json`) stay the shared
Python ↔ Android fixture; both suites assert the same file.

## Open architectural decisions

### D1 — Where the FCM sending identity lives — RESOLVED (2026-10-01)

`replanteamiento.md` §19–21. The requirement: the sending identity has only
`firebase.messaging`, no long-lived private key on the laptop, no long-lived
credentials JSON, short-lived access tokens, revocable. The current state keeps
the Google credential in the Windows Credential Manager (`notify/dpapi.py`),
which removes a plaintext file but **still holds a non-expiring refresh token
that carries the operator's own project permissions**.

Two shapes satisfy the requirement:

- **A. Push Relay Cloud** (§20): the local gateway calls a tiny authenticated
  HTTPS relay that holds a platform-managed identity and talks to FCM. Removes
  the Google credential from the laptop entirely; adds a cloud component.
- **B. Narrow the local credential** to the messaging scope and, separately,
  move the send to a least-privilege service account — accepting that some
  Google identity still exists on the machine.

**Resolved 2026-10-01**: the operator chose **B**, refined by research into a
narrowed ADC credential with a **dedicated Google identity** — a separate
account, not the operator's, logged in with
`gcloud auth application-default login --scopes=https://www.googleapis.com/auth/firebase.messaging`,
so the refresh token mints only messaging-scoped access tokens (short-lived,
revocable by deleting the grant) and carries none of the operator's own project
permissions. It lives in the Windows Credential Manager via the existing
`notify/dpapi.py`: no plaintext file, no private key JSON, no cloud component —
local-first preserved. The research that chose it (P2P vs FCM vs hybrid,
UnifiedPush, VAPID, prior art) is recorded in `decision-D1.md` (untracked
operator document). The hybrid architecture was confirmed, not changed: the SSE
stream stays the primary path and FCM is the fallback for a device that is
asleep, off-LAN, or has a killed app.

### D2 — `ERROR` triage state (§10) — RESOLVED (2026-10-01)

The specification lists `ERROR` among the minimum states; herdr's vocabulary is
`idle/working/blocked/done/unknown` and the gateway forwards it unchanged. Either
herdr never reports `ERROR` (and the contract should say so) or the gateway must
derive it.

Resolved 2026-10-01 by herdr source evidence, taking the first branch: herdr
0.9.1's `AgentStatus` (`src/api/schema/common.rs`) is
`idle | working | blocked | done | unknown` — no `Error` arm; `PaneAgentState`,
the raw detection state, has none either; and `parse_agent_status`
(`src/cli.rs`) accepts only those five strings. herdr never reports `ERROR`, so
[`contracts/state.md`](contracts/state.md) now says so and drops the pending
state; the gateway derives nothing. No state was added to the model just to
close the milestone. (The 2026-09-30 on-device watch had shown only
`trabajando` / `terminado` / `listo` plus idle — consistent with the source.)

## Contracts

All wire, auth, pairing, state, push and error contracts are in
[`docs/contracts/`](contracts/) (Fase 1, done — see the section above). They are
the agreement Android and Python must both consume. Future changes are additive
unless an architectural decision is recorded here.
