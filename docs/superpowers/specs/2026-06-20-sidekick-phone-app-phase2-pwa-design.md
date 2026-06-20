# Sidekick Phone App — Phase 2: the SvelteKit PWA

**Date:** 2026-06-20
**Status:** Approved (design), pending implementation plan
**Scope:** Build the front end of the phone app — a mobile-first, installable SvelteKit PWA that reads the dashboard from the Phase 1 host API and adds the two actions the file-based dashboard can't do: **complete** a task and **capture** a new one. The app reaches the API **same-origin via a proxy** (Vite in dev, Caddy in prod), so no CORS and **no change to the Phase 1 backend**. The "game brain" (levels, branches, recent log) from `sidekick-render.js` is ported into the app and computed client-side from the raw feed. Builds on the merged Phase 1 (host engine + API). Phase 3 (offline write-queue, Capacitor native, nudge relocation) and Phase 4 (Mac Obsidian-Git) remain separate later work.

---

## 1. Why

Phase 1 delivered the always-on host API (`GET /feed`, `POST /tasks`, `POST /tasks/{id}/complete`) but no UI — opening it in a browser yields JSON/401. The existing `sidekick.html` is a static, read-only, file-based dashboard that can't act on tasks and isn't connected to the API. Phase 2 is the surface the user actually sees and touches: a real app, installable on the iPhone home screen, that renders the same dashboard and lets the user complete and capture tasks on the go against the live API.

## 2. Goals / non-goals

**Goals**
- A **SvelteKit** PWA, mobile-first, **installable on iPhone** (Add to Home Screen), self-contained in a new `web/` directory.
- Renders the full dashboard the existing `sidekick-render.js` produces — hero level + ring, open tasks with prepared plans, the 5 branches, recent-cleared log — visually matching today's dashboard, adapted to mobile.
- **Complete** a task and **capture** a new task against the live API, with optimistic UI and an idempotency key per write.
- Reaches the API **same-origin via a proxy** — Vite dev proxy and Caddy in prod — so there is **no CORS and no change to the Phase 1 backend**.
- The level/branch/log derivation is **computed client-side** from the raw `{events, active}` feed (scoring stays derived-at-read-time; the backend keeps serving only raw data).
- Opens offline: a service worker caches the app shell + last feed.

**Non-goals (YAGNI)**
- No change to the Phase 1 API, `sidekick.py`, the ledger, the wiki, or `sidekick.html`. The backend is consumed as-is.
- No offline **write** queue in v1 (the app opens offline and shows last-known state, but completing/capturing needs a connection). The IndexedDB outbox stays parked (Phase 3).
- No Capacitor native build in v1 (the app is built to be Capacitor-wrappable later, but that's Phase 3).
- No `set-plan`/research from the app — planning stays a Mac/orchestrator job (the API exposes no such endpoint).
- No multi-user/auth provider — single-user bearer token, entered once.
- No server-side rendering — the app is a static SPA/PWA (`adapter-static`), served as files.

## 3. Locked decisions

| Decision | Choice |
|---|---|
| Framework | SvelteKit + Vite, `adapter-static` (static SPA/PWA, no SSR) |
| PWA tooling | `vite-plugin-pwa` (manifest + service worker) |
| API access | Same-origin via proxy — app calls relative `/api/*`; Vite proxies in dev, Caddy in prod. No CORS; backend untouched. |
| Repo layout | New self-contained `web/` directory (own `package.json`, Node/npm toolchain) |
| Scoring/derivation | Client-side, ported from `sidekick-render.js` (raw feed in, levels/branches out) |
| Visual | Port the existing `sidekick.html` aesthetic (design tokens, ring, cards), mobile-first |
| Auth | Single-user bearer token, entered in Settings, stored in `localStorage`; sent as `Authorization: Bearer <token>` |
| Writes | Optimistic UI; client-generated `Idempotency-Key` (`crypto.randomUUID()`) per POST |
| Offline | Service worker caches shell + last feed (read-only offline); no write queue in v1 |

## 4. Architecture

```
  iPhone / browser                         proxy layer                      Phase 1 host API (unchanged)
  ┌──────────────────────────┐                                            ┌───────────────────────────┐
  │ SvelteKit PWA (web/)      │   GET  /api/feed                          │ GET  /feed                 │
  │  - Dashboard (game brain) │── POST /api/tasks ──► dev: Vite proxy ──► │ POST /tasks                │
  │  - Capture / Complete     │   POST /api/tasks/   prod: Caddy          │ POST /tasks/{id}/complete  │
  │  - Settings (token)       │        {id}/complete  (strip /api)        │ (bearer auth, git publish) │
  │  - service worker cache   │   Authorization: Bearer <token>           └───────────────────────────┘
  └──────────────────────────┘
       client-side: levels / branches / recent log derived from raw {events, active}
```

- The app only ever calls **relative `/api/*`**. The proxy (Vite in dev, Caddy in prod) strips `/api` and forwards to the host API. Same-origin → no CORS, no backend change.
- The app holds the bearer token (localStorage) and attaches it to every request.
- The dashboard's level/branch/log numbers are derived in the browser from the raw feed — the backend never computes scoring.

## 5. Components

### 5.1 `web/` — the SvelteKit project (toolchain)
- A self-contained SvelteKit app: `web/package.json`, `web/svelte.config.js` (`@sveltejs/adapter-static`, SPA fallback `index.html`), `web/vite.config.*` (with `vite-plugin-pwa` and a dev proxy for `/api`).
- Node/npm toolchain (Node 20+ is available). Nothing outside `web/` is disturbed; `sidekick.py`, `server/`, and `sidekick.html` are untouched.
- A `web/.gitignore` for `node_modules/`, `build/`, and PWA-generated artifacts.

### 5.2 The game-brain module (`web/src/lib/game.ts`)
- A direct, tested port of the pure logic in `sidekick-render.js`: the `BRANCHES` predicate table (diplomat/pathfinder/hearthkeeper/loremaster/swift), `CAT_HUE`, the `progress(count, base, step)` level curve, `OVERALL_CURVE`/`BRANCH_CURVE`, `LEVEL_WORDS`, and the `fmtDate`/`dur`/`ago` formatters.
- Input: the raw `{events, active}` feed. Output: the derived view model (overall level/ring, per-branch levels, sorted recent log). Pure functions, unit-tested against the same expectations the current dashboard encodes.

### 5.3 Data layer / API client (`web/src/lib/api.ts`)
- Thin client over the relative API: `getFeed()`, `createTask(title, category)`, `completeTask(id, completedAt)`.
- Attaches `Authorization: Bearer <token>` (from the settings store) to every request and a fresh `Idempotency-Key: crypto.randomUUID()` to each POST.
- Maps responses: `401` → signal "token missing/invalid" (route to Settings); `4xx/5xx` with `{error}` → surface the message; network failure → "offline / can't reach the host".
- A small Svelte store holds the token + optional API base, persisted to `localStorage`.

### 5.4 Screens
- **Dashboard** (`/`) — fetches `/api/feed`, derives via `game.ts`, renders hero level + animated ring, open-task cards (category hue, sat duration, prepared plan steps with `tel:`/external links), the 5 branches, and the recent-cleared log (top 7). Each open-task card carries a **Complete** control.
- **Capture** (`/new`) — title field + category picker (`phone|admin|errand|chore`) → `createTask` → return to Dashboard with the new task shown.
- **Complete** — the per-card control → `completeTask(id, nowISO())` with optimistic removal from the open list; on error, roll back and show the message; on success, refresh the feed.
- **Settings** (`/settings`) — paste the bearer token (+ optional API base URL), stored in `localStorage`. If no token is set, the app routes here first.

### 5.5 PWA shell
- `vite-plugin-pwa` generates the web app **manifest** (name, icons, `theme_color`, `display: standalone`) and a **service worker** that precaches the app shell and runtime-caches the last `/api/feed` response, so the app **opens offline** and shows last-known state.
- Installable on iPhone via Safari → Share → Add to Home Screen. The build remains Capacitor-wrappable (Phase 3) with no rewrite.

### 5.6 Dev & prod serving
- **Dev:** run the Phase 1 API (`uvicorn … --port 8000`), then `npm run dev` in `web/`; Vite serves the app and **proxies `/api` → `http://127.0.0.1:8000`** (stripping `/api`). Open the Vite URL in a browser — instant live app.
- **Prod:** `npm run build` produces static files in `web/build`; **Caddy** serves them and proxies `/api/*` → uvicorn (same host as Phase 1). Documented in `web/README.md`; provisioning is manual (like Phase 1).

## 6. Data flow

```
load: PWA --GET /api/feed--> API --> {events, active} --> game.ts derives --> render dashboard
                                          (service worker caches last feed for offline open)
capture: /new form --POST /api/tasks (Bearer + Idempotency-Key)--> API --> 201 --> refresh feed
complete: card control --POST /api/tasks/{id}/complete {completed_at}--> API --> 200 --> refresh feed
                         (optimistic: remove from open list immediately; roll back on error)
```

## 7. Error handling / edge cases
- **No token set / 401:** route to Settings with a clear "enter your token" message; never silently fail a write.
- **Offline / host unreachable:** the app opens from the service-worker cache and shows last-known state; write controls report "offline — needs a connection" (no queue in v1).
- **Optimistic write fails (4xx/5xx/network):** roll back the optimistic UI change and surface the API's `{error}` message; the feed is re-fetched to reconcile.
- **Stale feed then act:** completing an already-done/removed task → API is idempotent/`404`; the app refreshes and reconciles.
- **Bad category / empty title:** validated in the form before POST (and the API also returns `400`).
- **Git failure on the host (`409`):** surfaced as "couldn't publish to the host, try again" (Phase 1 returns `409 {error}` for this).

## 8. Testing
- **Game-brain unit tests (Vitest):** port-fidelity tests for `game.ts` — `progress()` curve at boundaries, branch predicates per category/orchestrator/swift, recent-log sort/limit, `dur`/`ago` formatting. Seed sample feeds and assert the derived view model.
- **Component tests (Vitest + Testing Library):** Dashboard renders level/branches/cards from a feed; Capture validates input; Complete triggers the optimistic path and rolls back on a stubbed error.
- **End-to-end (Playwright):** read → capture → complete against a **mock `/api`** (no real backend), asserting the optimistic UI and feed refresh.
- **PWA installability check:** manifest + service worker present in the build; app shell loads offline.
- The Phase 1 Python suites (`tests/`, `server/tests/`) are untouched and must stay green (the backend isn't modified).

## 9. Integrity & boundaries
- **The Phase 1 backend is consumed unchanged** — no CORS, no new endpoints, no edits to `sidekick.py`/`server/`. The proxy makes requests same-origin.
- **Scoring stays derived-at-read-time** — levels/branches/log are computed in the browser from the raw ledger feed, exactly as `sidekick-render.js` does today; the ledger remains the spine, written only by the host engine.
- **The app never touches the ledger or vault directly** — it only calls the API, which routes through the engine.
- **`web/` is self-contained** — a new toolchain in its own directory; the existing Python app and static dashboard are unaffected.

## 10. Out of scope / parked
Offline **write** queue (IndexedDB outbox); Capacitor native/App Store build; relocating the nudge to the host; push notifications; multi-user/sharing; a visual redesign beyond porting the current aesthetic; choosing/automating the prod host (manual, as in Phase 1). None block this design.
