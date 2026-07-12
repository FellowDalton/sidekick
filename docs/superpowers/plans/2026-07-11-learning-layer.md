# Learning Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Completed-task data compounds: `complete` records richer ledger events (`note`, `via`, `from`), `regenerate` computes deterministic stats (completions by category, median sat-for-hours, day-of-week/time-of-day histograms, current streak) into `sidekick-data.js`, and both dashboards (static HTML + PWA) render a stats panel. Sub-project 5 of `docs/superpowers/specs/2026-07-10-sidekick-next-phase-design.md`.

**Architecture:** `sidekick.complete()` stays the sole ledger writer and gains three optional event fields — `note`/`via` from its caller, `from` copied from task frontmatter when present (trivially available; written by sub-project 2). A new pure function `compute_stats(events)` runs inside `regenerate()` and lands under a `stats` key in `window.SIDEKICK`. The static dashboard reads that key (hiding the panel when an old feed lacks it). The PWA gets its feed from `/feed` (raw events, no `stats` key), so it mirrors the same aggregate math client-side in `web/src/lib/stats.ts` — cheap, because the PWA already computes its whole game brain client-side in `web/src/lib/game.ts`.

**Tech Stack:** Python 3 stdlib (`datetime`, `json`) + pyyaml (existing), stdlib `unittest` collected by pytest (existing `tests/`), FastAPI + pytest (existing `server/`), vanilla JS (`sidekick-render.js`), SvelteKit + Vitest + testing-library (existing `web/`).

**Explicitly out of scope** (from the spec's sub-project 5, per approval):
- Bootstrapping `wiki/` + `raw/` — needs **no code**; `wiki_index()` and the orchestrator flow already no-op / create-on-write when absent. The agent (sub-project 3) creates them on first run.
- Graph growth via `[[wikilinks]]` — that is usage (orchestrator behavior), not code.
- Feeding day-of-week data into nudge timing — spec marks it "out of scope now".

## Global Constraints

- **No new Python dependencies** (pyyaml stays the only one) and **no new npm dependencies**.
- **The ledger is append-only and `complete()` is its sole writer.** This plan adds optional fields to the event `complete()` writes; nothing else touches `ledger.jsonl`, and no existing field changes shape.
- **Backward compatibility is a hard requirement:** every ledger line written before this plan lacks `note`/`via`/`from`, and lines written after it may still lack them (the fields are optional and omitted when absent — never written as `null`). Every reader must tolerate missing fields; Tasks 3 and 6 test this explicitly against legacy-shaped events.
- **Generated outputs are never hand-edited.** `sidekick-data.js` and the `chrome-extension/` mirrors change in this plan **only** because the generator (`sidekick.py regenerate`) changes; the refreshed outputs are committed as generated artifacts (Task 5). `wiki/_index.md` is untouched.
- **`regenerate` stays idempotent and deterministic:** `compute_stats` is a pure function of `(events, today)`; category keys are emitted in sorted order so the JSON is byte-stable for a given vault + clock. No model logic anywhere in the data path (spec: "Deterministic code only").
- **Timezone:** `completed_at` is stored as UTC ISO (`...Z`); all stats bin in **UTC**. Dalton lives in Europe/Copenhagen (UTC+1/+2), so a late-evening local completion can bin to the previous/same UTC day and a UTC hour 1–2 earlier than wall clock. This is accepted and labeled in both UIs ("UTC") rather than guessing a display timezone in deterministic code.
- **Parallel sub-projects may have shifted `server/app.py`** (role/identity handling from sub-project 2). Task 4 gives *snippets to locate*, not line numbers — adapt placement to the file as found; the anchors are stable.
- Test commands, always from the repo root: engine `python3 -m pytest tests/ -q`, server `python3 -m pytest server/tests/ -q`, web `npm --prefix web test`.

## File Structure

```
sidekick.py                        MOD  complete(): note/via/from event fields · compute_stats() · regenerate embeds stats · CLI --note/--via
tests/test_engine_api.py           MOD  ledger-field tests (Task 1)
tests/test_cli_complete.py         NEW  CLI --note/--via subprocess tests (Task 2)
tests/test_stats.py                NEW  compute_stats + regenerate embedding (Task 3)
server/app.py                      MOD  post_complete passes via="phone" + note passthrough (Task 4)
server/tests/test_api_writes.py    MOD  via/note assertions (Task 4)
sidekick.html                      MOD  Patterns section + stat-tile CSS (Task 5)
sidekick-render.js                 MOD  render stats panel; tolerate missing stats (Task 5)
sidekick-data.js                   GEN  refreshed by regenerate — never hand-edited
chrome-extension/sidekick-*.js     GEN  mirrors refreshed by regenerate — never hand-edited
web/src/lib/types.ts               MOD  LedgerEvent gains note?/via?/from? (Task 6)
web/src/lib/stats.ts               NEW  client-side mirror of compute_stats (Task 6)
web/src/lib/stats.test.ts          NEW  (Task 6)
web/src/routes/Dashboard.svelte    MOD  Patterns section (Task 6)
web/src/routes/dashboard.test.ts   MOD  patterns assertion (Task 6)
web/src/app.css                    MOD  stat-tile styles (Task 6)
```

---

### Task 1: Engine — `complete()` writes optional `note`, `via`, `from` ledger fields

**Files:**
- Modify: `sidekick.py` (the `complete()` function, currently at lines 129–157)
- Test: `tests/test_engine_api.py` (append to the existing `EngineApiExtensions` class)

**Interfaces:**
- Consumes: nothing new (existing `read_note`/`write_note`/`hours_since`).
- Produces: `complete(task_id, completed_at=None, note=None, via=None)` — same return dict and idempotency as today. The ledger event gains `note` (when a non-empty string is passed), `via` (when passed), and `from` (copied from task frontmatter `from:` when present — sub-project 2 writes that key; here we only *read* it, which is trivially available at completion time). Absent values are **omitted**, never written as `null`, so old and new lines stay shape-compatible.

- [ ] **Step 1: Write the failing tests**

Append to the `EngineApiExtensions` class in `tests/test_engine_api.py` (before the `if __name__ == "__main__":` block):

```python
    def test_complete_records_note_and_via(self):
        tid = sidekick.create_task("Fix bike light", "chore")
        sidekick.complete(tid, note="battery is CR2032", via="cli")
        event = json.loads(self._ledger_lines()[0])
        self.assertEqual(event["note"], "battery is CR2032")
        self.assertEqual(event["via"], "cli")

    def test_complete_omits_absent_optional_fields(self):
        # regression guard: old-format lines must stay reproducible — no null-stuffing
        tid = sidekick.create_task("Water plants", "chore")
        sidekick.complete(tid)
        event = json.loads(self._ledger_lines()[0])
        self.assertNotIn("note", event)
        self.assertNotIn("via", event)
        self.assertNotIn("from", event)

    def test_complete_copies_from_frontmatter(self):
        # sub-project 2 writes `from:` into frontmatter; complete() copies it if present
        tid = sidekick.create_task("Buy milk", "errand")
        path = sidekick.task_path(tid)
        fm, body = sidekick.read_note(path)
        fm["from"] = "wife"
        sidekick.write_note(path, fm, body)
        sidekick.complete(tid)
        event = json.loads(self._ledger_lines()[0])
        self.assertEqual(event["from"], "wife")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_engine_api.py -q`
Expected: 2 failed (`TypeError: complete() got an unexpected keyword argument 'note'` and `KeyError: 'from'`), the omission guard already passes, 5 existing pass — total `2 failed, 5 passed`.

- [ ] **Step 3: Write the implementation**

In `sidekick.py`, replace the whole `complete()` function with:

```python
def complete(task_id, completed_at=None, note=None, via=None):
    """Append the completion event to the ledger (its only writer), then mark the
    task done. Idempotent: an already-done task is NOT re-appended. `completed_at` (ISO
    string) lets a caller (e.g. the phone) stamp the moment of completion; defaults to
    now. `note` (what worked / what happened) and `via` (cli|phone|agent) are optional
    learning-layer fields; `from` is copied from task frontmatter when present (who
    captured the task — written by the shared-list layer). All three are OMITTED when
    absent, never null — old and new ledger lines stay shape-compatible, and readers
    must tolerate missing fields. Returns a result dict. Raises FileNotFoundError if
    the task file is absent."""
    fm, body = read_note(task_path(task_id))
    title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), task_id)
    if fm.get("status") == "done":
        return {"id": task_id, "task": title, "category": fm.get("category"),
                "status": "done", "completed_at": fm.get("completed"),
                "sat_for_hours": None, "already_done": True}
    plan = fm.get("plan")
    stamp = completed_at or now_iso()
    event = {
        "task": title,
        "category": fm.get("category"),
        "completed_at": stamp,
        "sat_for_hours": hours_since(fm.get("created")),
        "orchestrator": (plan or {}).get("summary"),   # what the orchestrator did to help (§6)
    }
    if note:
        event["note"] = note
    if via:
        event["via"] = via
    if fm.get("from"):
        event["from"] = fm["from"]
    with open(LEDGER, "a", encoding="utf-8") as f:       # append-only, code-only
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    fm["status"] = "done"
    fm["completed"] = stamp
    write_note(task_path(task_id), fm, body)
    print(f"completed {task_id}  ->  ledger +1")
    return {"id": task_id, "task": title, "category": event["category"],
            "status": "done", "completed_at": stamp,
            "sat_for_hours": event["sat_for_hours"], "already_done": False}
```

(This is the existing function with the docstring extended and the three `if` lines inserted after the `event = {...}` literal — nothing else changes.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_engine_api.py -q`
Expected: `7 passed`

Then the full engine + server suites (server calls `complete()` too):
Run: `python3 -m pytest tests/ server/tests/ -q`
Expected: `0 failed`

- [ ] **Step 5: Commit**

```bash
git add sidekick.py tests/test_engine_api.py
git commit -m "engine: complete() records optional note/via/from ledger fields"
```

---

### Task 2: CLI — `complete <id> --note ... --via cli|phone|agent`

**Files:**
- Modify: `sidekick.py` (`main()`, the `complete` subparser and dispatch, currently lines 285 and 298–299)
- Test: `tests/test_cli_complete.py` (new file; subprocess style like `tests/test_regenerate.py`)

**Interfaces:**
- Consumes: `complete(task_id, note=, via=)` from Task 1.
- Produces: `python sidekick.py complete <id> [--note "<text>"] [--via cli|phone|agent]`. `--via` defaults to `"cli"` (a human/orchestrator at the keyboard); the server passes `phone` programmatically (Task 4); the future agent runner passes `--via agent` in its prompt template (sub-project 3 — no code here). Invalid `--via` values are rejected by argparse.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_complete.py`:

```python
"""complete's CLI flags (--note, --via) must reach the ledger event, and --via must
default to "cli". Runs sidekick.py as a subprocess against a throwaway vault
(SIDEKICK_VAULT), so it exercises the real CLI. Requires pyyaml (the only dep)."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sidekick.py"


class CliCompleteFlags(unittest.TestCase):
    def _run(self, vault, *args, check=True):
        env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              check=check, env=env, cwd=str(vault),
                              capture_output=True, text=True)

    def _make_task(self, vault):
        (vault / "ledger.jsonl").write_text("", encoding="utf-8")
        out = self._run(vault, "new", "Fix the bike light", "--category", "chore").stdout
        return out.splitlines()[0].split()[1]          # "created <id>"

    def _event(self, vault):
        lines = [l for l in (vault / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        self.assertEqual(len(lines), 1)
        return json.loads(lines[0])

    def test_note_and_via_reach_the_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            tid = self._make_task(vault)
            self._run(vault, "complete", tid, "--note", "battery is CR2032", "--via", "agent")
            e = self._event(vault)
            self.assertEqual(e["note"], "battery is CR2032")
            self.assertEqual(e["via"], "agent")

    def test_via_defaults_to_cli_and_note_is_omitted(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            tid = self._make_task(vault)
            self._run(vault, "complete", tid)
            e = self._event(vault)
            self.assertEqual(e["via"], "cli")
            self.assertNotIn("note", e)

    def test_invalid_via_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            tid = self._make_task(vault)
            r = self._run(vault, "complete", tid, "--via", "carrier-pigeon", check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("invalid choice", r.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_cli_complete.py -q`
Expected: `3 failed` — the first two with `KeyError`/unrecognized-argument `CalledProcessError` (the CLI doesn't accept `--note`/`--via` yet and writes no `via`), the third because the unknown flag exits 2 with `unrecognized arguments`, not `invalid choice`.

- [ ] **Step 3: Write the implementation**

In `sidekick.py` `main()`, replace:

```python
    pc = sub.add_parser("complete"); pc.add_argument("id")
```

with:

```python
    pc = sub.add_parser("complete"); pc.add_argument("id")
    pc.add_argument("--note", help="what worked / what happened — recorded in the ledger event")
    pc.add_argument("--via", choices=["cli", "phone", "agent"], default="cli",
                    help="which surface completed it (default: cli)")
```

and replace the dispatch:

```python
    elif a.cmd == "complete":
        complete(a.id); regenerate()
```

with:

```python
    elif a.cmd == "complete":
        complete(a.id, note=a.note, via=a.via); regenerate()
```

Also extend the module docstring's command list line (line 15) from

```
    python sidekick.py complete <id>              # -> appends to ledger, marks done
```

to

```
    python sidekick.py complete <id> [--note "<what worked>"] [--via cli|phone|agent]
                                                  # -> appends to ledger, marks done
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: `0 failed` (17 engine tests at this point: 11 pre-existing + 3 from Task 1 + 3 here — count may be higher if parallel sub-projects added tests).

- [ ] **Step 5: Commit**

```bash
git add sidekick.py tests/test_cli_complete.py
git commit -m "cli: complete gains --note and --via (default cli)"
```

---

### Task 3: Engine — `compute_stats()` + `regenerate` embeds a `stats` key

**Files:**
- Modify: `sidekick.py` (new `_parse_completed_at` + `compute_stats` functions inserted between `read_ledger()` and `regenerate()`; two-line change inside `regenerate()`)
- Test: `tests/test_stats.py` (new file)

**Interfaces:**
- Consumes: ledger events as parsed by `read_ledger()` (plain dicts).
- Produces: `compute_stats(events, today=None) -> dict` — pure, deterministic, UTC-only. Shape:
  - `total` — number of (dict) events;
  - `by_category` — `{category: count}`, `None`/missing category counted as `"uncategorized"`, keys sorted (byte-stable JSON);
  - `median_sat_hours` — median of non-null `sat_for_hours` (mean of the two middle values for even counts), `None` when empty;
  - `by_weekday` — 7 ints, Monday-first (matches `datetime.weekday()`), UTC;
  - `by_hour` — 24 ints, hour 00–23, UTC;
  - `streak_days` — consecutive UTC days with ≥1 completion counted back from `today`, with a grace rule: an empty *today* doesn't break the streak until the day is over (count back from yesterday instead).
  - `today` is injectable (a `datetime.date`) for tests; `regenerate` passes nothing → current UTC date. The `stats` value is therefore a pure function of (ledger, clock) — same idempotency class as the existing timestamp banner.
- `regenerate()` payload becomes `{"events": ..., "active": ..., "stats": compute_stats(events)}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stats.py`:

```python
"""compute_stats() must be a deterministic, UTC-binned aggregate over ledger events,
tolerant of pre-learning-layer lines (missing fields), with an injectable `today` so
streak tests are stable; regenerate() must embed it under the feed's "stats" key."""
import datetime as dt
import json, tempfile, unittest
from pathlib import Path

import sidekick


def ev(**over):
    e = {"task": "T", "category": "chore", "completed_at": "2026-06-10T21:30:00Z",
         "sat_for_hours": 50, "orchestrator": None}
    e.update(over)
    return e


TODAY = dt.date(2026, 6, 10)   # a Wednesday


class ComputeStats(unittest.TestCase):
    def test_empty_ledger(self):
        s = sidekick.compute_stats([], today=TODAY)
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["by_category"], {})
        self.assertIsNone(s["median_sat_hours"])
        self.assertEqual(s["by_weekday"], [0] * 7)
        self.assertEqual(s["by_hour"], [0] * 24)
        self.assertEqual(s["streak_days"], 0)

    def test_by_category_counts_and_uncategorized(self):
        s = sidekick.compute_stats([ev(), ev(category="phone"), ev(category=None)], today=TODAY)
        self.assertEqual(s["by_category"], {"chore": 1, "phone": 1, "uncategorized": 1})
        self.assertEqual(s["total"], 3)

    def test_median_ignores_null_and_averages_even_counts(self):
        odd = [ev(sat_for_hours=1), ev(sat_for_hours=100), ev(sat_for_hours=3),
               ev(sat_for_hours=None)]
        self.assertEqual(sidekick.compute_stats(odd, today=TODAY)["median_sat_hours"], 3)
        even = [ev(sat_for_hours=h) for h in (1, 2, 3, 4)]
        self.assertEqual(sidekick.compute_stats(even, today=TODAY)["median_sat_hours"], 2.5)

    def test_weekday_and_hour_histogram_utc(self):
        # 2026-06-10T21:30Z is a Wednesday, hour 21 UTC (23:30 in Copenhagen — binned in UTC)
        s = sidekick.compute_stats([ev()], today=TODAY)
        self.assertEqual(s["by_weekday"], [0, 0, 1, 0, 0, 0, 0])
        self.assertEqual(s["by_hour"][21], 1)
        self.assertEqual(sum(s["by_hour"]), 1)

    def test_streak_counts_back_from_today(self):
        events = [ev(completed_at=f"2026-06-{d:02d}T10:00:00Z") for d in (10, 9, 8, 5)]
        self.assertEqual(sidekick.compute_stats(events, today=TODAY)["streak_days"], 3)

    def test_streak_grace_when_today_is_empty(self):
        # nothing cleared today yet — the streak isn't broken until the day is over
        events = [ev(completed_at=f"2026-06-{d:02d}T10:00:00Z") for d in (9, 8)]
        self.assertEqual(sidekick.compute_stats(events, today=TODAY)["streak_days"], 2)

    def test_streak_broken_by_a_full_missed_day(self):
        events = [ev(completed_at="2026-06-08T10:00:00Z")]
        self.assertEqual(sidekick.compute_stats(events, today=TODAY)["streak_days"], 0)

    def test_tolerates_legacy_and_malformed_events(self):
        events = [
            {"task": "pre-learning-layer line"},        # no category/completed_at/sat_for_hours
            ev(completed_at="not-a-date"),               # unparseable stamp: skipped from bins
            ["not", "a", "dict"],                        # defensive: skipped entirely
        ]
        s = sidekick.compute_stats(events, today=TODAY)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_category"], {"chore": 1, "uncategorized": 1})
        self.assertEqual(sum(s["by_weekday"]), 0)
        self.assertEqual(sum(s["by_hour"]), 0)
        self.assertEqual(s["streak_days"], 0)


class RegenerateEmbedsStats(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "tasks").mkdir()
        (self.vault / "ledger.jsonl").write_text(json.dumps(ev()) + "\n", encoding="utf-8")
        sidekick.configure(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def test_stats_key_in_feed(self):
        sidekick.regenerate()
        text = (self.vault / "sidekick-data.js").read_text(encoding="utf-8")
        payload = json.loads(text.split("window.SIDEKICK = ", 1)[1].rstrip().rstrip(";"))
        self.assertIn("stats", payload)
        self.assertEqual(payload["stats"]["total"], 1)
        self.assertEqual(payload["stats"]["by_category"], {"chore": 1})
        self.assertEqual(len(payload["stats"]["by_weekday"]), 7)
        self.assertEqual(len(payload["stats"]["by_hour"]), 24)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_stats.py -q`
Expected: `9 failed` — eight with `AttributeError: module 'sidekick' has no attribute 'compute_stats'`, the regenerate test with `AssertionError: 'stats' not found`.

- [ ] **Step 3: Write the implementation**

In `sidekick.py`, insert between `read_ledger()` and `regenerate()`:

```python
# ── stats (deterministic aggregates over the ledger) ─────────────────────────
def _parse_completed_at(iso):
    """UTC datetime from a ledger completed_at, or None if absent/malformed.
    Naive stamps are assumed UTC (the engine always writes Z)."""
    if not iso or not isinstance(iso, str):
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc)


def compute_stats(events, today=None):
    """Deterministic aggregates for the dashboards' stats panel (spec sub-project 5).
    Pure function of (events, today) — `today` (a dt.date) is injectable for tests;
    regenerate passes nothing and gets the current UTC date. All calendar math is UTC
    because completed_at is stored as UTC ISO; a late evening in Copenhagen (UTC+1/+2)
    can bin to an earlier UTC hour / previous UTC day — accepted and labeled "UTC" in
    the UIs rather than guessing a display timezone here. Tolerates pre-learning-layer
    ledger lines: every field may be missing. NO model logic — deterministic only."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    total = 0
    by_category = {}
    sat = []
    by_weekday = [0] * 7            # Monday..Sunday, matching datetime.weekday()
    by_hour = [0] * 24              # 00..23 UTC
    days = set()
    for e in events:
        if not isinstance(e, dict):
            continue                # defensive: a ledger line that parsed to a non-object
        total += 1
        cat = e.get("category") or "uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1
        h = e.get("sat_for_hours")
        if isinstance(h, (int, float)) and not isinstance(h, bool):
            sat.append(h)
        t = _parse_completed_at(e.get("completed_at"))
        if t is not None:
            by_weekday[t.weekday()] += 1
            by_hour[t.hour] += 1
            days.add(t.date())
    # current streak: consecutive UTC days with >=1 completion, counted back from
    # today — or from yesterday when today is still empty (an empty today doesn't
    # break the streak until the day is over).
    streak = 0
    day = today if today in days else today - dt.timedelta(days=1)
    while day in days:
        streak += 1
        day -= dt.timedelta(days=1)
    median = None
    if sat:
        s = sorted(sat)
        mid = len(s) // 2
        median = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
    return {
        "total": total,
        "by_category": dict(sorted(by_category.items())),   # sorted keys => byte-stable JSON
        "median_sat_hours": median,
        "by_weekday": by_weekday,
        "by_hour": by_hour,
        "streak_days": streak,
    }
```

Then in `regenerate()`, replace:

```python
    payload = {"events": read_ledger(), "active": read_active()}
```

with:

```python
    events = read_ledger()
    payload = {"events": events, "active": read_active(), "stats": compute_stats(events)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: `0 failed` (26 engine tests at this point; higher if parallel work added more).

- [ ] **Step 5: Commit**

```bash
git add sidekick.py tests/test_stats.py
git commit -m "engine: compute_stats — deterministic UTC aggregates embedded by regenerate"
```

---

### Task 4: Server — `post_complete` passes `via="phone"` (+ note passthrough)

**Files:**
- Modify: `server/app.py` (inside `post_complete`)
- Test: `server/tests/test_api_writes.py` (append)

> **Drift warning:** sub-project 2 (shared list) may land role/identity handling in `server/app.py` in parallel — line numbers and surrounding code may have shifted, and `post_complete` may have gained role checks. **Locate the snippets below by content, not by line number**, and keep any role logic that is already there. If sub-project 2 has introduced a per-token identity, it is fine (and expected) to keep `via="phone"` for all phone-API completions — `via` is the *surface*, identity is the `from` frontmatter field.

**Interfaces:**
- Consumes: `sidekick.complete(task_id, completed_at=, note=, via=)` from Task 1.
- Produces: every completion through the HTTP API stamps `via: "phone"` on the ledger event; an optional `note` string in the request body is passed through. No endpoint shape change.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_api_writes.py`:

```python
def test_complete_stamps_via_phone_and_passes_note(client):
    tid = client.post("/tasks", json={"title": "Book dentist", "category": "phone"},
                      headers=AUTH).json()["id"]
    r = client.post(f"/tasks/{tid}/complete",
                    json={"note": "receptionist answers after 10am"}, headers=AUTH)
    assert r.status_code == 200
    events = client.get("/feed", headers=AUTH).json()["events"]
    e = next(e for e in events if e["task"] == "Book dentist")
    assert e["via"] == "phone"
    assert e["note"] == "receptionist answers after 10am"


def test_complete_note_is_optional_and_never_null(client):
    tid = client.post("/tasks", json={"title": "No note", "category": "chore"},
                      headers=AUTH).json()["id"]
    client.post(f"/tasks/{tid}/complete", json={}, headers=AUTH)
    e = next(e for e in client.get("/feed", headers=AUTH).json()["events"]
             if e["task"] == "No note")
    assert e["via"] == "phone"
    assert "note" not in e
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_writes.py -q`
Expected: the two new tests fail with `KeyError: 'via'`; all pre-existing tests pass.

- [ ] **Step 3: Write the implementation**

In `server/app.py`, inside `post_complete`, **locate** (current code as of this plan — may have shifted):

```python
        completed_at = data.get("completed_at")
```

and change it to:

```python
        completed_at = data.get("completed_at")
        note = data.get("note")
        if not (isinstance(note, str) and note.strip()):
            note = None            # never forward junk/empty into the ledger
```

Then **locate** the engine call inside the endpoint's `run()` closure:

```python
                    result = sidekick.complete(task_id, completed_at=completed_at)
```

and change it to:

```python
                    result = sidekick.complete(task_id, completed_at=completed_at,
                                               note=note, via="phone")
```

Leave everything else (auth, role checks if present, idempotency, `regenerate`, `commit_and_push`) exactly as found.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/ -q`
Expected: `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_writes.py
git commit -m "server: phone completions stamp via=phone and pass note through"
```

---

### Task 5: Static dashboard — Patterns panel in `sidekick.html` + `sidekick-render.js`

**Files:**
- Modify: `sidekick.html` (one new section + CSS block — the *view source*, which is hand-maintained; it is never *regenerated*, so editing it is sanctioned)
- Modify: `sidekick-render.js` (read `window.SIDEKICK.stats`, render tiles, tolerate a missing key)
- Generated fallout to commit: `sidekick-data.js` and `chrome-extension/sidekick-data.js` + `chrome-extension/sidekick-render.js` (refreshed by `regenerate` — never hand-edit them)

**Interfaces:**
- Consumes: the `stats` object from Task 3 via `window.SIDEKICK.stats`.
- Produces: a "Patterns" section (between "Skill branches" and "Recently cleared") with four tiles: streak, median time-to-done, category counts, weekday histogram. **Backward compatible:** if the feed predates the learning layer (no `stats` key), the section and its heading are hidden — the reader tolerates the missing field.

> No JS test harness exists for the static dashboard (by design — it is a doubleclickable file; the render brain is exercised visually and by the PWA's mirrored logic in Task 6). Verification here is a syntax check + `regenerate` + eyeball, mirroring how the file has always been maintained.

- [ ] **Step 1: Add the section to `sidekick.html`**

Locate:

```html
  <div class="head"><h2>Skill branches</h2><span class="rule"></span></div>
  <section class="section branches" id="branches"></section>

  <div class="head"><h2>Recently cleared</h2><span class="rule"></span></div>
```

and insert between the branches section and the "Recently cleared" head:

```html
  <div class="head" id="patternsHead"><h2>Patterns</h2><span class="rule"></span></div>
  <section class="section patterns" id="patterns"></section>
```

- [ ] **Step 2: Add the CSS**

In the `<style>` block of `sidekick.html`, locate the line

```css
  .branch.lit{ opacity:0; animation:kindle .55s ease forwards; }
```

and insert after it:

```css
  .patterns{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
  .stat{ background:var(--ink-raised); border:1px solid var(--line); border-radius:14px; padding:16px 16px 18px; }
  .stat .slabel{ font-size:11px; letter-spacing:.26em; text-transform:uppercase; color:var(--bone-dim); font-weight:600; }
  .stat .sval{ font-family:var(--display); font-weight:500; font-size:34px; color:var(--brass-soft); margin-top:6px; }
  .stat .sval.sm{ font-size:21px; color:var(--bone); }
  .stat .ssub{ font-family:var(--mono); font-size:11px; color:var(--bone-faint); margin-top:6px; line-height:1.5; }
  .stat .wk{ display:flex; gap:4px; align-items:flex-end; height:36px; margin-top:12px; }
  .stat .wk i{ flex:1; background:var(--brass); opacity:.8; border-radius:2px 2px 0 0; min-height:2px; }
  .stat .wkl{ display:flex; gap:4px; margin-top:4px; }
  .stat .wkl span{ flex:1; text-align:center; font-family:var(--mono); font-size:9px; color:var(--bone-faint); }
```

- [ ] **Step 3: Render the panel in `sidekick-render.js`**

At the top of the file, after

```js
const ACTIVE = (window.SIDEKICK && window.SIDEKICK.active) || [];
```

add:

```js
const STATS  = (window.SIDEKICK && window.SIDEKICK.stats) || null;   // absent on pre-learning-layer feeds
```

Inside `render()`, between the branches block and the `// recently cleared` block, insert:

```js
  // patterns — deterministic aggregates computed by `sidekick.py regenerate`.
  // Older feeds have no stats key: hide the section instead of rendering zeros.
  const phost = document.getElementById("patterns");
  if (STATS){
    const cats = Object.entries(STATS.by_category||{}).sort((a,b)=>b[1]-a[1] || (a[0]<b[0]?-1:1));
    const wk = STATS.by_weekday || [0,0,0,0,0,0,0];
    const wkMax = Math.max(1, ...wk);
    const WD = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
    const busiest = wk.some(v=>v>0) ? WD[wk.indexOf(Math.max(...wk))] : "—";
    phost.innerHTML = `
      <div class="stat"><div class="slabel">Streak</div><div class="sval">${STATS.streak_days||0}d</div><div class="ssub">consecutive days cleared · UTC</div></div>
      <div class="stat"><div class="slabel">Median to done</div><div class="sval">${dur(STATS.median_sat_hours)}</div><div class="ssub">capture → cleared</div></div>
      <div class="stat"><div class="slabel">Top category</div><div class="sval sm">${cats.length?esc(cats[0][0]):"—"}</div><div class="ssub">${cats.map(([c,n])=>esc(c)+" "+n).join(" · ")||"nothing yet"}</div></div>
      <div class="stat"><div class="slabel">By weekday</div>
        <div class="wk">${wk.map(v=>`<i style="height:${Math.round(v/wkMax*100)}%"></i>`).join("")}</div>
        <div class="wkl">${WD.map(n=>`<span>${n}</span>`).join("")}</div>
        <div class="ssub">busiest: ${busiest} · UTC days</div></div>`;
  } else {
    phost.style.display = "none";
    document.getElementById("patternsHead").style.display = "none";
  }
```

(`dur` and `esc` already exist in this file; category names pass through `esc` — they originate from hand-editable frontmatter.)

- [ ] **Step 4: Verify**

Run: `node --check sidekick-render.js`
Expected: no output, exit 0.

Run: `python3 sidekick.py regenerate`
Expected: `regenerated sidekick-data.js — N events, M open` — and `git status` now shows `sidekick-data.js` plus the `chrome-extension/` mirrors modified (the feed gained its `stats` key). Inspect `sidekick-data.js` and confirm a `"stats"` object with `by_weekday` of length 7.

Visual check: `python3 -m http.server 8765` then open `http://localhost:8765/sidekick.html` — a "Patterns" row of four tiles renders between Skill branches and Recently cleared; kill the server after. Also confirm the tolerance path: temporarily serving an old feed (e.g. `git stash` the data file change) hides the section without console errors, then restore.

Run: `python3 -m pytest tests/ -q` — Expected: `0 failed` (regenerate output shape is covered by `tests/test_stats.py` and `tests/test_regenerate.py`).

- [ ] **Step 5: Commit (view change + regenerated artifacts together)**

```bash
git add sidekick.html sidekick-render.js sidekick-data.js chrome-extension/sidekick-data.js chrome-extension/sidekick-render.js
git commit -m "dashboard: Patterns panel — streak, median, categories, weekday histogram"
```

---

### Task 6: PWA — client-side stats (`web/src/lib/stats.ts`) + Patterns section on the dashboard

**Files:**
- Modify: `web/src/lib/types.ts` (`LedgerEvent` gains the optional fields)
- Create: `web/src/lib/stats.ts`
- Test: `web/src/lib/stats.test.ts` (new), `web/src/routes/dashboard.test.ts` (append one test)
- Modify: `web/src/routes/Dashboard.svelte`, `web/src/app.css`

**Interfaces:**
- Consumes: `Feed.events` from `/feed` (the API returns raw events with **no** `stats` key — the PWA computes its whole game brain client-side, so stats follow the same pattern; see `web/src/lib/game.ts`).
- Produces: `computeStats(events, now?) -> Stats` — a client-side mirror of `sidekick.py compute_stats`, same definitions (UTC bins, Monday-first weekday, median with even-count averaging, streak with empty-today grace). `now` is an injectable epoch-ms for tests. Kept in **lockstep** with the Python function — a definition change in one must land in both.

- [ ] **Step 1: Extend the event type**

In `web/src/lib/types.ts`, replace the `LedgerEvent` interface with:

```ts
export interface LedgerEvent {
  task: string;
  category: string | null;
  completed_at: string;
  sat_for_hours: number | null;
  orchestrator?: string | null;
  /* learning-layer fields — absent on pre-learning-layer ledger lines */
  note?: string | null;
  via?: string | null;
  from?: string | null;
}
```

- [ ] **Step 2: Write the failing tests**

Create `web/src/lib/stats.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { computeStats } from "./stats";
import type { LedgerEvent } from "./types";

const ev = (over: Partial<LedgerEvent> = {}): LedgerEvent => ({
  task: "T", category: "chore", completed_at: "2026-06-10T21:30:00Z",
  sat_for_hours: 50, orchestrator: null, ...over
});

describe("computeStats", () => {
  it("counts categories, treating null as uncategorized", () => {
    const s = computeStats([ev(), ev({ category: "phone" }), ev({ category: null })]);
    expect(Object.fromEntries(s.byCategory)).toEqual({ chore: 1, phone: 1, uncategorized: 1 });
    expect(s.total).toBe(3);
  });

  it("orders byCategory by count desc, then name", () => {
    const s = computeStats([ev({ category: "phone" }), ev({ category: "phone" }), ev()]);
    expect(s.byCategory[0]).toEqual(["phone", 2]);
  });

  it("takes the median of sat_for_hours, ignoring nulls, averaging even counts", () => {
    expect(computeStats([ev({ sat_for_hours: 1 }), ev({ sat_for_hours: 100 }),
      ev({ sat_for_hours: 3 }), ev({ sat_for_hours: null })]).medianSatHours).toBe(3);
    expect(computeStats([1, 2, 3, 4].map(h => ev({ sat_for_hours: h }))).medianSatHours).toBe(2.5);
    expect(computeStats([ev({ sat_for_hours: null })]).medianSatHours).toBeNull();
  });

  it("bins weekday (Mon-first, like Python) and hour in UTC", () => {
    // 2026-06-10T21:30Z is a Wednesday
    const s = computeStats([ev()]);
    expect(s.byWeekday).toEqual([0, 0, 1, 0, 0, 0, 0]);
    expect(s.byHour[21]).toBe(1);
    expect(s.byHour.reduce((a, b) => a + b)).toBe(1);
  });

  it("computes the streak with injectable now; empty today doesn't break it", () => {
    const now = Date.parse("2026-06-10T12:00:00Z");
    const on = (d: string) => ev({ completed_at: `${d}T10:00:00Z` });
    expect(computeStats([on("2026-06-10"), on("2026-06-09"), on("2026-06-08")], now).streakDays).toBe(3);
    expect(computeStats([on("2026-06-09"), on("2026-06-08")], now).streakDays).toBe(2);
    expect(computeStats([on("2026-06-10"), on("2026-06-08")], now).streakDays).toBe(1);
    expect(computeStats([on("2026-06-01")], now).streakDays).toBe(0);
  });

  it("tolerates pre-learning-layer events without crashing", () => {
    const legacy = { task: "old", category: null, completed_at: "not-a-date",
                     sat_for_hours: null } as LedgerEvent;
    const s = computeStats([legacy]);
    expect(s.total).toBe(1);
    expect(s.byWeekday.reduce((a, b) => a + b)).toBe(0);
    expect(s.streakDays).toBe(0);
  });
});
```

Append to `web/src/routes/dashboard.test.ts` (inside the existing `describe("Dashboard", ...)` block; the shared `feed` fixture at the top of that file already has `phone` and `errand` events):

```ts
  it("renders the patterns panel computed from events", () => {
    const { container } = render(Dashboard, { props: { feed } });
    expect(screen.getByText("Patterns")).toBeInTheDocument();
    const panel = container.querySelector(".patterns");
    expect(panel?.textContent).toContain("phone 1");
    expect(panel?.textContent).toContain("consecutive days");
  });
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npm --prefix web test`
Expected: `stats.test.ts` fails to resolve `./stats` (module not found); the new dashboard test fails (`Patterns` not in the document); all pre-existing tests pass.

- [ ] **Step 4: Write the implementation**

Create `web/src/lib/stats.ts`:

```ts
import type { LedgerEvent } from "./types";

/* Client-side mirror of sidekick.py compute_stats(): the PWA gets raw events from
   /feed (no stats key — that key only exists in the generated sidekick-data.js), so
   it derives the same aggregates itself, like everything else in $lib/game.ts.
   All calendar math is UTC — completed_at is stored as UTC ISO; a late evening in
   Copenhagen (UTC+1/+2) can bin to an earlier UTC hour / previous UTC day. Labeled
   "UTC" in the UI. KEEP DEFINITIONS IN LOCKSTEP with sidekick.py compute_stats. */

export interface Stats {
  total: number;
  byCategory: [string, number][];   // count desc, then name asc
  medianSatHours: number | null;
  byWeekday: number[];              // Mon..Sun, UTC (Python weekday() order)
  byHour: number[];                 // 00..23, UTC
  streakDays: number;
}

const DAY = 86400000;
const utcDay = (t: number) => Math.floor(t / DAY);

export function computeStats(events: LedgerEvent[], now: number = Date.now()): Stats {
  const byCat = new Map<string, number>();
  const sat: number[] = [];
  const byWeekday = new Array(7).fill(0);
  const byHour = new Array(24).fill(0);
  const days = new Set<number>();
  for (const e of events) {
    const cat = e.category || "uncategorized";
    byCat.set(cat, (byCat.get(cat) || 0) + 1);
    if (typeof e.sat_for_hours === "number") sat.push(e.sat_for_hours);
    const t = Date.parse(e.completed_at ?? "");
    if (!Number.isNaN(t)) {
      const d = new Date(t);
      byWeekday[(d.getUTCDay() + 6) % 7] += 1;   // JS Sunday-first -> Monday-first
      byHour[d.getUTCHours()] += 1;
      days.add(utcDay(t));
    }
  }
  // current streak: consecutive UTC days counted back from today, or from
  // yesterday when today is still empty (grace until the day is over).
  let streak = 0;
  let day = utcDay(now);
  if (!days.has(day)) day -= 1;
  while (days.has(day)) { streak += 1; day -= 1; }
  let median: number | null = null;
  if (sat.length) {
    const s = [...sat].sort((a, b) => a - b);
    const mid = s.length >> 1;
    median = s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  }
  return {
    total: events.length,
    byCategory: [...byCat.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])),
    medianSatHours: median,
    byWeekday, byHour, streakDays: streak
  };
}

export const WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
```

In `web/src/routes/Dashboard.svelte`, extend the `<script lang="ts">` block — after the existing `import { hero, branchVMs, recentLog, catHue, dur } from "$lib/game";` add:

```ts
  import { computeStats, WEEKDAY_NAMES } from "$lib/stats";
```

and after the existing `const log = $derived(recentLog(feed, 7));` add:

```ts
  const stats = $derived(computeStats(feed.events));
  const wkMax = $derived(Math.max(1, ...stats.byWeekday));
```

Then insert this markup between the closing `</section>` of the branches block and the `<div class="head"><h2>Recently cleared</h2>...` line:

```svelte
<div class="head"><h2>Patterns</h2><span class="rule"></span></div>
<section class="section patterns">
  <div class="stat"><div class="slabel">Streak</div><div class="sval">{stats.streakDays}d</div><div class="ssub">consecutive days cleared · UTC</div></div>
  <div class="stat"><div class="slabel">Median to done</div><div class="sval">{dur(stats.medianSatHours)}</div><div class="ssub">capture → cleared</div></div>
  <div class="stat"><div class="slabel">Top category</div>
    <div class="sval sm">{stats.byCategory[0]?.[0] ?? "—"}</div>
    <div class="ssub">{stats.byCategory.map(([c, n]) => `${c} ${n}`).join(" · ") || "nothing yet"}</div></div>
  <div class="stat"><div class="slabel">By weekday</div>
    <div class="wk">{#each stats.byWeekday as v}<i style="height:{Math.round((v / wkMax) * 100)}%"></i>{/each}</div>
    <div class="wkl">{#each WEEKDAY_NAMES as n}<span>{n}</span>{/each}</div>
    <div class="ssub">UTC days</div></div>
</section>
```

Append to `web/src/app.css` (note: the class is `.patterns`, **not** `.stats` — `.stats` is already the hero stat line and is asserted on in `dashboard.test.ts`):

```css
.patterns{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }
.stat{ background:var(--ink-raised); border:1px solid var(--line); border-radius:14px; padding:14px; }
.stat .slabel{ font-size:11px; letter-spacing:.2em; text-transform:uppercase; color:var(--bone-dim); font-weight:600; }
.stat .sval{ font-family:var(--display); font-size:30px; color:var(--brass-soft); margin-top:4px; }
.stat .sval.sm{ font-size:19px; color:var(--bone); }
.stat .ssub{ font-family:var(--mono); font-size:11px; color:var(--bone-faint); margin-top:6px; line-height:1.5; }
.stat .wk{ display:flex; gap:4px; align-items:flex-end; height:32px; margin-top:10px; }
.stat .wk i{ flex:1; background:var(--brass); opacity:.8; border-radius:2px 2px 0 0; min-height:2px; }
.stat .wkl{ display:flex; gap:4px; margin-top:4px; }
.stat .wkl span{ flex:1; text-align:center; font-family:var(--mono); font-size:9px; color:var(--bone-faint); }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npm --prefix web test`
Expected: `0 failed` (6 new stats tests + 1 new dashboard test + all pre-existing).

Run: `npm --prefix web run check`
Expected: `0 errors` (svelte-check over the new types/markup).

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/stats.ts web/src/lib/stats.test.ts web/src/routes/Dashboard.svelte web/src/routes/dashboard.test.ts web/src/app.css
git commit -m "web: client-side stats mirror + Patterns panel on the dashboard"
```

---

## Deployment note (manual ops, after merge)

- **VPS:** the sync timer from sub-project 1 (`sidekick-sync.timer`) pulls `main` automatically within ~3 minutes — no manual vault update. Because `server/app.py` changed (Task 4), restart the API once: `sudo systemctl restart sidekick`.
- **PWA:** if the VPS serves a built copy of `web/`, rebuild/redeploy it per `deploy/WALKTHROUGH.md` (`npm --prefix web run build` + the walkthrough's publish step); the API change is live either way.
- **Mac clone:** per CLAUDE.md, `git pull` before the next task session; the first `regenerate` there already carries the `stats` key (committed in Task 5).
- **Old feeds are harmless:** any surface still holding a pre-learning-layer `sidekick-data.js` simply hides the Patterns panel (Task 5's tolerance path); the PWA computes stats from `/feed` regardless.
