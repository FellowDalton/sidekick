# Sidekick `raw/` → wiki reusable-memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the orchestrator a durable, reusable life-knowledge memory: two vault folders (`raw/` archive, `wiki/` topic notes), a CLAUDE.md loop protocol, and one deterministic `sidekick wiki` command that rebuilds a map-of-content index — with no change to the ledger/task/dashboard data path.

**Architecture:** The model maintains the knowledge (writes `raw/` and `wiki/` markdown directly, as it already does with task files); code only *indexes* it. `sidekick wiki` scans `wiki/*.md`, reads each note's frontmatter via the existing `read_note()`, and atomically writes `wiki/_index.md` as a pure function of the notes (no timestamp → byte-identical on rerun). Obsidian is the browse surface; there is no HTML view.

**Tech Stack:** Python 3 stdlib + `pyyaml` (the project's only dependency). Tests are stdlib `unittest` run as subprocesses against a throwaway vault via `SIDEKICK_VAULT`, exactly like `tests/test_regenerate.py`.

## Global Constraints

Every task's requirements implicitly include these (copied from the spec):

- **No new runtime dependency** — still just `pyyaml`.
- **No model logic in `sidekick.py`** — `sidekick wiki` is deterministic indexing only; it never synthesizes.
- **Strict I/O boundary** — `wiki` reads only `wiki/*.md`, writes only `wiki/_index.md`. It must never touch `ledger.jsonl`, `tasks/`, or `sidekick-data.js`, and is **not** called by `regenerate` (separate cadence).
- **No churn** — the index is a pure function of the notes with **NO generation timestamp**, so re-running with unchanged notes produces a byte-identical file.
- **`_index.md` is always excluded** from the scan (so it never indexes itself).
- **Degrade, never crash** — a note whose frontmatter fails to parse (or isn't a dict) falls back to `title=stem`, empty summary/updated.
- **`updated` coercion** — PyYAML parses an unquoted `updated: 2026-06-19` as a `datetime.date`, so coerce with `str(...)` before sorting/displaying (a quoted string passes through unchanged).
- **Sort order** — `updated` descending (ISO dates sort lexically; empty `updated` sorts **last**), then `title` ascending as a tiebreaker. Fully deterministic; no filesystem mtime.
- **Git tracking** — `raw/` and `wiki/` are tracked in git (like `tasks/`); `wiki/_index.md` is generated but committed. `.gitignore` already leaves these paths alone.
- **Atomic writes** — write to `path + ".tmp"` then `os.replace(...)`, the existing pattern.
- **No empty-folder creation** — `sidekick wiki` must **not** create `wiki/` when it is absent; it no-ops with a notice. The folders come into existence when the orchestrator seeds the first note at runtime (the protocol), so this build adds **no** `raw/`/`wiki/` directories or `.gitkeep` files.

---

## File Structure

- **`sidekick.py`** (modify) — add two path constants and the deterministic `wiki_index()` function; wire `wiki` into the argparse subcommands and the `main()` dispatch. No change to any existing function.
- **`tests/test_wiki.py`** (create) — stdlib `unittest`, same shape as `test_regenerate.py`: build+sort+format, degradation, no-churn, no-wiki no-op, empty-wiki placeholder.
- **`sidekick`** (modify) — route `wiki` through the existing dispatch and add a usage line.
- **`CLAUDE.md`** (modify) — add `raw/`/`wiki/` to the vault file list, a "## The wiki — reusable memory (Layer 2)" loop-protocol section, a routine-table row, and a "Don't" bullet.
- **`README.md`** (modify) — add a "## Layer 2 — the wiki (reusable memory)" subsection, two pieces-table rows, and reconcile the two now-stale "deferred" lines.

---

## Task 1: The `sidekick wiki` command + its test suite

**Files:**
- Modify: `sidekick.py` (paths block after line 48; new function after `regenerate()` ~line 199; argparse + dispatch in `main()` ~lines 204 and 210)
- Test: `tests/test_wiki.py` (create)

**Interfaces:**
- Consumes: existing `read_note(path) -> (fm_dict, body_str)` (raises `yaml.YAMLError` on malformed frontmatter — must be caught here), and the module-level `VAULT` path.
- Produces: `wiki_index()` — no args, no return; prints either `no wiki/ directory — nothing to index` (when `wiki/` is absent) or `wrote wiki/_index.md — N topics`. New CLI subcommand `python sidekick.py wiki`. New constants `WIKI` and `WIKI_INDEX`.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_wiki.py`:

```python
"""`sidekick wiki` rebuilds wiki/_index.md — a deterministic map-of-content over
wiki/*.md. Runs sidekick.py as a subprocess against a throwaway vault
(SIDEKICK_VAULT), so it exercises the real CLI. Requires pyyaml."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sidekick.py"


def run_wiki(vault):
    """Run `sidekick.py wiki` against `vault`; return the CompletedProcess."""
    env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
    return subprocess.run([sys.executable, str(SCRIPT), "wiki"],
                          env=env, capture_output=True, text=True)


def seed(wiki, name, text):
    (wiki / name).write_text(text, encoding="utf-8")


class WikiIndex(unittest.TestCase):
    def test_build_sorts_and_formats(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); wiki = vault / "wiki"; wiki.mkdir()
            seed(wiki, "car-insurance.md",
                 "---\nsummary: Renewal facts and account refs.\n"
                 "updated: 2026-06-13\n---\n\n# Car insurance\n\nbody\n")
            seed(wiki, "dentist.md",
                 "---\nsummary: Checkup cadence and contact.\n"
                 "updated: 2026-06-16\n---\n\n# Dentist\n\nbody\n")

            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)

            idx = wiki / "_index.md"
            self.assertTrue(idx.exists(), "index not written")
            text = idx.read_text(encoding="utf-8")

            self.assertIn("do not hand-edit", text)
            self.assertIn("# Wiki — reusable memory", text)
            self.assertIn("[[car-insurance|Car insurance]] — Renewal facts and account refs.", text)
            self.assertIn("[[dentist|Dentist]] — Checkup cadence and contact.", text)
            self.assertIn("updated 2026-06-16", text)
            # newer `updated` first: dentist (06-16) precedes car-insurance (06-13)
            self.assertLess(text.index("[[dentist"), text.index("[[car-insurance"))
            self.assertIn("2 topics", r.stdout)

    def test_degrades_on_malformed_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); wiki = vault / "wiki"; wiki.mkdir()
            # unterminated quoted scalar -> yaml.safe_load raises -> must degrade to stem
            seed(wiki, "broken.md", '---\nsummary: "oops never closed\n---\n\n# Ignored\n')

            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (wiki / "_index.md").read_text(encoding="utf-8")
            self.assertIn("[[broken|broken]]", text)   # title falls back to the stem
            self.assertNotIn("_No topics yet._", text)

    def test_no_churn_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); wiki = vault / "wiki"; wiki.mkdir()
            seed(wiki, "landlord.md",
                 "---\nsummary: Lease + contacts.\nupdated: 2026-06-10\n---\n\n# Landlord\n")
            seed(wiki, "passport.md",
                 "---\nsummary: Renewal steps.\nupdated: 2026-06-11\n---\n\n# Passport\n")

            self.assertEqual(run_wiki(vault).returncode, 0)
            first = (wiki / "_index.md").read_text(encoding="utf-8")
            self.assertEqual(run_wiki(vault).returncode, 0)
            second = (wiki / "_index.md").read_text(encoding="utf-8")
            self.assertEqual(first, second, "re-run produced a different index (timestamp leak?)")

    def test_no_wiki_dir_noops(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)   # deliberately NO wiki/ dir
            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("no wiki/", r.stdout)
            self.assertFalse((vault / "wiki").exists(), "wiki/ must not be created")

    def test_empty_wiki_writes_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); (vault / "wiki").mkdir()
            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (vault / "wiki" / "_index.md").read_text(encoding="utf-8")
            self.assertIn("_No topics yet._", text)
            self.assertIn("0 topics", r.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_wiki -v`
Expected: FAIL — every test errors because `wiki` is not yet a valid subcommand (argparse exits non-zero: `invalid choice: 'wiki'`), so `returncode` is not 0 / `_index.md` is never written.

- [ ] **Step 3: Add the two path constants**

In `sidekick.py`, after the `RENDER_JS = ...` line (currently line 48), add:

```python
WIKI       = os.path.join(VAULT, "wiki")
WIKI_INDEX = os.path.join(WIKI, "_index.md")
```

- [ ] **Step 4: Add the `wiki_index()` function**

In `sidekick.py`, insert this **after** the `regenerate()` function and **before** the `# ── CLI ──` section header (currently around line 199–200):

```python
# ── the wiki indexer (reusable-memory map-of-content) ─────────────────────────
def wiki_index():
    """Rebuild wiki/_index.md from wiki/*.md — a deterministic map-of-content.
    Pure function of the notes (NO timestamp), so unchanged notes => byte-identical
    output (no spurious git diffs). Reads only wiki/*.md; writes only wiki/_index.md.
    No model logic, and it never touches the ledger / tasks / feed. The wiki is the
    sanctioned LLM-maintained layer; this code only indexes it (spec §4.4)."""
    if not os.path.isdir(WIKI):
        print("no wiki/ directory — nothing to index")
        return                               # no-op; do NOT create the folder

    entries = []
    for name in sorted(os.listdir(WIKI)):
        if not name.endswith(".md") or name == "_index.md":
            continue                         # never index the index itself
        stem = name[:-3]
        try:
            fm, body = read_note(os.path.join(WIKI, name))
        except Exception:
            fm, body = {}, ""                # malformed frontmatter degrades; never crashes
        if not isinstance(fm, dict):
            fm = {}
        title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), stem)
        summary = str(fm.get("summary") or "").strip()
        updated = str(fm.get("updated") or "").strip()   # yaml may parse a date obj
        entries.append({"stem": stem, "title": title, "summary": summary, "updated": updated})

    # updated descending (empty last), title ascending as tiebreaker — two stable passes
    entries.sort(key=lambda e: e["title"].lower())
    entries.sort(key=lambda e: (e["updated"] != "", e["updated"]), reverse=True)

    head = ("<!-- GENERATED by `sidekick wiki` — do not hand-edit. -->\n\n"
            "# Wiki — reusable memory\n\n")
    if entries:
        lines = []
        for e in entries:
            line = f"- [[{e['stem']}|{e['title']}]]"
            if e["summary"]:
                line += f" — {e['summary']}"
            if e["updated"]:
                line += f"  ·  updated {e['updated']}"
            lines.append(line)
        body = "\n".join(lines) + "\n"
    else:
        body = "_No topics yet._\n"

    tmp = WIKI_INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(head + body)
    os.replace(tmp, WIKI_INDEX)              # atomic: a half-written index is never read
    print(f"wrote wiki/_index.md — {len(entries)} topics")
```

- [ ] **Step 5: Wire `wiki` into the CLI**

In `main()`, register the subparser. After the line `sub.add_parser("regenerate")` (currently line 204) add:

```python
    sub.add_parser("wiki")
```

Then add the dispatch branch. After the `if a.cmd == "regenerate":` / `regenerate()` block (currently lines 210–211), add a new branch — place it directly after the `regenerate` branch:

```python
    elif a.cmd == "wiki":
        wiki_index()
```

(Do **not** call `regenerate()` here — the wiki runs on a separate cadence.)

- [ ] **Step 6: Run the test suite to verify it passes**

Run: `python3 -m unittest tests.test_wiki -v`
Expected: PASS — all five tests green.

Then run the whole suite to confirm nothing else broke:
Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — `test_wiki` (5) and `test_regenerate` (2) all green.

- [ ] **Step 7: Commit**

```bash
git add sidekick.py tests/test_wiki.py
git commit -m "feat: deterministic 'sidekick wiki' index for the reusable-memory wiki

$(cat <<'MSG'
Adds wiki_index(): scans wiki/*.md (excluding _index.md), reads frontmatter
via read_note(), and atomically writes wiki/_index.md as a map-of-content.
Pure function of the notes — no timestamp — so re-runs are byte-identical.
Sorts updated-desc / title-asc, degrades (never crashes) on malformed
frontmatter, coerces yaml-parsed dates to str, and no-ops without creating
wiki/ when absent. Reads only wiki/*.md, writes only wiki/_index.md; never
touches the ledger/tasks/feed and is not called by regenerate.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ
MSG
)"
```

---

## Task 2: Route `wiki` through the `sidekick` wrapper

**Files:**
- Modify: `sidekick` (dispatch `case` at line 35; usage block lines 18–21)

**Interfaces:**
- Consumes: the `wiki` subcommand added to `sidekick.py` in Task 1.
- Produces: `sidekick wiki` invokes `python3 sidekick.py wiki`.

- [ ] **Step 1: Add `wiki` to the dispatch case**

In `sidekick`, change the first `case` arm (line 35) from:

```bash
  new|set-plan|complete|regenerate)  exec python3 "$DIR/sidekick.py" "$cmd" "$@" ;;
```

to:

```bash
  new|set-plan|complete|regenerate|wiki)  exec python3 "$DIR/sidekick.py" "$cmd" "$@" ;;
```

- [ ] **Step 2: Add the usage line**

In the `usage()` heredoc, after the `sidekick regenerate` line (line 21), add:

```bash
  sidekick wiki                                  rebuild wiki/_index.md
```

- [ ] **Step 3: Verify the wrapper routes correctly**

Run a smoke test against a throwaway vault so the real vault is untouched:

```bash
tmp=$(mktemp -d); mkdir "$tmp/wiki"
SIDEKICK_VAULT="$tmp" ./sidekick wiki
test -f "$tmp/wiki/_index.md" && echo "OK: wrapper routed wiki" || echo "FAIL"
./sidekick help | grep -q "rebuild wiki/_index.md" && echo "OK: usage line present" || echo "FAIL"
rm -rf "$tmp"
```

Expected: prints `wrote wiki/_index.md — 0 topics`, then `OK: wrapper routed wiki` and `OK: usage line present`.

- [ ] **Step 4: Commit**

```bash
git add sidekick
git commit -m "feat: route 'sidekick wiki' through the wrapper + usage line

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 3: Document the loop (CLAUDE.md + README)

**Files:**
- Modify: `CLAUDE.md` (vault file list ~line 8; routine table ~line 21; new section after the orchestrator-step section ~line 30; "Don't" list ~line 35)
- Modify: `README.md` (pieces table ~lines 15–18; new subsection after "The daily loop" ~line 91; stale lines 113 and 121)

**Interfaces:**
- Consumes: the `sidekick wiki` command (Tasks 1–2). Documentation only — no tests.

- [ ] **Step 1: CLAUDE.md — add `raw/`/`wiki/` to the vault file list**

After the `sidekick.html` bullet (line 8), add:

```markdown
- `raw/*.md` — verbatim research dumps (archival, lossless). Model-written. Tracked in git.
- `wiki/*.md` — synthesized topic notes: the orchestrator's reusable memory (model-maintained, lossy). `wiki/_index.md` is **generated** by `sidekick wiki` — never hand-edit it.
```

- [ ] **Step 2: CLAUDE.md — add the routine-table row**

After the "Just refresh the view" row (line 21), add:

```markdown
| Folded research into the wiki | edit `wiki/<topic>.md`, then `python sidekick.py wiki` (rebuilds `wiki/_index.md`) |
```

- [ ] **Step 3: CLAUDE.md — add the Layer-2 protocol section**

Immediately after the "## The orchestrator step" section (after line 30, before the "## Don't" header), insert:

```markdown
## The wiki — reusable memory (Layer 2)
The wiki is the orchestrator's durable life-knowledge — the sanctioned **model-maintained, lossy** layer. It lives entirely outside the ledger/task data path and cannot affect scoring. Obsidian is the browse surface (backlinks, `[[wikilinks]]`, graph); there is no HTML view.

- **Before researching a task:** read `wiki/_index.md`, then grep/glob `wiki/` for the task's subject. Read any matching topic note(s) and **reuse** known facts instead of re-researching.
- **After researching:**
  1. write the verbatim prose to `raw/<YYYYMMDD>-<slug>.md` with `task` / `topic` / `created` frontmatter (the lossless archive);
  2. fold the durable facts into `wiki/<topic>.md` — create or update it; refresh `summary` / `updated` / `sources`; cross-link with `[[wikilinks]]`. Topics are areas of life (`car-insurance`, `dentist`), **not** the task categories;
  3. run `python sidekick.py wiki` (or `sidekick wiki`) to rebuild the index.
- **Integrity:** never let wiki work touch `ledger.jsonl` or task frontmatter. `wiki/_index.md` is generated — never hand-edit it.
```

- [ ] **Step 4: CLAUDE.md — add the "Don't" bullet**

In the "## Don't" list, after the "Don't write to `ledger.jsonl`…" bullet (line 34), add:

```markdown
- Don't hand-edit `wiki/_index.md` — it's generated by `sidekick wiki`.
```

- [ ] **Step 5: README — update the `sidekick.py` pieces-table row and add `raw/`/`wiki/` rows**

Change the `sidekick.py` row (line 15) from:

```markdown
| `sidekick.py`       | The CLI + assembler. `new` / `set-plan` / `complete` / `regenerate`. Deterministic — no LLM in it.                  | —                                 |
```

to:

```markdown
| `sidekick.py`       | The CLI + assembler. `new` / `set-plan` / `complete` / `regenerate` / `wiki`. Deterministic — no LLM in it.         | —                                 |
```

Then, after the `sidekick.html` row (line 18), add two rows:

```markdown
| `raw/*.md`          | Verbatim research dumps (archival, lossless). One file per research session.                                        | the orchestrator (LLM)            |
| `wiki/*.md`         | Synthesized topic notes — the orchestrator's reusable memory. `wiki/_index.md` is generated by `sidekick wiki`.     | orchestrator; index by `sidekick wiki` |
```

- [ ] **Step 6: README — add the "Layer 2" subsection**

After the "## The daily loop" section (after line 90, before "## Make it feel like one app"), insert:

```markdown
## Layer 2 — the wiki (reusable memory)

The orchestrator used to re-research the same subjects (the car insurer, the dentist, the landlord) every session. Two folders give it a memory:

- **`raw/`** — verbatim research dumps, one file per session (`raw/YYYYMMDD-<slug>.md`). The lossless archive; the receipts.
- **`wiki/`** — synthesized topic notes, one per recurring subject (`wiki/car-insurance.md`). Durable, reusable facts in the orchestrator's words, cross-linked with `[[wikilinks]]`. This is the memory.

The loop (in `CLAUDE.md`): **before** researching, the orchestrator reads `wiki/` and reuses what's there; **after**, it archives the prose to `raw/`, folds the durable facts into `wiki/<topic>.md`, and runs `sidekick wiki` to rebuild `wiki/_index.md` (a map-of-content). **Obsidian is the browser** — backlinks, graph, search; no custom UI.

This is the one **model-maintained** layer, deliberately fuzzy/lossy. `sidekick wiki` is the only code involved and it is purely mechanical — it indexes notes, never synthesizes — so the wiki lives entirely outside the ledger/task data path and can never affect scoring.
```

- [ ] **Step 7: README — reconcile the two stale "deferred" lines**

Change line 113 from:

```markdown
No mechanical game perks yet (cosmetic only; the full event history is stored so they can be added later). The LLM-wiki pattern is reserved for the orchestrator's fuzzy life-knowledge (`raw/`, deferred), never the integrity-critical ledger.
```

to:

```markdown
No mechanical game perks yet (cosmetic only; the full event history is stored so they can be added later). The LLM-wiki pattern is the orchestrator's fuzzy life-knowledge (`raw/`, `wiki/` — see _Layer 2_), kept entirely separate from the integrity-critical ledger.
```

Then change the tail of line 121 from:

```markdown
Optional later additions: reply-"done"-to-complete (Beeper can read messages, so the nudge becomes the action surface); a lighter new-tab variant; and the `raw/` → wiki compilation loop once there's a real pile of context. None are urgent, and "unify it further" is the kind of pleasant, infinite task the system was built to protect you from — the map is done; the dials are the work.
```

to:

```markdown
Optional later additions: reply-"done"-to-complete (Beeper can read messages, so the nudge becomes the action surface) and a lighter new-tab variant. (The `raw/` → wiki reusable-memory loop is now built — see _Layer 2_.) None are urgent, and "unify it further" is the kind of pleasant, infinite task the system was built to protect you from — the map is done; the dials are the work.
```

- [ ] **Step 8: Verify the docs and that nothing broke**

```bash
grep -q "The wiki — reusable memory (Layer 2)" CLAUDE.md && echo "OK: CLAUDE.md protocol" || echo "FAIL"
grep -q "Layer 2 — the wiki (reusable memory)" README.md && echo "OK: README subsection" || echo "FAIL"
grep -q "regenerate / \`wiki\`" README.md && echo "OK: pieces table updated" || echo "FAIL"
python3 -m unittest discover -s tests -v
```

Expected: three `OK:` lines and the suite passing (docs don't affect code, but this guards against an accidental edit elsewhere).

- [ ] **Step 9: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document the raw/ -> wiki reusable-memory loop

CLAUDE.md gets the Layer-2 loop protocol (read wiki/ before researching;
archive to raw/, fold into wiki/<topic>.md, run 'sidekick wiki' after), a
routine row, the vault file-list entries, and a 'do not hand-edit _index.md'
rule. README gets a Layer-2 subsection, two pieces-table rows, and reconciles
the two now-stale 'deferred' lines.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Notes for the executor

- **The `raw/` and `wiki/` folders are intentionally not created by this work.** Git can't track empty folders, and `sidekick wiki` no-ops when `wiki/` is absent by design (spec §6). The folders appear at runtime when the orchestrator seeds the first note (the CLAUDE.md protocol). Do not add `.gitkeep` or seed example notes.
- **Mark the spec status.** This plan implements `docs/superpowers/specs/2026-06-19-sidekick-wiki-reusable-memory-design.md` (status was "Approved (design), pending implementation plan"). No code change there; leave the spec as the record.

## Self-Review (completed during authoring)

- **Spec coverage:** §4.1 `raw/` and §4.2 `wiki/<topic>.md` are runtime artifacts created by the orchestrator (documented in Task 3, not built — per the no-empty-folder constraint). §4.3 protocol → Task 3 Steps 2–4. §4.4 `sidekick wiki` (all five sub-behaviors: no-dir no-op, scan, sort, atomic write/format, print) → Task 1 Steps 3–5. §4.5 wrapper → Task 2. §4.6 docs → Task 3. §6 edge cases → Task 1 tests (no-wiki, empty, malformed, `_index.md` excluded). §7 testing → `tests/test_wiki.py` (build+sort+format, degradation, no-churn, empty/no-wiki). §8 integrity/git → Global Constraints + Task 1 docstring.
- **Placeholder scan:** every code/edit step carries the exact content; no TBD/TODO/"handle edge cases".
- **Type consistency:** `wiki_index()`, `WIKI`, `WIKI_INDEX` names match across Tasks 1–2; the index line format in the implementation (Step 4) matches the assertions in the tests (Step 1); `str(... or "").strip()` coercion matches the YAML-date finding.
