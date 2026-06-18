# Sidekick

An ADHD execution-support system. It solves the _doing_ problem, not the planning problem — it does the legwork while you stay the protagonist. Solo by design (no second user, no shared dashboards). The game layer is paint that makes opening it feel good; the orchestrator and the nudge are the engine that keeps it useful.

> **This file is the map.** What you have is already one app: a single git-tracked vault folder with one CLI, two view surfaces, and one scheduled push. "Bringing it together" means a shared mental model plus a couple of thin wrappers — **not** a rewrite. The parts are deliberately decoupled (see _What to keep separate_); collapsing them into a monolith would throw that away. `CLAUDE.md` holds the agent's operating rules; this is the human overview and bring-up plan.

---

## The pieces

| File / folder       | What it is                                                                                                          | Written by                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `tasks/*.md`        | Open tasks. One markdown file each; metadata (category, created, status, plan) in YAML frontmatter.                 | `sidekick.py`, or you in Obsidian |
| `ledger.jsonl`      | Completed tasks. Append-only, one JSON event per line. The game's spine.                                            | `sidekick.py complete` **only**   |
| `sidekick.py`       | The CLI + assembler. `new` / `set-plan` / `complete` / `regenerate`. Deterministic — no LLM in it.                  | —                                 |
| `sidekick-data.js`  | Generated feed for the standalone dashboard (`window.SIDEKICK = …`).                                                | `sidekick.py regenerate`          |
| `sidekick-render.js` | The single dashboard render logic. Loaded by both `sidekick.html` and the extension's `newtab.html`. | — |
| `sidekick.html`     | The dashboard (level, branches, open tasks + prepared plans, recent log). Static; reads the feed.                   | —                                 |
| `chrome-extension/` | New-tab dashboard: `manifest.json` + `newtab.html` (a thin shell). Reads the same `sidekick-data.js` + shared `sidekick-render.js`, mirrored in by `regenerate`. | `regenerate` syncs both files |
| `nudge.py`          | The "comes at you" push. Decides (Claude, or deterministic fallback) and sends via Beeper → iMessage.               | —                                 |
| `install-nudge.sh`  | Installs `nudge.py` as a launchd agent that fires daily.                                                            | —                                 |
| `nudge.config.json` | Token, chat id, knobs. **Gitignored.** Copy from `nudge.config.example.json`.                                       | you                               |
| `CLAUDE.md`         | Operating rules for Claude Code (the one-rule, the routine, the don'ts).                                            | —                                 |
| `.gitignore`        | Keeps the token and logs out of git.                                                                                | —                                 |

---

## How it flows

```
            capture (Claude Code, or edit a file in Obsidian)
                              │
                              ▼
                        tasks/<id>.md  ──────────────┐
                              │                      │
              orchestrator (LLM) researches          │
              and writes a plan → set-plan           │
                              │                      │
                              ▼                      ▼
   complete ──► ledger.jsonl          sidekick.py regenerate
                    │                         │
                    │                  ┌──────┴───────┐
                    └──────────────────►              ▼
                              sidekick-data.js   chrome-extension/  (feed + render synced)
                                     │                    │
                                     ▼                    ▼
                              sidekick.html         new-tab dashboard
                              (Mac / served)        (Chrome)

   launchd (9am) ──► nudge.py ──► decide ──► Beeper API ──► iMessage ──► your phone
                                  (Claude, else deterministic; silent if nothing stalled)
```

The one invariant that makes everything else safe: **levels and branches are _derived_ from the raw ledger at read time, never stored.** Keep the raw events and you can recompute any scoring scheme later. Nothing but `complete` writes the ledger, and no model is ever in that write path.

---

## Bring-up from zero

Each step is independent — stop after any one and you have a working subset.

**0. Prerequisites.** `python3` with `pyyaml` (`pip install pyyaml`). A folder you'll make a git repo (the vault). Optional but intended: Obsidian (to browse), Chrome (new-tab dashboard), Claude Code (the motor + orchestrator), Beeper Desktop with iMessage on macOS (the nudge channel).

**1. The vault.** Put `sidekick.py`, `ledger.jsonl`, `sidekick.html`, `CLAUDE.md`, `.gitignore`, the `tasks/` and `chrome-extension/` folders, and the nudge files in one folder. `git init`. That folder _is_ the app.

**2. Seed it.**

```
python sidekick.py new "Call the dentist" --category phone
python sidekick.py regenerate
```

**3. A dashboard** — pick either or both:

- _Standalone:_ open `sidekick.html` in a browser. (If it can't load the feed over `file://`, serve the folder: `python3 -m http.server`.)
- _New tab:_ run `python sidekick.py regenerate` once (so `chrome-extension/` has its feed), then `chrome://extensions` → Developer mode → **Load unpacked** → pick `chrome-extension/`. Every new tab is the live dashboard; it refreshes on the next `regenerate`.

**4. The nudge** (the load-bearing piece — do this last, but do it):

1. Beeper: Settings → Integrations → Approved connections → **+** → make a token.
2. `cp nudge.config.example.json nudge.config.json`, paste the token.
3. `python nudge.py find-chat "<your name>"` → paste your self-chat `id` into the config.
4. `python nudge.py run --dry-run` (decides, prints, sends nothing) → `python nudge.py test "hi"` (confirms it reaches your phone).
5. `./install-nudge.sh 9 0` (daily at 09:00).

---

## The daily loop

Sunday: brain-dump becomes tasks (`new`). During the week: when something needs research, the orchestrator preps a plan (`set-plan`) so the hard first step is done. Each morning: the nudge surfaces one genuinely-stalled task with its first step — or stays quiet. You act, then `complete`, and the dashboard climbs. The dashboard is the passive "feel good / what's next" surface; the nudge is the active "do this now."

---

## Make it feel like one app (optional, bounded)

If you want the surface to feel unified without re-architecting:

1. **One command.** `sidekick` on your `PATH` dispatches to both scripts: `sidekick new …`, `sidekick regenerate`, `sidekick nudge`, `sidekick nudge-install`, `sidekick setup`. Run `sidekick help` for the full list. Pure ergonomics; changes nothing underneath.
2. **One setup.** `./setup.sh` runs the whole bring-up interactively (checks deps, installs pyyaml, regenerates, seeds the Beeper config, runs `find-chat`, optionally installs the agent, and prints the Load-unpacked steps). Idempotent and skippable.

Put the repo dir on your `PATH` (or symlink `sidekick` into one) and `sidekick` works from anywhere.

### What to keep separate (and why)

- **View vs. data** — the static HTML never changes when data changes; that decoupling means the whole backend can be swapped without touching the dashboard.
- **Ledger writer (code) vs. orchestrator (LLM)** — an earned points total must never become "whatever the model last summarized." Code writes the ledger; the model only ever drops a finished plan into a task.
- **Nudge job (launchd) vs. the CLI** — a push has to fire unprompted; a Claude Code session can't. They're different runtimes on purpose.

---

## Deliberately not here

No Google anything (the OAuth death-point is gone). No shared or wife-facing features — solo by decision, not limitation. No mechanical game perks yet (cosmetic only; the full event history is stored so they can be added later). The LLM-wiki pattern is reserved for the orchestrator's fuzzy life-knowledge (`raw/`, deferred), never the integrity-critical ledger.

---

## Honest state & what's actually left

Everything is built and verified except the three things that need your Mac: the live `claude -p` call, the real Beeper send, and launchd's environment. The first scheduled run is where the classic launchd gotchas bite (`claude` or `pyyaml` not on the agent's PATH) — which is exactly why the nudge has a deterministic fallback and writes `nudge.log`. Do one `--dry-run` and one `test` before trusting the 9am job.

The genuinely open work is **not** more building — it's behavioural. Whether a nudge actually moves you is, by your own track record, unproven. Treat `min_sat_hours`, the wording, and the timing as dials, and watch honestly over a few weeks whether the nudge becomes wallpaper. Optional later additions: reply-"done"-to-complete (Beeper can read messages, so the nudge becomes the action surface); a lighter new-tab variant; and the `raw/` → wiki compilation loop once there's a real pile of context. None are urgent, and "unify it further" is the kind of pleasant, infinite task the system was built to protect you from — the map is done; the dials are the work.
