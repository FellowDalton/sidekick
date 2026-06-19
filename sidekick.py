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
    python sidekick.py complete <id>              # -> appends to ledger, marks done

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
def create_task(title, category):
    os.makedirs(TASKS, exist_ok=True)
    task_id = dt.datetime.now().strftime("%Y%m%d") + "-" + slug(title)
    n, base = 2, task_id
    while os.path.exists(task_path(task_id)):
        task_id = f"{base}-{n}"; n += 1
    fm = {"category": category, "created": now_iso(), "status": "open"}
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

def complete(task_id):
    """Append the completion event to the ledger (its only writer), then mark the
    task done. sat_for_hours comes from the stamped `created` field."""
    fm, body = read_note(task_path(task_id))
    plan = fm.get("plan")
    title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), task_id)
    event = {
        "task": title,
        "category": fm.get("category"),
        "completed_at": now_iso(),
        "sat_for_hours": hours_since(fm.get("created")),
        "orchestrator": (plan or {}).get("summary"),   # what the orchestrator did to help (§6)
    }
    with open(LEDGER, "a", encoding="utf-8") as f:       # append-only, code-only
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    fm["status"] = "done"
    fm["completed"] = event["completed_at"]
    write_note(task_path(task_id), fm, body)
    print(f"completed {task_id}  ->  ledger +1")

# ── the assembler (read side) ────────────────────────────────────────────────
def read_active():
    active = []
    if not os.path.isdir(TASKS):
        return active
    for name in sorted(os.listdir(TASKS)):
        if not name.endswith(".md"):
            continue
        fm, body = read_note(os.path.join(TASKS, name))
        if fm.get("status", "open") != "open":
            continue
        title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), name[:-3])
        active.append({
            "id": name[:-3],
            "task": title,
            "category": fm.get("category"),
            "sat_for_hours": hours_since(fm.get("created")),
            "plan": fm.get("plan"),
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

def regenerate():
    """Build sidekick-data.js from open task files (+ their plans) and the ledger.
    Regenerates the DATA only — sidekick.html is static and never touched."""
    payload = {"events": read_ledger(), "active": read_active()}
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
        body = "\n".join(lines) + "\n"
    else:
        body = "_No topics yet._\n"

    tmp = WIKI_INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(head + body)
    os.replace(tmp, WIKI_INDEX)              # atomic: a half-written index is never read
    print(f"wrote wiki/_index.md — {len(entries)} topics")

# ── CLI ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Sidekick data feed (vault-backed)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("regenerate")
    sub.add_parser("wiki")
    pn = sub.add_parser("new");      pn.add_argument("title"); pn.add_argument("--category", required=True)
    pp = sub.add_parser("set-plan"); pp.add_argument("id"); pp.add_argument("--file", help="JSON {summary, steps}; omit to read stdin")
    pc = sub.add_parser("complete"); pc.add_argument("id")
    a = ap.parse_args()

    if a.cmd == "regenerate":
        regenerate()
    elif a.cmd == "wiki":
        wiki_index()
    elif a.cmd == "new":
        create_task(a.title, a.category); regenerate()
    elif a.cmd == "set-plan":
        raw = open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read()
        plan = json.loads(raw)
        set_plan(a.id, plan["summary"], plan["steps"]); regenerate()
    elif a.cmd == "complete":
        complete(a.id); regenerate()

if __name__ == "__main__":
    main()
