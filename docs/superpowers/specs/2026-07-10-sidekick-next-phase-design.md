# Sidekick next phase — agent runner, shared list, web-push nudges, learning layer

**Date:** 2026-07-10 · **Status:** approved design, pre-implementation
**Decided with:** Dalton (brainstorming session)

## Goals

1. Completed-task data compounds: the vault becomes a knowledge graph (Obsidian graph view) and richer ledger data enables stats and smarter nudging.
2. Claude can execute/advance tasks, triggered from the phone — research, plans, task breakdown.
3. Notifications reach the phone reliably (no Mac-awake dependency, no Beeper).
4. A shared task list Dalton's wife can use from her Android — and *only* that list.

## Non-goals

- Google Drive or any second storage system. The vault (git repo) stays the single source of truth.
- Rewriting existing, working pieces (sidekick.py engine, PWA dashboard, deploy).
- Multi-tenant generality. Exactly two humans: Dalton (full access) and wife (shared list only).

## Architecture

```
 Dalton (iPhone PWA + Siri shortcut) ─┐
 Wife (Android PWA, shared page only) ┼─ Tailscale ─► VPS ◄─► GitHub ◄─► Mac / claude.ai-code
 web push ◄───────────────────────────┘              │
                                        API (FastAPI, existing)
                                        pi agent runner (new)
                                        web-push nudger (new)
                                        git sync: push (existing) + pull timer (new)
```

The VPS (Hetzner, existing `server/` deployment behind Tailscale) gains three residents. The vault clone on the VPS remains the serving copy; the agent works in a **separate clone**.

## Sub-project 1 — Two-way git sync on the VPS *(build first)*

**Problem:** the VPS pushes after writes but never pulls, so pushes from the Mac, claude.ai/code, or the agent never reach the phones.

- A systemd timer (~3 min) runs a sync script: `git pull --rebase` on the serving clone.
- The pull must hold the same exclusivity as API writes. Mechanism: the API's write lock becomes a **file lock** (e.g. `flock` on `.sidekick-write.lock` in the vault) shared by both the API process and the sync script. The in-process `threading.Lock` is replaced/wrapped by this file lock.
- No regenerate step is needed after a pull: the API reads the feed directly from `tasks/` + `ledger.jsonl`, and generated artifacts (`sidekick-data.js`) arrive already-built in the pulled commits.
- Failure mode: pull conflict → log, leave repo clean (abort rebase), alert via nudger channel if it persists.

## Sub-project 2 — Shared list

**Identity & authorization (server):**
- `SIDEKICK_API_TOKEN` (Dalton, role `full`) is joined by a second token (wife, role `shared`). Config: a token→`{name, role}` map (env or config file).
- Role `shared` is enforced **server-side** on every endpoint:
  - `GET /feed` → only tasks with `shared: true` (and only shared-task ledger events, or an empty events list — her page doesn't need the game feed).
  - `POST /tasks` → forced `shared: true`, `from` set from token identity (never from the client).
  - `POST /tasks/{id}/complete` → 404 unless the task is shared.
  - Agent endpoints: `breakdown` allowed on shared tasks; `research` full-role only.
- Role `full` (Dalton) sees everything, unchanged.

**Task frontmatter (code-written only, via sidekick.py):**
- `from:` — `dalton | wife | sidekick` (who created it).
- `shared: true` — membership in the shared list. Absent = personal.

**PWA:**
- New route **/shared**: a plain checkbox list of shared tasks — add box at top, tick to complete, a "break it down" button per task. Mobile-first, minimal.
- After token entry, the app asks the server for the token's role (`GET /me` or role piggybacked on `/feed`) and routes: role `shared` → /shared only (no dashboard, no other routes render); role `full` → full app including /shared.
- UI hiding is convenience; the API enforcement above is the security boundary.

**Wife's device:** Tailscale Android app joined to the tailnet (free tier covers 3 users), PWA installed, her token pasted once.

**Siri capture (Dalton):** an iOS Shortcut that POSTs `{title, category}` to `/api/tasks` with his Bearer token over Tailscale. Documented in the repo (`docs/`), no server change needed.

## Sub-project 3 — Agent runner (pi headless on the VPS)

**Runtime:** [pi](https://pi.dev) installed on the VPS. Auth: copy `~/.pi/agent/auth.json` from the Mac (Claude Pro/Max + OpenAI/Codex OAuth tokens; they auto-refresh). Billed to existing subscriptions, no API key.

**API:**
- `POST /tasks/{id}/agent` body `{action: "research" | "breakdown"}` → enqueue job, return job id. Idempotency-Key honored.
- `GET /agent/jobs` and `GET /agent/jobs/{id}` → status (`queued | running | done | failed`) + result summary/tail of log.

**Execution:**
- Jobs run strictly one at a time (queue, single worker).
- Runs as a dedicated low-privilege user in a **separate vault clone** (`~/agent/sidekick`), never the serving clone.
- Job = `pi -p "<prompt>"` (print mode) with a prompt template per action, cwd = agent clone, timeout (e.g. 15 min), log captured to a per-job file.
- **research**: follow CLAUDE.md orchestrator rules — read `wiki/_index.md`, grep `wiki/`, research (pi web tools), write `raw/<date>-<slug>.md`, fold into `wiki/<topic>.md`, run `sidekick wiki`, compose plan JSON, `sidekick set-plan <id>`.
- **breakdown**: split the task into sub-tasks via `sidekick new` (each `from: sidekick`; inherits `shared: true` when the parent is shared), then set a short plan on the parent linking the children.
- On success: commit + push from the agent clone (its own deploy key or the host's). The sync timer (sub-project 1) delivers results to the serving clone and phones within minutes.
- On failure: job marked failed with log tail; agent clone reset to clean state (`git reset --hard && git clean -fd`).

**PWA:** "Ask Sidekick" button on task detail (role `full`) → research; "break it down" on shared list (both roles) → breakdown. Job status shown by polling `GET /agent/jobs/{id}`.

**Fallback surface:** the GitHub repo stays connected to claude.ai/code for heavy interactive sessions from the phone; no build required.

**Integrity rules (unchanged):** the agent never writes `ledger.jsonl` or `sidekick-data.js` by hand; all mutations go through `sidekick.py` commands.

## Sub-project 4 — Web-push nudges from the VPS

- Nudge decide logic ported from `nudge.py` into a server-side module + daily systemd timer (09:00 Europe/Copenhagen). Beeper + launchd path retired (`nudge.py` kept as documented offline fallback).
- Message wording: try `pi -p` with a cheap model (same judgment prompt as today); **any** failure falls back to the deterministic message (longest-sitting task with a plan → its first step). Silent when nothing is genuinely stalled (same `min_sat_hours` knob).
- Delivery: Web Push — VAPID keypair, `pywebpush`, `POST /push/subscribe` (stores subscription per token identity), service-worker `push` handler + `Notification` display in the PWA.
- Routing: Dalton gets all nudges. Wife receives no push notifications in this phase; a "new shared task added" ping is explicitly deferred.
- iOS constraint: push only works for the *installed* (Home-Screen) PWA — already how Dalton runs it. Android: native support.

## Sub-project 5 — Learning layer

- **Bootstrap `wiki/` + `raw/`** on first agent run (code already no-ops if absent; the agent creates them).
- **Richer ledger via `complete`:** optional `--note "<what worked/what happened>"` and `--via cli|phone|agent`. Server passes `via=phone` (or `agent`). New optional JSONL fields: `note`, `via`, `from`. Append-only format is naturally forward-compatible; readers must tolerate missing fields.
- **Graph growth:** task bodies and plans use `[[wikilinks]]` to wiki topics; wiki topics interlink. Obsidian graph view over the vault is the visualization — no new tooling.
- **Stats:** `regenerate` computes aggregates into `sidekick-data.js`: completions by category, median `sat_for_hours`, day-of-week/time-of-day completion histogram, current streak. Dashboard + PWA render a stats panel. Deterministic code only. (Later, day-of-week data can inform nudge timing — out of scope now.)

## Build order

1. Two-way git sync (unblocks everything; smallest).
2. Shared list: tokens/roles → frontmatter fields → API enforcement → PWA /shared → wife's device setup.
3. Agent runner (pi install/auth → queue+endpoints → prompt templates → PWA buttons).
4. Web-push nudges.
5. Learning layer (ledger fields + stats; wiki growth is usage, not code).

Each sub-project is independently shippable and lands with tests in the existing suites (`tests/` unittest, `server/tests/` pytest, `web/` Vitest/Playwright).

## Error handling & honest limits

- Agent jobs consume Claude/Codex subscription quota; the queue is single-worker to bound spend and load on the CX23.
- pi on the VPS has shell access on that box: mitigated by dedicated low-privilege user, separate clone, no access to the serving clone or API secrets.
- Web push delivery is best-effort (OS-level throttling); the nudge is a nudge, not an alarm.
- Wife's page depends on Tailscale being connected on her phone; if that proves annoying, revisit Tailscale Funnel for the single /shared page (explicitly deferred).
- Pull-rebase conflicts on the VPS abort cleanly and are logged; the vault is never left mid-rebase.
