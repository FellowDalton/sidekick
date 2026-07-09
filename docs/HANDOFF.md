# Sidekick — session handoff

**As of:** 2026-07-09 · `main` @ `8b44c67` (pushed to `origin/main`)
**Purpose:** Bring a fresh session up to speed. Read this, then `CLAUDE.md` (agent operating rules) and `README.md` (human overview).

> **Update 2026-07-09 — the phone app is now DEPLOYED and live.** Phase 4 is done: `server/` runs on an always-on Hetzner CX23 VPS (Falkenstein) behind a localhost Caddy router, reached privately over **Tailscale** with auto-HTTPS at `https://sidekick.tail81b55b.ts.net`. The PWA is installed on the iPhone and does live read/write/publish; the host pushes ledger commits to GitHub via a deploy key. Runbook + artifacts: `deploy/`. The "NOT deployed" notes below are historical. Obsidian Git (old Phase 4 item) was **dropped** — the user drives Sidekick via the app + Claude Code, not Obsidian; instead this Mac clone syncs by plain git (`git pull` before task work, `git push` after — see `CLAUDE.md`).

---

## 1. What Sidekick is

An ADHD execution-support system built as **one git-tracked vault** of markdown + a deterministic Python CLI. It solves the *doing* problem: the orchestrator (Claude) does the legwork and preps plans; a game-layer dashboard makes progress feel good; a daily nudge pushes one stalled task. Solo by design. No Google/OAuth/external API in the core.

**The load-bearing invariant:** levels/branches are *derived* from the raw `ledger.jsonl` at read time, never stored. `sidekick.py` is the **sole, append-only, code-only writer** of the ledger — no model reasoning is ever in that write path. Keep this true; everything else can change.

---

## 2. Current state (what's built & merged)

All of the following is on `main`, reviewed (subagent-driven dev + opus whole-branch review), and green.

| Area | What | Where | Status |
|---|---|---|---|
| **Original system** | Vault (`tasks/*.md` + `ledger.jsonl`), `sidekick.py` CLI, static `sidekick.html` dashboard, `chrome-extension/` new-tab, `nudge.py` | repo root | Pre-existing, working |
| **Layer 2 — reusable memory** | `raw/` (verbatim research archive) + `wiki/` (synthesized topic notes) + `sidekick wiki` (deterministic `wiki/_index.md` map-of-content) | `sidekick.py`, `tests/test_wiki.py` | **Done, merged.** Folders are created by the orchestrator at first use (code no-ops if absent) |
| **Phone app — Phase 1** | Always-on host **HTTP API** wrapping `sidekick.py`: `GET /feed`, `POST /tasks`, `POST /tasks/{id}/complete`; bearer auth; `Idempotency-Key` replay; write lock; git publish (union-merge ledger) | `server/` | **Done, merged. DEPLOYED** on the Hetzner VPS (systemd `sidekick`) |
| **Phone app — Phase 2** | Installable **SvelteKit PWA**: dashboard (game brain ported), Complete + Capture, Settings (token); same-origin via proxy (no CORS); offline-read service worker | `web/` | **Done, merged. DEPLOYED & installed on the iPhone** (served by Caddy behind `tailscale serve`) |
| **Phase 4 — deploy** | VPS bootstrap + systemd + localhost Caddy router + Tailscale front door; deploy key for host→GitHub pushes; unattended git on the Mac | `deploy/` | **Done, live.** See the 2026-07-09 update above |

**Tests (all green on `main`):** `tests/` → 11 (stdlib unittest) · `server/tests/` → 18 (pytest) · `web/` → 21 unit/component (Vitest) + 1 e2e (Playwright).

---

## 3. Architecture — the phone-app vision

The phone app keeps the **vault as the source of truth** but moves the engine to an always-on host so the phone works even when the Mac is asleep:

```
 iPhone (SvelteKit PWA, web/)                ALWAYS-ON HOST                      Mac (Obsidian editor)
  reads GET /api/feed          ── relative /api/* ──► sidekick.py + thin API ◄── git ──► GitHub remote ◄── git ──► Obsidian Git
  Complete / Capture (POST)       (Vite proxy dev /     (server/, SOLE ledger writer)        (canonical history)
  bearer token + Idempotency-Key   Caddy proxy prod)    commit → pull --rebase → push
  offline-read service worker
```

- **Same-origin via proxy** → no CORS, backend untouched. The PWA only ever calls relative `/api/*`.
- **Scoring derived client-side** in the PWA from the raw feed (ported from `sidekick-render.js`).
- **`ledger.jsonl` uses a git `union` merge driver** (`.gitattributes`) so concurrent appends (host + Mac) never conflict.

Design specs (read these for the *why*):
- `docs/superpowers/specs/2026-06-20-sidekick-phone-app-design.md` — the overall phone-app architecture (host + sync model).
- `docs/superpowers/specs/2026-06-20-sidekick-phone-app-phase2-pwa-design.md` — the PWA.
- `docs/superpowers/specs/2026-06-19-sidekick-wiki-reusable-memory-design.md` — the wiki loop.
- Matching implementation plans live in `docs/superpowers/plans/` (same dates/names).

---

## 4. How to run / test each piece

**Engine / wiki (Python, dep: `pyyaml`):**
```bash
python3 sidekick.py regenerate          # rebuild the dashboard feed
python3 sidekick.py wiki                # rebuild wiki/_index.md (no-op if no wiki/)
python3 -m unittest discover -s tests   # 11 tests
```

**Phase 1 host API (`server/`, deps: `server/requirements.txt` = fastapi, uvicorn):**
```bash
pip install -r server/requirements.txt -r server/requirements-dev.txt
SIDEKICK_VAULT=$(pwd) SIDEKICK_API_TOKEN=dev-token SIDEKICK_GIT_PUSH=0 \
  python3 -m uvicorn server.app:create_app --factory --port 8000 --workers 1
python3 -m pytest server/tests -q       # 18 tests
```
Env: `SIDEKICK_VAULT` (required), `SIDEKICK_API_TOKEN` (required), `SIDEKICK_GIT_PUSH` (default 1 — set 0 for local), `SIDEKICK_GIT_REMOTE` (default origin). **Single worker** — the write lock is per-process. See `server/README.md` for VPS/Caddy/TLS deploy.

**Phase 2 PWA (`web/`, Node 20 / npm):**
```bash
cd web && npm install
npm run dev        # Vite serves the app, proxies /api -> 127.0.0.1:8000 (run the API too)
npm test           # 21 vitest unit/component
npm run e2e        # 1 Playwright e2e (needs: npx playwright install chromium)
npm run build      # static SPA -> web/build (+ PWA manifest/sw.js)
```
To **see it**: run the API (above) + `npm run dev`, open the Vite URL, paste `dev-token` in Settings → live dashboard with working Complete/Capture. See `web/README.md` for the Caddy same-origin prod deploy + iPhone install.

---

## 5. What's next / parked (nothing blocking)

**Phase 3 (specced as out-of-scope, not built):**
- Offline **write** queue on the phone (IndexedDB outbox + replay) — v1 is offline-read only.
- **Capacitor** native wrapper for a real App Store app (the PWA is built to be wrappable).
- Relocate the **nudge** from Mac-launchd to host-cron (kills its "Mac must be awake at 9am" reliability hole).

**Phase 4 (deploy/integration — DONE 2026-07-09):**
- ✅ Host provisioned (Hetzner CX23, Falkenstein), `server/` runs under systemd behind a localhost Caddy router, exposed via `tailscale serve` (auto-HTTPS, tailnet-only). Bootstrap + runbook in `deploy/`.
- ✅ Reached from the iPhone over Tailscale; PWA installed to the home screen; live read/write/publish confirmed.
- ↳ **Obsidian Git was dropped** (the user doesn't use Obsidian). Mac clone syncs via plain git instead — pull before / push after task work; git is unattended (no Touch ID). See `CLAUDE.md`.
- Still parked from the original Phase 4: relocating the **nudge** to host-cron (still Mac-launchd).

**Known minor/cosmetic items (deliberately left; none block):**
- `wiki` malformed-frontmatter degrades title→stem (per spec §4.4; **decided** behavior, not a bug).
- `server` git_sync "nothing to commit" uses string-match (locale-fragile, English-Mac fine); on a *persistent* push failure a retried `POST /tasks` could create a duplicate task (local commit is kept per spec §8; single-user, low risk).
- `web` cosmetics: optimistic-complete rollback prepends the card instead of restoring position; `ago()` shows "just now" for sub-hour gaps (intentional, differs from legacy renderer); `goto("/")` not awaited in Capture; the `sidekick-feed` SW cache outlives a cleared token (low sev, single-user); `apiBase` in Settings is an intentional cross-origin escape hatch (blank = same-origin).
- A **HIGH XSS** (javascript: URI in a plan-step href) was found during Phase 2 and **fixed** (`safeHref` scheme allowlist + regression test in `web/src/routes/Dashboard.svelte`).

---

## 6. Conventions & gotchas for the next session

- **Workflow used here:** brainstorming → writing-plans → **subagent-driven-development** (fresh implementer per task, spec+quality review each, opus whole-branch review at the end) → finishing-a-development-branch. The superpowers skills drive this; follow the same loop for new work.
- **Branching:** never commit feature work directly on `main` — branch first (`feat/...`), then merge with **`--no-ff`** (matches repo history: `Merge feat/...: <summary>`). Verify tests **on the merged result** before deleting the branch (this caught a real `npm test` config bug post-merge).
- **Don't hand-edit generated files:** `ledger.jsonl` (only via `complete`), `sidekick-data.js`, `wiki/_index.md`. Don't put model logic in `sidekick.py`.
- **`web/` is self-contained** — adding the Node toolchain there didn't touch the Python app. The Phase 1 API is consumed by the PWA **unchanged** (no CORS).
- **Vitest scope:** `web/vite.config.ts` restricts `test.include` to `src/**` so Vitest doesn't try to run the Playwright e2e (`e2e/*.spec.ts`). The e2e runs only via `npm run e2e`.
- **SDD scratch** (`.superpowers/sdd/progress.md`, task briefs, reports, diffs) is git-ignored, per-session, and **not durable** — that's why this handoff exists. Don't rely on it surviving.
- Commit-message trailers used this session: `Co-Authored-By: Claude ...` + `Claude-Session: ...` (see recent `git log`).

---

## 7. Quick orientation commands

```bash
git log --oneline -15                      # recent history (wiki + Phase 1 + Phase 2 merges)
ls docs/superpowers/specs docs/superpowers/plans   # all design docs + plans
cat CLAUDE.md                              # agent operating rules (incl. the wiki loop)
cat server/README.md web/README.md         # run/deploy guides for the two new surfaces
```
