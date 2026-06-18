#!/usr/bin/env python3
"""
Sidekick nudge — the "comes at you" push (spec §8, the load-bearing piece).

Fired by launchd (see install-nudge.sh), NOT by Claude Code — a Claude Code
session is user-initiated and can't push. This job decides whether to nudge and
sends one short message to yourself via the Beeper Desktop API (→ iMessage →
your phone).

Decision order:
  1. If use_claude: ask headless Claude (`claude -p`) to judge the current state.
       - Claude returns a line  -> send it.
       - Claude returns NONE     -> stay silent (it judged nothing worth it).
       - Claude call FAILS        -> deterministic fallback (below).
  2. Deterministic fallback / use_claude=false: pick the longest-sitting open
     task that has a prepared plan and send its first step. Silent if nothing
     has been sitting at least `min_sat_hours`.

A failed Claude call therefore never costs you the nudge — the fallback fires.
Nothing here is the channel's scheduler; launchd is. This only decides + sends.

Config lives in nudge.config.json (copy nudge.config.example.json). Keep the
token out of git. Logs go to nudge.log so you can see what fired at 9am.
"""

import os, sys, json, subprocess, datetime as dt
import urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sidekick  # reuse read_active() / read_ledger() — same vault

CONFIG = os.path.join(HERE, "nudge.config.json")
LOG    = os.path.join(HERE, "nudge.log")

DEFAULTS = {
    "base_url": "http://localhost:23373",   # Beeper Desktop local API
    "access_token": "",                      # Beeper token (or env BEEPER_ACCESS_TOKEN)
    "chat_id": "",                           # target chat — get it with `find-chat`
    "min_sat_hours": 24,                     # don't nudge about tasks fresher than this
    "use_claude": True,                      # let Claude judge + word the nudge
    "claude_cmd": ["claude", "-p"],          # headless Claude Code invocation
    "claude_timeout_sec": 60,
}

def log(msg):
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass

def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG):
        try:
            cfg.update(json.load(open(CONFIG, encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            log(f"WARN bad config ({e}); using defaults")
    if os.environ.get("BEEPER_ACCESS_TOKEN"):
        cfg["access_token"] = os.environ["BEEPER_ACCESS_TOKEN"]
    return cfg

# ── Beeper Desktop API (stdlib HTTP, no dependency) ───────────────────────
def _req(method, url, token, data=None, timeout=15):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}

def beeper_send(cfg, text):
    chat = urllib.parse.quote(cfg["chat_id"], safe="")
    url = f"{cfg['base_url']}/v1/chats/{chat}/messages"
    return _req("POST", url, cfg["access_token"], {"text": text})

def beeper_search(cfg, query):
    url = f"{cfg['base_url']}/v1/chats/search?" + urllib.parse.urlencode({"query": query, "limit": 20})
    return _req("GET", url, cfg["access_token"])

# ── deterministic pick + wording (the always-works fallback) ───────────────
def pick_task(active, min_sat):
    stalled = [t for t in active if (t.get("sat_for_hours") or 0) >= min_sat]
    if not stalled:
        return None
    pool = [t for t in stalled if t.get("plan")] or stalled
    pool.sort(key=lambda t: t.get("sat_for_hours") or 0, reverse=True)
    return pool[0]

def _sat_str(h):
    h = h or 0
    return f"{round(h/24)}d" if h >= 24 else f"{round(h)}h"

def deterministic_message(t):
    plan = t.get("plan")
    if plan and plan.get("steps"):
        s0 = plan["steps"][0]
        extra = ""
        href = s0.get("href", "")
        if href.startswith("http"):
            extra = f" {href}"
        return f"Sidekick · \u201c{t['task']}\u201d has sat {_sat_str(t.get('sat_for_hours'))}. First step's ready: {s0.get('text','')}.{extra}"
    return f"Sidekick · \u201c{t['task']}\u201d has sat {_sat_str(t.get('sat_for_hours'))}. Open Claude Code and ask for a first step?"

# ── Claude-decides (headless), returns (status, text) ─────────────────────
def claude_message(cfg, active, events):
    rows = []
    for t in active:
        plan = t.get("plan")
        first = plan["steps"][0]["text"] if (plan and plan.get("steps")) else None
        sat = t.get("sat_for_hours")
        d = "unknown" if sat is None else _sat_str(sat)
        rows.append(f"- {t['task']} [{t.get('category')}], sitting {d}"
                    + (f"; prepared first step: {first}" if first else "; no plan yet"))
    state = "\n".join(rows) if rows else "(no open tasks)"
    prompt = (
        "You are the nudge for Sidekick, an ADHD execution-support tool for one person. "
        "Decide whether to send ONE short text-message nudge right now.\n\n"
        "Rules:\n"
        "- If nothing genuinely warrants interrupting them (nothing stalled long, or it would just be nagging), "
        "reply with exactly: NUDGE: NONE\n"
        "- Otherwise reply with ONE line under ~200 characters, naming ONE specific task and its prepared first "
        "concrete action so starting is trivial. Kind, not naggy. No preamble. Output only the message text.\n\n"
        f"Open tasks:\n{state}\n\nCompleted to date: {len(events)}\n"
    )
    cmd = list(cfg["claude_cmd"]) + [prompt]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=cfg["claude_timeout_sec"])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log(f"claude call failed ({e}) — falling back")
        return ("fail", None)
    if out.returncode != 0:
        log(f"claude exit {out.returncode}: {out.stderr.strip()[:200]} — falling back")
        return ("fail", None)
    text = (out.stdout or "").strip()
    if not text:
        return ("fail", None)
    if text.upper().replace(" ", "").startswith("NUDGE:NONE") or text.strip().upper() == "NONE":
        return ("none", None)
    line = next((l.strip().strip('"').strip() for l in text.splitlines() if l.strip()), "")
    return ("ok", line) if line else ("fail", None)

# ── orchestration ──────────────────────────────────────────────────────────
def decide(cfg, active, events):
    """Return (message_or_None, source)."""
    if cfg.get("use_claude"):
        status, text = claude_message(cfg, active, events)
        if status == "ok":
            return text, "claude"
        if status == "none":
            return None, "claude-none"
        # status == "fail" -> deterministic fallback
        t = pick_task(active, cfg["min_sat_hours"])
        return (deterministic_message(t), "fallback") if t else (None, "fallback-empty")
    t = pick_task(active, cfg["min_sat_hours"])
    return (deterministic_message(t), "deterministic") if t else (None, "deterministic-empty")

def run(dry_run=False):
    cfg = load_config()
    active = sidekick.read_active()
    events = sidekick.read_ledger()
    msg, source = decide(cfg, active, events)
    if not msg:
        log(f"no nudge [{source}] (open={len(active)})")
        return
    if dry_run:
        log(f"DRY-RUN [{source}]: {msg}")
        print("\n" + msg)
        return
    if not cfg.get("access_token") or not cfg.get("chat_id"):
        log("ERROR: access_token / chat_id not configured — cannot send. See nudge.config.example.json")
        sys.exit(1)
    try:
        res = beeper_send(cfg, msg)
        log(f"SENT [{source}] id={res.get('pendingMessageID','?')}: {msg}")
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log(f"ERROR send failed ({e}). Is Beeper Desktop running and the token valid?")
        sys.exit(1)

def find_chat(query):
    cfg = load_config()
    if not cfg.get("access_token"):
        sys.exit("Set access_token in nudge.config.json first.")
    try:
        res = beeper_search(cfg, query)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        sys.exit(f"search failed ({e}). Is Beeper Desktop running?")
    items = res.get("items", [])
    if not items:
        print(f"No chats matched {query!r}.")
        return
    print("Copy the id of your self/Note-to-Self chat into nudge.config.json:\n")
    for c in items:
        print(f"{c.get('id')}\n    [{c.get('network')}] {c.get('title')} ({c.get('type')})")

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Sidekick nudge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run");       pr.add_argument("--dry-run", action="store_true")
    sub.add_parser("preview")  # alias for run --dry-run
    fc = sub.add_parser("find-chat"); fc.add_argument("query")
    ts = sub.add_parser("test");      ts.add_argument("text")
    a = ap.parse_args()
    if a.cmd == "run":
        run(dry_run=a.dry_run)
    elif a.cmd == "preview":
        run(dry_run=True)
    elif a.cmd == "find-chat":
        find_chat(a.query)
    elif a.cmd == "test":
        cfg = load_config()
        res = beeper_send(cfg, a.text)
        log(f"TEST sent id={res.get('pendingMessageID','?')}: {a.text}")

if __name__ == "__main__":
    main()
