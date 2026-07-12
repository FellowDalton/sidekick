"""Daily nudge, delivered by web push (spec sub-project 4). Ports nudge.py's
DETERMINISTIC decide: the longest-sitting open task at least min_sat_hours old,
preferring one with a prepared plan, first step in the body so starting is
trivial; silent when nothing is genuinely stalled. An optional model may WORD
the message (SIDEKICK_NUDGE_CMD, e.g. "pi -p" — absent until the agent runner
lands); the model never decides more than phrasing, and ANY wording failure
falls back to the deterministic text, so a broken model call never costs the
nudge. Routing is hardcoded: dalton gets every nudge, wife gets none this
phase. Never writes vault data (tasks/, ledger.jsonl); the only mutation is
subscription pruning inside the gitignored push store.

Run: python -m server.nudge_job [--dry-run]    (systemd: deploy/sidekick-nudge.timer)"""
import argparse
import os
import shlex
import subprocess
import sys

# ensure the repo root (where sidekick.py lives) is importable, same as server/app.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidekick                         # noqa: E402
from server import push                 # noqa: E402
from server.config import load_config   # noqa: E402

NUDGE_IDENTITY = "dalton"       # spec: Dalton gets all nudges; wife gets NONE this phase
DEFAULT_MIN_SAT_HOURS = 48.0


def pick_task(active, min_sat):
    """Longest-sitting stalled task, preferring one with a prepared plan.
    (Ported verbatim from nudge.py.)"""
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
    """The always-works wording (nudge.py's, minus its "Sidekick ·" prefix —
    the notification TITLE carries the app name now)."""
    plan = t.get("plan")
    if plan and plan.get("steps"):
        s0 = plan["steps"][0]
        extra = ""
        href = s0.get("href", "")
        if href.startswith("http"):
            extra = f" {href}"
        return (f'"{t["task"]}" has sat {_sat_str(t.get("sat_for_hours"))}. '
                f'First step\'s ready: {s0.get("text", "")}.{extra}')
    return (f'"{t["task"]}" has sat {_sat_str(t.get("sat_for_hours"))}. '
            "Open Claude Code and ask for a first step?")


def model_message(cmd, t):
    """Ask a model command (e.g. `pi -p`) to WORD the nudge for the already-picked
    task. Returns one line, or None on ANY failure — wording never costs the send."""
    plan = t.get("plan")
    first = plan["steps"][0]["text"] if (plan and plan.get("steps")) else None
    prompt = (
        "Word ONE short push-notification nudge (under 200 characters) for this "
        "stalled task. Kind, not naggy. Name the task and, if given, its prepared "
        "first step so starting is trivial. Output only the message text, no preamble.\n\n"
        f"Task: {t['task']} [{t.get('category')}], sitting {_sat_str(t.get('sat_for_hours'))}"
        + (f"; prepared first step: {first}" if first else "; no plan yet")
    )
    timeout = float(os.environ.get("SIDEKICK_NUDGE_TIMEOUT_SEC", "60"))
    try:
        out = subprocess.run(shlex.split(cmd) + [prompt],
                             capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    line = next((l.strip().strip('"').strip()
                 for l in (out.stdout or "").splitlines() if l.strip()), "")
    if not line or line.upper().replace(" ", "").startswith("NUDGE:NONE") or line.upper() == "NONE":
        return None
    return line[:300]


def decide(active, min_sat, cmd=""):
    """(title, body, source) or None for silence. The DECISION (send vs silent,
    which task) is always deterministic; `cmd` affects wording only."""
    t = pick_task(active, min_sat)
    if t is None:
        return None
    if cmd:
        worded = model_message(cmd, t)
        if worded:
            return ("Sidekick", worded, "model")
    return ("Sidekick", deterministic_message(t), "deterministic")


def run(config=None, dry_run=False):
    config = config or load_config()
    sidekick.configure(config.vault)
    active = sidekick.read_active()          # lock-free read, same as GET /feed
    min_sat = float(os.environ.get("SIDEKICK_NUDGE_MIN_SAT_HOURS",
                                   str(DEFAULT_MIN_SAT_HOURS)))
    cmd = os.environ.get("SIDEKICK_NUDGE_CMD", "").strip()
    decision = decide(active, min_sat, cmd)
    if decision is None:
        print(f"nudge: silent (open={len(active)}, none sat >= {min_sat:g}h)")
        return 0
    title, body, source = decision
    if dry_run:
        print(f"nudge DRY-RUN [{source}] -> {NUDGE_IDENTITY}: {body}")
        return 0
    delivered = push.send_to_identity(config, NUDGE_IDENTITY, title, body)
    print(f"nudge [{source}]: delivered to {delivered} subscription(s): {body}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sidekick web-push nudge (daily)")
    ap.add_argument("--dry-run", action="store_true", help="decide + print, send nothing")
    args = ap.parse_args(argv)
    try:
        return run(dry_run=args.dry_run)
    except Exception as e:
        print(f"nudge: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
