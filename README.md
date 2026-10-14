# herdr-notify

Push notifications and a secure control plane for
[herdr](https://github.com/herdrdev/herdr) coding agents.

When an agent running in herdr needs you — it hit an approval dialog, or it
finished a task you asked for — your phone buzzes, and tapping it takes you
straight to the answer. No terminal hunting, no pane-by-pane archaeology.

## Status

| Phase | What exists | Gate |
|-------|-------------|------|
| **F1** herdr client | Async client, gap-free bootstrap, live stream | 32 unit tests + 3 live tests green |
| **F2** real-time state | `events.subscribe`, stream rotation, authoritative reducer | idempotent under replay; rolls up per workspace |
| F3 Firebase | FCM HTTP v1 sender, push policy, dedup/cooldown | pending |
| F4 control plane | HTTPS API + SSE, device tokens, Tailscale | pending |
| F5 Android app | Compose app, FCM receiver, notifications | pending |
| F6 GUI | Triage grid, agent detail, design system | pending |
| F7 actions | Approve / respond via `agent.send_keys` and `agent.prompt` | pending |
| F8 E2E | Deterministic ADB-driven tests on a real phone | pending |
| F9 security | Audit with `cloudflare/security-audit-skill` | pending |

## Architecture

```
herdr server  ──NDJSON──▶  gateway (Python, runs beside herdr)
                                │
                                ├─ herdr client     subscribe + request/response
                                ├─ state store      authoritative reduced session
                                ├─ attention ranker blocked ▸ done ▸ working ▸ idle
                                ├─ push policy      dedup, cooldown, budget
                                └─ HTTP API         127.0.0.1 only
                                       │
                        ┌──────────────┴───────────────┐
                    FCM HTTP v1                  Tailscale serve
                        │                              │
                        └──────────▶ 📱 Android ◀──────┘
                                   push + live SSE
```

**No port is exposed to the internet.** The gateway binds loopback; Tailscale
publishes it over TLS inside the tailnet. Interactive SSH, when wanted, is
Tailscale SSH — Ed25519 keys, no `sshd` install, no forwarded port.

## Layout

```
gateway/     Python 3.13 · herdr client, state store, (soon) push + API
android/     Kotlin · Jetpack Compose app
e2e/         Deterministic ADB-driven end-to-end scenarios
tooling/     Firebase bootstrap, wireless-device pairing
docs/        Protocol notes, threat model, setup guides
security/    Audit artefacts (coverage ledger, findings, report)
```

## Quick start

```bash
cd gateway
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"

# Does the herdr endpoint resolve, and is the server answering?
.venv/Scripts/python.exe -m herdr_notify.cli doctor --ping

# What does herdr look like right now?
.venv/Scripts/python.exe -m herdr_notify.cli dump
PYTHONPATH=src .venv/Scripts/python.exe -m herdr_notify.cli dump --follow

# Pair a phone: mint a single-use code and print it as a QR to scan.
.venv/Scripts/python.exe -m herdr_notify.cli enroll --qr --url https://pc.tailnet.ts.net
```

## Pairing a phone

A device is paired with a **single-use enrollment code** the operator mints on
the host and the phone enters once. `enroll --qr` prints that code together with
a QR the phone scans, so the base URL and the code travel in one step:

```
$ herdr-notify enroll --qr --url https://pc.tailnet.ts.net
pairing code : THMDRVA
valid for    : 600s
trust store  : ~/.config/herdr-notify/devices.json

On the phone, enter this code once to register its public key.

scan this QR, or open the URI below:
████████████████ ... ████████████████
...
pairing uri  : herdr-notify://pair?u=https%3A%2F%2Fpc.tailnet.ts.net&c=THMDRVA&v=1
```

The payload is `herdr-notify://pair?u=<base URL>&c=<code>&v=1`: the gateway's
base URL percent-encoded, the enrollment code, and the version. The code keeps
its existing **600 s TTL and single use** — the QR is a shorter way to type the
same code, not a second enrollment path.

The base URL for `--qr` comes from, in order: `--url`,
`HERDR_NOTIFY_PUBLIC_URL`, a `"public_url"` key in
`~/.config/herdr-notify/gateway.json`, and finally the host's own tailnet
address (`http://<tailnet-ip>:8787`). If none of those answers, `enroll --qr`
refuses with guidance and mints no code. Without `--qr`, `enroll` prints the
code exactly as before.


## Testing

```bash
cd gateway
.venv/Scripts/python.exe -m pytest              # 32 unit tests, hermetic
.venv/Scripts/python.exe -m pytest -m integration   # 3 tests, needs a running herdr
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m mypy src
```

Unit tests drive a scriptable in-process fake of herdr's API rather than a live
session, because the behaviour worth testing — subscribe-before-snapshot,
rotation without losing an event, idempotence under replay — is timing behaviour,
and mutating a real coding session to exercise it is not an acceptable trade.

## Read this before touching the herdr client

[`docs/herdr-integration.md`](docs/herdr-integration.md) documents the protocol
facts that are **not** in herdr's prose docs and that each cost real debugging
time: the endpoint is a named pipe and not the `.sock` file, there is exactly one
request per connection, subscription sets are frozen at subscribe time,
`session.snapshot` nests under `result.snapshot`, and the Windows CRT
read/write position plus `CloseHandle` deadlock are both real and both fail
confusingly.

## Seguridad

Sin token estático: cada dispositivo es una clave pública P-256 que el host
registra y firma cada petición; el host puede revocarla y los permisos son por
dispositivo. El gateway rechaza direcciones comodín (`0.0.0.0`, `::`) y corre
solo dentro de Tailscale (más loopback). Ver `docs/contracts/auth.md`.

Configuración local (no versionada): copia `android/local.properties` con
`gatewayUrl=http://<tu-ip-tailscale>:8788` y `tailnetHosts=<tu-ip-tailscale>`.
Sin ese fichero la app compila con placeholders inocuos.

## Security posture

The gateway is the crown jewel: it holds a socket that can drive any coding agent
on the machine. Design rules already in place:

- The client may only ask for **typed actions**. It can never name a herdr
  method, so there is no arbitrary-invocation surface.
- The resolved herdr endpoint is pinned inside herdr's config directory, so a
  tampered `HERDR_SOCKET_PATH` cannot redirect the control plane.
- Event payloads are treated as untrusted; an unrecognised status or event name
  is dropped rather than stored.
- Secrets are gitignored, and the FCM service account is referenced by path, not
  embedded.

Formal audit: phase F9.
