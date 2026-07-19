#!/usr/bin/env python3
"""
Sidekick — Obsidian vault  ->  dashboard data feed.

Tasks are markdown files in tasks/ with YAML frontmatter. No Google, no OAuth,
no API client. This file is DETERMINISTIC — the only model-driven step in the
system is the orchestrator composing a plan; it hands the finished plan to
set_plan(), which writes it to frontmatter verbatim. complete() is the SOLE
writer of ledger.jsonl — append-only (spec §6).

Commands (Claude Code runs these):
    python sidekick.py regenerate                 # the assembler — rebuild the feed
    python sidekick.py new "Call the dentist" --category phone
    python sidekick.py set-plan <id> --file plan.json     # or pipe JSON on stdin
    python sidekick.py complete <id> [--note "<what worked>"] [--via cli|phone|agent]
                                                  # -> appends to ledger, marks done

Setup:
    pip install pyyaml          # the only dependency
    The script lives in the vault root, beside ledger.jsonl and sidekick.html.
    Override the location with SIDEKICK_VAULT=/path/to/vault if it lives elsewhere.

A task file (tasks/20260612-sort-the-car-insurance-renewal.md):
    ---
    category: admin
    created: 2026-06-12T08:00:00Z
    status: open
    plan:
      summary: Compared three renewal quotes — current insurer no longer cheapest.
      steps:
        - text: Call Topdanmark and ask them to match the lower quote
          href: tel:+4570115050
        - text: If they won't match, switch to the Alm. Brand quote
        - text: Cancel the old direct debit once the switch confirms
    ---

    # Sort the car insurance renewal
    <the body is free space — orchestrator research prose, anything. Ignored by the script.>
"""

import os, re, sys, json, shutil, argparse, datetime as dt
import yaml

# ── paths ──────────────────────────────────────────────────────────────────
VAULT   = os.environ.get("SIDEKICK_VAULT", os.path.dirname(os.path.abspath(__file__)))
TASKS   = os.path.join(VAULT, "tasks")
LEDGER  = os.path.join(VAULT, "ledger.jsonl")
DATA_JS   = os.path.join(VAULT, "sidekick-data.js")
RENDER_JS = os.path.join(VAULT, "sidekick-render.js")
WIKI       = os.path.join(VAULT, "wiki")
WIKI_INDEX = os.path.join(WIKI, "_index.md")

def configure(vault):
    """Re-point the engine at a different vault. Recomputes every path global from
    `vault`. Used by the host server (one vault per process) and by tests (throwaway
    vaults). The engine is otherwise unchanged and stays deterministic."""
    global VAULT, TASKS, LEDGER, DATA_JS, RENDER_JS, WIKI, WIKI_INDEX
    VAULT = vault
    TASKS = os.path.join(VAULT, "tasks")
    LEDGER = os.path.join(VAULT, "ledger.jsonl")
    DATA_JS = os.path.join(VAULT, "sidekick-data.js")
    RENDER_JS = os.path.join(VAULT, "sidekick-render.js")
    WIKI = os.path.join(VAULT, "wiki")
    WIKI_INDEX = os.path.join(WIKI, "_index.md")

# ── time helpers ─────────────────────────────────────────────────────────────
def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def hours_since(iso):
    if not iso:
        return None
    s = iso if isinstance(iso, str) else (iso.isoformat() if hasattr(iso, "isoformat") else None)
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return round((dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600)

# ── frontmatter read / write ─────────────────────────────────────────────────
def read_note(path):
    """Return (frontmatter_dict, body_str)."""
    text = open(path, encoding="utf-8").read()
    if text.startswith("---"):
        parts = text.split("---", 2)              # ['', fm, body] — body keeps any later '---'
        if len(parts) == 3:
            fm = yaml.safe_load(parts[1]) or {}
            return (fm if isinstance(fm, dict) else {}), parts[2].lstrip("\n")
    return {}, text

def write_note(path, fm, body):
    block = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("---\n" + block + "\n---\n\n" + body.strip() + "\n")
    os.replace(tmp, path)

def slug(s):
    s = re.sub(r"[^\w\s-]", "", s.lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:50] or "task"

def task_path(task_id):
    return os.path.join(TASKS, task_id + ".md")

# ── capture / orchestrator helpers (write side) ─────────────────────────────
def create_task(title, category, *, from_=None, shared=False, parent=None):
    """Create an open task. `from_` (dalton|wife|sidekick) and `shared` are the
    shared-list frontmatter fields (spec sub-project 2) — written only when set,
    so a plain create produces the same file as before. `parent` (a task id) links
    a sub-task to its parent (nested sub-tasks spec) — the parent must exist and
    be open."""
    if parent is not None:
        try:
            pfm, _ = read_note(task_path(parent))
        except FileNotFoundError:
            raise ValueError(f"parent task {parent} not found")
        if pfm.get("status", "open") != "open":
            raise ValueError(f"parent task {parent} is not open")
    os.makedirs(TASKS, exist_ok=True)
    task_id = dt.datetime.now().strftime("%Y%m%d") + "-" + slug(title)
    n, base = 2, task_id
    while os.path.exists(task_path(task_id)):
        task_id = f"{base}-{n}"; n += 1
    fm = {"category": category, "created": now_iso(), "status": "open"}
    if from_:
        fm["from"] = from_
    if shared:
        fm["shared"] = True
    if parent:
        fm["parent"] = parent
    write_note(task_path(task_id), fm, f"# {title}\n")
    print(f"created {task_id}")
    return task_id

def set_plan(task_id, summary, steps):
    """Write a structured plan into the task's frontmatter. The orchestrator (LLM)
    composes summary/steps; this only persists them — no model in the write path."""
    fm, body = read_note(task_path(task_id))
    fm["plan"] = {"summary": summary, "steps": steps}
    write_note(task_path(task_id), fm, body)
    print(f"plan set on {task_id}")

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

# ── the assembler (read side) ────────────────────────────────────────────────
def read_active():
    """Open tasks, plus completed sub-tasks whose parent is still open (they render
    as checked rows under the parent until the parent itself completes — nested
    sub-tasks spec). Completed top-level tasks never appear."""
    active = []
    if not os.path.isdir(TASKS):
        return active
    notes = []
    for name in sorted(os.listdir(TASKS)):
        if not name.endswith(".md"):
            continue
        fm, body = read_note(os.path.join(TASKS, name))
        notes.append((name[:-3], fm, body))
    open_ids = {tid for tid, fm, _ in notes if fm.get("status", "open") == "open"}
    for tid, fm, body in notes:
        title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), tid)
        status = fm.get("status", "open")
        if status == "open":
            active.append({
                "id": tid,
                "task": title,
                "category": fm.get("category"),
                "sat_for_hours": hours_since(fm.get("created")),
                "plan": fm.get("plan"),
                "from": fm.get("from"),
                "shared": bool(fm.get("shared")),
                "parent": fm.get("parent"),
                "status": "open",
            })
        elif status == "done" and fm.get("parent") in open_ids:
            active.append({
                "id": tid,
                "task": title,
                "category": fm.get("category"),
                "sat_for_hours": None,
                "plan": None,
                "from": fm.get("from"),
                "shared": bool(fm.get("shared")),
                "parent": fm.get("parent"),
                "status": "done",
                "completed_at": fm.get("completed"),
            })
    # longest-sitting first — the most-stalled task surfaces at the top
    active.sort(key=lambda a: (a["sat_for_hours"] is not None, a["sat_for_hours"] or 0), reverse=True)
    return active

def read_ledger():
    events = []
    if not os.path.exists(LEDGER):
        return events
    with open(LEDGER, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"ledger.jsonl line {n} is not valid JSON ({e}). "
                         "Fix it; refusing to write a partial feed.")
    return events

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

def regenerate():
    """Build sidekick-data.js from open task files (+ their plans) and the ledger.
    Regenerates the DATA only — sidekick.html is static and never touched."""
    events = read_ledger()
    payload = {"events": events, "active": read_active(), "stats": compute_stats(events)}
    banner = ("/* GENERATED by sidekick.py — do not hand-edit. "
              f"{now_iso()} | {len(payload['events'])} events, {len(payload['active'])} open */\n")
    js = banner + "window.SIDEKICK = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    tmp = DATA_JS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(js)
    os.replace(tmp, DATA_JS)     # atomic: a half-written feed is never served

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

    print(f"regenerated sidekick-data.js — {len(payload['events'])} events, {len(payload['active'])} open")

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
        content = "\n".join(lines) + "\n"
    else:
        content = "_No topics yet._\n"

    tmp = WIKI_INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(head + content)
    os.replace(tmp, WIKI_INDEX)              # atomic: a half-written index is never read
    print(f"wrote wiki/_index.md — {len(entries)} topics")

# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Sidekick data feed (vault-backed)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("regenerate")
    sub.add_parser("wiki")
    pn = sub.add_parser("new");      pn.add_argument("title"); pn.add_argument("--category", required=True)
    pn.add_argument("--from", dest="from_", default=None, help="who created it (dalton|wife|sidekick)")
    pn.add_argument("--shared", action="store_true", help="put it on the shared list")
    pn.add_argument("--parent", default=None,
                    help="parent task id — links this as a sub-task (parent must be open)")
    pp = sub.add_parser("set-plan"); pp.add_argument("id"); pp.add_argument("--file", help="JSON {summary, steps}; omit to read stdin")
    pc = sub.add_parser("complete"); pc.add_argument("id")
    pc.add_argument("--note", help="what worked / what happened — recorded in the ledger event")
    pc.add_argument("--via", choices=["cli", "phone", "agent"], default="cli",
                    help="which surface completed it (default: cli)")
    a = ap.parse_args()

    try:
        if a.cmd == "regenerate":
            regenerate()
        elif a.cmd == "wiki":
            wiki_index()
        elif a.cmd == "new":
            create_task(a.title, a.category, from_=a.from_, shared=a.shared, parent=a.parent); regenerate()
        elif a.cmd == "set-plan":
            raw = open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read()
            plan = json.loads(raw)
            set_plan(a.id, plan["summary"], plan["steps"]); regenerate()
        elif a.cmd == "complete":
            complete(a.id, note=a.note, via=a.via); regenerate()
    except ValueError as e:
        sys.exit(str(e))

if __name__ == "__main__":
    main()
