# herdr-notify

## What it is

A phone companion for [herdr](https://github.com/herdrdev/herdr), the terminal
multiplexer that runs coding agents. When an agent hits an approval dialog or
finishes a task, the phone buzzes; tapping it takes you to the answer. When
there is no push, the same state is live and openable from the phone over an
encrypted channel.

The user is one person: a developer whose agents keep working after they close
the laptop. The entire product exists because of one failure — an agent sat
blocked on a permission dialog for forty minutes and nobody knew.

## Who it is for

Someone who runs several coding agents across several projects for hours a day,
on more than one device, and who is regularly away from the machine where the
agents live. They already live in a terminal; this is not a new mental model, it
is the same state of affairs rendered for a phone.

Not for: teams, for multi-tenant hosting, for anyone who needs to see more than
one person's agents. There is no account, no organisation, no sharing.

## The product promise

**Nothing that needs you goes unnoticed, and nothing that does not is ever
interrupting you.**

That second half is the harder half and the one that decides whether the app
survives. A notification channel that fires for "your agent is still working" is
muted within a day, and once muted the blocked-agent alert is muted with it.
The hierarchy is therefore:

1. `blocked` — an approval or question UI is up. Someone is waiting. Push, high
   priority, may wake the screen, one-tap actions.
2. `done` — finished and not yet seen. Worth a notification, never an
   interruption. Normal priority, separate channel.
3. everything else — `working`, `idle`, `unknown` — surfaced in the app, never
   pushed.

And between those, three brakes: never notify twice inside a cooldown, never
push a change that came from a snapshot rather than a live event, and never
exceed a hard budget of sends per agent, hour and day. The budget is not only
about manners: push delivery is metered, and an agent flapping between two states
must not be able to spend money unattended.

## How it reaches the phone

Two independent paths, so neither is a single point of failure.

**Push** wakes the app when nothing is running: an agent state change is turned
into a message, the phone shows a notification, tapping it opens the agent. This
is the only path that works when the app is killed.

**Live** is a persistent event stream over an encrypted channel to a gateway
running beside herdr. With the app open, state appears as it changes.

The app is fully usable on the live path alone. Push is an accelerant, never a
prerequisite — which is why an incomplete push backend must not block the app.

## Security posture

The gateway can submit prompts and write keystrokes into any coding agent on the
host. It is the crown jewel, and the design treats it as one.

- **No static secret exists.** A device is a public key; requests are signed with
  the private key in the phone's hardware keystore. A stolen log, a captured
  proxy request, or a phone backup yields nothing usable.
- **The client names actions, never API methods.** No method passthrough, so
  there is no arbitrary-invocation surface.
- **Keys are allowlisted**, destructive ones behind an explicit confirmation.
- **Adding a device is a host-side action.** There is no unauthenticated write in
  the API.
- **Nothing is exposed to the internet.** The gateway binds loopback; an
  encrypted overlay network carries traffic to the phone.

## Surface

The core, built properly rather than broadly.

1. **Pairing** — one-time, shows the host's key fingerprint before trusting it.
2. **Triage** — every agent, ranked by who needs you. The screen you open when
   the phone buzzes.
3. **Agent detail** — what it is doing, which project, its task, its state, and
   the actions to answer it.
4. **Notifications** — blocked and done only, with inline actions.
5. **Settings** — host, per-channel notification control, quiet hours, biometric
   gate for acting, about.
6. **States** — empty, first run, loading, offline, reconnecting, and a hard
   error that says what to do. Every one of these is designed, not defaulted.

## Deliberately out of scope

An embedded SSH terminal. Deep multi-host management (herdr's own SSH federation
already aggregates remote machines into one agent list, and duplicating it in the
phone would mean two sources of truth). Accounts, sharing, and web access. A
design tool for branding — the craft budget goes into density, legibility and
reliability instead.

## Design mode

**Operate.** The visitor is completing a task under time pressure, often one
handed, often outdoors, often at a glance. Scanability, consistency and native
expectations outrank expression here. The brand lives in precise details: the
status colours match herdr's own semantics so the phone and the terminal read as
one system.

## Distribution

Signed release APK attached to a GitHub release. Zero cost, and the channel
already in use for the author's other apps. A debug-signed build is not an
acceptable shippable artefact even on a sideload channel.
