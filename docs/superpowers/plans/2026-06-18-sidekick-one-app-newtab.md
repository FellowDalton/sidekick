# Sidekick — One App + Chrome New-Tab Front Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Chrome new tab open on a live Sidekick dashboard, fed by one shared render brain and the existing deterministic generator, plus a `sidekick` command and a `setup.sh` so the whole thing installs and runs like one tool.

**Architecture:** Extract the duplicated dashboard render logic into a single `sidekick-render.js`. Both the standalone `sidekick.html` and the extension's `chrome-extension/newtab.html` become thin shells that load `sidekick-data.js` (`window.SIDEKICK`) then `sidekick-render.js`. `sidekick.py regenerate` writes the root feed and mirrors both moving files (`sidekick-data.js` + `sidekick-render.js`) into `chrome-extension/`, so every new tab is live with no manual step. A `sidekick` shell wrapper and `setup.sh` add ergonomics without changing anything underneath.

**Tech Stack:** Plain HTML/CSS/JS (no framework, no build), Python 3 + `pyyaml` (already present), POSIX shell, Chrome MV3 (`chrome_url_overrides.newtab`), `unittest` (stdlib) for the one piece of real Python logic.

## Global Constraints

- No new runtime dependencies — Python deps stay exactly `pyyaml`. Tests use stdlib `unittest` only (no pytest).
- No always-on server/daemon. The system stays "files on disk + the scheduled nudge."
- `sidekick.py` stays deterministic — no model logic in any write path; `complete` remains the sole writer of `ledger.jsonl`.
- Chrome MV3: **no inline `<script>` on extension pages.** All page JS is external `.js` files loaded with `<script src>`.
- One render implementation only — `sidekick-render.js`. Reading `window.SIDEKICK`. The old `fetch("sidekick-data.json")` path and `newtab.js` are retired, not kept "just in case."
- The extension must be self-contained: it can only load files inside `chrome-extension/` (Chrome cannot reach `../`). The two moving files are supplied there by `regenerate`.
- Atomic writes everywhere `regenerate` touches disk: write `*.tmp`, then `os.replace()`.
- Generated copies inside `chrome-extension/` (`sidekick-data.js`, `sidekick-render.js`) are git-ignored; only `manifest.json` + `newtab.html` are committed there.
- Commit messages end with the repo's co-author trailer:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Work happens on branch `feat/one-app-newtab` (already checked out).

## File Structure (after this plan)

```
sidekick/                         (vault root = git repo, branch feat/one-app-newtab)
├── sidekick.py                   EDITED (Task 3) — regenerate mirrors feed+render into chrome-extension/
├── ledger.jsonl                  unchanged
├── tasks/*.md                    SEEDED (Task 2.5) — 4 demo tasks backing the active list
├── sidekick-render.js            NEW (Task 1) — the single render brain
├── sidekick-data.js              generated; unchanged format (window.SIDEKICK)
├── sidekick.html                 EDITED (Task 1) — thin shell, foot-note fixed
├── chrome-extension/             NEW (Task 2)
│   ├── manifest.json             committed (moved from root)
│   ├── newtab.html               committed thin shell (Task 2)
│   ├── sidekick-render.js        generated copy (Task 3); git-ignored
│   └── sidekick-data.js          generated copy (Task 3); git-ignored
├── sidekick                      NEW (Task 4) — command wrapper, +x
├── setup.sh                      NEW (Task 5) — one-shot bring-up, +x
├── tests/test_regenerate.py      NEW (Task 3) — stdlib unittest
├── .gitignore                    NEW (Task 2)
├── nudge.py / install-nudge.sh / nudge.config.example.json   unchanged (committed in Task 6)
├── README.md / CLAUDE.md         EDITED (Task 6)
└── docs/superpowers/{specs,plans}/…   this plan + the spec
```

Deleted in Task 2: root `newtab.js`, root `newtab.html`, root `manifest.json` (all currently untracked — plain `rm`).

---

### Task 1: Shared render brain + standalone shell

Extract the inline render script from `sidekick.html` into `sidekick-render.js` (verbatim — this is a move, not a rewrite), point `sidekick.html` at it, and fix the stale "Google Tasks" foot-note. Deliverable: `sidekick.html` renders exactly as before, but its logic now lives in the shared file.

**Files:**
- Create: `sidekick-render.js`
- Modify: `sidekick.html` (inline `<script>` at lines 175–298; foot-note at lines 166–170)

**Interfaces:**
- Produces: `sidekick-render.js` — a standalone script that, when loaded **after** a `<script src="sidekick-data.js">` and at the end of `<body>`, reads `window.SIDEKICK = {events, active}` and renders into the page's existing DOM ids (`asOf`, `level`, `levelWord`, `heroStats`, `arc`, `active`, `activeCount`, `branches`, `log`). Self-invokes `render()` at the bottom. Shows a "couldn't load the feed" fallback if `window.SIDEKICK` is undefined.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Extract the inline script body verbatim into `sidekick-render.js`**

The inline script body is `sidekick.html` lines 176–297 (everything between `<script>` on line 175 and `</script>` on line 298). Extract it exactly:

```bash
cd /Users/dalton/projects/sidekick
sed -n '176,297p' sidekick.html > sidekick-render.js
```

- [ ] **Step 2: Verify the extracted file's boundaries**

Run: `head -3 sidekick-render.js && echo '...' && tail -3 sidekick-render.js`
Expected — first lines:
```
/* Data is provided by sidekick-data.js as window.SIDEKICK (see that file for the contract). */
const EVENTS = (window.SIDEKICK && window.SIDEKICK.events) || [];
const ACTIVE = (window.SIDEKICK && window.SIDEKICK.active) || [];
```
Expected — last lines:
```
  });
}
render();
```
If the boundaries differ (e.g. a stray `<script>`/`</script>` tag was captured), re-check the line numbers in `sidekick.html` and redo Step 1. `sidekick-render.js` must contain **no** `<script>` tags.

- [ ] **Step 3: Replace the inline script in `sidekick.html` with two external tags**

In `sidekick.html`, the tail currently reads:
```html
<script src="sidekick-data.js"></script>
<script>
/* Data is provided by sidekick-data.js as window.SIDEKICK (see that file for the contract). */
const EVENTS = (window.SIDEKICK && window.SIDEKICK.events) || [];
...
render();
</script>
</body>
</html>
```
Replace the entire inline `<script>…</script>` block (lines 175–298) so the tail becomes:
```html
<script src="sidekick-data.js"></script>
<script src="sidekick-render.js"></script>
</body>
</html>
```
(Keep line 174's `<script src="sidekick-data.js"></script>` as-is; only the inline block is removed.)

- [ ] **Step 4: Fix the stale foot-note in `sidekick.html`**

Replace the foot-note (lines 166–170). Old:
```html
  <p class="foot-note">
    Levels and branches are computed from <code>ledger.jsonl</code>; open tasks come from Google Tasks.
    Both arrive via <code>sidekick-data.js</code>. Nothing here is stored or editable — complete tasks in
    Claude Code or the Tasks app, and they move into the ledger.
  </p>
```
New:
```html
  <p class="foot-note">
    Levels and branches are computed from <code>ledger.jsonl</code>; open tasks come from your
    <code>tasks/*.md</code> files. Both arrive via <code>sidekick-data.js</code>. Nothing here is stored or
    editable — complete tasks in Claude Code, and they move into the ledger.
  </p>
```

- [ ] **Step 5: Verify the standalone dashboard renders identically (in-session browser check)**

The repo already has a populated `sidekick-data.js`. Serve and open the page (use the existing `claude-in-chrome` tools, or do it manually):
```bash
cd /Users/dalton/projects/sidekick && python3 -m http.server 8765 >/tmp/sk_http.log 2>&1 &
```
Open `http://localhost:8765/sidekick.html`. Confirm:
- Hero shows a level numeral + arc, "N tasks cleared".
- "In front of you" lists the 4 active tasks with their plans.
- "Skill branches" shows lit branches (Diplomat/Pathfinder/Hearthkeeper/etc.).
- "Recently cleared" lists recent log rows.
- **Browser console has zero errors.**

Stop the server when done: `kill %1` (or `pkill -f "http.server 8765"`).
Expected: visually identical to before the refactor; no console errors.

- [ ] **Step 6: Commit**

```bash
cd /Users/dalton/projects/sidekick
git add sidekick-render.js sidekick.html
git commit -m "$(printf 'refactor: extract shared render brain into sidekick-render.js\n\nStandalone dashboard now loads sidekick-data.js + sidekick-render.js\ninstead of an inline script; foot-note updated to the vault-backed model.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 2: Chrome extension folder (static files) + cleanup + gitignore

Create the self-contained `chrome-extension/` folder with the only two hand-written files (`manifest.json`, `newtab.html`), remove the misplaced loose root files, and add a `.gitignore`. Deliverable: a loadable extension shell (it will show the "no feed yet" fallback until Task 3 supplies the data — that's expected and verified here).

**Files:**
- Create: `chrome-extension/manifest.json` (moved from root `manifest.json`)
- Create: `chrome-extension/newtab.html` (new thin shell, based on `sidekick.html`)
- Create: `.gitignore`
- Delete: root `newtab.js`, root `newtab.html`, root `manifest.json` (untracked → plain `rm`)

**Interfaces:**
- Consumes: `sidekick.html` from Task 1 (copied as the shell, so it already loads `sidekick-data.js` + `sidekick-render.js`).
- Produces: `chrome-extension/` containing `manifest.json` (MV3, `chrome_url_overrides.newtab → newtab.html`) and `newtab.html` (thin shell). Task 3 fills the folder with the two generated files.

- [ ] **Step 1: Create the folder and move `manifest.json` into it**

```bash
cd /Users/dalton/projects/sidekick
mkdir -p chrome-extension
mv manifest.json chrome-extension/manifest.json
```

- [ ] **Step 2: Confirm the manifest is MV3 + new-tab override (no edit expected)**

Run: `cat chrome-extension/manifest.json`
Expected:
```json
{
  "manifest_version": 3,
  "name": "Sidekick",
  "version": "1.0.0",
  "description": "Your Sidekick dashboard as Chrome's new tab.",
  "chrome_url_overrides": { "newtab": "newtab.html" }
}
```
This is correct as-is (MV3, points at `newtab.html`, no inline scripts, no extra permissions). Leave it unchanged.

- [ ] **Step 3: Create `chrome-extension/newtab.html` from the Task-1 shell**

`sidekick.html` is now a thin shell that loads the two external scripts. Copy it as the new-tab page, then give it an extension-appropriate foot-note:

```bash
cd /Users/dalton/projects/sidekick
cp sidekick.html chrome-extension/newtab.html
```

Then in `chrome-extension/newtab.html`, replace the foot-note (the `<p class="foot-note">…</p>` block) with:
```html
  <p class="foot-note">
    Levels and branches are computed from <code>ledger.jsonl</code>; open tasks come from your
    <code>tasks/*.md</code> files. The dashboard refreshes whenever <code>sidekick regenerate</code> runs in
    your vault — open a fresh tab to see the latest. Nothing here is stored or editable.
  </p>
```

The script tags at the tail must already be (inherited from the copy):
```html
<script src="sidekick-data.js"></script>
<script src="sidekick-render.js"></script>
</body>
</html>
```
Confirm with: `tail -4 chrome-extension/newtab.html` — expect exactly those four lines. There must be **no** inline `<script>` (MV3 forbids it).

- [ ] **Step 4: Remove the misplaced loose root files**

These are untracked leftovers now superseded:
```bash
cd /Users/dalton/projects/sidekick
rm -f newtab.js newtab.html
```
(`manifest.json` already moved in Step 1.)
Run: `ls newtab.js newtab.html manifest.json 2>&1` — expect "No such file or directory" for all three at the root.

- [ ] **Step 5: Create `.gitignore`**

There is no `.gitignore` yet. Create it:
```
# secrets & logs
nudge.config.json
nudge.log

# generated copies mirrored into the extension by `sidekick.py regenerate`
chrome-extension/sidekick-data.js
chrome-extension/sidekick-render.js

# atomic-write temp files
*.tmp
```

- [ ] **Step 6: Verify the extension shell loads (fallback expected, no feed yet)**

Open `file:///Users/dalton/projects/sidekick/chrome-extension/newtab.html` in the browser (no data files in the folder yet). Expected: the graceful fallback paragraph ("No data yet — run `python sidekick.py regenerate`…" / "Couldn't load `sidekick-data.js`…"), **not** a blank page or a thrown error. This confirms the shell + shared brain degrade correctly. Task 3 supplies the feed.

- [ ] **Step 7: Commit**

```bash
cd /Users/dalton/projects/sidekick
git add .gitignore chrome-extension/manifest.json chrome-extension/newtab.html
git commit -m "$(printf 'feat: chrome-extension/ shell (manifest + newtab) and .gitignore\n\nMoves the new-tab extension into a self-contained chrome-extension/ folder\n(the only hand-written files are manifest.json + newtab.html, a thin shell\nmirroring sidekick.html). Removes the misplaced loose root files. Adds a\n.gitignore for the nudge secret/log, the generated extension copies, and tmp files.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 2.5: Seed the four demo tasks

Create the `tasks/*.md` files that back the four sample active tasks, so that once `regenerate` rebuilds the feed from real files (Task 3) the "In front of you" list stays populated instead of going empty. These reproduce the active entries currently hard-coded in `sidekick-data.js`. Deliverable: `read_active()` returns the four tasks with their plans.

**Files:**
- Create: `tasks/20260613-sort-the-car-insurance-renewal.md`
- Create: `tasks/20260616-book-the-kids-dentist-check-up.md`
- Create: `tasks/20260609-replace-the-bathroom-extractor-fan.md`
- Create: `tasks/20260615-renew-your-passport.md`

**Interfaces:**
- Consumes: nothing from other tasks (frontmatter schema is in `sidekick.py`'s `read_active`/`read_note`).
- Produces: four open task files. `read_active()` returns them sorted longest-sitting first; three carry a `plan`, the passport one does not. Task 3 regenerates the feed from these.

- [ ] **Step 1: Create the four task files (exact content)**

`tasks/20260613-sort-the-car-insurance-renewal.md`:
```markdown
---
category: admin
created: 2026-06-13T10:00:00Z
status: open
plan:
  summary: Compared three renewal quotes — your current insurer is no longer the cheapest.
  steps:
    - text: Call Topdanmark on 70 11 50 50 and ask them to match the lower quote
      href: tel:+4570115050
    - text: If they won't match, switch to the Alm. Brand quote
      href: https://www.almbrand.dk
    - text: Cancel the old direct debit once the switch confirms
---

# Sort the car insurance renewal
```

`tasks/20260616-book-the-kids-dentist-check-up.md`:
```markdown
---
category: phone
created: 2026-06-16T12:00:00Z
status: open
plan:
  summary: Found the clinic's online booking — two slots open next week.
  steps:
    - text: Open the booking page
      href: https://example-dentist.dk/book
    - text: Take the Tuesday 15:30 slot
    - text: Add it to the family calendar
---

# Book the kids' dentist check-up
```

`tasks/20260609-replace-the-bathroom-extractor-fan.md`:
```markdown
---
category: chore
created: 2026-06-09T20:00:00Z
status: open
plan:
  summary: Shortlisted two fans that fit a 100 mm duct, both under 400 kr.
  steps:
    - text: Measure the existing duct to confirm it's 100 mm
    - text: Order the Vortice Punto
      href: https://example.com/vortice-punto
    - text: Book the handyman for fitting
---

# Replace the bathroom extractor fan
```

`tasks/20260615-renew-your-passport.md`:
```markdown
---
category: admin
created: 2026-06-15T16:00:00Z
status: open
---

# Renew your passport
```

- [ ] **Step 2: Verify `read_active()` returns the four tasks (write-free check)**

Run (imports the module to call `read_active()` in-process — no files written):
```bash
cd /Users/dalton/projects/sidekick && python3 -c "import sidekick, json; a=sidekick.read_active(); print(len(a)); [print('-', t['task'], '| plan:', bool(t['plan'])) for t in a]"
```
Expected: `4`, then four lines — the extractor fan and car-insurance tasks first (longest-sitting), passport showing `plan: False`, the other three `plan: True`. If parsing fails, a YAML error will surface — re-check the frontmatter indentation.

- [ ] **Step 3: Commit**

```bash
cd /Users/dalton/projects/sidekick
git add tasks/
git commit -m "$(printf 'feat: seed the four demo tasks backing the active list\n\nReal tasks/*.md (with plans) for the sample active tasks, so regenerate\nrebuilds a populated In-front-of-you list instead of emptying it. These\nreplace the hand-authored active entries that had no backing files.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 3: Wire `regenerate` to mirror the feed + render brain into the extension

Replace `regenerate`'s old conditional `sidekick-data.json` branch with an atomic copy of both moving files into `chrome-extension/`. This is the keystone: it makes every new tab live. Test-first with stdlib `unittest`.

**Files:**
- Create: `tests/test_regenerate.py`
- Modify: `sidekick.py` (add `import shutil`; add `RENDER_JS` path constant near line 47; replace the extension branch in `regenerate()` at lines 184–190)

**Interfaces:**
- Consumes: `chrome-extension/` (Task 2); `sidekick-render.js` (Task 1); the seeded `tasks/*.md` (Task 2.5), so the regenerated feed has 4 active tasks.
- Produces: after `regenerate`, `chrome-extension/sidekick-data.js` and `chrome-extension/sidekick-render.js` exist and are byte-identical to their root sources (when those sources exist and the folder is present).

- [ ] **Step 1: Write the failing test**

Create `tests/test_regenerate.py`:
```python
"""regenerate must mirror the live feed + shared render brain into chrome-extension/.
Runs sidekick.py as a subprocess against a throwaway vault (SIDEKICK_VAULT), so it
exercises the real CLI. Requires pyyaml (the project's only runtime dep)."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sidekick.py"

class RegenerateExtensionSync(unittest.TestCase):
    def test_mirrors_feed_and_render_into_extension(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "ledger.jsonl").write_text(
                json.dumps({"task": "X", "category": "chore",
                            "completed_at": "2026-06-18T00:00:00Z",
                            "sat_for_hours": 1, "orchestrator": None}) + "\n",
                encoding="utf-8")
            (vault / "sidekick-render.js").write_text("/* render brain marker */\n", encoding="utf-8")
            (vault / "chrome-extension").mkdir()

            env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
            subprocess.run([sys.executable, str(SCRIPT), "regenerate"],
                           check=True, env=env, cwd=d)

            ext = vault / "chrome-extension"
            self.assertTrue((ext / "sidekick-data.js").exists(), "feed not mirrored")
            self.assertTrue((ext / "sidekick-render.js").exists(), "render brain not mirrored")
            self.assertEqual((ext / "sidekick-data.js").read_text(encoding="utf-8"),
                             (vault / "sidekick-data.js").read_text(encoding="utf-8"))
            self.assertEqual((ext / "sidekick-render.js").read_text(encoding="utf-8"),
                             "/* render brain marker */\n")
            # the retired JSON feed must not be produced
            self.assertFalse((ext / "sidekick-data.json").exists(), "stale .json feed still written")

    def test_skips_when_extension_absent(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "ledger.jsonl").write_text("", encoding="utf-8")
            (vault / "sidekick-render.js").write_text("/* x */\n", encoding="utf-8")
            env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
            subprocess.run([sys.executable, str(SCRIPT), "regenerate"],
                           check=True, env=env, cwd=d)
            self.assertTrue((vault / "sidekick-data.js").exists())
            self.assertFalse((vault / "chrome-extension").exists())

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `cd /Users/dalton/projects/sidekick && python3 tests/test_regenerate.py -v`
Expected: `test_mirrors_feed_and_render_into_extension` FAILS — `chrome-extension/sidekick-data.js` does not exist (current code writes `sidekick-data.json` instead and never copies the render brain). `test_skips_when_extension_absent` should already PASS.

- [ ] **Step 3: Add the `shutil` import and `RENDER_JS` path constant**

In `sidekick.py`, add `shutil` to the imports (line 40):
```python
import os, re, sys, json, shutil, argparse, datetime as dt
```
And add the render-brain path beside `DATA_JS` (after line 47, which is `DATA_JS = os.path.join(VAULT, "sidekick-data.js")`):
```python
RENDER_JS = os.path.join(VAULT, "sidekick-render.js")
```

- [ ] **Step 4: Replace the extension branch in `regenerate()`**

In `sidekick.py`, the current block is:
```python
    # if the Chrome new-tab extension is present, refresh its JSON feed too
    ext = os.path.join(VAULT, "chrome-extension")
    if os.path.isdir(ext):
        tmpj = os.path.join(ext, "sidekick-data.json.tmp")
        with open(tmpj, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmpj, os.path.join(ext, "sidekick-data.json"))
```
Replace it with (mirror both moving files; same `window.SIDEKICK` format on both surfaces):
```python
    # mirror the live feed + shared render brain into the Chrome extension, if present.
    # the extension can only load files inside its own folder, so we copy (atomically)
    # rather than reference ../. both surfaces then read the identical window.SIDEKICK feed.
    ext = os.path.join(VAULT, "chrome-extension")
    if os.path.isdir(ext):
        for src in (DATA_JS, RENDER_JS):
            if not os.path.exists(src):
                continue
            dst = os.path.join(ext, os.path.basename(src))
            tmp = dst + ".tmp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)     # atomic: a half-written file is never served
```

- [ ] **Step 5: Run the test, verify it passes**

Run: `cd /Users/dalton/projects/sidekick && python3 tests/test_regenerate.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Regenerate the real vault so the extension folder is populated**

Run: `cd /Users/dalton/projects/sidekick && python3 sidekick.py regenerate`
Then: `ls chrome-extension/`
Expected output includes: `manifest.json  newtab.html  sidekick-data.js  sidekick-render.js`
And: `diff sidekick-data.js chrome-extension/sidekick-data.js && diff sidekick-render.js chrome-extension/sidekick-render.js && echo IN_SYNC`
Expected: `IN_SYNC`.

- [ ] **Step 7: In-session check — extension page renders live data over file://**

Open `file:///Users/dalton/projects/sidekick/chrome-extension/newtab.html`. Because `sidekick-data.js` + `sidekick-render.js` now sit beside it and load via relative `<script src>` (which works over `file://`), the full dashboard must render (hero, active tasks, branches, log), **no console errors**. This exercises the exact extension files minus only Chrome's new-tab override.

- [ ] **Step 8: Manual acceptance — the unpacked-reload behavior (spec §7.1, the one real risk)**

This step needs Chrome's extension UI (folder picker), so it's done by the user; provide these instructions and wait for confirmation:
1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → select the `chrome-extension/` folder.
2. Open a **new tab** → the Sidekick dashboard renders with live data.
3. In the vault run `python3 sidekick.py complete <some-open-id>` (or just `python3 sidekick.py regenerate`).
4. Open **another new tab** → it reflects the change **without** clicking "Reload" on the extension card.

Expected: step 4 shows fresh data. If it does **not** auto-refresh, stop and report — the fallback is to document a one-time "Reload" after regenerate, or revisit the feed mechanism (the rest of the plan still stands). Expectation, from how unpacked extensions read resources fresh per navigation, is that it passes.

- [ ] **Step 9: Commit**

```bash
cd /Users/dalton/projects/sidekick
git add sidekick.py tests/test_regenerate.py sidekick-data.js chrome-extension/sidekick-data.js chrome-extension/sidekick-render.js 2>/dev/null
git add sidekick.py tests/test_regenerate.py
git commit -m "$(printf 'feat: regenerate mirrors live feed + render brain into chrome-extension/\n\nReplaces the retired sidekick-data.json branch with an atomic copy of\nsidekick-data.js and sidekick-render.js into chrome-extension/, so the new\ntab is always live with no manual step. Adds a stdlib unittest that runs the\nreal CLI against a throwaway vault.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```
(The generated `chrome-extension/sidekick-data.js` and `…/sidekick-render.js` are git-ignored from Task 2, so the first `git add` is a harmless no-op for them; the second `git add` is the authoritative one. `sidekick-data.js` at root is tracked and will show as modified — include it if changed.)

---

### Task 4: The `sidekick` command wrapper

A single executable that dispatches to both Python tools, resolving its own directory so it works from anywhere on `PATH` (including via a symlink). Pure pass-through.

**Files:**
- Create: `sidekick` (executable shell script)

**Interfaces:**
- Consumes: `sidekick.py`, `nudge.py`, `install-nudge.sh`, `setup.sh` sitting beside the wrapper.
- Produces: subcommands `new`, `set-plan`, `complete`, `regenerate`, `nudge [--dry-run]`, `nudge-test`, `find-chat`, `nudge-install`, `setup`, `help`.

- [ ] **Step 1: Write the wrapper**

Create `sidekick`:
```bash
#!/usr/bin/env bash
# sidekick — one front door for the vault's tools. Pure dispatch; nothing lives here.
set -euo pipefail

# resolve our own directory, following symlinks (so it works when symlinked onto PATH)
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [ "${SOURCE#/}" = "$SOURCE" ] && SOURCE="$DIR/$SOURCE"
done
DIR="$(cd -P "$(dirname "$SOURCE")" >/dev/null 2>&1 && pwd)"

usage() {
  cat <<'EOF'
sidekick — vault commands

  sidekick new "<title>" --category <phone|admin|errand|chore>
  sidekick set-plan <id> [--file plan.json]      (omit --file to read stdin)
  sidekick complete <id>
  sidekick regenerate

  sidekick nudge [--dry-run]                      decide + send (or just print)
  sidekick nudge-test "<text>"                    channel check
  sidekick find-chat "<query>"                    list chat ids
  sidekick nudge-install [HOUR MINUTE]            schedule the daily nudge (default 9 0)

  sidekick setup                                  one-shot bring-up
  sidekick help
EOF
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  new|set-plan|complete|regenerate)  exec python3 "$DIR/sidekick.py" "$cmd" "$@" ;;
  nudge)                             exec python3 "$DIR/nudge.py" run "$@" ;;
  nudge-test)                        exec python3 "$DIR/nudge.py" test "$@" ;;
  find-chat)                         exec python3 "$DIR/nudge.py" find-chat "$@" ;;
  nudge-install)                     exec "$DIR/install-nudge.sh" "$@" ;;
  setup)                             exec "$DIR/setup.sh" "$@" ;;
  help|-h|--help)                    usage ;;
  *) echo "sidekick: unknown command '$cmd'" >&2; echo >&2; usage >&2; exit 2 ;;
esac
```

- [ ] **Step 2: Make it executable**

```bash
cd /Users/dalton/projects/sidekick && chmod +x sidekick
```

- [ ] **Step 3: Smoke-test help + a real dispatch**

Run: `cd /Users/dalton/projects/sidekick && ./sidekick help`
Expected: the usage block prints; exit code 0.
Run: `cd /Users/dalton/projects/sidekick && ./sidekick regenerate`
Expected: `regenerated sidekick-data.js — N events, M open` (dispatched to `sidekick.py`).
Run: `cd /Users/dalton/projects/sidekick && ./sidekick bogus; echo "exit=$?"`
Expected: "unknown command 'bogus'" + usage on stderr, `exit=2`.

- [ ] **Step 4: Commit**

```bash
cd /Users/dalton/projects/sidekick
git add sidekick
git commit -m "$(printf 'feat: sidekick command wrapper (one front door, pure dispatch)\n\nDispatches new/set-plan/complete/regenerate to sidekick.py and\nnudge/find-chat/install to nudge.py + install-nudge.sh. Resolves its own\ndir through symlinks so it works from anywhere on PATH.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 5: `setup.sh` — one-shot bring-up

An idempotent, skippable interactive bring-up. Safe to re-run; never writes the ledger.

**Files:**
- Create: `setup.sh` (executable)

**Interfaces:**
- Consumes: `sidekick.py`, `nudge.py`, `install-nudge.sh`, `nudge.config.example.json`, `chrome-extension/`.
- Produces: a runnable environment — pyyaml present, feed regenerated, `nudge.config.json` seeded, optional launchd agent, printed extension-load steps.

- [ ] **Step 1: Write `setup.sh`**

Create `setup.sh`:
```bash
#!/usr/bin/env bash
# setup.sh — bring Sidekick up from zero. Idempotent and skippable; never writes the ledger.
set -euo pipefail
DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
ask() { # ask "prompt" -> echoes the reply (empty allowed)
  local reply; read -r -p "$1 " reply || true; printf '%s' "$reply"; }

say "1/5  Checking Python + pyyaml"
command -v python3 >/dev/null || { echo "python3 not found — install it first."; exit 1; }
if python3 -c "import yaml" 2>/dev/null; then
  echo "  pyyaml: OK"
else
  echo "  pyyaml missing."
  if [ "$(ask 'Install pyyaml with pip3 now? [y/N]')" = "y" ]; then
    pip3 install pyyaml
  else
    echo "  Skipped — the CLI and nudge need pyyaml to run."
  fi
fi

say "2/5  Building the feed"
python3 "$DIR/sidekick.py" regenerate

say "3/5  Nudge config"
if [ -f "$DIR/nudge.config.json" ]; then
  echo "  nudge.config.json already exists — leaving it."
else
  cp "$DIR/nudge.config.example.json" "$DIR/nudge.config.json"
  echo "  Created nudge.config.json from the example."
  token="$(ask 'Paste your Beeper token (blank to skip):')"
  if [ -n "$token" ]; then
    python3 - "$DIR/nudge.config.json" "$token" <<'PY'
import json, sys
p, token = sys.argv[1], sys.argv[2]
cfg = json.load(open(p)); cfg["token"] = token
json.dump(cfg, open(p, "w"), indent=2); print("  Token saved.")
PY
    q="$(ask 'Your name to find your self-chat (blank to skip):')"
    [ -n "$q" ] && python3 "$DIR/nudge.py" find-chat "$q" || true
    echo "  Paste the chat id into nudge.config.json (\"chat_id\")."
  fi
fi

say "4/5  Schedule the daily nudge"
if [ "$(ask 'Install the launchd agent now (daily 09:00)? [y/N]')" = "y" ]; then
  "$DIR/install-nudge.sh" 9 0
else
  echo "  Skipped — run 'sidekick nudge-install 9 0' later."
fi

say "5/5  Chrome new tab"
cat <<EOF
  Load the new-tab dashboard:
    1. Open chrome://extensions
    2. Enable Developer mode (top-right)
    3. Load unpacked -> select:
         $DIR/chrome-extension
    4. Open a new tab. It refreshes whenever 'sidekick regenerate' runs.

Done. Day-to-day: use the 'sidekick' command (run 'sidekick help').
EOF
```

- [ ] **Step 2: Make it executable + syntax-check**

```bash
cd /Users/dalton/projects/sidekick && chmod +x setup.sh && bash -n setup.sh && echo "syntax OK"
```
Expected: `syntax OK`.

- [ ] **Step 3: Verify the non-interactive parts run**

Drive it with empty answers (every prompt declines/skips), in a way that won't touch your real config — only run this if `nudge.config.json` does **not** already exist, or temporarily move it aside first:
```bash
cd /Users/dalton/projects/sidekick && yes '' | head -20 | ./setup.sh
```
Expected: steps 1–2 run (pyyaml OK, feed regenerated), step 3 creates `nudge.config.json` from the example and skips the token, step 4 skips the agent, step 5 prints the Chrome steps with the correct absolute `chrome-extension` path. No errors.
Clean up the seeded config if you don't want it: `rm -f nudge.config.json` (it's git-ignored regardless).

- [ ] **Step 4: Commit**

```bash
cd /Users/dalton/projects/sidekick
git add setup.sh
git commit -m "$(printf 'feat: setup.sh one-shot bring-up (idempotent, skippable)\n\nChecks python3/pyyaml, regenerates the feed, seeds nudge.config.json,\noptionally installs the launchd agent, and prints the Load-unpacked steps.\nNever writes the ledger.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 6: Reconcile the docs (and bring the core scripts under version control)

Update `README.md` + `CLAUDE.md` to the real layout and the new commands, and commit the previously-untracked core source files so the repo actually *is* the app.

**Files:**
- Modify: `README.md` (pieces table + bring-up step 3 + the "Make it feel like one app" section)
- Modify: `CLAUDE.md` (note the shared render brain + that `regenerate` syncs the extension; add the `sidekick`/`setup.sh` ergonomics)
- Add to git (currently untracked): `sidekick.py`, `nudge.py`, `install-nudge.sh`, `nudge.config.example.json`, `CLAUDE.md`

**Interfaces:**
- Consumes: the final layout from Tasks 1–5.
- Produces: docs that match reality; a fully version-controlled app.

- [ ] **Step 1: Fix the `chrome-extension/` row in the README pieces table**

In `README.md`, replace the table row:
```
| `chrome-extension/` | New-tab version of the dashboard (`manifest.json`, `newtab.html`, `newtab.js`) + its own `sidekick-data.json` feed. | `regenerate` refreshes the JSON |
```
with:
```
| `chrome-extension/` | New-tab dashboard: `manifest.json` + `newtab.html` (a thin shell). Reads the same `sidekick-data.js` + shared `sidekick-render.js`, mirrored in by `regenerate`. | `regenerate` syncs both files |
```
And add a row for the shared brain right under the `sidekick-data.js` row:
```
| `sidekick-render.js` | The single dashboard render logic. Loaded by both `sidekick.html` and the extension's `newtab.html`. | — |
```

- [ ] **Step 2: Update README bring-up step 3 (the new tab)**

Replace:
```
- _New tab:_ `chrome://extensions` → Developer mode → **Load unpacked** → pick `chrome-extension/` → keep the new-tab change.
```
with:
```
- _New tab:_ run `python sidekick.py regenerate` once (so `chrome-extension/` has its feed), then `chrome://extensions` → Developer mode → **Load unpacked** → pick `chrome-extension/`. Every new tab is the live dashboard; it refreshes on the next `regenerate`.
```

- [ ] **Step 3: Update the README "Make it feel like one app" section**

That section currently says the `sidekick` wrapper and `setup.sh` are optional/"say the word and I'll build them." Replace its numbered list + closing line with the built reality:
```
1. **One command.** `sidekick` on your `PATH` dispatches to both scripts: `sidekick new …`, `sidekick regenerate`, `sidekick nudge`, `sidekick nudge-install`, `sidekick setup`. Run `sidekick help` for the full list. Pure ergonomics; changes nothing underneath.
2. **One setup.** `./setup.sh` runs the whole bring-up interactively (checks deps, installs pyyaml, regenerates, seeds the Beeper config, runs `find-chat`, optionally installs the agent, and prints the Load-unpacked steps). Idempotent and skippable.

Put the repo dir on your `PATH` (or symlink `sidekick` into one) and `sidekick` works from anywhere.
```

- [ ] **Step 4: Update `CLAUDE.md`**

Under the data-files description, add a line noting the shared brain (place it near the `sidekick-data.js` mention):
```
- `sidekick-render.js` — the dashboard's render logic, shared by `sidekick.html` and the Chrome new tab. Static. `regenerate` copies it (with the feed) into `chrome-extension/`.
```
And in the Routine table, add a final row:
```
| Day-to-day shorthand | `sidekick <cmd>` wraps these (`sidekick help`); `./setup.sh` does first-time bring-up |
```

- [ ] **Step 5: Verify docs have no stale references**

Run: `cd /Users/dalton/projects/sidekick && grep -rn "Google Tasks\|sidekick-data.json\|newtab.js" README.md CLAUDE.md sidekick.html chrome-extension/newtab.html; echo "exit=$?"`
Expected: no matches; `exit=1` (grep found nothing). If any line matches, fix it (these are all retired references).

- [ ] **Step 6: Commit (docs + bring core scripts under version control)**

```bash
cd /Users/dalton/projects/sidekick
git add README.md CLAUDE.md sidekick.py nudge.py install-nudge.sh nudge.config.example.json
git commit -m "$(printf 'docs: reconcile README/CLAUDE to the unified layout; track core scripts\n\nDocuments the shared render brain, the chrome-extension/ feed sync, and the\nsidekick command + setup.sh. Brings the previously-untracked core scripts\n(sidekick.py, nudge.py, install-nudge.sh, the example config, CLAUDE.md)\nunder version control so the repo is the whole app.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

- [ ] **Step 7: Final whole-system verification**

```bash
cd /Users/dalton/projects/sidekick
python3 tests/test_regenerate.py -v          # both tests PASS
./sidekick regenerate                        # feed rebuilt, extension synced
diff sidekick-render.js chrome-extension/sidekick-render.js && \
diff sidekick-data.js   chrome-extension/sidekick-data.js   && echo SYNCED
git status                                   # generated extension copies ignored; tree clean
```
Expected: tests pass, `SYNCED` prints, and `git status` shows a clean tree with no stray tracked generated copies.

---

## Self-Review

**1. Spec coverage** (spec §4 components → tasks):
- §4.1 shared render brain → Task 1 ✓
- §4.2 `sidekick.html` rewire + foot-note → Task 1 ✓
- §4.3 `chrome-extension/newtab.html` shell → Task 2 ✓
- §4.4 `regenerate` copy step → Task 3 ✓
- §4.5 `sidekick` wrapper → Task 4 ✓
- §4.6 `setup.sh` → Task 5 ✓
- §4.7 docs → Task 6 ✓
- §4.8 `.gitignore` → Task 2 ✓
- §7 acceptance: §7.1 unpacked-reload → Task 3 Step 8; §7.2 standalone identical → Task 1 Step 5; §7.3 no `newtab.js`/`.json` consumer → Task 6 Step 5 grep; §7.4 both feeds identical → Task 3 Step 6 / Task 6 Step 7; §7.5 wrapper+setup run → Task 4 Step 3 + Task 5 Step 3; §7.6 generated copies ignored → Task 6 Step 7. ✓

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". All code shown in full; the one verbatim extraction (Task 1) is a `sed` move with explicit boundary verification rather than a retype. ✓

**3. Type/name consistency:** `RENDER_JS`/`DATA_JS` constants and the `chrome-extension/` basename copy are consistent between Task 3's implementation and its test. The wrapper subcommands in Task 4 match those documented in Task 6. The foot-note replacement text is internally consistent (vault-backed) across Tasks 1, 2, 6. ✓

**Note on the one risk:** Task 3 Step 8 (unpacked auto-refresh) is the only step gated on real Chrome behavior; it has an explicit fallback and does not block Tasks 4–6.
