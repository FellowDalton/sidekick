# Sidekick — one app, Chrome new tab as the front page

**Date:** 2026-06-18
**Status:** Approved (design), pending implementation plan
**Scope:** Make the Chrome new-tab dashboard work reliably as the app's front page (wired to live data, correctly placed, MV3-clean), collapse the duplicated render logic into one shared brain, and add the bounded "one app" polish (a `sidekick` command + a `setup.sh`). No rewrite, no always-on process, no new dependencies.

---

## 1. Why

Two problems, one root cause.

The Chrome new-tab piece is currently broken: `manifest.json`, `newtab.html`, `newtab.js` sit loose in the repo root and are untracked, but `sidekick.py regenerate` only writes the extension's data feed into a `chrome-extension/` subfolder *if that folder exists* — which it doesn't. And `newtab.js` `fetch`es `sidekick-data.json` (a `{events, active}` JSON), while `sidekick.py` generates `sidekick-data.js` (a `window.SIDEKICK = …` script) for the standalone page. So the new tab would render the "No data yet" fallback.

The root cause is duplication: the render logic (`BRANCHES`, `progress()`, `render()`) exists twice — inline in `sidekick.html` and again in `newtab.js` — fed by two different data formats. Patching the JSON wiring would leave the two copies to drift. Collapsing to **one render brain + one data format** fixes the breakage *and* delivers the user's actual goal ("put it together as one app").

A hard constraint shapes the solution: **Chrome MV3 forbids inline `<script>` on extension pages.** `sidekick.html`'s current inline render block cannot be reused inside the extension. The render logic must live in an external `.js` file regardless — which is exactly what a shared brain requires. The two constraints point the same way.

## 2. Goals / non-goals

**Goals**
- Opening a new Chrome tab shows the real, current dashboard (live tasks + ledger), with zero manual step after a `regenerate`.
- One render implementation and one data format feed both surfaces (standalone `sidekick.html` and the extension's new tab).
- Installing and operating the whole system feels like one tool: a `sidekick` command and a one-shot `setup.sh`.
- Docs (`README.md`, `CLAUDE.md`, in-page foot-notes) match the real layout.

**Non-goals (YAGNI)**
- No always-on server/daemon (rejected approach C). The system stays "files on disk + a scheduled push."
- No publishing to the Chrome Web Store; "Load unpacked" remains the install path.
- No new runtime dependencies (still just `pyyaml`).
- No change to the ledger/plan data contract, the scoring curves, or the nudge logic.
- No collapsing the deliberately-separate parts (view vs. data, ledger-writer vs. orchestrator, launchd vs. CLI).

## 3. Architecture

Canonical sources live at the repo root. The extension folder is a self-contained surface that `regenerate` keeps fresh by copying the two moving files into it. The only hand-written file inside the extension is `manifest.json`.

```
sidekick/                         (vault root = git repo)
├── sidekick.py                   CLI + assembler  (edited: §4.4 copy step)
├── ledger.jsonl                  append-only completed-task log (unchanged)
├── tasks/*.md                    open tasks (unchanged)
├── sidekick-render.js            NEW — the single render brain (§4.1)
├── sidekick-data.js              generated feed  window.SIDEKICK = {events, active}
├── sidekick.html                 standalone shell (edited: §4.2)
├── chrome-extension/             NEW folder
│   ├── manifest.json             committed, hand-written (moved from root)
│   ├── newtab.html               committed thin shell (moved + rewritten, §4.3)
│   ├── sidekick-render.js        COPIED in by regenerate  (gitignored)
│   └── sidekick-data.js          COPIED in by regenerate  (gitignored)
├── nudge.py / install-nudge.sh / nudge.config.example.json   (unchanged)
├── sidekick                      NEW — shell wrapper on PATH (§4.5)
├── setup.sh                      NEW — interactive bring-up (§4.6)
├── .gitignore                    edited: ignore generated copies in chrome-extension/
├── README.md / CLAUDE.md         edited: §4.7
└── docs/superpowers/specs/…      this spec
```

`newtab.js` (root) is **deleted** — its logic moves into the shared brain.

## 4. Components

Each unit below states *what it does*, *how it's used*, and *what it depends on*.

### 4.1 `sidekick-render.js` — the render brain (NEW)
- **Does:** Reads `window.SIDEKICK` and renders the dashboard (hero/level arc, active tasks + plans, skill branches, recent log). Extracted **verbatim** from the existing `sidekick.html` inline script — same `BRANCHES`, `progress()`, curves, `LEVEL_WORDS`, helpers, and `render()`. Keeps the existing "couldn't load data" fallback so a missing feed degrades gracefully.
- **Used by:** Both `sidekick.html` and `chrome-extension/newtab.html`, each via `<script src="sidekick-render.js"></script>` *after* the data script.
- **Depends on:** `window.SIDEKICK` being defined by a preceding `<script src="sidekick-data.js">`; the DOM ids/classes in the shell markup; the CSS custom properties (`--h-*`, etc.) defined in each shell's `<style>`.
- **Source of truth:** This file is based on the `window.SIDEKICK` (script-tag) variant in `sidekick.html`, **not** the `fetch()` variant in `newtab.js`. The fetch variant is retired.

### 4.2 `sidekick.html` — standalone surface (EDITED)
- **Change:** Replace the large inline `<script>…render…</script>` with two tags:
  `<script src="sidekick-data.js"></script>` then `<script src="sidekick-render.js"></script>`.
- **Also:** Fix the stale foot-note ("open tasks come from Google Tasks") → vault-backed wording; keep the `python3 -m http.server` hint for `file://` users.
- **Unchanged:** All markup, CSS, and the data contract.

### 4.3 `chrome-extension/newtab.html` — new-tab surface (MOVED + REWRITTEN)
- **Does:** The new-tab page. Same markup + `<style>` as `sidekick.html` (the visual is identical), but the body ends with the same two external script tags (§4.1). No inline script (MV3).
- **Foot-note:** Extension-appropriate (data refreshes on `regenerate` in the vault; nothing here is editable). No `http.server` hint — irrelevant in the extension.
- **Depends on:** `sidekick-render.js` and `sidekick-data.js` being present *in the same folder* (Chrome can only package files inside the extension root — it cannot reach `../`). Those two are supplied by `regenerate` (§4.4).

### 4.4 `sidekick.py regenerate` — the wiring (EDITED)
- **Today:** writes `sidekick-data.js` at root; *conditionally* writes `chrome-extension/sidekick-data.json` (the now-retired JSON format).
- **Change:** Keep writing root `sidekick-data.js`. Then, **if `chrome-extension/` exists**, atomically copy the freshly-written `sidekick-data.js` into it, and copy the canonical root `sidekick-render.js` into it too (so the extension's render brain never drifts from the standalone's). Remove the `.json` branch entirely.
- **Atomicity:** Write to a `.tmp` in the destination and `os.replace()` — same pattern already used for the root feed, so a half-written file is never served.
- **Determinism preserved:** still no model in the write path; pure file I/O.

### 4.5 `sidekick` — command wrapper (NEW)
- **Does:** A ~15–25 line POSIX shell script that dispatches subcommands to the two Python tools, resolving paths relative to its own location so it works from anywhere on `PATH`:
  - `sidekick new|set-plan|complete|regenerate` → `python3 sidekick.py …`
  - `sidekick nudge [--dry-run]` → `python3 nudge.py run …`
  - `sidekick nudge-test "<text>"` / `sidekick find-chat "<q>"` → `nudge.py test|find-chat`
  - `sidekick nudge-install [H M]` → `./install-nudge.sh`
  - `sidekick setup` → `./setup.sh`
  - bare/`help` → usage.
- **Used by:** The human, ergonomically. Pure pass-through; changes nothing underneath.
- **Depends on:** `python3` on PATH; the two scripts beside it.

### 4.6 `setup.sh` — one-shot bring-up (NEW)
- **Does:** Interactive, idempotent bring-up: check `python3`; ensure `pyyaml` (offer `pip install`); seed an example task if `tasks/` is empty + `regenerate`; copy `nudge.config.example.json`→`nudge.config.json` if absent and prompt for the Beeper token; run `nudge.py find-chat` and capture the chat id; offer `install-nudge.sh`; finally print the exact "chrome://extensions → Developer mode → Load unpacked → pick `chrome-extension/`" steps. Every step is skippable and safe to re-run.
- **Depends on:** the scripts and `pyyaml`; never writes the ledger.

### 4.7 Docs (EDITED)
- `README.md`: correct the layout (extension lives in `chrome-extension/`, `newtab.js` retired in favour of the shared `sidekick-render.js`, `regenerate` copies both moving files in), and document `sidekick` + `setup.sh`.
- `CLAUDE.md`: note the shared render brain and that `regenerate` syncs the extension folder; nothing else in the routine changes.
- In-page foot-notes: drop "Google Tasks".

### 4.8 `.gitignore` (EDITED)
- Ignore `chrome-extension/sidekick-data.js` and `chrome-extension/sidekick-render.js` (generated copies). Commit `chrome-extension/manifest.json` and `chrome-extension/newtab.html`.

## 5. Data flow

```
tasks/*.md  +  ledger.jsonl
        │  (sidekick.py regenerate — deterministic)
        ▼
   sidekick-data.js  (window.SIDEKICK = {events, active})   ── root
        │                                   └── copied ──┐
        ▼                                                ▼
  sidekick.html  ──┐                         chrome-extension/sidekick-data.js
                   │  both load                          │
  sidekick-render.js (root) ── copied ──► chrome-extension/sidekick-render.js
                   │                                      │
                   ▼                                      ▼
        standalone dashboard                  new-tab dashboard (Chrome)
```

One generator, one format, one render brain → two surfaces.

## 6. Error handling / edge cases
- **No feed yet:** the shared brain shows the existing "run `regenerate`" fallback on both surfaces.
- **`chrome-extension/` absent:** `regenerate` simply skips the copy (standalone still works) — same defensive shape as today.
- **MV3 CSP:** no inline scripts anywhere; remote Google-Fonts `<link>` stays (styles/fonts aren't restricted by the default extension-page CSP, and the page degrades to a system serif if blocked).
- **Stale tab content:** a tab open *before* a `regenerate` keeps old data until the next new tab — acceptable; new tabs are cheap and frequent.
- **`setup.sh` partial/re-run:** each step guards on existing state; re-running is safe.

## 7. Verification (acceptance)
1. **Unpacked-reload assumption (the one open risk):** load `chrome-extension/` unpacked → open a new tab (real dashboard renders) → `sidekick.py complete <id>` (or `regenerate`) → open *another* new tab → it reflects the change **without** clicking "Reload" on the extension. If this fails, fall back to documenting a one-time reload, or revisit the feed mechanism — but expectation is it passes.
2. Standalone `sidekick.html` renders identically to before the refactor (visual diff: hero, branches, plans, log).
3. `newtab.js` is gone and nothing references it; `grep` finds no `sidekick-data.json` consumer.
4. `sidekick regenerate` leaves root + `chrome-extension/` feeds byte-identical; `sidekick new "x" --category chore` then `complete` updates both.
5. `sidekick help`, `sidekick nudge --dry-run`, and a dry `setup.sh` run without error.
6. `git status` shows the generated extension copies ignored; only static files tracked.

## 8. Risks
- **Primary:** the unpacked-reload behavior (§7.1) — mitigated by being the first build check, with a documented fallback.
- **Minor:** shell-wrapper path resolution across `sh`/`zsh`/symlinks — handled by resolving the script's own dir; covered by §7.5.

## 9. Out of scope (parked)
Reply-"done"-to-complete via Beeper; a lighter new-tab variant; the `raw/` → wiki loop; Web-Store packaging. None block this work.
