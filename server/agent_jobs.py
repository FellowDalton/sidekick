"""Job queue + store for the agent runner (spec sub-project 3). Jobs run
STRICTLY one at a time: a single daemon worker thread owned by the API process
drains an in-process queue. Records persist to <vault>/.sidekick-agent-jobs.json
(gitignored runtime state, like the idempotency store) so the GET endpoints and
restarts can read state; a job a restart interrupted is marked failed on startup
("interrupted by restart"). The runner executes a configurable command template
(env SIDEKICK_AGENT_CMD, default "pi -p") in a SEPARATE vault clone (env
SIDEKICK_AGENT_CLONE) — never the serving clone — with a per-job log file under
<vault>/.sidekick-agent-logs/. Success: commit+push from the agent clone (the
sync timer delivers it to the serving clone). ANY failure: the clone is reset
hard + cleaned and the job carries the log tail. No model logic in this file."""
import datetime as dt
import json
import os

STORE_NAME = ".sidekick-agent-jobs.json"
LOG_DIR_NAME = ".sidekick-agent-logs"
STORE_CAP = 200            # newest records kept on disk
LIST_CAP = 50              # newest records returned by list_jobs
LOG_TAIL_CHARS = 2000
SUMMARY_CHARS = 300


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def store_path(vault):
    return os.path.join(vault, STORE_NAME)


def log_path(vault, job_id):
    return os.path.join(vault, LOG_DIR_NAME, f"{job_id}.log")


def load_jobs(vault):
    """The persisted job list, oldest first. Missing/corrupt store => empty."""
    try:
        with open(store_path(vault), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_jobs(vault, jobs):
    """Atomic write, capped to the newest STORE_CAP records (bounded growth)."""
    tmp = store_path(vault) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(jobs[-STORE_CAP:], f, indent=1)
    os.replace(tmp, store_path(vault))


def mark_interrupted(vault):
    """Startup pass: any job the previous process left queued/running is dead —
    the queue lives in memory, so no job can survive its process. Returns how many
    records were marked failed."""
    jobs = load_jobs(vault)
    n = 0
    for j in jobs:
        if j.get("status") in ("queued", "running"):
            j["status"] = "failed"
            j["error"] = "interrupted by restart"
            j["finished_at"] = _now_iso()
            n += 1
    if n:
        save_jobs(vault, jobs)
    return n
