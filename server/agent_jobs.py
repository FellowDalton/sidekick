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
import queue
import shlex
import signal
import subprocess
import threading
import uuid

from server import agent_prompts, git_sync

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


class AgentJobs:
    """Owns the queue, the single worker thread, and the persisted records.
    One instance per app process. Store mutations hold self._lock — the worker
    and the request handlers share this process (single uvicorn worker is
    already mandatory, so cross-process locking is not needed here)."""

    def __init__(self, vault, start_worker=True):
        self.vault = vault
        self._lock = threading.Lock()
        self._queue = queue.Queue()
        with self._lock:
            mark_interrupted(vault)
        if start_worker:
            threading.Thread(target=self._work, daemon=True,
                             name="sidekick-agent-worker").start()

    @staticmethod
    def configured():
        return bool(os.environ.get("SIDEKICK_AGENT_CLONE"))

    # ── records ──────────────────────────────────────────────────────────────
    def enqueue(self, *, task_id, action, title, category, shared, requested_by):
        job = {
            "id": uuid.uuid4().hex,
            "task_id": task_id,
            "action": action,
            "title": title,
            "category": category,
            "shared": bool(shared),
            "requested_by": requested_by,
            "status": "queued",
            "created_at": _now_iso(),
            "started_at": None,
            "finished_at": None,
            "summary": None,
            "error": None,
            "log_tail": None,
        }
        with self._lock:
            jobs = load_jobs(self.vault)
            jobs.append(job)
            save_jobs(self.vault, jobs)
        self._queue.put(job["id"])
        return dict(job)

    def get(self, job_id):
        with self._lock:
            for j in load_jobs(self.vault):
                if j["id"] == job_id:
                    return dict(j)
        return None

    def list_jobs(self, shared_only=False):
        """Newest first, capped. shared_only => only breakdown jobs on shared tasks
        (research transcripts stay private) — what role `shared` may see (spec sub-projects 2+3)."""
        with self._lock:
            jobs = load_jobs(self.vault)
        if shared_only:
            jobs = [j for j in jobs if j.get("shared") and j.get("action") == "breakdown"]
        return [dict(j) for j in reversed(jobs[-LIST_CAP:])]

    def _update(self, job_id, **fields):
        with self._lock:
            jobs = load_jobs(self.vault)
            for j in jobs:
                if j["id"] == job_id:
                    j.update(fields)
                    break
            save_jobs(self.vault, jobs)

    # ── execution ────────────────────────────────────────────────────────────
    def _work(self):
        while True:
            job_id = self._queue.get()
            try:
                self._execute(job_id)
            except Exception as e:      # belt & braces: the worker must never die
                self._update(job_id, status="failed", error=str(e)[:500],
                             finished_at=_now_iso())

    @staticmethod
    def _runner_env():
        clone = os.environ.get("SIDEKICK_AGENT_CLONE", "")
        cmd = os.environ.get("SIDEKICK_AGENT_CMD", "pi -p")
        timeout = float(os.environ.get("SIDEKICK_AGENT_TIMEOUT", "900"))
        return clone, cmd, timeout

    def _execute(self, job_id):
        job = self.get(job_id)
        if job is None or job["status"] != "queued":
            return                       # e.g. marked interrupted meanwhile
        # pre-bind so the except blocks below stay safe even when _runner_env()
        # or log_path() is what raised (unbound locals would NameError there)
        clone, timeout, log_file, baseline = None, None, None, None
        try:
            clone, cmd, timeout = self._runner_env()
            self._update(job_id, status="running", started_at=_now_iso())
            log_file = log_path(self.vault, job_id)
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            if not clone or not os.path.isdir(os.path.join(clone, ".git")):
                raise RuntimeError(f"agent clone not available: {clone!r}")
            # a crash mid-job (process killed, etc.) can leave the clone dirty;
            # reset it before touching it so that never fails the NEXT job's rebase
            self._reset_clone(clone)
            git_sync.pull_latest(clone)                # fresh state before every job
            baseline = self._head_sha(clone)            # roll back here if this job fails after committing
            if job["action"] == "research":
                prompt = agent_prompts.research_prompt(
                    job["task_id"], job["title"], job["category"])
            elif job["action"] == "breakdown":
                prompt = agent_prompts.breakdown_prompt(
                    job["task_id"], job["title"], job["category"], job["shared"])
            else:
                raise ValueError(f"unknown action: {job['action']}")
            with open(log_file, "w", encoding="utf-8") as lf:
                # start_new_session=True puts the command in its own process
                # group so a timeout can kill the whole tree, not just the
                # immediate child — a wrapper (pi, sh -c ...) that forks further
                # work would otherwise be orphaned and keep running past the
                # timeout instead of being reaped.
                # pin SIDEKICK_VAULT to the agent clone: in production the
                # systemd EnvironmentFile sets it to the SERVING clone, and
                # sidekick.py prefers SIDEKICK_VAULT over its own script
                # location — left untouched, the agent's writes land in
                # /srv/sidekick instead of its own clone (incident ad1e97cb)
                child_env = dict(os.environ, SIDEKICK_VAULT=clone)
                proc = subprocess.Popen(shlex.split(cmd) + [prompt], cwd=clone,
                                        stdout=lf, stderr=subprocess.STDOUT,
                                        text=True, start_new_session=True,
                                        env=child_env)
                try:
                    returncode = proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass  # group already gone — nothing to kill
                    proc.wait()
                    raise
            if returncode != 0:
                raise RuntimeError(f"agent command exited {returncode}")
            git_sync.commit_and_push(clone, f"agent: {job['action']} {job['task_id']}")
            self._update(job_id, status="done", finished_at=_now_iso(),
                         summary=self._summary(log_file),
                         log_tail=self._tail(log_file))
        except subprocess.TimeoutExpired:
            self._reset_clone(clone, baseline)
            self._update(job_id, status="failed", finished_at=_now_iso(),
                         error=f"agent command timed out after {timeout:g}s",
                         log_tail=self._tail(log_file))
        except Exception as e:
            self._reset_clone(clone, baseline)
            self._update(job_id, status="failed", finished_at=_now_iso(),
                         error=str(e)[:500], log_tail=self._tail(log_file))

    @staticmethod
    def _tail(log_file):
        if not log_file:                 # job failed before the log existed
            return None
        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                return f.read()[-LOG_TAIL_CHARS:]
        except OSError:
            return None

    @staticmethod
    def _summary(log_file):
        """Last non-empty output line, capped — the one-line result the PWA shows."""
        try:
            with open(log_file, encoding="utf-8", errors="replace") as f:
                lines = [l.strip() for l in f.read().splitlines() if l.strip()]
        except OSError:
            return None
        return lines[-1][:SUMMARY_CHARS] if lines else None

    @staticmethod
    def _head_sha(clone):
        """HEAD sha right after pull_latest — the baseline _reset_clone rolls back
        to if this job fails after committing but before (or during) its push, so
        a failed job's commit never silently rides along with the next job."""
        try:
            out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone,
                                 capture_output=True, text=True, check=True)
            return out.stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            return None

    @staticmethod
    def _reset_clone(clone, baseline=None):
        """Spec: reset --hard && clean -fd on failure. With a baseline sha, reset
        to that commit instead of current HEAD — otherwise a commit this job made
        (whose push then failed) would survive the reset and publish silently
        alongside the next job. Best-effort — never raise from cleanup (the job
        is already failed, or this is just the pre-job dirty-clone guard)."""
        if not clone or not os.path.isdir(clone):
            return
        reset_args = ["reset", "--hard", baseline] if baseline else ["reset", "--hard"]
        for args in (reset_args, ["clean", "-fd"]):
            subprocess.run(["git", *args], cwd=clone, capture_output=True, text=True)
