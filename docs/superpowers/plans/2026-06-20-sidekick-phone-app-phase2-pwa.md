# Sidekick Phone App — Phase 2: SvelteKit PWA — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mobile-first, installable SvelteKit PWA in `web/` that reads the dashboard from the Phase 1 host API and lets the user complete and capture tasks, reaching the API same-origin via a proxy (no CORS, backend untouched).

**Architecture:** A self-contained SvelteKit static-SPA (`adapter-static`, `ssr=false`) in `web/`. The "game brain" from `sidekick-render.js` is ported to a pure TS module and computed client-side from the raw `{events, active}` feed. A thin API client calls relative `/api/*` (Vite proxies in dev, Caddy in prod) with a bearer token from `localStorage` and an `Idempotency-Key` per write. `vite-plugin-pwa` adds the manifest + service worker (installable, opens offline).

**Tech Stack:** SvelteKit 2 + Svelte 5 + Vite + `@sveltejs/adapter-static` + `vite-plugin-pwa`; TypeScript; Vitest + `@testing-library/svelte` + jsdom (unit/component); Playwright (e2e). Node 20 / npm 11 (present).

## Global Constraints

- **No change to the Phase 1 backend** — `sidekick.py`, `server/`, `tests/`, `server/tests/`, `ledger.jsonl`, the wiki, and `sidekick.html` are untouched. The app consumes the API as-is.
- **Same-origin via proxy** — the app calls only relative `/api/*`; the proxy (Vite dev / Caddy prod) strips `/api` and forwards to the host API. No CORS code anywhere.
- **Scoring is derived client-side** — levels/branches/log are computed in the browser from the raw feed (ported from `sidekick-render.js`); the backend serves only raw `{events, active}`.
- **Auth** — single-user bearer token, entered in Settings, stored in `localStorage`, sent as `Authorization: Bearer <token>`; every POST also sends `Idempotency-Key: crypto.randomUUID()`.
- **Category set is exactly** `phone | admin | errand | chore`.
- **Offline** — service worker caches the app shell + last feed (read-only offline); **no write queue in v1** (parked, Phase 3).
- **Static SPA** — `adapter-static` with SPA fallback `index.html`, `ssr=false`, no server-side code.
- **Self-contained** — everything lives under `web/`; nothing outside `web/` changes except a one-line pointer added to the root `README.md` (Task 10).
- **Branch rules / curves (verbatim from `sidekick-render.js`):** branches diplomat(`phone|admin`), pathfinder(`errand`), hearthkeeper(`chore`), loremaster(`orchestrator` truthy), swift(`sat_for_hours != null && <= 2`); `OVERALL_CURVE = {base:4, step:2}`, `BRANCH_CURVE = {base:2, step:1}`.

---

## File Structure (all under `web/` unless noted)

- `package.json`, `svelte.config.js`, `vite.config.ts`, `tsconfig.json`, `.gitignore`, `vitest-setup.ts` — toolchain/config.
- `src/app.html` — shell; `src/app.css` — ported design tokens + component styles.
- `src/routes/+layout.js` — `ssr=false`/`prerender=false`; `src/routes/+layout.svelte` — nav + token gate.
- `src/routes/+page.svelte` — Dashboard; `src/routes/new/+page.svelte` — Capture; `src/routes/settings/+page.svelte` — Settings.
- `src/lib/types.ts` — shared types; `src/lib/game.ts` (+ `game.test.ts`) — the game brain.
- `src/lib/settings.ts` — token store; `src/lib/api.ts` (+ `api.test.ts`) — API client.
- `static/icon-192.png`, `static/icon-512.png` — PWA icons.
- `e2e/app.spec.ts`, `playwright.config.ts` — e2e.
- `web/README.md` — run/deploy doc. Root `README.md` — one-line pointer (Task 10).

---

## Task 1: Scaffold the SvelteKit static-SPA + toolchain + ported styles

**Files:** Create `web/package.json`, `web/svelte.config.js`, `web/vite.config.ts`, `web/tsconfig.json`, `web/.gitignore`, `web/vitest-setup.ts`, `web/src/app.html`, `web/src/app.css`, `web/src/routes/+layout.js`, `web/src/routes/+layout.svelte`, `web/src/routes/+page.svelte` (placeholder), `web/src/lib/smoke.test.ts`.

**Interfaces:**
- Produces: a building SvelteKit app (`npm run build` succeeds) with Vitest wired (`npm test` runs). `+layout.js` exports `ssr=false`, `prerender=false`. `app.css` exposes the design tokens (`--ink`, `--bone`, `--brass`, `--h-*` hues, `--display/--sans/--mono`).

- [ ] **Step 1: Create `web/package.json`**

```json
{
  "name": "sidekick-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite dev",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "check": "svelte-check --tsconfig ./tsconfig.json",
    "e2e": "playwright test"
  },
  "devDependencies": {
    "@sveltejs/adapter-static": "^3.0.0",
    "@sveltejs/kit": "^2.5.0",
    "@sveltejs/vite-plugin-svelte": "^4.0.0",
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/svelte": "^5.2.0",
    "@playwright/test": "^1.45.0",
    "jsdom": "^25.0.0",
    "svelte": "^5.0.0",
    "svelte-check": "^4.0.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vite-plugin-pwa": "^0.20.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 2: Create the config files**

`web/svelte.config.js`:
```js
import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ fallback: "index.html" }) // SPA fallback
  }
};
```

`web/vite.config.ts`:
```ts
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, "")
      }
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest-setup.ts"]
  }
});
```

`web/tsconfig.json`:
```json
{
  "extends": "./.svelte-kit/tsconfig.json",
  "compilerOptions": {
    "allowJs": true,
    "checkJs": true,
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "sourceMap": true,
    "strict": true,
    "moduleResolution": "bundler"
  }
}
```

`web/.gitignore`:
```
node_modules/
/build/
/.svelte-kit/
/dev-dist/
/test-results/
/playwright-report/
.DS_Store
```

`web/vitest-setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// SvelteKit's $app/environment is not provided by Vitest — stub it so modules
// that import `browser` work in tests.
vi.mock("$app/environment", () => ({ browser: true, dev: true, building: false }));
```

- [ ] **Step 3: Create the app shell, SPA layout config, and a placeholder page**

`web/src/app.html`:
```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="theme-color" content="#15171F" />
    %sveltekit.head%
  </head>
  <body data-sveltekit-preload-data="hover">
    <div style="display: contents">%sveltekit.body%</div>
  </body>
</html>
```

`web/src/routes/+layout.js`:
```js
export const ssr = false;        // pure client-rendered SPA
export const prerender = false;
```

`web/src/routes/+layout.svelte`:
```svelte
<script>
  import "../app.css";
  let { children } = $props();
</script>

<div class="wrap">
  {@render children()}
</div>
```

`web/src/routes/+page.svelte` (placeholder, replaced in Task 4):
```svelte
<h1>Sidekick</h1>
```

- [ ] **Step 4: Create `web/src/app.css` (ported design tokens + component styles)**

```css
:root{
  --ink:#15171F; --ink-raised:#1B1E29; --ink-inner:#212533;
  --bone:#EAE3D2; --bone-dim:#8E8B7C; --bone-faint:#5E5C53;
  --brass:#C9A24B; --brass-soft:#E7C46A;
  --line:rgba(234,227,210,0.10); --line-soft:rgba(234,227,210,0.06);
  --h-diplomat:#8FB3D9; --h-pathfinder:#9CB86F; --h-hearthkeeper:#D99B5A; --h-loremaster:#A98FD9; --h-swift:#6FC9C0;
  --display:"Iowan Old Style",Palatino,"Palatino Linotype",Georgia,serif;
  --sans:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Menlo,Consolas,monospace;
}
*{ box-sizing:border-box; }
html,body{ margin:0; }
body{
  background:radial-gradient(1200px 700px at 70% -10%, rgba(201,162,75,0.06), transparent 60%), var(--ink);
  color:var(--bone); font-family:var(--sans); line-height:1.5; -webkit-font-smoothing:antialiased;
  padding:clamp(16px,5vw,40px);
}
.wrap{ max-width:680px; margin:0 auto; }
a{ color:var(--brass-soft); }

.nav{ display:flex; gap:8px; margin-bottom:24px; }
.nav a{ font-family:var(--mono); font-size:12px; letter-spacing:.06em; text-transform:uppercase;
  color:var(--bone-dim); text-decoration:none; padding:8px 12px; border:1px solid var(--line); border-radius:999px; }
.nav a.active{ color:var(--brass-soft); border-color:color-mix(in srgb,var(--brass) 40%,transparent); }

.hero{ display:flex; align-items:center; gap:clamp(16px,4vw,32px); margin-bottom:32px; }
.sigil{ position:relative; width:112px; height:112px; flex:none; }
.sigil svg{ width:100%; height:100%; transform:rotate(-90deg); }
.sigil .track{ fill:none; stroke:var(--line); stroke-width:6; }
.sigil .arc{ fill:none; stroke:var(--brass); stroke-width:6; stroke-linecap:round;
  filter:drop-shadow(0 0 8px rgba(201,162,75,0.35)); transition:stroke-dashoffset 1.1s cubic-bezier(.2,.7,.2,1); }
.sigil .numeral{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
  font-family:var(--display); font-weight:500; font-size:50px; color:var(--brass-soft); }
.hero .eyebrow{ font-size:11px; letter-spacing:.3em; text-transform:uppercase; color:var(--bone-dim); font-weight:600; }
.hero h1{ font-family:var(--display); font-weight:400; font-size:clamp(26px,6vw,38px); margin:.12em 0 .28em; line-height:1; }
.hero .stats{ font-size:14px; color:var(--bone-dim); }
.hero .stats b{ color:var(--bone); font-weight:600; }
.hero .stats .dot{ color:var(--bone-faint); padding:0 .5em; }

.head{ display:flex; align-items:center; gap:14px; margin:0 0 14px; }
.head h2{ font-weight:600; font-size:12px; letter-spacing:.26em; text-transform:uppercase; color:var(--bone-dim); margin:0; }
.head .count{ font-family:var(--mono); font-size:11px; color:var(--bone-faint); }
.head .rule{ flex:1; height:1px; background:var(--line-soft); }
.section{ margin-bottom:32px; }

.task-card{ background:var(--ink-raised); border:1px solid var(--line); border-left:2px solid var(--brass);
  border-radius:14px; padding:14px 16px; margin-bottom:12px; }
.task-card.noplan{ border-left-color:var(--line); }
.tc-head{ display:flex; align-items:baseline; justify-content:space-between; gap:12px; }
.tc-name{ font-family:var(--display); font-weight:500; font-size:20px; color:var(--bone); margin:0; }
.tc-meta{ display:flex; align-items:center; gap:10px; flex:none; }
.cat{ font-family:var(--mono); font-size:10.5px; letter-spacing:.04em; padding:3px 8px; border-radius:999px;
  border:1px solid var(--cl,var(--line)); color:var(--cl,var(--bone-dim)); white-space:nowrap; }
.sat{ font-family:var(--mono); font-size:11px; color:var(--bone-faint); white-space:nowrap; }
.plan-sum{ font-size:13.5px; color:var(--bone-dim); margin:10px 0 2px; }
.prep{ font-family:var(--mono); font-size:9.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--brass);
  border:1px solid color-mix(in srgb, var(--brass) 40%, transparent); border-radius:4px; padding:2px 5px; margin-right:8px; }
.steps{ list-style:none; counter-reset:step; margin:10px 0 2px; padding:0; }
.steps li{ counter-increment:step; position:relative; padding:8px 0 8px 32px; font-size:14px; color:var(--bone-dim); border-top:1px solid var(--line-soft); }
.steps li:first-child{ border-top:0; }
.steps li::before{ content:counter(step); position:absolute; left:0; top:7px; width:20px; height:20px; border-radius:50%;
  border:1px solid var(--line); font-family:var(--mono); font-size:11px; color:var(--bone-faint); display:flex; align-items:center; justify-content:center; }
.steps li.next{ color:var(--bone); font-weight:500; }
.steps li.next::before{ border-color:var(--brass); color:var(--brass-soft); }
.steps a{ color:var(--brass-soft); }

.btn{ font-family:var(--sans); font-size:14px; font-weight:600; cursor:pointer; border-radius:10px;
  padding:10px 16px; border:1px solid var(--line); background:var(--ink-inner); color:var(--bone); }
.btn-done{ margin-top:12px; border-color:color-mix(in srgb,var(--brass) 40%,transparent); color:var(--brass-soft); }
.btn-primary{ background:var(--brass); color:var(--ink); border-color:var(--brass); }
.btn:disabled{ opacity:.5; cursor:default; }

.branches{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
.branch{ background:var(--ink-raised); border:1px solid var(--line); border-radius:14px; padding:14px;
  border-top:2px solid var(--hue, var(--line)); }
.branch .bname{ font-family:var(--display); font-size:19px; font-weight:500; color:var(--bone); }
.branch .blvl{ font-family:var(--mono); font-size:12px; color:var(--hue, var(--bone-dim)); margin-top:2px; }
.branch .bar{ height:5px; border-radius:3px; background:var(--ink-inner); margin:12px 0 8px; overflow:hidden; }
.branch .bar > i{ display:block; height:100%; background:var(--hue, var(--bone-dim)); border-radius:3px; transition:width 1s cubic-bezier(.2,.7,.2,1); }
.branch .foot{ display:flex; justify-content:space-between; font-size:11.5px; color:var(--bone-dim); }
.branch.unlit{ border-top-color:var(--line); background:#181A22; }
.branch.unlit .bname{ color:var(--bone-faint); }
.branch.unlit .invite{ font-size:12px; color:var(--bone-dim); margin-top:8px; }

.row{ display:flex; align-items:center; gap:12px; padding:11px 2px; border-bottom:1px solid var(--line-soft); }
.row:last-child{ border-bottom:0; }
.row .task{ flex:1; color:var(--bone); font-size:14.5px; }
.row .when{ font-family:var(--mono); font-size:11px; color:var(--bone-faint); white-space:nowrap; }

.field{ display:block; margin-bottom:16px; }
.field span{ display:block; font-size:12px; color:var(--bone-dim); margin-bottom:6px; letter-spacing:.04em; }
.field input, .field select{ width:100%; font-size:16px; padding:11px 12px; border-radius:10px;
  background:var(--ink-inner); color:var(--bone); border:1px solid var(--line); }
.msg-err{ color:#E08A7A; font-size:13px; margin:8px 0; }
.msg-ok{ color:var(--h-pathfinder); font-size:13px; margin:8px 0; }
.muted{ color:var(--bone-faint); font-size:12px; }

@media (prefers-reduced-motion:reduce){
  .sigil .arc, .branch .bar > i{ transition:none; }
}
```

- [ ] **Step 5: Write the smoke test**

`web/src/lib/smoke.test.ts`:
```ts
import { describe, it, expect } from "vitest";

describe("toolchain", () => {
  it("runs vitest", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 6: Install, build, and test**

Run (from `web/`): `npm install`
Expected: dependencies install without errors.

Run: `npm run build`
Expected: SvelteKit build succeeds, producing `web/build/` (with `index.html` fallback).

Run: `npm test`
Expected: PASS — the smoke test (`1 + 1 == 2`).

- [ ] **Step 7: Commit**

```bash
git add web/package.json web/svelte.config.js web/vite.config.ts web/tsconfig.json \
        web/.gitignore web/vitest-setup.ts web/src/app.html web/src/app.css \
        web/src/routes/+layout.js web/src/routes/+layout.svelte web/src/routes/+page.svelte \
        web/src/lib/smoke.test.ts web/package-lock.json
git commit -m "feat(web): scaffold SvelteKit static-SPA + toolchain + ported styles

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 2: Types + the game brain (`game.ts`)

**Files:** Create `web/src/lib/types.ts`, `web/src/lib/game.ts`, `web/src/lib/game.test.ts`.

**Interfaces:**
- Produces (`types.ts`): `Category`, `PlanStep`, `Plan`, `ActiveTask`, `LedgerEvent`, `Feed`.
- Produces (`game.ts`): `hero(feed) -> Hero {level, word, total, toNext, pct}`; `branchVMs(feed) -> BranchVM[] {key,name,hue,lit,level,into,span,count,invite}`; `recentLog(feed, limit=7) -> {task, chips:{name,hue}[], when}[]`; plus `progress`, `dur`, `ago`, `fmtDate` helpers.

- [ ] **Step 1: Write the failing tests**

`web/src/lib/game.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { progress, dur, ago, hero, branchVMs, recentLog } from "./game";
import type { Feed } from "./types";

const ev = (over: Partial<import("./types").LedgerEvent> = {}) => ({
  task: "T", category: "chore", completed_at: "2026-06-10T00:00:00Z",
  sat_for_hours: 50, orchestrator: null, ...over
});

describe("progress (level curve)", () => {
  it("levels up with linearly rising cost", () => {
    // base 4, step 2: lvl1 costs 4, lvl2 costs 6, lvl3 costs 8...
    expect(progress(0, 4, 2).level).toBe(0);
    expect(progress(4, 4, 2).level).toBe(1);
    expect(progress(9, 4, 2).level).toBe(1);  // 4 used, need 6 more for lvl2
    expect(progress(10, 4, 2).level).toBe(2); // 4+6=10
    const p = progress(5, 4, 2);
    expect(p.into).toBe(1); expect(p.span).toBe(6); expect(p.toNext).toBe(5);
  });
});

describe("dur", () => {
  it("formats hours/days and null", () => {
    expect(dur(null)).toBe("—");
    expect(dur(5)).toBe("5h");
    expect(dur(48)).toBe("2d");
  });
});

describe("ago", () => {
  it("uses an injectable now", () => {
    const now = Date.parse("2026-06-10T05:00:00Z");
    expect(ago("2026-06-10T04:30:00Z", now)).toBe("just now");
    expect(ago("2026-06-10T02:00:00Z", now)).toBe("3h ago");
    expect(ago("2026-06-08T05:00:00Z", now)).toBe("2d ago");
  });
});

describe("hero", () => {
  it("derives overall level from event count (base 4, step 2)", () => {
    const feed: Feed = { events: Array.from({ length: 10 }, () => ev()), active: [] };
    const h = hero(feed);
    expect(h.total).toBe(10);
    expect(h.level).toBe(2);          // 4 + 6 = 10
    expect(h.word).toBe("Warmed up"); // LEVEL_WORDS[2]
  });
});

describe("branchVMs", () => {
  it("lights branches by predicate and counts", () => {
    const feed: Feed = {
      events: [
        ev({ category: "phone" }), ev({ category: "admin" }),  // diplomat x2
        ev({ category: "errand" }),                            // pathfinder x1
        ev({ orchestrator: "did research", category: "chore" }), // loremaster + hearthkeeper
        ev({ sat_for_hours: 1, category: "chore" })            // swift + hearthkeeper
      ],
      active: []
    };
    const vms = Object.fromEntries(branchVMs(feed).map(b => [b.key, b]));
    expect(vms.diplomat.count).toBe(2);
    expect(vms.diplomat.lit).toBe(true);
    expect(vms.pathfinder.count).toBe(1);
    expect(vms.loremaster.count).toBe(1);
    expect(vms.swift.count).toBe(1);
    expect(vms.hearthkeeper.count).toBe(2);
  });
  it("marks zero-count branches unlit with an invite", () => {
    const vms = Object.fromEntries(branchVMs({ events: [], active: [] }).map(b => [b.key, b]));
    expect(vms.swift.lit).toBe(false);
    expect(vms.swift.invite).toMatch(/couple of hours/i);
  });
});

describe("recentLog", () => {
  it("returns newest first, capped, with branch chips", () => {
    const feed: Feed = {
      events: [
        ev({ task: "old", completed_at: "2026-06-01T00:00:00Z", category: "phone" }),
        ev({ task: "new", completed_at: "2026-06-09T00:00:00Z", category: "errand" })
      ],
      active: []
    };
    const log = recentLog(feed, 7);
    expect(log[0].task).toBe("new");
    expect(log[0].chips.map(c => c.name)).toContain("Pathfinder");
    expect(log.length).toBe(2);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `web/`): `npm test -- game`
Expected: FAIL — `Cannot find module './game'` (and `./types`).

- [ ] **Step 3: Create `web/src/lib/types.ts`**

```ts
export type Category = "phone" | "admin" | "errand" | "chore";

export interface PlanStep { text: string; href?: string; }
export interface Plan { summary: string; steps: PlanStep[]; }

export interface ActiveTask {
  id: string;
  task: string;
  category: Category | string;
  sat_for_hours: number | null;
  plan: Plan | null;
}

export interface LedgerEvent {
  task: string;
  category: string | null;
  completed_at: string;
  sat_for_hours: number | null;
  orchestrator?: string | null;
}

export interface Feed { events: LedgerEvent[]; active: ActiveTask[]; }
```

- [ ] **Step 4: Create `web/src/lib/game.ts`** (ported from `sidekick-render.js`)

```ts
import type { Feed, LedgerEvent, Category } from "./types";

export interface Branch {
  key: string; name: string; hue: string;
  test: (e: LedgerEvent) => boolean; invite: string;
}

export const BRANCHES: Branch[] = [
  { key: "diplomat",     name: "Diplomat",     hue: "var(--h-diplomat)",     test: e => e.category === "phone" || e.category === "admin", invite: "Untapped — clear a call or an admin task." },
  { key: "pathfinder",   name: "Pathfinder",   hue: "var(--h-pathfinder)",   test: e => e.category === "errand",                          invite: "Untapped — run an errand." },
  { key: "hearthkeeper", name: "Hearthkeeper", hue: "var(--h-hearthkeeper)", test: e => e.category === "chore",                           invite: "Untapped — knock out a chore." },
  { key: "loremaster",   name: "Loremaster",   hue: "var(--h-loremaster)",   test: e => !!e.orchestrator,                                 invite: "Untapped — let the orchestrator take one on." },
  { key: "swift",        name: "Swift",        hue: "var(--h-swift)",        test: e => e.sat_for_hours != null && e.sat_for_hours <= 2,  invite: "Untapped — clear one within a couple of hours." }
];

export const CAT_HUE: Record<string, string> = {
  phone: "var(--h-diplomat)", admin: "var(--h-diplomat)",
  errand: "var(--h-pathfinder)", chore: "var(--h-hearthkeeper)"
};

const OVERALL_CURVE = { base: 4, step: 2 };
const BRANCH_CURVE = { base: 2, step: 1 };
const LEVEL_WORDS = ["Getting started","Finding the rhythm","Warmed up","In the swing","Hitting stride","On a roll","Dialled in","Unstoppable"];

export interface Progress { level: number; into: number; span: number; toNext: number; pct: number; }
export function progress(count: number, base: number, step: number): Progress {
  let lvl = 0, used = 0, cost = base;
  while (used + cost <= count) { used += cost; lvl++; cost = base + step * lvl; }
  const into = count - used, span = cost;
  return { level: lvl, into, span, toNext: span - into, pct: span ? into / span : 0 };
}

export const catHue = (c: string) => CAT_HUE[c] || "var(--line)";
export const fmtDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
export const dur = (h: number | null) => h == null ? "—" : (h < 24 ? Math.round(h) + "h" : Math.round(h / 24) + "d");
export function ago(iso: string, now: number = Date.now()): string {
  const h = Math.round((now - new Date(iso).getTime()) / 36e5);
  if (h < 1) return "just now";
  if (h < 24) return h + "h ago";
  return Math.round(h / 24) + "d ago";
}

export interface Hero { level: number; word: string; total: number; toNext: number; pct: number; }
export function hero(feed: Feed): Hero {
  const total = feed.events.length;
  const p = progress(total, OVERALL_CURVE.base, OVERALL_CURVE.step);
  return { level: p.level, word: LEVEL_WORDS[Math.min(p.level, LEVEL_WORDS.length - 1)], total, toNext: p.toNext, pct: p.pct };
}

export interface BranchVM {
  key: string; name: string; hue: string; invite: string;
  lit: boolean; level: number; into: number; span: number; pct: number; count: number;
}
export function branchVMs(feed: Feed): BranchVM[] {
  return BRANCHES.map(b => {
    const count = feed.events.filter(b.test).length;
    const p = progress(count, BRANCH_CURVE.base, BRANCH_CURVE.step);
    return { key: b.key, name: b.name, hue: b.hue, invite: b.invite,
      lit: count > 0, level: p.level, into: p.into, span: p.span, pct: p.pct, count };
  });
}

export interface LogRow { task: string; chips: { name: string; hue: string }[]; when: string; }
export function recentLog(feed: Feed, limit = 7, now: number = Date.now()): LogRow[] {
  return [...feed.events]
    .sort((a, b) => new Date(b.completed_at).getTime() - new Date(a.completed_at).getTime())
    .slice(0, limit)
    .map(e => ({
      task: e.task,
      chips: BRANCHES.filter(b => b.test(e)).map(b => ({ name: b.name, hue: b.hue })),
      when: ago(e.completed_at, now)
    }));
}

export type { Category };
```

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `web/`): `npm test -- game`
Expected: PASS — all game-brain tests.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/game.ts web/src/lib/game.test.ts
git commit -m "feat(web): shared types + game-brain port (levels/branches/log) with tests

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 3: Settings store + API client (`settings.ts`, `api.ts`)

**Files:** Create `web/src/lib/settings.ts`, `web/src/lib/api.ts`, `web/src/lib/api.test.ts`.

**Interfaces:**
- Produces (`settings.ts`): `settings` (writable store of `{ token: string; apiBase: string }`, persisted to `localStorage` under `sidekick.settings`); `hasToken(): boolean`.
- Produces (`api.ts`): `ApiError extends Error { status: number }`; `getFeed(): Promise<Feed>`; `createTask(title, category): Promise<ActiveTask>`; `completeTask(id, completedAt): Promise<CompleteResult>` where `CompleteResult = { id; status; completed_at; sat_for_hours: number|null; already_done: boolean }`. All send `Authorization: Bearer <token>`; POSTs send `Idempotency-Key`. `401` → `ApiError(401, "unauthorized")`.

- [ ] **Step 1: Write the failing API tests**

`web/src/lib/api.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { getFeed, createTask, completeTask, ApiError } from "./api";
import { settings } from "./settings";

function mockFetch(status: number, body: unknown) {
  return vi.fn(async () => new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" }
  }));
}

beforeEach(() => {
  settings.set({ token: "t0ken", apiBase: "" });
});

describe("getFeed", () => {
  it("calls /api/feed with the bearer token and returns the feed", async () => {
    const f = mockFetch(200, { events: [], active: [] });
    vi.stubGlobal("fetch", f);
    const feed = await getFeed();
    expect(feed).toEqual({ events: [], active: [] });
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/feed");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("throws ApiError(401) on unauthorized", async () => {
    vi.stubGlobal("fetch", mockFetch(401, { error: "unauthorized" }));
    await expect(getFeed()).rejects.toMatchObject({ status: 401 });
  });
});

describe("createTask", () => {
  it("POSTs title+category with an Idempotency-Key", async () => {
    const f = mockFetch(201, { id: "x", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null });
    vi.stubGlobal("fetch", f);
    const res = await createTask("Buy milk", "errand");
    expect(res.id).toBe("x");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/tasks");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ title: "Buy milk", category: "errand" });
    expect(typeof opts.headers["Idempotency-Key"]).toBe("string");
    expect(opts.headers["Idempotency-Key"].length).toBeGreaterThan(0);
  });

  it("surfaces the API error message on 400", async () => {
    vi.stubGlobal("fetch", mockFetch(400, { error: "category must be one of [...]" }));
    await expect(createTask("x", "bad" as any)).rejects.toMatchObject({ status: 400 });
  });
});

describe("completeTask", () => {
  it("POSTs completed_at to the complete endpoint", async () => {
    const f = mockFetch(200, { id: "x", status: "done", completed_at: "T", sat_for_hours: 1, already_done: false });
    vi.stubGlobal("fetch", f);
    const res = await completeTask("x", "2026-06-20T10:00:00Z");
    expect(res.status).toBe("done");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/tasks/x/complete");
    expect(JSON.parse(opts.body)).toEqual({ completed_at: "2026-06-20T10:00:00Z" });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `web/`): `npm test -- api`
Expected: FAIL — `Cannot find module './api'` (and `./settings`).

- [ ] **Step 3: Create `web/src/lib/settings.ts`**

```ts
import { writable, get } from "svelte/store";
import { browser } from "$app/environment";

export interface Settings { token: string; apiBase: string; }
const KEY = "sidekick.settings";
const EMPTY: Settings = { token: "", apiBase: "" };

function load(): Settings {
  if (!browser) return EMPTY;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) { const v = JSON.parse(raw); return { token: v.token || "", apiBase: v.apiBase || "" }; }
  } catch { /* ignore */ }
  return EMPTY;
}

export const settings = writable<Settings>(load());

if (browser) {
  settings.subscribe(v => {
    try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* ignore */ }
  });
}

export const hasToken = () => get(settings).token.trim().length > 0;
```

- [ ] **Step 4: Create `web/src/lib/api.ts`**

```ts
import { get } from "svelte/store";
import { settings } from "./settings";
import type { Feed, ActiveTask, Category } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiError"; }
}

export interface CompleteResult {
  id: string; status: string; completed_at: string | null;
  sat_for_hours: number | null; already_done: boolean;
}

const base = () => get(settings).apiBase || "";   // "" => relative /api via the proxy

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { Authorization: `Bearer ${get(settings).token}`, ...extra };
}

async function handle(res: Response): Promise<any> {
  if (res.status === 401) throw new ApiError(401, "unauthorized");
  if (!res.ok) {
    let msg = `request failed (${res.status})`;
    try { const b = await res.json(); if (b && b.error) msg = b.error; } catch { /* ignore */ }
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export async function getFeed(): Promise<Feed> {
  return handle(await fetch(`${base()}/api/feed`, { headers: headers() }));
}

export async function createTask(title: string, category: Category): Promise<ActiveTask> {
  return handle(await fetch(`${base()}/api/tasks`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ title, category })
  }));
}

export async function completeTask(id: string, completedAt: string): Promise<CompleteResult> {
  return handle(await fetch(`${base()}/api/tasks/${encodeURIComponent(id)}/complete`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ completed_at: completedAt })
  }));
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run (from `web/`): `npm test -- api`
Expected: PASS — all API-client tests.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/settings.ts web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "feat(web): settings store (localStorage token) + API client with tests

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 4: Dashboard route (read-only render)

**Files:** Create `web/src/routes/Dashboard.svelte` (presentational), replace `web/src/routes/+page.svelte`, create `web/src/routes/dashboard.test.ts`.

**Interfaces:**
- Consumes: `game.ts` (`hero`, `branchVMs`, `recentLog`, `catHue`, `dur`), `types.ts` (`Feed`).
- Produces: `Dashboard.svelte` — props `{ feed: Feed, onComplete?: (id: string) => void, pending?: Set<string> }` — renders hero/open-tasks/branches/log. (The Complete wiring lands in Task 5; `onComplete`/`pending` are accepted now but the button is added in Task 5.)

- [ ] **Step 1: Write the failing component test**

`web/src/routes/dashboard.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/svelte";
import Dashboard from "./Dashboard.svelte";
import type { Feed } from "$lib/types";

const feed: Feed = {
  events: [
    { task: "Called dentist", category: "phone", completed_at: "2026-06-09T00:00:00Z", sat_for_hours: 5, orchestrator: null },
    { task: "Ran errand", category: "errand", completed_at: "2026-06-08T00:00:00Z", sat_for_hours: 30, orchestrator: null }
  ],
  active: [
    { id: "t1", task: "Replace fan", category: "chore", sat_for_hours: 120,
      plan: { summary: "Three quotes compared.", steps: [{ text: "Call the electrician", href: "tel:+4500" }, { text: "Book a slot" }] } },
    { id: "t2", task: "Email landlord", category: "admin", sat_for_hours: 10, plan: null }
  ]
};

describe("Dashboard", () => {
  it("renders the level, open tasks, branches, and log from a feed", () => {
    render(Dashboard, { props: { feed } });
    // hero: 2 events -> level 0 (need 4 for level 1)
    expect(screen.getByText("Getting started")).toBeInTheDocument();
    expect(screen.getByText(/2/)).toBeInTheDocument();
    // open tasks
    expect(screen.getByText("Replace fan")).toBeInTheDocument();
    expect(screen.getByText("Email landlord")).toBeInTheDocument();
    expect(screen.getByText("Call the electrician")).toBeInTheDocument();
    expect(screen.getByText(/No plan yet/i)).toBeInTheDocument();
    // a branch + a log row
    expect(screen.getByText("Diplomat")).toBeInTheDocument();
    expect(screen.getByText("Called dentist")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `web/`): `npm test -- dashboard`
Expected: FAIL — `Cannot find module './Dashboard.svelte'`.

- [ ] **Step 3: Create `web/src/routes/Dashboard.svelte`**

```svelte
<script lang="ts">
  import type { Feed } from "$lib/types";
  import { hero, branchVMs, recentLog, catHue, dur } from "$lib/game";

  let { feed, onComplete = (_id: string) => {}, pending = new Set<string>() }:
    { feed: Feed; onComplete?: (id: string) => void; pending?: Set<string> } = $props();

  const h = $derived(hero(feed));
  const branches = $derived(branchVMs(feed));
  const log = $derived(recentLog(feed, 7));
  const R = 52, C = 2 * Math.PI * R;
</script>

<section class="hero">
  <div class="sigil">
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <circle class="track" cx="60" cy="60" r={R}></circle>
      <circle class="arc" cx="60" cy="60" r={R}
        style="stroke-dasharray:{C};stroke-dashoffset:{C * (1 - h.pct)}"></circle>
    </svg>
    <div class="numeral">{h.level}</div>
  </div>
  <div>
    <div class="eyebrow">Level</div>
    <h1>{h.word}</h1>
    <div class="stats"><b>{h.total}</b> tasks cleared <span class="dot">·</span> <b>{h.toNext}</b> to level {h.level + 1}</div>
  </div>
</section>

<div class="head"><h2>In front of you</h2><span class="count">{feed.active.length} open</span><span class="rule"></span></div>
<section class="section">
  {#each feed.active as t (t.id)}
    <article class="task-card" class:noplan={!t.plan}>
      <div class="tc-head">
        <h3 class="tc-name">{t.task}</h3>
        <span class="tc-meta">
          <span class="cat" style="--cl:{catHue(t.category)}">{t.category}</span>
          <span class="sat">{dur(t.sat_for_hours)}</span>
        </span>
      </div>
      {#if t.plan}
        <div class="plan-sum"><span class="prep">Prepared</span>{t.plan.summary}</div>
        <ol class="steps">
          {#each t.plan.steps as s, i}
            <li class:next={i === 0}>
              {#if s.href}<a href={s.href} target={s.href.startsWith("tel:") ? undefined : "_blank"} rel="noopener">{s.text}</a>
              {:else}{s.text}{/if}
            </li>
          {/each}
        </ol>
      {:else}
        <div class="noplan-msg muted">No plan yet — ask the orchestrator to clear the first step.</div>
      {/if}
      <!-- Complete button added in Task 5 -->
    </article>
  {/each}
</section>

<div class="head"><h2>Skill branches</h2><span class="rule"></span></div>
<section class="section branches">
  {#each branches as b (b.key)}
    {#if b.lit}
      <div class="branch" style="--hue:{b.hue}">
        <div class="bname">{b.name}</div>
        <div class="blvl">Level {b.level}</div>
        <div class="bar"><i style="width:{b.pct * 100}%"></i></div>
        <div class="foot"><span>{b.into}/{b.span} to next</span><span>{b.count} done</span></div>
      </div>
    {:else}
      <div class="branch unlit">
        <div class="bname">{b.name}</div>
        <div class="blvl">Unlit</div>
        <div class="invite">{b.invite}</div>
      </div>
    {/if}
  {/each}
</section>

<div class="head"><h2>Recently cleared</h2><span class="rule"></span></div>
<section class="section">
  {#each log as r}
    <div class="row"><span class="task">{r.task}</span><span class="when">{r.when}</span></div>
  {/each}
</section>
```

- [ ] **Step 4: Replace `web/src/routes/+page.svelte` to load the feed and render the dashboard**

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import Dashboard from "./Dashboard.svelte";
  import { getFeed, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { Feed } from "$lib/types";

  let feed = $state<Feed | null>(null);
  let error = $state("");

  async function load() {
    error = "";
    try { feed = await getFeed(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
</script>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{:else if feed}
  <Dashboard {feed} />
{:else}
  <p class="muted">Loading…</p>
{/if}
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `web/`): `npm test -- dashboard`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/Dashboard.svelte web/src/routes/+page.svelte web/src/routes/dashboard.test.ts
git commit -m "feat(web): dashboard route renders the derived feed (hero/tasks/branches/log)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 5: Complete action (optimistic)

**Files:** Modify `web/src/routes/Dashboard.svelte` (add the Complete button), modify `web/src/routes/+page.svelte` (wire `onComplete` with optimistic update + rollback), create `web/src/routes/complete.test.ts`.

**Interfaces:**
- Consumes: `completeTask(id, completedAt)` from `api.ts`.
- Produces: clicking "Done" on a card calls `onComplete(id)`; `+page.svelte` optimistically removes the task, calls `completeTask`, and on error re-adds it and shows the message; `pending` disables the button mid-flight.

- [ ] **Step 1: Write the failing test**

`web/src/routes/complete.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import Dashboard from "./Dashboard.svelte";
import type { Feed } from "$lib/types";

const feed: Feed = {
  events: [],
  active: [{ id: "t1", task: "Pay rent", category: "admin", sat_for_hours: 10, plan: null }]
};

describe("Complete button", () => {
  it("calls onComplete with the task id when Done is clicked", async () => {
    const onComplete = vi.fn();
    render(Dashboard, { props: { feed, onComplete } });
    await fireEvent.click(screen.getByRole("button", { name: /done/i }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith("t1"));
  });

  it("disables the button when the task id is pending", () => {
    render(Dashboard, { props: { feed, pending: new Set(["t1"]) } });
    expect(screen.getByRole("button", { name: /done/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `web/`): `npm test -- complete`
Expected: FAIL — no button with name "done" exists yet.

- [ ] **Step 3: Add the Complete button to `Dashboard.svelte`**

Inside the `<article class="task-card">`, replace the `<!-- Complete button added in Task 5 -->` comment with:

```svelte
      <button class="btn btn-done" disabled={pending.has(t.id)} onclick={() => onComplete(t.id)}>
        {pending.has(t.id) ? "Completing…" : "Done"}
      </button>
```

- [ ] **Step 4: Wire optimistic complete in `+page.svelte`**

Replace the `<script>` block of `web/src/routes/+page.svelte` with:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import Dashboard from "./Dashboard.svelte";
  import { getFeed, completeTask, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { Feed } from "$lib/types";

  let feed = $state<Feed | null>(null);
  let error = $state("");
  let pending = $state(new Set<string>());

  async function load() {
    error = "";
    try { feed = await getFeed(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  async function onComplete(id: string) {
    if (!feed || pending.has(id)) return;
    const removed = feed.active.find(t => t.id === id);
    if (!removed) return;
    pending = new Set(pending).add(id);
    feed = { ...feed, active: feed.active.filter(t => t.id !== id) };  // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                                    // reconcile (ledger/branches)
    } catch (e) {
      feed = { ...feed, active: [removed, ...feed.active] };           // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
</script>
```

And update the markup's Dashboard usage to pass the handlers:
```svelte
{:else if feed}
  <Dashboard {feed} {onComplete} {pending} />
{:else}
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `web/`): `npm test -- complete`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/Dashboard.svelte web/src/routes/+page.svelte web/src/routes/complete.test.ts
git commit -m "feat(web): optimistic Complete action on task cards

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 6: Capture route + nav

**Files:** Create `web/src/routes/new/+page.svelte`, modify `web/src/routes/+layout.svelte` (add nav), create `web/src/routes/new/capture.test.ts`.

**Interfaces:**
- Consumes: `createTask(title, category)` from `api.ts`.
- Produces: `/new` — a form (title input + category select over `phone|admin|errand|chore`) that calls `createTask` and navigates to `/` on success; validates non-empty title before POST.

- [ ] **Step 1: Write the failing test**

`web/src/routes/new/capture.test.ts`:
```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/api", () => ({ createTask: vi.fn(async () => ({ id: "new1" })), ApiError: class extends Error {} }));

import Capture from "./+page.svelte";
import { createTask } from "$lib/api";
import { goto } from "$app/navigation";

beforeEach(() => { vi.clearAllMocks(); });

describe("Capture", () => {
  it("creates a task and navigates home", async () => {
    render(Capture);
    await fireEvent.input(screen.getByLabelText(/title/i), { target: { value: "Book MOT" } });
    await fireEvent.change(screen.getByLabelText(/category/i), { target: { value: "errand" } });
    await fireEvent.click(screen.getByRole("button", { name: /capture/i }));
    await waitFor(() => expect(createTask).toHaveBeenCalledWith("Book MOT", "errand"));
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/"));
  });

  it("does not submit an empty title", async () => {
    render(Capture);
    await fireEvent.click(screen.getByRole("button", { name: /capture/i }));
    expect(createTask).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `web/`): `npm test -- capture`
Expected: FAIL — `Cannot find module './+page.svelte'` under `new/`.

- [ ] **Step 3: Create `web/src/routes/new/+page.svelte`**

```svelte
<script lang="ts">
  import { goto } from "$app/navigation";
  import { createTask } from "$lib/api";
  import type { Category } from "$lib/types";

  const CATEGORIES: Category[] = ["phone", "admin", "errand", "chore"];
  let title = $state("");
  let category = $state<Category>("phone");
  let busy = $state(false);
  let error = $state("");

  async function submit(e: Event) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    busy = true; error = "";
    try { await createTask(title.trim(), category); goto("/"); }
    catch (err) { error = err instanceof Error ? err.message : "couldn't capture — try again"; busy = false; }
  }
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">New task</h1>
<form onsubmit={submit}>
  <label class="field">
    <span>Title</span>
    <input type="text" bind:value={title} placeholder="What needs doing?" />
  </label>
  <label class="field">
    <span>Category</span>
    <select bind:value={category}>
      {#each CATEGORIES as c}<option value={c}>{c}</option>{/each}
    </select>
  </label>
  {#if error}<p class="msg-err">{error}</p>{/if}
  <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Capturing…" : "Capture"}</button>
</form>
```

- [ ] **Step 4: Add nav to `web/src/routes/+layout.svelte`**

```svelte
<script lang="ts">
  import "../app.css";
  import { page } from "$app/stores";
  let { children } = $props();
  const is = (p: string) => $page.url.pathname === p;
</script>

<div class="wrap">
  <nav class="nav">
    <a href="/" class:active={is("/")}>Dashboard</a>
    <a href="/new" class:active={is("/new")}>New</a>
    <a href="/settings" class:active={is("/settings")}>Settings</a>
  </nav>
  {@render children()}
</div>
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `web/`): `npm test -- capture`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/new/+page.svelte web/src/routes/new/capture.test.ts web/src/routes/+layout.svelte
git commit -m "feat(web): capture route (new task) + nav

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 7: Settings route + token gate

**Files:** Create `web/src/routes/settings/+page.svelte`, create `web/src/routes/settings/settings.test.ts`.

**Interfaces:**
- Consumes: the `settings` store from `settings.ts`.
- Produces: `/settings` — inputs bound to the `settings` store (token + optional API base) persisted to `localStorage`; saving a token enables the app (the Dashboard's existing `hasToken()` gate routes here when empty).

- [ ] **Step 1: Write the failing test**

`web/src/routes/settings/settings.test.ts`:
```ts
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
import { get } from "svelte/store";
import Settings from "./+page.svelte";
import { settings } from "$lib/settings";

beforeEach(() => settings.set({ token: "", apiBase: "" }));

describe("Settings", () => {
  it("writes the entered token into the settings store", async () => {
    render(Settings);
    await fireEvent.input(screen.getByLabelText(/token/i), { target: { value: "secret-123" } });
    expect(get(settings).token).toBe("secret-123");
  });

  it("prefills from the existing settings", () => {
    settings.set({ token: "abc", apiBase: "" });
    render(Settings);
    expect((screen.getByLabelText(/token/i) as HTMLInputElement).value).toBe("abc");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `web/`): `npm test -- settings`
Expected: FAIL — `Cannot find module './+page.svelte'` under `settings/`.

- [ ] **Step 3: Create `web/src/routes/settings/+page.svelte`**

```svelte
<script lang="ts">
  import { settings } from "$lib/settings";

  let token = $state($settings.token);
  let apiBase = $state($settings.apiBase);

  // keep the store in sync as the user types (persists to localStorage via the store)
  $effect(() => { settings.set({ token: token.trim(), apiBase: apiBase.trim() }); });
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Settings</h1>
<label class="field">
  <span>API token</span>
  <input type="password" bind:value={token} placeholder="paste your bearer token" autocomplete="off" />
</label>
<label class="field">
  <span>API base URL (optional)</span>
  <input type="text" bind:value={apiBase} placeholder="leave blank to use this site (/api)" autocomplete="off" />
</label>
<p class="muted">Stored only in this browser. Leave the base URL blank in normal use — the app proxies <code>/api</code> to the host.</p>
{#if token.trim()}<p class="msg-ok">Token saved. Open the Dashboard.</p>{/if}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `web/`): `npm test -- settings`
Expected: PASS.

- [ ] **Step 5: Run the full unit suite + build**

Run (from `web/`): `npm test`
Expected: PASS — all unit/component tests (smoke, game, api, dashboard, complete, capture, settings).

Run: `npm run build`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/settings/+page.svelte web/src/routes/settings/settings.test.ts
git commit -m "feat(web): settings route (token + optional API base) with token gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 8: PWA manifest + service worker (installable, offline shell)

**Files:** Modify `web/vite.config.ts` (add `vite-plugin-pwa`), create `web/static/icon-192.png` and `web/static/icon-512.png`.

**Interfaces:**
- Produces: a build that emits a web manifest (name "Sidekick", standalone, theme `#15171F`, the two icons) and a service worker that precaches the app shell and runtime-caches `GET /api/feed` (so the app opens offline with last-known data).

- [ ] **Step 1: Create the icons**

Generate two solid-background PNG app icons (brass glyph on the ink background is fine; exact art is not load-bearing). Run from `web/`:
```bash
python3 - <<'PY'
import struct, zlib, os
os.makedirs("static", exist_ok=True)
def png(path, size, rgb=(21,23,31)):
    def chunk(t,d): return struct.pack(">I",len(d))+t+d+struct.pack(">I",zlib.crc32(t+d)&0xffffffff)
    raw=b"".join(b"\x00"+bytes(rgb)*size for _ in range(size))
    data=zlib.compress(raw)
    ihdr=struct.pack(">IIBBBBB",size,size,8,2,0,0,0)
    open(path,"wb").write(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",ihdr)+chunk(b"IDAT",data)+chunk(b"IEND",b""))
png("static/icon-192.png",192); png("static/icon-512.png",512)
print("wrote static/icon-192.png, static/icon-512.png")
PY
```
Expected: prints the two written paths.

- [ ] **Step 2: Add `vite-plugin-pwa` to `web/vite.config.ts`**

Replace the file with:
```ts
import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";
import { SvelteKitPWA } from "@vite-pwa/sveltekit";

export default defineConfig({
  plugins: [
    sveltekit(),
    SvelteKitPWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Sidekick",
        short_name: "Sidekick",
        description: "Your ADHD execution sidekick",
        theme_color: "#15171F",
        background_color: "#15171F",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png" }
        ]
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,png,svg,woff2}"],
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname === "/api/feed",
            handler: "NetworkFirst",
            options: { cacheName: "sidekick-feed", expiration: { maxEntries: 1 } }
          }
        ]
      }
    })
  ],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, "")
      }
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest-setup.ts"]
  }
});
```

Add the plugin to dependencies:
Run (from `web/`): `npm install -D @vite-pwa/sveltekit`
Expected: installs the SvelteKit PWA integration.

- [ ] **Step 3: Build and verify the PWA artifacts**

Run (from `web/`): `npm run build`
Expected: build succeeds and emits a service worker + `manifest.webmanifest` into `web/build/`.

Verify the manifest and SW exist:
```bash
ls web/build/manifest.webmanifest && ls web/build/sw.js 2>/dev/null || ls web/build/service-worker.js
grep -q '"name":"Sidekick"' web/build/manifest.webmanifest && echo "OK: manifest" || echo "FAIL: manifest"
```
Expected: the manifest file exists and contains the app name; a service worker file exists. (`OK: manifest`.)

- [ ] **Step 4: Run the unit suite (no regression)**

Run (from `web/`): `npm test`
Expected: PASS — all unit/component tests still green.

- [ ] **Step 5: Commit**

```bash
git add web/vite.config.ts web/static/icon-192.png web/static/icon-512.png web/package.json web/package-lock.json
git commit -m "feat(web): installable PWA — manifest, icons, offline-feed service worker

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 9: Playwright end-to-end (read → capture → complete vs a mock API)

**Files:** Create `web/playwright.config.ts`, `web/e2e/app.spec.ts`.

**Interfaces:**
- Consumes: the built/preview app. Mocks `/api/*` at the browser level (`page.route`) so no real backend is needed; seeds a token via `localStorage` before load.

- [ ] **Step 1: Create `web/playwright.config.ts`**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  webServer: {
    command: "npm run build && npm run preview -- --port 4173",
    port: 4173,
    reuseExistingServer: !process.env.CI
  },
  use: { baseURL: "http://localhost:4173" }
});
```

- [ ] **Step 2: Create `web/e2e/app.spec.ts`**

```ts
import { test, expect } from "@playwright/test";

const feed = {
  events: [{ task: "Called dentist", category: "phone", completed_at: "2026-06-09T00:00:00Z", sat_for_hours: 5, orchestrator: null }],
  active: [{ id: "t1", task: "Replace fan", category: "chore", sat_for_hours: 120, plan: null }]
};

test("read, capture, and complete against a mocked API", async ({ page }) => {
  // seed the token before the app loads
  await page.addInitScript(() => localStorage.setItem("sidekick.settings", JSON.stringify({ token: "test", apiBase: "" })));

  let created = false, completed = false;
  await page.route("**/api/feed", r => r.fulfill({ json: feed }));
  await page.route("**/api/tasks", r => { created = true; r.fulfill({ status: 201, json: { id: "t2", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null } }); });
  await page.route("**/api/tasks/*/complete", r => { completed = true; r.fulfill({ json: { id: "t1", status: "done", completed_at: "x", sat_for_hours: 1, already_done: false } }); });

  await page.goto("/");
  await expect(page.getByText("Replace fan")).toBeVisible();
  await expect(page.getByText("Called dentist")).toBeVisible();

  // capture
  await page.goto("/new");
  await page.getByLabel(/title/i).fill("Buy milk");
  await page.getByLabel(/category/i).selectOption("errand");
  await page.getByRole("button", { name: /capture/i }).click();
  await expect.poll(() => created).toBe(true);

  // complete
  await page.getByRole("button", { name: /done/i }).click();
  await expect.poll(() => completed).toBe(true);
});
```

- [ ] **Step 3: Install browsers and run the e2e**

Run (from `web/`): `npx playwright install chromium`
Expected: Chromium downloads.

Run: `npm run e2e`
Expected: PASS — the single e2e flows through read → capture → complete against the mocked API.

- [ ] **Step 4: Commit**

```bash
git add web/playwright.config.ts web/e2e/app.spec.ts web/package.json web/package-lock.json
git commit -m "test(web): Playwright e2e — read/capture/complete against a mock API

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 10: Docs — `web/README.md` + root pointer

**Files:** Create `web/README.md`, modify root `README.md`.

**Interfaces:** Documentation only — verify by `grep`.

- [ ] **Step 1: Create `web/README.md`**

````markdown
# Sidekick web (phone app — Phase 2)

A mobile-first, installable SvelteKit PWA that reads the dashboard from the Phase 1
host API and lets you complete and capture tasks. It calls the API **same-origin via
a proxy** (Vite in dev, Caddy in prod), so there's no CORS and the backend is untouched.
The level/branch/log "game brain" is computed in the browser from the raw feed.

## Develop
```bash
# 1) run the Phase 1 host API (from the repo root)
SIDEKICK_VAULT=/path/to/vault SIDEKICK_API_TOKEN=dev-token \
  python3 -m uvicorn server.app:create_app --factory --port 8000 --workers 1
# 2) run the web app (from web/)
npm install
npm run dev
```
Open the Vite URL it prints. Vite proxies `/api/*` → `http://127.0.0.1:8000`. On first
load you'll land on **Settings** — paste `dev-token` — then the Dashboard loads.

## Test
```bash
npm test                       # Vitest unit + component
npx playwright install chromium && npm run e2e   # Playwright end-to-end
```

## Build & deploy (prod)
```bash
npm run build                  # static output in web/build/
```
Serve `web/build` and proxy `/api` to the host API with the same web server. Example
`Caddyfile` (one origin → no CORS, installable PWA):
```
sidekick.example.com {
    handle /api/* {
        uri strip_prefix /api
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        root * /srv/sidekick/web/build
        try_files {path} /index.html
        file_server
    }
}
```

## Install on iPhone
Open the site in Safari → Share → **Add to Home Screen**. The app installs with its own
icon and opens standalone; it caches the shell + last feed so it opens offline (writes
still need a connection in this version).
````

- [ ] **Step 2: Add a pointer from the root `README.md`**

In the root `README.md`, in the "Honest state & what's actually left" section, append to the same final paragraph that already references Phase 1:

```markdown
Phase 2 — the installable SvelteKit PWA front end — lives in `web/` (`web/README.md`; design: `docs/superpowers/specs/2026-06-20-sidekick-phone-app-phase2-pwa-design.md`).
```

- [ ] **Step 3: Verify**

```bash
grep -q "Sidekick web" web/README.md && echo "OK: web README" || echo "FAIL"
grep -q "web/README.md" README.md && echo "OK: root pointer" || echo "FAIL"
cd web && npm test && npm run build && cd ..
python3 -m unittest discover -s tests && python3 -m pytest server/tests -q
```
Expected: two `OK:` lines; the web unit suite + build green; the untouched Python suites (11 root + 18 server) still green.

- [ ] **Step 4: Commit**

```bash
git add web/README.md README.md
git commit -m "docs(web): run/deploy guide for the PWA; pointer from root README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Notes for the executor

- **Run everything from `web/`** unless a step says repo root. The Python backend is **not modified** by any task — if you find yourself editing `server/` or `sidekick.py`, stop: it's out of scope.
- **Svelte 5 runes** (`$state`, `$derived`, `$props`, `$effect`) are used throughout — this is current SvelteKit. If `@testing-library/svelte` needs a specific Svelte-5 import style, follow its current docs; the component contracts (props, roles, labels) are what the tests assert.
- **If `npm install` resolves a major version that breaks a config** (e.g. a Vite/SvelteKit/PWA-plugin mismatch), reconcile to a compatible set — the deliverable is "`npm run build` + `npm test` green," not the exact version pins.
- **The dev proxy targets `127.0.0.1:8000`** — that's where Task-1-of-Phase-1's API runs locally. Tests never hit a real backend (fetch is mocked in unit tests; `page.route` in e2e).

## Self-Review (completed during authoring)

- **Spec coverage:** §3 framework/adapter/proxy → Task 1; §5.2 game brain → Task 2; §5.3 api client + token store → Task 3; §5.4 Dashboard/Complete/Capture/Settings → Tasks 4–7; §5.5 PWA/offline → Task 8; §5.6 dev/prod serving → Tasks 1 & 10; §7 error handling (401→Settings, offline, optimistic rollback, validation) → Tasks 3–6; §8 testing (game unit, component, e2e, installability) → Tasks 2,4,5,6,7,8,9; §9 integrity (backend untouched, derived client-side) → Global Constraints + verified in Tasks 4 & 10. Parked items (offline writes, Capacitor) correctly excluded.
- **Placeholder scan:** every code/config/command step is concrete; no TBD/"handle errors"/"similar to".
- **Type consistency:** `Feed`/`ActiveTask`/`LedgerEvent`/`Category` (types.ts) are used identically across game.ts, api.ts, and components; `getFeed`/`createTask(title,category)`/`completeTask(id,completedAt)` and `CompleteResult` match between api.ts and its callers; `Dashboard` props `{feed,onComplete,pending}` match between Task 4 (defined), Task 5 (button uses them), and `+page.svelte` (passes them); `settings` store shape `{token,apiBase}` matches across settings.ts, api.ts, and the Settings route.
