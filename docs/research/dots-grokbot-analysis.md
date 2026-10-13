# Dots (OpenAI) and Grok Bot — UI, navigation and feature analysis

Research note. Docs and public product material only; **no code, no product
screenshots redistributed**. Every image referenced here is linked to its
official source rather than copied — see [`img/README.md`](img/README.md) for
the licensing reasoning.

Two different bets on the same problem: *an agent that works while you are away
from the machine, and a phone that lets you answer it.* Dots is one personal
agent per person, living in the ChatGPT surface. Grok Bot is a team of agents
with a coordinator, living on a shared cloud computer. Both are read to feed
**herdr-notify**, whose axis is different: many coding agents across many
projects, ranked by who needs you, over a local gateway.

---

## 1. Dots (OpenAI)

A **dot** is "a personal AI agent that belongs to one person." It texts, it
calls, and it works on a hosted cloud computer with its own browser. It is
reached through the ChatGPT surface — desktop app, web, mobile app — and through
Slack and Teams (texting "coming soon"). Setup historically began on desktop;
since the October 5–9 2026 release it can be created in the ChatGPT mobile app.
Mobile **web** is explicitly unsupported.

> Note on sourcing: `openai.usethedots.com` is a promotional/concept page
> ("six dots, one floor", "Powered by Astra 6") and is **not** treated as
> authoritative for UI behaviour below; the behavioural facts come from
> `learn.chatgpt.com/docs/dots/*` and the OpenAI announcement.

### 1.1 Screens

| Screen | What it shows / does |
|--------|----------------------|
| **Intro / setup** ("meet dot") | Name the dot, customize appearance (shape, colour, eyes, glasses, accessories — changeable later), connect plugins (email, calendar, files), connect your computer (desktop app). The dot introduces itself and suggests work. |
| **Conversation (home)** | Chat transcript with the dot, text composer + mic, "Send message". Messages you assign continue after a call ends. |
| **Dot profile** | The control hub: **Computers** (inspect/open the cloud computer), **Activity**, **Scheduled**, **Add** (connect a contact method), and the link into settings. |
| **Activity** | Delegated tasks: progress, files, results, and **requests for input**. Open one to inspect and redirect. Background work appears here. |
| **Scheduled** | Recurring tasks with their instructions, timing, and destination. Stopped separately from Activity. |
| **Settings → Personalization → Custom rules** | Per-action autonomy policy (see rules table below), under **Permissions**. |
| **Plugin permissions** | App-action permissions, controlled separately from custom rules. |

### 1.2 Flows

- **Create** — open dots → follow intro → name + avatar → connect plugins
  (skippable) → connect computer → first conversation. Handle starts as
  `@yourname-dot`; naming updates it (e.g. `@tibo-alfred`).
- **Assign work** — describe the outcome in natural language. The dot can use
  background agents, start cloud threads, create **Work** or **Codex** tasks on
  a connected computer, continue existing local Codex tasks, and use a Codex
  cloud environment for repo-bound coding work.
- **Review / redirect** — open Activity, inspect a task, change direction while
  it runs. Ask the dot what it is working on and what needs input.
- **Stop** — **Pause** stops the current main task; delegated tasks are stopped
  in Activity; recurring tasks are cancelled in Scheduled. These are three
  separate actions. Ending a voice call does **not** stop assigned work.
- **Cross-channel** — the same dot is reachable in ChatGPT, on a call, in Slack
  (DM or channel mention), and in Teams. Changing channel does not reset memory,
  though each channel shows only its own messages. Before sharing from a private
  conversation with others, the dot checks that you allowed it.

### 1.3 Custom rules (the autonomy vocabulary)

| Rule | Behaviour |
|------|-----------|
| Take action without asking | Act without approval. |
| Take action when you say so | Proceed when explicitly requested; otherwise ask immediately before acting. |
| Ask before taking action | Ask for approval before the action. |
| Hand off to you | Ask **you** to do it instead. |

Rules are per-action instructions the dot *tries* to follow; they do not grant
app access and do not override built-in safety requirements. Built-in safeguards,
existing ChatGPT app permissions, and automatic approval review apply from the
start. Safety monitoring can **pause or stop** a dot. "Proactive research" is
restricted to **read-only** tools (cannot send, mutate, or drive the browser or
computer).

### 1.4 Feature summary

| Capability | Present | Notes |
|------------|:-------:|-------|
| Personal agent per person | ✅ | One owner; no teams/sharing. |
| Cloud computer + browser | ✅ | Available when your machine is off. |
| Local computer access | ✅ | Desktop app can connect your computer for Codex tasks/files. |
| Multi-channel (ChatGPT, call, Slack, Teams) | ✅ | Shared context across channels. |
| Assigned + recurring tasks | ✅ | Activity vs Scheduled are separate surfaces. |
| Per-action autonomy rules | ✅ | 4-option vocabulary above. |
| Approvals / human handoff | ✅ | Automatic approval review; requests for input in Activity. |
| Read-only proactive research | ✅ | Cannot mutate connected apps. |
| Safety pause/stop | ✅ | Server-side monitor. |
| Notifications | ✅ (implicit) | Dot messages you with progress, questions, decisions. |
| Mobile creation | ✅ (Oct 2026) | Mobile web still unsupported. |

Access: Pro tiers, 18+, region-gated (outside EEA/UK/Switzerland), gradual
rollout. Enterprise shape (specialist dots, Microsoft Agent 365, IT-provisioned
hardware) is announced but separate.

### 1.5 Strengths

- **Continuity across surfaces.** The same identity and memory follow the user
  from desktop to phone to Slack; only the channel transcript differs.
- **A small, legible autonomy model.** Four named rules beat an opaque
  "restricted/allowed" switch, and they compose with built-in safety.
- **Clean separation of time scales.** *Activity* (running) and *Scheduled*
  (recurring) are distinct, and stopping one does not silently stop the other.
- **Work continues without the device.** Cloud computer means closing the laptop
  does not stop the job.
- **Read-only means read-only.** Proactive research cannot mutate anything — a
  sharp, defensible safety line.

### 1.6 What to copy

1. **The four-option autonomy rule vocabulary** — map it directly onto our
   approval gate (autonomous / on-request / ask / hand-off), per action type.
2. **Activity vs Scheduled separation** — our orchestrator needs the same two
   views and the same "stopping one does not stop the other" honesty.
3. **Inspectable task detail** — progress, files, results, and *requests for
   input* in one place, answerable inline.
4. **Read-only research posture** — a first-class "observe without mutating"
   capability is exactly what a leader agent's reconnaissance should be.
5. **Cross-channel continuity** — one identity, one memory, many entry points.
6. **Safety pause/stop** — a host-side kill switch on autonomous work.

### 1.7 What to avoid

- **One agent per person, no project grouping, no teams.** Our whole premise is
  many projects and many agents; Dots' single-dot model does not scale to that.
- **Chat-first, low-density UI.** A conversation is a poor surface for scanning
  a dozen concurrent agents ranked by urgency.
- **No explicit agent status vocabulary.** Dots has no `blocked/done/working`
  triage primitive; "decisions that need you" is a chat event, not a ranked
  queue. We already have a better primitive (`state.md`).
- **Cloud-resident by construction.** Conflicts with herdr-notify's local-first,
  no-cloud posture.
- **Generic notification path.** Progress/questions arrive as chat messages, not
  as a priority-tiered alert (blocked vs done). It lacks our cooldown/budget
  discipline.

---

## 2. Grok Bot (xAI / Cursor)

"AI teammates you can give real work to." Bots sign in to your tools, use them
via GUI computer-use, and finish end-to-end workflows. Desktop (macOS/Windows)
and iOS/Android; desktop is the primary, keyboard-heavy surface. Bundled with
Cursor Ultra / Cursor Premium Teams (and SuperGrok Heavy per launch material),
early beta.

### 2.1 Screens

| Screen | What it shows / does |
|--------|----------------------|
| **Home / sidebar** | Bot list with attention states, search, `+` to **New Bot** / **New Group Chat**. Pin, hide, unhide, duplicate. |
| **Bot chat** | Composer: text, paste text/links/images, attach files, dictation, voice chat. `@Bot` mentions, `/skill`, routine/connector references. Editable **draft cards** (Send email / Send message / Discard). **Approval cards**. |
| **Computer view** | The bot's live screen: watch a run, **take over**, inspect, hand back with **I'm done**. |
| **Skills / Routines** | Create a skill (from description, save a finished task, or "teach a task"); routines with schedule/trigger, run history, enable/pause/test. |
| **Settings** | Account, appearance, language (>20), notifications. |
| **Mobile home** | `+` → New Bot / New Group Chat; search across Messages, Bots, Group Chats, Files, Routines; review the computer. |

### 2.2 Attention states (the triage primitive)

The sidebar distinguishes three states, which is the closest thing either app
has to our attention ranking:

- **Needs attention** — a question, approval, or handoff.
- **Unread activity** — a new result.
- **Working / typing.**

Opening a conversation marks its activity read; you can mark read/unread
manually.

### 2.3 Flows

- **Create / organize** — new Bot, give it a name/description/avatar, assign a
  concrete task. Build a roster: start with one owner of an end-to-end outcome,
  add a specialist only when the role is stable, put collaborators in a **group
  chat** so handoffs are visible.
- **Coordinate** — a **"Chief of Staff"** bot distributes work to specialists.
  Bots message each other, hand off task ownership, and run in parallel.
  `@Bot`, `/skill`, and routine references drive it from one thread.
- **Teach → run** — do the task once via "Teach a task" (records up to 10 min,
  no audio) → the bot drafts a **skill** → you review/test → a **routine**
  schedules it (every weekday 8:00) or triggers it on an event (Slack, GitHub).
  Skills are account-wide; a bot can toggle them. One bot owns up to **50**
  routines, keeping the last **20** run records each.
- **Approve** — an Auto Review approval from a chat you are in waits for your
  answer. One from work that **started without you** (routine, trigger, another
  bot) **expires after ~10 minutes**, the card shows **Expired**, and the action
  does not run. An expired card may offer **"Always allow this in the future"**,
  which adds an **Allow automatically** rule without running the expired action.
- **Take over** — for auth, 2FA or CAPTCHA the bot asks you to take control; you
  sign in; you hand back; the session is saved and shared with other bots.

### 2.4 Feature summary

| Capability | Present | Notes |
|------------|:-------:|-------|
| Persistent cloud computer (browser, FS, terminal, GUI) | ✅ | **One per account, shared by all bots.** |
| Computer Use (click/type/navigate) | ✅ | Works with tools that have no API. |
| Multiple bots, parallel | ✅ | Bot-to-bot messaging, ownership handoff, group chats. |
| Coordinator role ("Chief of Staff") | ✅ | Routes work to specialists. |
| Skills (reusable instructions) | ✅ | Text, saved-task, or teach-by-demonstration. |
| Routines (schedule/event trigger) | ✅ | ≤50/bot; last 20 runs; enable/pause/test/history. |
| Memory over time | ✅ | Preferences, project/account context, corrections. |
| Approval boundaries | ✅ | Defaults: external sends, financial, deletions, prod changes. |
| Approval expiry for unattended work | ✅ | ~10 min, then Expired. |
| Human takeover (auth/2FA/CAPTCHA) | ✅ | Session saved and shared. |
| Files and result artifacts | ✅ | Attach in, view/download out. |
| Notifications + mobile | ✅ | Completion + approval requests; desktop and mobile. |

### 2.5 Strengths

- **Explicit team topology.** The coordinator + specialists + group-chat handoff
  is exactly the *master → leader → subagent* shape we want, shipped as a
  first-class concept rather than an emergent one.
- **Attention states.** "Needs attention / unread result / working" is a
  rankable signal — the right primitive for a triage screen.
- **Approval expiry.** Unattended self-initiated work cannot pile up stale
  approvals forever; ~10 minutes then it dies cleanly.
- **Takeover flow.** Clean human handoff for interactive auth the agent cannot
  do alone, with a reusable saved session.
- **Teach-once pipeline.** Demonstration → skill → routine is a strong
  repeatability story, and the run history gives it accountability.

### 2.6 What to copy

1. **Attention-state vocabulary** — map *needs attention → blocked*, *unread
   result → done*, *working → working*. We already rank this way; adopt the
   naming discipline for the phone.
2. **Approval expiry + "always allow in the future"** — a stale approval for a
   self-started task must not hang indefinitely; turn a repeated decision into a
   rule.
3. **Takeover/handoff for interactive auth** — a first-class "the human does
   this one step" path.
4. **Coordinator + visible handoff (group chat)** — our leader agent needs a
   visible handoff channel to subagents, not a hidden RPC.
5. **Per-routine run history** — a task ledger with success/failure, essential
   for an orchestrator you trust.
6. **Draft-before-send card** — review the exact outgoing message/keystroke
   before submit is the safe shape for `respond`/`keys`.

### 2.7 What to avoid

- **Account-level shared computer (shared browser, logins, files).** The security
  boundary is the *account*, not the bot. For coding across several projects with
  different repos and secrets this is disqualifying — one leaked login crosses
  every project. Our isolation must be **per project/workspace**, not per account.
- **GUI computer-use for coding.** Clicking and typing into a browser is brittle,
  slow, and non-deterministic; a coding agent in a terminal is already headless
  and scriptable. Do not import click-typing as the control mechanism.
- **Cloud-hosted worker.** Same local-first conflict as Dots; our gateway and
  models stay on the host.
- **Desktop-first, keyboard-heavy UX.** Many actions are keyboard shortcuts and
  a recording-based teaching flow; the phone is a companion, not a workstation.
- **Surface bloat.** Group chats, 50 routines/bot, memory, marketplace, team
  bots — too much to render legibly one-handed under time pressure.
- **Subscription coupling.** Tied to Cursor/xAI plans; not a model we inherit.

---

## 3. Cross-app takeaways for herdr-notify

| Theme | Dots | Grok Bot | Our position |
|-------|------|----------|--------------|
| Unit | One dot / person | Team of bots + coordinator | Many agents **per project**, grouped |
| Status primitive | none (chat events) | Needs attention / unread / working | `blocked/done/working/idle` + attention rank |
| Autonomy control | 4-option per-action rules | Approval boundaries + expiry + auto-allow | Per-action policy + expiry + budget |
| Worker host | Cloud computer | Shared cloud computer | **Local gateway** (host stays the source of truth) |
| Approval handoff | Requests for input in Activity | Approval cards + takeover | Blocked pushed high; takeover for auth |
| Continuity | Same dot across channels | Same thread desktop↔mobile | Same agent across terminal + phone |
| Recurrence | Scheduled vs Activity | Routines + run history | Orchestrator task ledger (leader-owned) |

Both apps prove the demand for *"answer the agent from your phone, keep the work
running."* Neither is built for **one developer running several coding agents
across several repositories at once**, which is exactly the gap the orchestrator
concept targets.

## Sources

- OpenAI, *Introducing dots* — `https://openai.com/index/introducing-dots`
- OpenAI, *Meet dots* (ChatGPT Learn) — `https://learn.chatgpt.com/docs/dots`
- OpenAI, *Control your dot* — `https://learn.chatgpt.com/docs/dots/controls`
- OpenAI, *Get started with your dot* — `https://learn.chatgpt.com/docs/dots/getting-started`
- OpenAI, *Message your dot* — `https://learn.chatgpt.com/docs/dots/channels`
- OpenAI, *Tasks and memory* — `https://learn.chatgpt.com/docs/dots/tasks-and-memory`
- OpenAI, *Connect computers and apps* — `https://learn.chatgpt.com/docs/dots/computers-and-apps`
- OpenAI, *Create your dot in the ChatGPT mobile app* (Oct 5–9 2026) — `https://learn.chatgpt.com/docs/whats-new/dots-october-9-2026`
- NeoTeo, *OpenAI adds mobile setup, Codex and Work tools to Dots* (2026-10-11)
- Grok Bot docs — `https://docs.x.ai/grok-bot/mobile`, `/bots`, `/chat-and-collaboration`, `/computer-and-apps`, `/files-and-results`, `/skills-routines-and-automations`, `/settings-and-notifications`, `/approvals-security-and-privacy`
- Grok Bot, *README* (feature list) — `https://github.com/grok-bot-app/grok-bot`
- Grok Bot on the App Store — `https://apps.apple.com/us/app/grok-bot/id6794501026`
