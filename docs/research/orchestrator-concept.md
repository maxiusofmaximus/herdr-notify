# Orchestrator concept — one phone, any ADE, many projects

Concept note. **No code, no schema migration, no commit.** This builds on the
shipped contract set (`docs/contracts/`) and the two apps analysed in
[`dots-grokbot-analysis.md`](dots-grokbot-analysis.md).

The idea in one line: **the phone stops being a herdr companion and becomes a
front end for any Agent Development Environment (ADE) — opencode, pi, claude,
hermes — and a higher-level orchestrator that drives several projects through
each project's own *leader agent*.**

Two layers, deliberately separate:

1. **ADE-agnostic front end.** The gateway normalises every ADE into one state
   model; the app renders that model and never learns which ADE it is talking to.
2. **Orchestrator.** A local coordinator above the ADEs. It owns *goals and
   projects*; each project is run by one **leader agent** that decomposes the
   goal and drives its **subagents** (ordinary ADE agents).

> Constraint carried from PRODUCT.md: local-first, no cloud, one operator, no
> accounts. The orchestrator is a **local service**, not a hosted one.

---

## 1. Architecture

```
                         📱 Android app  (Kotlin / Compose)
                              │  signed HTTP + SSE (loopback → Tailscale)
                              ▼
                    ┌───────────────────────────┐
                    │   gateway (Python, local) │   ← today: herdr only
                    │                           │
                    │  HTTP API   /v1/*         │
                    │  state model (reducer)    │
                    │  attention ranker         │
                    │  push policy              │
                    │  ── ADE adapter layer ──  │   ← NEW boundary
                    └────────┬──────────────────┘
                             │  normalized snapshot + events + actions
        ┌────────────────────┼───────────────────────┬────────────────┐
        ▼                    ▼                        ▼                ▼
   herdr adapter       opencode adapter          pi adapter      claude / hermes
        │                    │                        │                │
        └──────── each adapter speaks its ADE's native protocol ───────┘
                             │
                    ┌────────┴─────────┐
                    │  ORCHESTRATOR    │  ← local service, above the adapters
                    │  (new)           │
                    │  project registry│
                    │  task graph      │
                    │  review inbox    │
                    │  budgets/policy  │
                    └────────┬─────────┘
                             │  goals + status + approvals
              ┌──────────────┼───────────────┐
              ▼              ▼               ▼
        project leader  project leader  project leader     (one per project)
              │              │               │
        subagents      subagents        subagents           (ADE agents)
```

### Layers

- **Mobile app.** Existing contract only: signed requests, action names (never
  ADE methods), SSE for live state. Gains orchestration *views*, not new trust.
- **Gateway.** Keeps its role (mirror, reduce, rank, push, authorize). Gains an
  **ADE adapter interface** and a few additive orchestration endpoints. It stays
  the only network-facing process; the orchestrator is behind it.
- **ADE adapter.** One module per ADE that normalises *snapshot → state*,
  *events → stream*, and *typed actions → native calls*. herdr's client is the
  first adapter and the reference implementation of the interface.
- **Orchestrator.** Owns projects, goals, the task graph, the review inbox, and
  budgets. It does not speak to an ADE directly; it speaks through adapters, and
  it appears to the gateway as just another state producer.
- **Project leader.** One agent per project, with an orchestrator skill/MCP. It
  receives a goal, plans, spawns subagents, and reports status and needs upward.
- **Subagents.** Ordinary ADE agents inside one project's workspace.

### Why a leader layer at all

The whole point is **locality of context**: a leader lives inside its project's
repo, history and conventions, so it can decompose and sequence work with the
context a central master lacks. The master stays high-level (which projects
exist, which goals, where the money/time is going) and never touches code. This
is the Dots *Activity/dev* and Grok Bot *Chief of Staff* shape, but oriented
around **projects** instead of a person or a single cloud computer — and with
the isolation that a shared account-level computer (Grok Bot) cannot give.

---

## 2. Data model

Everything is a projection over the event stream the gateway already reduces.
The existing `state` object (`revision`, `focused`, `counts`, `agents`) is
**extended additively**; older clients ignore the new keys.

### 2.1 Orchestration entities

```
Project          id, name, root_path (host-local), ade ("opencode"|…),
                 leader_pane_id, status, goal (current), budget_policy,
                 created_at, updated_at

Goal             id, project_id, text, state (proposed|active|done|cancelled),
                 created_by (operator), created_at

Task             id, project_id, parent_task_id, goal_id,
                 title, state (queued|running|blocked|done|failed|cancelled),
                 assignee_pane_id, depends_on[], attempt, budget,
                 created_at, updated_at, finished_at

Review           id, project_id, task_id, pane_id,
                 kind (approval|question|handoff|draft),
                 origin (operator|routine|leader|subagent),
                 payload, expires_at, state (open|answered|expired|denied)

RunRecord        id, task_id, routine_id?, started_at, ended_at,
                 outcome (success|failure), summary, artefacts[]
```

`Task` and `Review` are the new primitives. A `Review` is how a blocked agent
becomes a phone notification; a `Task` is what the orchestrator tracks when no
single agent is running it yet.

### 2.2 Mapping onto the existing state model

| Orchestrator concept | Existing contract | Change |
|----------------------|-------------------|--------|
| Project | workspace label on `TriageRow.project` | promote to a first-class, grouped object |
| Task running on a pane | `TriageRow` | add `orchestrator: {project_id, task_id, role, parent_pane_id}` |
| Blocked / done | `attention` URGENT (3) / REVIEW (2) | unchanged — a leader's `blocked` and a subagent's `blocked` both rank highest |
| Review | a `blocked` pane + an approval UI | new **unified review inbox** keyed by `Review.id`, sourced from panes |
| RunRecord | — | new ledger, per task/routine |
| Budget | `push.policy` per agent + global | extend profiles from per-agent to per-project |

`role` is `leader | subagent`; `parent_pane_id` links a subagent to its leader so
the app can collapse a project into one row and expand on demand. A `leader` with
no running subagent is still visible as the project's health signal.

### 2.3 Autonomy policy (borrowed from Dots, sharpened)

Per **action class**, four dispositions:

| Disposition | Meaning |
|-------------|---------|
| `auto` | Run without asking. |
| `on_request` | Run when the operator asked; otherwise ask immediately before acting. |
| `ask` | Ask before acting. |
| `handoff` | Ask the operator to do it. |

Action classes at minimum: prompt/keystroke submit, file write, git commit, push,
network call, destructive key (`ctrl+c`, delete). Stored per project, overridable
per task. Evaluated **host-side**, never in the app — the app only ever sees the
resulting `Review`. `handoff` is where the Grok Bot *takeover* flow lands for
interactive auth.

---

## 3. Mobile UX

Design mode stays **Operate** (PRODUCT.md): one-handed, outdoors, at a glance.
The app already has Pairing, Triage, Agent detail, Notifications, Settings. The
orchestrator adds three surfaces and changes none of the trust model.

### 3.1 Project grouping (primary change to Triage)

- Triage gets a **grouped mode**: rows roll up under a project header. The
  header shows the leader's state, task counts (`2 running · 1 blocked`) and the
  project's attention colour — the worst state inside it.
- A project with a blocked agent **floats to the top as a project**, not as a
  bare agent, so the phone answers "which project needs me" first.
- Expanding a project reveals its tasks/agents, leader first, ranked exactly as
  today (`-attention, focused, project, pane_id`). Subagents nest under their
  leader via `parent_pane_id`.
- Flat mode remains one tap away — the current single list must never be lost.
- A project header is not a new entity to the trust model: it is a client-side
  grouping of rows that already carry `project_id`.

### 3.2 Unified approval inbox (new tab)

- One inbox across all projects, ranked by the same attention ranker. Each card
  is a `Review`: what it is (`approval|question|handoff|draft`), which project
  and task, who is waiting (leader or subagent), and **inline actions**.
- **Draft-on-submit** (from Grok Bot): for prompts/keystrokes, show the exact
  payload before the send. `respond` previews the text; `keys` previews the key
  sequence; destructive keys require the existing `confirm: true`.
- **Expiry for unattended work** (from Grok Bot): a review that came from
  routine/leader self-started work shows a countdown and expires (proposed
  default 15 min), turning the action off rather than running late. An expired
  card may offer **"always allow this"**, which writes an `auto` policy row.
- Answering a review reuses the existing signed actions
  (`/v1/agents/{pane_id}/respond|keys`) — the inbox is a view, not a new
  authority.
- A `handoff` review opens the takeover flow: the phone shows "this needs you at
  the machine" (or, where an ADE exposes it, a scoped interactive session).

### 3.3 Notifications

The failed-hierarchy rule from PRODUCT.md is preserved and extended, not
weakened:

| Event | Tier | Push? |
|-------|------|:-----:|
| A `Review` opens (leader or subagent blocked on approval/question/handoff) | `URGENT` / 3 | yes, high priority, may wake |
| A `Task` completes and is unseen | `REVIEW` / 2 | yes, normal channel |
| A project's leader finishes its goal | `REVIEW` / 2 | yes, one per goal |
| Subagent `working`, leader `working`, run progress | `INFO` / 1 | **no** |
| Project idle | `NONE` / 0 | no |

- **Collapse key becomes project-scoped**: `project-<project_id>` for the review
  digest, `agent-<pane_id>` retained for a single agent. Many subagents in one
  project must not stack into a wall of tray entries.
- **Quiet hours** unchanged: `URGENT` ignores them, `REVIEW` defers.
- **Budgets** become per-project as well as global: a leader that flaps between
  two states while spawning subagents must not be able to spend the day's send
  budget on progress.
- **Patience** (N:1): a review that has already been pushed is not re-pushed
  merely because a second subagent in the same project also blocks — it is
  folded into the same digest.

### 3.4 Detail and controls

- **Task detail** = today's Agent detail plus: goal, parent task, dependencies,
  run history, and the artefacts a run produced.
- **Scheduled / recurring** is a distinct surface from *Activity*, mirroring the
  Dots lesson: cancelling a schedule and stopping a run are different actions
  with different consequences, and the UI must say so.
- **Pause** stops the leader's current plan; stopping a subagent stops one task;
  cancelling a routine cancels the schedule. Three verbs, never conflated.

---

## 4. Gateway API extensions

Additive only, same rules as `docs/contracts/README.md`: signed requests, the
endpoint matrix is load-bearing (a new endpoint without a rule fails closed
`403`), client names actions never ADE methods, uniform `401`/`403`, one shape
per concept. New endpoints are introduced with an explicit matrix row and grant.

### 4.1 New endpoints

| Method | Path | Grant | Purpose |
|--------|------|-------|---------|
| `GET` | `/v1/projects` | `READ_STATE` | Projects with rollup status and leader health |
| `GET` | `/v1/projects/{project_id}` | `READ_STATE` | One project: goal, tasks, agents, budget |
| `GET` | `/v1/projects/{project_id}/tasks` | `READ_STATE` | Task list (pageable) |
| `GET` | `/v1/tasks/{task_id}` | `READ_STATE` | Task detail + run history + artefacts |
| `GET` | `/v1/reviews` | `READ_STATE` | The unified approval inbox, ranked |
| `POST` | `/v1/reviews/{review_id}/answer` | `RESPOND` | Answer/approve/deny a review |
| `POST` | `/v1/projects/{project_id}/goals` | `ORCHESTRATE` | Give a project leader a goal |
| `POST` | `/v1/tasks/{task_id}/pause` | `ORCHESTRATE` | Pause one task |
| `POST` | `/v1/tasks/{task_id}/resume` | `ORCHESTRATE` | Resume one task |
| `POST` | `/v1/tasks/{task_id}/cancel` | `ORCHESTRATE` | Cancel one task |
| `POST` | `/v1/projects/{project_id}/pause` | `ORCHESTRATE` | Pause the leader's plan |
| `GET` | `/v1/ades` | `ADMIN` | Registered ADE adapters and health |
| `GET` | `/v1/orchestrator/health` | `READ_STATE` | Orchestrator liveness, no operator data |

Actions on a pane stay exactly as they are (`/v1/agents/{pane_id}/respond`,
`/keys`, `/focus`, `/seen`, `/read`); a review answering an approval resolves to
those. `/v1/workspaces` generalises toward "create a project workspace in ADE
X", but that is deferred until the adapter interface exists.

### 4.2 New permission and matrix rows

- Add **`ORCHESTRATE`** (`orchestrate`), not granted at pairing, alongside the
  existing five. It gates goal creation and pause/resume/cancel — the acts that
  change the shape of work rather than answer one pane. `APPROVE` (currently
  reserved) can remain reserved, or be adopted by
  `/v1/reviews/{id}/answer`; recommended: keep `APPROVE` reserved and use
  `RESPOND`, so dialog answering stays unified with prompts/keys.
- Every new endpoint gets a matrix row in `contracts/auth.md` in the **same
  commit** as the code, or it answers `403`.

### 4.3 State and stream extensions

- `state` object gains `projects: [ {id, name, leader_pane_id, status, counts,
  attention} ]` and `reviews_count`.
- `TriageRow` gains `orchestrator: {project_id, task_id, role, parent_pane_id}`.
- New SSE event names on `/v1/events` (same framing, same "re-read
  `/v1/state`" rule): `project.updated`, `task.updated`, `review.opened`,
  `review.closed`. The opening frame remains the exact `/v1/state` object.
- Golden vectors stay Python ↔ Kotlin; the new event names and `orchestrator`
  block are covered by API/wire tests, not new signing vectors.

### 4.4 ADE adapter contract (host-side, not HTTP)

One interface, modelled on what the herdr client already does:

```
snapshot()                 -> normalized session state
subscribe(set)             -> gap-free stream of normalized events
rotate(pane_set)           -> re-subscribe for the discovered panes
send_prompt(pane_id, text) -> native prompt
send_keys(pane_id, keys)   -> native keys (allowlisted)
read_pane(pane_id, lines)  -> recent output
focus(pane_id)             -> native focus
```

Every adapter must honour the same bootstrap order herdr forced on us
(subscribe → snapshot → rotate), the same fail-closed status handling
(unrecognised status → `unknown`), and the same "one action, one native call"
discipline. `herdr` is adapter #1 and the conformance reference.

---

## 5. Phased roadmap

Ordering principle unchanged: **security → contracts → correctness → real
integration → recovery → observability → UX → extras.** No phase pulls a later
item forward.

| Phase | Deliverable | Gate |
|-------|-------------|------|
| **O0** | ADE adapter interface extracted; herdr client refactored behind it | herdr behaviour unchanged; all existing tests green; no new network surface |
| **O1** | Orchestrator core: project registry, goal + task graph, run ledger, review inbox; local only | tasks/owners/reviews modelled and unit-tested; no ADE writes without an `ORCHESTRATE` grant |
| **O2** | Gateway orchestration API + contracts (`projects`, `tasks`, `reviews`, matrix rows, SSE events) | contracts and code change together; golden vectors unchanged; a new endpoint without a rule answers `403` |
| **O3** | Mobile: project grouping, unified approval inbox, task detail, Activity vs Scheduled | on a physical device, blocked-by-project ranks first; answering a review uses only existing signed actions |
| **O4** | Leader agent: orchestrator skill/MCP, plan → subagent spawn → status → review | one real project driven end-to-end from the phone; leader `blocked` reaches the inbox |
| **O5** | Additional ADE adapters: opencode, pi, claude, hermes | each adapter passes the herdr conformance suite (snapshot/stream/rotate/actions) |
| **O6** | Notification policy for orchestration: per-project collapse keys and budgets, review digests | no progress push; blocked review wakes; a flapping leader cannot exhaust the budget |
| **O7** | Recovery/observability: leader restart, orphaned subagent reconciliation, run-ledger audit | forced disconnects measured; no orphaned task left `running` |
| **O8** | Hardening/audit across the new surface | security audit; orchestrator cannot be an escalation path around per-device grants |

Each phase is "done" only when executed in its real environment (the roadmap's
governing rule), not when the code exists.

---

## 6. The future Rust rewrite (deferred — do not start)

A **Rust rewrite** of the gateway and/or orchestrator is envisioned as a later
effort, to be carried out by **Pi Agent** together with **strata** and a **local
Qwen** model. Constraints on that work, recorded now so the decision is not made
by accident:

- It happens **only after explicit user approval** — it is not part of O0–O8 and
  must not be started speculatively.
- **No Rust is written now.** This document contains no Rust, no skeleton, no
  crate layout. The AI-generated Rust path is a *proposal*, not a deliverable.
- The Rust target would have to preserve every invariant already paid for in
  Python: the signing string and golden vectors, the load-bearing endpoint
  matrix, fail-closed status handling, the gap-free bootstrap order, and the
  Windows named-pipe transport lessons in `docs/herdr-integration.md`.
- The local Qwen constraint means the rewrite is generated and reviewed **on the
  host**, consistent with the no-cloud posture.

Until then, the Python gateway remains the reference implementation, and the
adapter interface (O0) is the seam the rewrite would slot behind without the app
or the contracts noticing.

## Open questions

1. **Leader transport.** Does the orchestrator talk to a leader over the ADE's
   own prompt channel, or over a dedicated orchestrator MCP? (Leaning: MCP, so a
   leader is portable across ADEs.)
2. **Approval expiry default.** Grok Bot uses ~10 min for unattended work; the
   right value here depends on how long a coding agent can idle before a stale
   approval costs more than it saves.
3. **`APPROVE` grant.** Fold dialog answering into `RESPOND` (recommended) or
   adopt the reserved `APPROVE` for `/v1/reviews/{id}/answer`.
4. **Project root path.** Host-local paths must never reach the phone beyond the
   workspace label already sent; confirm the grouping key is `project_id`, not
   the path.
