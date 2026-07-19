"""The agent job store: gitignored runtime state in the vault root (like the
idempotency and push stores). Restart safety: queued/running records are marked
failed ("interrupted by restart") — the queue lives in memory, so no job can
survive its process."""
from server import agent_jobs


def _job(i="j1", status="queued", shared=False):
    return {"id": i, "task_id": "t-" + i, "action": "research", "title": "T",
            "category": "admin", "shared": shared, "requested_by": "dalton",
            "status": status, "created_at": "2026-07-12T00:00:00Z",
            "started_at": None, "finished_at": None,
            "summary": None, "error": None, "log_tail": None}


def test_load_missing_store_is_empty(tmp_path):
    assert agent_jobs.load_jobs(str(tmp_path)) == []


def test_load_corrupt_store_is_empty(tmp_path):
    (tmp_path / agent_jobs.STORE_NAME).write_text("{not json", encoding="utf-8")
    assert agent_jobs.load_jobs(str(tmp_path)) == []


def test_save_load_roundtrip_caps_to_newest(tmp_path):
    jobs = [_job(f"j{i}") for i in range(agent_jobs.STORE_CAP + 5)]
    agent_jobs.save_jobs(str(tmp_path), jobs)
    kept = agent_jobs.load_jobs(str(tmp_path))
    assert len(kept) == agent_jobs.STORE_CAP
    assert kept[-1]["id"] == f"j{agent_jobs.STORE_CAP + 4}"   # newest survive


def test_mark_interrupted_fails_unfinished_jobs_only(tmp_path):
    agent_jobs.save_jobs(str(tmp_path), [_job("a", "queued"), _job("b", "running"),
                                         _job("c", "done"), _job("d", "failed")])
    assert agent_jobs.mark_interrupted(str(tmp_path)) == 2
    by_id = {j["id"]: j for j in agent_jobs.load_jobs(str(tmp_path))}
    assert by_id["a"]["status"] == "failed"
    assert by_id["a"]["error"] == "interrupted by restart"
    assert by_id["a"]["finished_at"] is not None
    assert by_id["b"]["status"] == "failed"
    assert by_id["c"]["status"] == "done"        # finished records untouched
    assert by_id["d"]["error"] is None


# ── the runner (AgentJobs) ────────────────────────────────────────────────────
import subprocess
import time

from server.agent_jobs import AgentJobs
from server.tests.conftest import clone, git


def _enqueue(aj, **kw):
    base = dict(task_id="20260712-fix-the-bike", action="research",
                title="Fix the bike", category="errand", shared=False,
                requested_by="dalton")
    base.update(kw)
    return aj.enqueue(**base)


def test_enqueue_persists_queued_job(vault_repo):
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    assert job["status"] == "queued"
    assert len(job["id"]) == 32                       # uuid4().hex
    assert aj.get(job["id"])["title"] == "Fix the bike"
    assert aj.get("nope") is None


def test_list_jobs_newest_first_and_shared_filter(vault_repo):
    aj = AgentJobs(str(vault_repo), start_worker=False)
    a = _enqueue(aj)
    b = _enqueue(aj, task_id="t-shared", action="breakdown", shared=True)
    assert [j["id"] for j in aj.list_jobs()] == [b["id"], a["id"]]
    assert [j["id"] for j in aj.list_jobs(shared_only=True)] == [b["id"]]


def test_init_marks_interrupted_jobs_failed(vault_repo):
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._update(job["id"], status="running")
    aj2 = AgentJobs(str(vault_repo), start_worker=False)   # "restart"
    j = aj2.get(job["id"])
    assert j["status"] == "failed"
    assert j["error"] == "interrupted by restart"


def test_execute_success_marks_done_and_pushes(vault_repo, bare_remote, tmp_path, agent_env):
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])
    done = aj.get(job["id"])
    assert done["status"] == "done"
    assert done["summary"] == "plan set: call the dentist first"
    assert done["started_at"] and done["finished_at"]
    # the agent's work reached the remote (the sync timer delivers it onward)
    verify = clone(bare_remote, tmp_path / "verify-ok")
    assert (verify / "agent-note.md").read_text(encoding="utf-8") == "agent was here\n"


def test_execute_writes_per_job_log_with_the_prompt(vault_repo, agent_env):
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])
    log = open(agent_jobs.log_path(str(vault_repo), job["id"]), encoding="utf-8").read()
    assert "PROMPT:" in log
    assert "Fix the bike" in log
    assert "wiki/_index.md" in log        # the research workflow reached pi intact


def test_execute_pulls_fresh_state_before_running(vault_repo, bare_remote, tmp_path,
                                                  agent_clone, make_script, monkeypatch):
    # the remote gains a commit the agent clone hasn't seen; the fake command
    # REQUIRES that file, so success proves pull-before-run
    other = clone(bare_remote, tmp_path / "other")
    (other / "fresh.md").write_text("x\n", encoding="utf-8")
    git(["add", "-A"], other)
    git(["commit", "-m", "fresh"], other)
    git(["push", "origin", "main"], other)
    check = make_script("check-pull", "test -f fresh.md || exit 9\necho ok\n")
    monkeypatch.setenv("SIDEKICK_AGENT_CLONE", str(agent_clone))
    monkeypatch.setenv("SIDEKICK_AGENT_CMD", check)
    monkeypatch.setenv("SIDEKICK_AGENT_TIMEOUT", "30")
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])
    assert aj.get(job["id"])["status"] == "done"


def test_execute_failure_resets_clone_and_records_tail(vault_repo, bare_remote, tmp_path,
                                                       agent_clone, make_script, monkeypatch):
    bad = make_script("bad-pi",
                      'echo "junk" > ledger.jsonl\n'      # modifies a tracked file
                      'echo "stray" > stray.md\n'         # leaves an untracked file
                      'echo "something went wrong"\n'
                      'exit 3\n')
    monkeypatch.setenv("SIDEKICK_AGENT_CLONE", str(agent_clone))
    monkeypatch.setenv("SIDEKICK_AGENT_CMD", bad)
    monkeypatch.setenv("SIDEKICK_AGENT_TIMEOUT", "30")
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])
    failed = aj.get(job["id"])
    assert failed["status"] == "failed"
    assert "exited 3" in failed["error"]
    assert "something went wrong" in failed["log_tail"]
    # spec: reset --hard && clean -fd — no local modifications survive
    out = subprocess.run(["git", "status", "--porcelain"], cwd=str(agent_clone),
                         capture_output=True, text=True)
    assert out.stdout.strip() == ""
    # and nothing leaked to the remote
    verify = clone(bare_remote, tmp_path / "verify-fail")
    assert not (verify / "stray.md").exists()


def test_execute_failed_push_resets_to_pre_job_baseline(vault_repo, agent_clone, agent_env,
                                                        monkeypatch):
    """If commit_and_push commits successfully but the push itself then fails, the
    commit must not survive the reset — otherwise it publishes silently alongside
    whatever the NEXT job commits (the clone would already be past the baseline
    when that job's failure path resets it)."""
    baseline = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(agent_clone),
                              capture_output=True, text=True, check=True).stdout.strip()

    def fake_commit_and_push(clone, message, **kwargs):
        subprocess.run(["git", "add", "-A"], cwd=clone, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=clone, check=True, capture_output=True)
        raise agent_jobs.git_sync.GitSyncError("push failed (simulated)")

    monkeypatch.setattr(agent_jobs.git_sync, "commit_and_push", fake_commit_and_push)

    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])

    failed = aj.get(job["id"])
    assert failed["status"] == "failed"
    after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(agent_clone),
                           capture_output=True, text=True, check=True).stdout.strip()
    assert after == baseline                    # the failed job's commit is gone
    out = subprocess.run(["git", "status", "--porcelain"], cwd=str(agent_clone),
                         capture_output=True, text=True)
    assert out.stdout.strip() == ""


def test_execute_pins_sidekick_vault_env_to_the_clone(vault_repo, agent_clone, make_script,
                                                       monkeypatch, tmp_path):
    """Incident ad1e97cb: the systemd EnvironmentFile sets SIDEKICK_VAULT to the
    SERVING clone. If that leaks into the pi subprocess, sidekick.py (which
    prefers SIDEKICK_VAULT over its own script location) writes into the serving
    vault instead of the agent's own clone. The runner must pin SIDEKICK_VAULT to
    the agent clone for the child regardless of what the parent process has set."""
    record_vault = make_script("record-vault",
                               'printf "%s" "$SIDEKICK_VAULT" > vault-env.txt\n')
    monkeypatch.setenv("SIDEKICK_AGENT_CLONE", str(agent_clone))
    monkeypatch.setenv("SIDEKICK_AGENT_CMD", record_vault)
    monkeypatch.setenv("SIDEKICK_AGENT_TIMEOUT", "30")
    monkeypatch.setenv("SIDEKICK_VAULT", str(tmp_path / "wrong-vault"))  # the serving clone, in prod

    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])

    assert aj.get(job["id"])["status"] == "done"
    recorded = (agent_clone / "vault-env.txt").read_text(encoding="utf-8")
    assert recorded == str(agent_clone)


def test_execute_timeout_fails_the_job(vault_repo, agent_clone, make_script, monkeypatch):
    slow = make_script("slow-pi", "sleep 5\n")
    monkeypatch.setenv("SIDEKICK_AGENT_CLONE", str(agent_clone))
    monkeypatch.setenv("SIDEKICK_AGENT_CMD", slow)
    monkeypatch.setenv("SIDEKICK_AGENT_TIMEOUT", "1")
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])
    failed = aj.get(job["id"])
    assert failed["status"] == "failed"
    assert "timed out" in failed["error"]


def test_execute_unconfigured_clone_fails_cleanly(vault_repo, monkeypatch):
    monkeypatch.delenv("SIDEKICK_AGENT_CLONE", raising=False)
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj)
    aj._execute(job["id"])
    failed = aj.get(job["id"])
    assert failed["status"] == "failed"
    assert "agent clone not available" in failed["error"]


def test_execute_unknown_action_fails_cleanly(vault_repo, agent_env):
    aj = AgentJobs(str(vault_repo), start_worker=False)
    job = _enqueue(aj, action="unknown-action")
    aj._execute(job["id"])
    failed = aj.get(job["id"])
    assert failed["status"] == "failed"
    assert "unknown action" in failed["error"]


def test_worker_thread_drains_the_queue(vault_repo, agent_env):
    aj = AgentJobs(str(vault_repo))                    # worker ON (the default)
    job = _enqueue(aj)
    deadline = time.time() + 15
    while time.time() < deadline and aj.get(job["id"])["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert aj.get(job["id"])["status"] == "done"
