# Sidekick — phone app: an always-on host + SvelteKit PWA

**Date:** 2026-06-20
**Status:** Approved (design), future work — not yet scheduled
**Scope:** Turn the read-only local dashboard into a real, on-the-go iPhone app that can read the dashboard, **complete** tasks, and **capture** new ones from anywhere. Achieved by relocating the deterministic engine (`sidekick.py`) and the canonical vault onto a small always-on host that exposes a thin HTTP API, and by building a SvelteKit Progressive Web App (PWA) against that API. The Mac keeps editing the same Obsidian vault via Git. No change to the ledger's semantics, the determinism rule, or the wiki; the standalone `sidekick.html` keeps working.

---

## 1. Why

Today the dashboard is a static, snapshot-at-load HTML file (`sidekick.html`) that reads a Mac-local feed; the whole system is Mac-local by design (vault + `sidekick.py` + generated feed), and the nudge already depends on the Mac being awake. There is no way to act on tasks — complete or capture — away from the Mac. The goal is a phone app that is a *primary* surface (read + complete + capture on the go), available anywhere even when the Mac is asleep, **without** sacrificing the two load-bearing invariants of the project: the **Obsidian markdown vault as the source of truth** and the **deterministic, code-only, append-only `ledger.jsonl`**.

The resolution is to stop treating "the Mac" as the place truth lives and instead treat "**the vault repo**" as the place truth lives — and host that repo (and the engine that writes it) on a cheap always-on box. The Mac becomes an always-synced Obsidian editor via Git. This removes the Mac-awake limitation entirely (the engine is always up, so writes apply in near-real-time) while keeping the markdown format, the Obsidian workflow, and the deterministic spine intact — the spine simply runs on the host now.

## 2. Goals / non-goals

**Goals**
- A SvelteKit **PWA**, installable on iPhone (Add to Home Screen) and **Capacitor-wrappable** into a real App Store app later with no rewrite.
- The app can **read** the dashboard, **complete** a task, and **capture** a new task, from anywhere, even with the Mac asleep.
- The **vault (markdown + `ledger.jsonl`) stays the source of truth**, Obsidian-editable, just hosted on an always-on box and Git-synced to the Mac.
- The **deterministic spine is preserved**: `sidekick.py` remains the *sole writer* of the ledger; no model logic in the write path; the ledger stays append-only.
- The hosting is **backend/vendor-agnostic** — the only hard requirement is persistent storage. The concrete provider is chosen at build time, not in this spec.
- Reuse, don't reimplement: the host API wraps existing `sidekick.py` functions; the PWA reuses the existing `sidekick-render.js` render logic.

**Non-goals (YAGNI)**
- No reimplementation of `sidekick.py` logic in JavaScript. The phone never writes the vault or the ledger directly.
- No `set-plan` / research from the phone — planning is the Mac/orchestrator's job (the phone does read + complete + capture only).
- No multi-user / sharing — still solo by design; single-user auth only.
- No cloud as a *source of truth*; the cloud/host holds the canonical *vault repo*, but authority is the markdown+ledger format, not a foreign database schema.
- No phone-side offline write queue **in v1** (the app *opens* offline via cached shell, but writes need the host). The offline outbox is an explicit phase-3 enhancement.
- No change to `ledger.jsonl` event schema, the wiki, the dashboard feed shape, or `sidekick.html`.

## 3. Locked decisions (from brainstorming)

| Decision | Choice |
|---|---|
| App role | Full two-way: read dashboard + complete + capture |
| Availability | Always-on (Mac may be asleep); engine hosted off the Mac |
| Source of truth | The vault repo (markdown + `ledger.jsonl`), Obsidian-format |
| Where truth lives physically | An always-on host (Hetzner VPS recommended; free tier only if it offers persistent storage) |
| Engine location | `sidekick.py` + thin HTTP API run on the host; sole ledger writer |
| Mac ↔ host sync | **Git** via the Obsidian Git plugin; canonical history = the existing GitHub remote |
| Phone framework | **SvelteKit** PWA; Capacitor-ready for a native build later |
| Cloud "relay/inbox" | Collapses into the host's always-on API (synchronous apply; no queue-until-wake) |
| Auth | Single-user bearer token; host behind HTTPS |

## 4. Architecture

```
  iPhone (SvelteKit PWA)            ALWAYS-ON HOST (Hetzner/other)             Mac (Obsidian editor)
  ┌─────────────────────┐          ┌──────────────────────────────┐         ┌──────────────────────┐
  │ GET  /feed          │◀───────▶ │  thin HTTP API (FastAPI/etc.) │         │ Obsidian Git plugin  │
  │ POST /tasks         │  HTTPS   │      │                         │         │   auto commit/pull   │
  │ POST /tasks/:id/    │  +token  │      ▼                         │         └─────────┬────────────┘
  │      complete       │          │  sidekick.py (SOLE ledger      │                   │ git
  └─────────────────────┘          │  writer) + regenerate         │                   │
        ▲  service worker          │      │                         │                   ▼
        │  caches shell + feed     │      ▼  per write: lock →       │            ┌─────────────┐
        │                          │  commit → pull --rebase → push │◀──────────▶│ GitHub remote│
        └──────────────────────────│         (canonical clone)      │   git      │ (canonical   │
                                    └──────────────────────────────┘            │   history)   │
                                                                                 └─────────────┘
```

Three loosely-coupled pieces around the unchanged spine:

1. **The host engine + API** — wraps `sidekick.py` over HTTP; the only writer of the vault/ledger; commits and pushes every change to the canonical Git remote.
2. **Git as the sync fabric** — the GitHub remote is canonical history; the host's working clone and the Mac's Obsidian vault are both clones that pull/push it.
3. **The SvelteKit PWA** — installable iPhone app; reads the feed, completes and captures via the API.

The phone never touches the vault or the ledger directly; it calls a small API, and the host applies changes deterministically.

## 5. Components

### 5.1 The host engine + HTTP API
- A thin web service (e.g. FastAPI or Flask — chosen at build time; FastAPI recommended for typed request models) that imports and calls the **existing** `sidekick.py` functions. No business logic is duplicated in the web layer.
- **Endpoints** (see §7 for full contract):
  - `GET /feed` → the read-model `{events, active}` (the same payload the dashboard already consumes as `window.SIDEKICK`), as JSON.
  - `POST /tasks` → `create_task(title, category)`.
  - `POST /tasks/{id}/complete` → `complete(id, completed_at?)`.
- **Write discipline (every mutating request):**
  1. Acquire a process-wide **write lock** (writes are serialized — single-user, low volume, so a simple in-process lock or single worker suffices).
  2. Check the **idempotency key** (request header `Idempotency-Key`): if already applied, return the prior result without re-applying.
  3. Call the `sidekick.py` function, which writes the vault/ledger and runs `regenerate`.
  4. `git add -A && git commit` with a machine message (e.g. `api: complete <id>`), then `git pull --rebase` and `git push` to the canonical remote. On a transient non-fast-forward, retry the pull-rebase-push a bounded number of times.
  5. Release the lock; return the updated entity (and the refreshed feed, optionally).
- **`complete()` extension:** add an optional `completed_at` parameter so a phone-supplied tap timestamp is honored (keeping `sat_for_hours` and the timeline honest even if the request is applied a moment later). Default remains `now_iso()` when omitted — backward compatible with the CLI.
- **Boundary:** the API is the *only* network-exposed surface; it touches the vault solely through `sidekick.py`. It never writes `ledger.jsonl` except via `complete()`. No model reasoning anywhere in it.

### 5.2 Git as the sync fabric
- **Canonical history** = the existing GitHub remote (`origin`). Both the host's working clone and the Mac's Obsidian vault are clones of it.
- **Ledger conflict-freedom:** a `.gitattributes` entry sets a **union merge** driver on `ledger.jsonl` so concurrent appends from host and Mac merge by keeping both lines, never conflicting. (Append-only + union merge = the log can only grow; line order is by merge but every event is preserved — acceptable because levels/branches are *derived* from the full event set, order-independent.)
- **Task-file independence:** one markdown file per task means edits to different tasks never conflict; same-task concurrent edits are rare for a solo user and resolve as normal Git conflicts (surfaced in Obsidian Git).
- The host commits/pushes on every write; the Mac's Obsidian Git plugin is configured to auto-pull and auto-commit/push on an interval so Obsidian edits propagate and host changes appear.

### 5.3 The SvelteKit PWA
- **Reads** `GET /feed` and renders the dashboard. The existing `sidekick-render.js` logic (level/branches/open-tasks/recent-log) is ported into Svelte components — same visual model, now reactive.
- **Actions:** a **Complete** control on each open task (optimistic UI; sends `POST /tasks/{id}/complete` with the tap timestamp and an idempotency key), and a **Capture** form (title + category picker over `phone|admin|errand|chore` → `POST /tasks`).
- **Installable PWA:** web app manifest (name, icons, theme, `display: standalone`) + a service worker that **caches the app shell and the last fetched feed**, so the app *opens* offline and shows last-known state. Built with `vite-plugin-pwa` (SvelteKit integration).
- **Native later:** the same build is wrappable with **Capacitor** for a real App Store app — no rewrite. Documented as a future option, not built here.
- **Offline writes (phase 3, parked):** an optional IndexedDB **outbox** that queues complete/capture actions when offline and flushes them on reconnect; idempotency keys make replay safe. Not in v1.

### 5.4 Auth & transport security
- **Single-user bearer token**: a secret stored in the host config and entered once into the PWA (kept in the app's local storage); sent as `Authorization: Bearer <token>` on every request. Requests without a valid token are rejected (401).
- **HTTPS required**: terminate TLS at the host (Caddy or Traefik with Let's Encrypt on a VPS; free-tier platforms typically provide TLS). The token must never travel over plaintext.
- Task data is personal but low-sensitivity; provider-default encryption-at-rest is assumed. Client-side/end-to-end encryption is parked (§13).

### 5.5 The Mac as a sync client
- Install the **Obsidian Git** community plugin; point the vault at the canonical remote; enable auto-pull and auto-commit/push on an interval.
- The Mac no longer runs the engine for the phone's sake; `sidekick.py` can still be run locally for ad-hoc CLI use, but the **host** is the authoritative writer. (If both write simultaneously, Git + the union-merge ledger reconcile.)

## 6. Data flow

```
CAPTURE (phone):  PWA --POST /tasks--> host: create_task -> regenerate -> commit/push
                                              │
COMPLETE (phone): PWA --POST /complete--> host: complete(id, tapped_at) -> ledger += event
                                              │                            -> regenerate -> commit/push
                                              ▼
                                    canonical GitHub remote
                                       ▲                 │ git pull (Obsidian Git)
                       git push        │                 ▼
                  ┌──────────────┐     │          ┌──────────────┐
   Obsidian edit ─► Mac vault    ├─────┘          │ host clone   ├──► GET /feed ──► PWA renders
                  └──────────────┘                └──────────────┘
```

Reads are "latest published feed" (regenerated on every host write, so effectively live). Writes apply synchronously on the always-on host. The Mac sees everything via Git pull; Obsidian edits flow back via Git push.

## 7. API contract

All requests require `Authorization: Bearer <token>`. Mutations require an `Idempotency-Key` header (a client-generated UUID) for safe retries. Responses are JSON.

- **`GET /feed`** → `200 {"events": [...], "active": [...]}` — identical shape to `window.SIDEKICK`. `events` are ledger events; `active` are open tasks (id, task, category, sat_for_hours, plan).
- **`POST /tasks`**
  - body: `{"title": "<string>", "category": "phone|admin|errand|chore"}`
  - → `201 {"id": "<task-id>", "task": "<title>", "category": "...", "sat_for_hours": 0, "plan": null}`
  - `400` on missing/invalid category.
- **`POST /tasks/{id}/complete`**
  - body: `{"completed_at": "<ISO8601>"}` (optional; defaults to server `now`)
  - → `200 {"id": "<id>", "status": "done", "completed_at": "...", "sat_for_hours": <int>}`
  - `404` if the id is unknown; idempotent — re-sending the same `Idempotency-Key` (or completing an already-done task) returns the prior result, never a second ledger event.
- **Errors:** `401` (bad/absent token), `409` (write-lock timeout / unresolved git conflict — client may retry), `5xx` (host error). All error bodies: `{"error": "<message>"}`.

## 8. Error handling / edge cases
- **Mac asleep:** irrelevant — the host is always up; writes apply immediately and reach the Mac on its next Git pull.
- **Stale phone read then act:** completing a task that's already done (or deleted) → `complete` is idempotent / `404`; no duplicate ledger event. The phone refreshes the feed after any action.
- **Concurrent host write + Mac Obsidian edit:** Git reconciles. `ledger.jsonl` uses union merge (no conflict). Same-task file edits may conflict → surfaced by Obsidian Git for manual resolution (rare for a solo user).
- **Non-fast-forward on host push:** the host does `pull --rebase` then re-pushes, bounded retries; on persistent failure it returns `409` and leaves the local commit (next write or the periodic reconcile pushes it). The ledger write already succeeded locally and is never lost.
- **Network retry / double-submit from the phone:** idempotency keys make complete/capture safe to replay.
- **Bad token / no token:** `401`, no side effects.
- **Phone offline:** the PWA opens from cache and shows last-known feed; write controls indicate "offline — will need connection" (v1) or queue to the outbox (phase 3).
- **Host disk loss:** the canonical history is on the GitHub remote and mirrored on the Mac clone; rehydrate the host by re-cloning. (This is why persistent storage is required but not *sufficient* alone — Git redundancy is the real backstop.)

## 9. Hosting requirements
- **Hard requirement: persistent storage** for the vault clone (the canonical data lives here between restarts). Ephemeral-filesystem free tiers are unsuitable unless they attach a persistent volume.
- **Recommended:** a small **Hetzner VPS** (≈€4/mo, persistent disk, full control, easy TLS via Caddy). A free tier (Fly.io with a volume, Oracle Cloud Always-Free VM, etc.) is acceptable if it provides real persistent storage and doesn't sleep.
- **Vendor-agnostic:** nothing in the design binds to a specific provider; the only couplings are "runs Python," "persistent disk," "reachable over HTTPS," and "can run a Git client."
- Runtime needs: `python3` + `pyyaml` (the existing dep) + the chosen web framework, a Git client, and a TLS reverse proxy.

## 10. Build phases (each becomes its own implementation plan)
1. **Host engine + API** — wrap `sidekick.py` in the web service; add the `complete(completed_at?)` param; write lock + idempotency; Git automation (`.gitattributes` union-merge ledger, commit/pull-rebase/push); bearer-token auth; TLS. *The backbone; testable on its own against a throwaway vault + remote.*
2. **SvelteKit PWA** — port `sidekick-render.js` into components; read/complete/capture against the API; manifest + service worker (installable, opens offline). *Delivers the iPhone app.*
3. **Optional/parked** — phone offline outbox (IndexedDB); Capacitor native build; relocate the nudge from Mac-launchd to host-cron (kills the "Mac awake at 9am" hole).
4. **Mac setup** — install/configure Obsidian Git against the canonical remote (auto pull/commit/push).

## 11. Testing strategy
- **Host API (phase 1):** integration tests that run the service against a **throwaway vault + a throwaway bare Git remote** (mirroring the existing `SIDEKICK_VAULT` subprocess test style). Assert: `POST /tasks` creates a file + appears in `/feed`; `POST /complete` appends exactly one ledger event; **idempotency** (same key → one event); a commit is created and pushed; auth rejects missing/invalid tokens.
- **Git union-merge:** a test that simulates two divergent ledger appends and merges them, asserting both events survive and the file stays valid JSONL.
- **PWA (phase 2):** component tests (Vitest) for the render/port; a small Playwright e2e for read → complete → capture against a mock API; a Lighthouse/PWA-installability check (manifest + service worker present, offline open works).
- **No change** to the existing `tests/` (regenerate, wiki) — they must stay green.

## 12. Integrity & boundaries
- **The deterministic spine is preserved, relocated.** `sidekick.py` is still the sole writer of `ledger.jsonl`; the append is still code-only and append-only; no model reasoning enters the write path. The host is just where that code now runs.
- **Levels/branches stay derived** from the raw ledger at read time — never stored — so union-merge line ordering of the ledger is safe (scoring is order-independent over the event set).
- **The vault remains the source of truth** in its existing Obsidian markdown form; Git is the only sync mechanism; the GitHub remote is the canonical backstop.
- **The phone is never in the write path of the ledger** — it submits intents to an API; the host's code does the writing.
- **Unchanged:** `ledger.jsonl` schema, the wiki (`sidekick wiki`), the dashboard feed shape, and the standalone `sidekick.html`.

## 13. Out of scope / parked
A native App Store build (Capacitor — designed-for but not built); a phone-side offline write outbox; relocating the nudge to the host; end-to-end/client-side encryption of vault data; multi-user or wife-facing features; automatic conflict-resolution UI beyond what Obsidian Git provides; choosing the concrete hosting vendor (deferred to build time). None block this design.
