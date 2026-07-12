# Agent Runner Implementation Plan (pi headless on the VPS)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The phone can hand a task to Claude: `POST /tasks/{id}/agent {action: research|breakdown}` enqueues a strictly-serial `pi` job that researches or breaks down the task in a **separate vault clone** and pushes the result through git (sub-project 1's sync timer delivers it to the serving clone and the phones); the PWA starts jobs and polls their status.

**Architecture:** A new module `server/agent_jobs.py` owns an in-process `queue.Queue` drained by **one** daemon worker thread inside the API process. Job records persist to `<vault>/.sidekick-agent-jobs.json` (gitignored, like the idempotency and push stores) so the GET endpoints and restarts can read state; jobs a restart interrupted are marked failed on startup (`"interrupted by restart"`). The runner shells out to a configurable command (`SIDEKICK_AGENT_CMD`, default `pi -p`) with cwd = `SIDEKICK_AGENT_CLONE`, a 15-minute default timeout (`SIDEKICK_AGENT_TIMEOUT`), and a per-job log under `<vault>/.sidekick-agent-logs/`. Success → commit+push from the agent clone; ANY failure → `git reset --hard && git clean -fd` on the agent clone + job failed with the log tail. Prompts are deterministic strings in `server/agent_prompts.py` embedding the CLAUDE.md orchestrator rules inline. Sub-project 3 of `docs/superpowers/specs/2026-07-10-sidekick-next-phase-design.md`.

**Tech Stack:** Python 3 stdlib (`queue`, `threading`, `subprocess`, `shlex`, `uuid`), FastAPI + pytest (existing `server/`), SvelteKit + Vitest (existing `web/`). **No new dependencies.**

## Global Constraints

- **Tests never invoke real `pi` or the network.** The agent command in every test is a local shell script (`make_script` fixture); git remotes are local bare repos (existing `server/tests/conftest.py` fixtures `vault_repo`, `bare_remote`, `clone`, `git` — reuse, don't reinvent).
- **The queue is strictly serial** — one daemon worker thread per process. The existing **single-uvicorn-worker rule stays mandatory** (job store and idempotency store are per-process; `deploy/sidekick.service` already pins `--workers 1`).
- **The engine stays the sole writer of the ledger.** The agent mutates the vault only via `sidekick.py` commands — enforced by the prompt text and the agent clone's own CLAUDE.md. **This is advisory for a model, stated honestly:** a misbehaving model could hand-edit files before exiting 0. The mechanical backstops are the failure-path clone reset and the fact that every job's work arrives as a reviewable git commit. Same trust level as the Mac-side orchestrator today.
- **Existing API behavior is unchanged.** No existing endpoint is modified; `create_app` gains only an optional kwarg (`agent_jobs=None`) so all current callers keep working.
- New runtime state (`.sidekick-agent-jobs.json`, `.sidekick-agent-logs/`) is **gitignored** — it must never ride along on the API's `git add -A`.
- All commands run from the repo root. Server tests: `python3 -m pytest server/tests/ -q`. Web tests: `cd web && npx vitest run`.

## Spec deviations & resolved ambiguities (read this, Dalton)

1. **Dedicated low-privilege user → NOT implemented.** The spec wants the agent running as its own user. The jobs run inside the API process (systemd `User=sidekick`), and spawning a subprocess **as another user** from a hardened systemd service is nontrivial (sudoers rules or a second daemon + IPC). Pragmatic call: the agent runs as the **same `sidekick` user but in the separate clone** (`SIDEKICK_AGENT_CLONE`), so it still never touches the serving clone in normal operation — but it is *not* privilege-separated from it. Documented as an explicit trade-off in `deploy/README.md` (Task 9). Revisit with a separate jobs daemon if it ever bites.
2. **"Task detail" PWA view does not exist** — tasks render as cards on the dashboard route (`web/src/routes/Dashboard.svelte`). The "Ask Sidekick" button therefore goes on each dashboard task card (smallest honest scope), not on a detail page.
3. **Agent clone's git credentials:** spec allows "its own deploy key or the host's" — we reuse the host's key (same user, simplest).
4. **Non-open task →** `409` on `POST /tasks/{id}/agent` (spec is silent; researching a done task is a client bug worth surfacing).
5. **Idempotent replay** of the POST returns the enqueue-time snapshot (status `queued`) per the existing replay-cached-response semantics — clients poll `GET /agent/jobs/{id}` for live status.
6. **Caps** (plan-level choices): job store keeps the newest 200 records on disk; `GET /agent/jobs` returns the newest 50; log tail 2000 chars; summary 300 chars.
7. **Prompts say `python3 sidekick.py …`** (Ubuntu has no `python`); the vault's CLAUDE.md says `python` but the VPS reality wins. `pyyaml` for the system python3 is an ops step (Task 9).

## File Structure

```
server/agent_prompts.py              NEW  deterministic prompt builders (research, breakdown)
server/agent_jobs.py                 NEW  job store + single-worker queue + runner
server/app.py                        MOD  POST /tasks/{id}/agent, GET /agent/jobs[/{id}], AgentJobs wiring
server/tests/test_agent_prompts.py   NEW
server/tests/test_agent_jobs.py      NEW  store + runner (fake cmd, local remotes only)
server/tests/test_api_agent.py       NEW  endpoints incl. one end-to-end HTTP test
server/tests/conftest.py             MOD  agent_clone, make_script, agent_env fixtures
.gitignore                           MOD  job store + log dir
web/src/lib/api.ts                   MOD  AgentJob type + startAgentJob/getAgentJob
web/src/lib/api.test.ts              MOD
web/src/routes/Dashboard.svelte      MOD  "Ask Sidekick" button + status chip per card
web/src/routes/+page.svelte          MOD  job state + 5 s polling
web/src/routes/dashboard.test.ts     MOD
web/src/routes/ask-sidekick.test.ts  NEW  route-level start + poll test
web/src/routes/shared/+page.svelte   MOD  "Break it down" button + chip + polling
web/src/routes/shared/shared.test.ts MOD
deploy/README.md                     MOD  "Agent runner (pi headless)" ops section
```

---

### Task 1: Prompt templates (`server/agent_prompts.py`)

**Files:**
- Create: `server/agent_prompts.py`
- Test: `server/tests/test_agent_prompts.py`

**Interfaces:**
- Consumes: nothing (pure string building).
- Produces: `research_prompt(task_id, title, category) -> str` and `breakdown_prompt(task_id, title, category, shared) -> str`. Deterministic — same args, byte-identical string. The model reasoning happens inside `pi` on the VPS; these only spell out the orchestrator rules.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_agent_prompts.py`:

```python
"""Prompt templates are deterministic strings that carry the orchestrator rules
INLINE — a job must not depend on pi going off to read CLAUDE.md. No model
logic here; pi does the reasoning on the VPS."""
from server import agent_prompts


def test_research_prompt_carries_task_and_workflow():
    p = agent_prompts.research_prompt("20260712-fix-the-bike", "Fix the bike", "errand")
    assert "Fix the bike" in p
    assert "20260712-fix-the-bike" in p
    assert "errand" in p
    # the CLAUDE.md orchestrator steps, present and in order
    assert "wiki/_index.md" in p
    assert "raw/" in p
    assert "python3 sidekick.py wiki" in p
    assert "set-plan 20260712-fix-the-bike" in p
    assert p.index("raw/") < p.index("python3 sidekick.py wiki") < p.index("set-plan")
    # ground rules: engine-only mutations, no git, no completing
    assert "ledger.jsonl" in p
    assert "Do NOT run any git command" in p
    assert "Do NOT complete any task" in p


def test_research_prompt_is_deterministic():
    a = agent_prompts.research_prompt("id-1", "T", "phone")
    assert a == agent_prompts.research_prompt("id-1", "T", "phone")


def test_breakdown_prompt_shared_parent_inherits_shared():
    p = agent_prompts.breakdown_prompt("20260712-plan-trip", "Plan the trip",
                                       "admin", shared=True)
    assert "--from sidekick --shared" in p
    assert "set-plan 20260712-plan-trip" in p
    assert "Do NOT run any git command" in p


def test_breakdown_prompt_personal_parent_never_shared():
    p = agent_prompts.breakdown_prompt("x", "Plan the trip", "admin", shared=False)
    assert "--shared" not in p          # the flag must not appear ANYWHERE
    assert "--from sidekick" in p


def test_breakdown_prompt_defaults_bad_category():
    # frontmatter is hand-editable; a missing/unknown category must not produce
    # an invalid `sidekick.py new` command in the prompt
    p = agent_prompts.breakdown_prompt("x", "T", None, shared=False)
    assert "--category chore" in p
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_agent_prompts.py -q`
Expected: 5 errors with `ModuleNotFoundError: No module named 'server.agent_prompts'`

- [ ] **Step 3: Write the implementation**

Create `server/agent_prompts.py`:

```python
"""Prompt templates for the agent runner (spec sub-project 3): deterministic
string building ONLY — the model reasoning happens inside `pi` on the VPS.
Each prompt embeds the vault's orchestrator rules INLINE (the agent clone has
CLAUDE.md too, but a job must not depend on the model going to read it).
Commands are spelled `python3 sidekick.py ...` — what actually exists on the
VPS. The integrity rules are ADVISORY for a model; the runner's failure path
(reset --hard + clean -fd) and the reviewable pushed commit are the backstop."""

_VALID_CATEGORIES = ("phone", "admin", "errand", "chore")

_GROUND_RULES = """\
Ground rules (non-negotiable):
- Mutate task data ONLY via `python3 sidekick.py <command>`. NEVER hand-edit
  ledger.jsonl, sidekick-data.js, or wiki/_index.md — generated or code-only.
- Do NOT run any git command (add/commit/push/pull). The runner that launched
  you commits and pushes your work when you exit.
- Do NOT complete any task.
- Work only inside the current directory (the vault clone you were started in)."""


def research_prompt(task_id, title, category):
    """The research action — the CLAUDE.md orchestrator step, spelled out."""
    return f"""You are Sidekick's orchestrator, running headless in the vault. Research the open task below and persist a plan for it.

Task: {title}
Id: {task_id}
Category: {category or "uncategorized"}

{_GROUND_RULES}

Follow the orchestrator workflow, in this order:
1. Read wiki/_index.md, then grep wiki/ for this task's subject. Read matching
   topic notes and REUSE known facts instead of re-researching them.
2. Research what remains, using your web tools.
3. Write the verbatim research prose to raw/<YYYYMMDD>-<slug>.md with `task`,
   `topic` and `created` YAML frontmatter (create raw/ if it is absent).
4. Fold the durable facts into wiki/<topic>.md — create or update the note;
   refresh its `summary`/`updated`/`sources` frontmatter; cross-link related
   notes with [[wikilinks]]. Topics are areas of life (car-insurance, dentist),
   never task categories.
5. Run: python3 sidekick.py wiki
6. Compose the plan as JSON: {{"summary": "<one line>", "steps": [{{"text": "<step>", "href": "<optional url/tel>"}}]}}.
   Write it to plan.json, run: python3 sidekick.py set-plan {task_id} --file plan.json
   (this also regenerates the feed), then delete plan.json.

End by printing exactly one line summarising the plan you set."""


def breakdown_prompt(task_id, title, category, shared):
    """The breakdown action — sub-tasks via `sidekick.py new` (from: sidekick,
    inheriting `shared` from the parent), plus a short parent plan linking them."""
    category = category if category in _VALID_CATEGORIES else "chore"
    shared_flag = " --shared" if shared else ""
    inherit = ("Every `new` command MUST include the shared flag shown above: "
               "the parent is on the shared list and its sub-tasks inherit that."
               if shared else
               "The parent is personal: do NOT mark the sub-tasks as shared.")
    return f"""You are Sidekick's orchestrator, running headless in the vault. Break the open task below into sub-tasks.

Task: {title}
Id: {task_id}
Category: {category}
Shared: {"yes" if shared else "no"}

{_GROUND_RULES}

Do exactly this:
1. Read tasks/{task_id}.md for context.
2. Split the work into 2-5 concrete sub-tasks, each doable in one sitting.
3. Create each one with:
   python3 sidekick.py new "<sub-task title>" --category {category} --from sidekick{shared_flag}
   {inherit}
   Note the id every command prints ("created <id>").
4. Set a SHORT plan on the parent linking the children: write
   {{"summary": "Broken into N sub-tasks", "steps": [{{"text": "<sub-task title> — [[<sub-task id>]]"}}, ...]}}
   to plan.json, run: python3 sidekick.py set-plan {task_id} --file plan.json
   then delete plan.json.

End by printing exactly one line: how many sub-tasks you created and their ids."""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_agent_prompts.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add server/agent_prompts.py server/tests/test_agent_prompts.py
git commit -m "server: agent prompt templates — deterministic orchestrator prompts"
```

---

### Task 2: Job store (`server/agent_jobs.py`, persistence half) + gitignore

**Files:**
- Create: `server/agent_jobs.py` (store functions; Task 3 adds the `AgentJobs` class to the same file)
- Modify: `.gitignore`
- Test: `server/tests/test_agent_jobs.py` (new file; Task 3 appends to it)

**Interfaces:**
- Consumes: stdlib only.
- Produces: `STORE_NAME`, `LOG_DIR_NAME`, `STORE_CAP`, `LIST_CAP`, `LOG_TAIL_CHARS`, `SUMMARY_CHARS`; `store_path(vault)`, `log_path(vault, job_id)`; `load_jobs(vault) -> list` (oldest first; missing/corrupt store → `[]`), `save_jobs(vault, jobs)` (atomic, caps to newest `STORE_CAP`), `mark_interrupted(vault) -> int` (queued/running → failed `"interrupted by restart"`). These are **unlocked primitives** — locking is the Task 3 class's job (worker + request handlers share one process).

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_agent_jobs.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_agent_jobs.py -q`
Expected: 4 errors with `ModuleNotFoundError: No module named 'server.agent_jobs'`

- [ ] **Step 3: Write the implementation**

Create `server/agent_jobs.py`:

```python
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
    the queue lives in memory. Returns how many records were marked failed."""
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
```

Append to `.gitignore` (after the `.sidekick-push.json` block):

```
# agent runner job store + per-job logs (runtime state, per-vault; never in git)
.sidekick-agent-jobs.json
.sidekick-agent-logs/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_agent_jobs.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add server/agent_jobs.py server/tests/test_agent_jobs.py .gitignore
git commit -m "server: agent job store — persisted records, interrupted-on-restart"
```

---

### Task 3: The runner (`AgentJobs`: queue, worker thread, execute flow)

**Files:**
- Modify: `server/agent_jobs.py` (append the class + imports)
- Modify: `server/tests/conftest.py` (append fixtures)
- Test: `server/tests/test_agent_jobs.py` (append)

**Interfaces:**
- Consumes: Task 1 prompts, Task 2 store functions, `git_sync.pull_latest` / `git_sync.commit_and_push` (existing).
- Produces: `AgentJobs(vault, start_worker=True)` — `configured()` (static: is `SIDEKICK_AGENT_CLONE` set), `enqueue(*, task_id, action, title, category, shared, requested_by) -> dict` (job ids: `uuid4().hex`), `get(job_id) -> dict|None`, `list_jobs(shared_only=False) -> list` (newest first, capped `LIST_CAP`; `shared_only` filters to jobs on shared tasks). Runner env read at execute time (`SIDEKICK_AGENT_CLONE` / `SIDEKICK_AGENT_CMD` default `pi -p` / `SIDEKICK_AGENT_TIMEOUT` default `900`) so tests can monkeypatch. `start_worker=False` lets tests drive `_execute` synchronously.

- [ ] **Step 1: Add shared fixtures to `server/tests/conftest.py`**

Append at the end of the file (before the `AUTH` constant is fine; keep `AUTH` last or not — position is cosmetic):

```python
@pytest.fixture
def agent_clone(bare_remote, tmp_path) -> Path:
    """The agent's SEPARATE vault clone (spec sub-project 3) — never the serving clone."""
    return clone(bare_remote, tmp_path / "agent-clone")


@pytest.fixture
def make_script(tmp_path):
    """Write an executable shell script; its path substitutes for `pi` in tests.
    Tests NEVER invoke real pi or the network."""
    def _make(name, body):
        path = tmp_path / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return str(path)
    return _make


@pytest.fixture
def agent_env(agent_clone, make_script, monkeypatch):
    """Runner env pointing at the throwaway clone + a fake success command that
    proves cwd (writes into the clone), prompt delivery ($1) and the push path."""
    ok = make_script("fake-pi",
                     'echo "PROMPT: $1"\n'
                     'printf "agent was here\\n" > agent-note.md\n'
                     'echo "plan set: call the dentist first"\n')
    monkeypatch.setenv("SIDEKICK_AGENT_CLONE", str(agent_clone))
    monkeypatch.setenv("SIDEKICK_AGENT_CMD", ok)
    monkeypatch.setenv("SIDEKICK_AGENT_TIMEOUT", "30")
    return agent_clone
```

- [ ] **Step 2: Write the failing tests**

Append to `server/tests/test_agent_jobs.py`:

```python
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


def test_worker_thread_drains_the_queue(vault_repo, agent_env):
    aj = AgentJobs(str(vault_repo))                    # worker ON (the default)
    job = _enqueue(aj)
    deadline = time.time() + 15
    while time.time() < deadline and aj.get(job["id"])["status"] in ("queued", "running"):
        time.sleep(0.05)
    assert aj.get(job["id"])["status"] == "done"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_agent_jobs.py -q`
Expected: 4 passed (Task 2's), 10 errors/failures (`ImportError: cannot import name 'AgentJobs'`)

- [ ] **Step 4: Write the implementation**

In `server/agent_jobs.py`, extend the import block to:

```python
import datetime as dt
import json
import os
import queue
import shlex
import subprocess
import threading
import uuid

from server import agent_prompts, git_sync
```

Append the class at the end of the file:

```python
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
        """Newest first, capped. shared_only => only jobs on shared tasks —
        what role `shared` may see (spec sub-projects 2+3)."""
        with self._lock:
            jobs = load_jobs(self.vault)
        if shared_only:
            jobs = [j for j in jobs if j.get("shared")]
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
        clone, cmd, timeout = self._runner_env()
        self._update(job_id, status="running", started_at=_now_iso())
        log_file = log_path(self.vault, job_id)
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        try:
            if not clone or not os.path.isdir(os.path.join(clone, ".git")):
                raise RuntimeError(f"agent clone not available: {clone!r}")
            git_sync.pull_latest(clone)                # fresh state before every job
            if job["action"] == "research":
                prompt = agent_prompts.research_prompt(
                    job["task_id"], job["title"], job["category"])
            else:
                prompt = agent_prompts.breakdown_prompt(
                    job["task_id"], job["title"], job["category"], job["shared"])
            with open(log_file, "w", encoding="utf-8") as lf:
                p = subprocess.run(shlex.split(cmd) + [prompt], cwd=clone,
                                   stdout=lf, stderr=subprocess.STDOUT,
                                   text=True, timeout=timeout)
            if p.returncode != 0:
                raise RuntimeError(f"agent command exited {p.returncode}")
            git_sync.commit_and_push(clone, f"agent: {job['action']} {job['task_id']}")
            self._update(job_id, status="done", finished_at=_now_iso(),
                         summary=self._summary(log_file),
                         log_tail=self._tail(log_file))
        except subprocess.TimeoutExpired:
            self._reset_clone(clone)
            self._update(job_id, status="failed", finished_at=_now_iso(),
                         error=f"agent command timed out after {timeout:g}s",
                         log_tail=self._tail(log_file))
        except Exception as e:
            self._reset_clone(clone)
            self._update(job_id, status="failed", finished_at=_now_iso(),
                         error=str(e)[:500], log_tail=self._tail(log_file))

    @staticmethod
    def _tail(log_file):
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
    def _reset_clone(clone):
        """Spec: reset --hard && clean -fd on failure. Best-effort — never raise
        from cleanup (the job is already failed)."""
        if not clone or not os.path.isdir(clone):
            return
        for args in (["reset", "--hard"], ["clean", "-fd"]):
            subprocess.run(["git", *args], cwd=clone, capture_output=True, text=True)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_agent_jobs.py -q`
Expected: `14 passed` (the timeout test takes ~1 s)

- [ ] **Step 6: Commit**

```bash
git add server/agent_jobs.py server/tests/test_agent_jobs.py server/tests/conftest.py
git commit -m "server: agent runner — single-worker queue, pi subprocess, reset-on-failure"
```

---

### Task 4: `POST /tasks/{id}/agent`

**Files:**
- Modify: `server/app.py`
- Test: `server/tests/test_api_agent.py` (new file; Task 5 appends to it)

**Interfaces:**
- Consumes: `AgentJobs` (Task 3), existing `require_auth`, `_idem_replay_or_run`, `vault_lock`, `sidekick.read_note`/`task_path`.
- Produces: `create_app(config=None, agent_jobs=None)` (kwarg lets tests inject a worker-off instance; default builds `AgentJobs(config.vault)` with the worker ON). `POST /tasks/{task_id}/agent` body `{"action": "research"|"breakdown"}` → `202` + job record. Rules: bad action → 400; role `shared` + `research` → 403 (research is full-role only; rejected at action level, so it can never leak task existence); unconfigured runner → 503; unknown task → 404; role `shared` + personal task → 404 (indistinguishable from missing, same as complete); non-open task → 409; Idempotency-Key honored with the existing `f"{name}:{path}"` scope.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_api_agent.py`:

```python
"""Agent endpoints (spec sub-project 3). POST enqueues; the server is the
security boundary: research is full-role only, role `shared` touches only
shared tasks, and a personal task is indistinguishable from a missing one."""
import time

import pytest
from fastapi.testclient import TestClient

from server.agent_jobs import AgentJobs, load_jobs
from server.app import create_app
from server.config import Config
from server.tests.conftest import clone

FULL = {"Authorization": "Bearer full-token"}
SHARED = {"Authorization": "Bearer shared-token"}

TOKENS = {"full-token": {"name": "dalton", "role": "full"},
          "shared-token": {"name": "wife", "role": "shared"}}


@pytest.fixture
def agent_api(vault_repo, agent_clone, monkeypatch):
    """Client with the runner configured but the worker OFF — enqueued jobs stay
    queued, so status assertions are deterministic. Execution is covered by
    test_agent_jobs.py and the end-to-end test below."""
    monkeypatch.setenv("SIDEKICK_AGENT_CLONE", str(agent_clone))
    cfg = Config(vault=str(vault_repo), tokens=TOKENS, push=True, remote="origin")
    jobs = AgentJobs(str(vault_repo), start_worker=False)
    return TestClient(create_app(cfg, agent_jobs=jobs))


def _new(client, headers, title="Fix the bike", category="errand", shared=False):
    body = {"title": title, "category": category}
    if shared:
        body["shared"] = True
    return client.post("/tasks", json=body, headers=headers).json()["id"]


def test_post_agent_enqueues_research(agent_api):
    tid = _new(agent_api, FULL)
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 202
    job = r.json()
    assert job["task_id"] == tid
    assert job["action"] == "research"
    assert job["status"] == "queued"
    assert len(job["id"]) == 32


def test_post_agent_invalid_action_400(agent_api):
    tid = _new(agent_api, FULL)
    for body in ({"action": "explode"}, {}, None):
        r = agent_api.post(f"/tasks/{tid}/agent", json=body, headers=FULL)
        assert r.status_code == 400


def test_post_agent_unknown_task_404(agent_api):
    r = agent_api.post("/tasks/nope/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 404
    assert r.json() == {"error": "no such task: nope"}


def test_post_agent_done_task_409(agent_api):
    tid = _new(agent_api, FULL)
    agent_api.post(f"/tasks/{tid}/complete", json={}, headers=FULL)
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 409


def test_shared_role_research_403_never_leaks(agent_api, vault_repo):
    # even on a task she CAN see — research is full-role only, rejected at
    # action level (before any task lookup, so existence can't leak)
    tid = _new(agent_api, SHARED, title="Buy milk", category="chore")
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=SHARED)
    assert r.status_code == 403
    assert load_jobs(str(vault_repo)) == []           # nothing enqueued


def test_shared_role_breakdown_personal_task_404(agent_api, vault_repo):
    tid = _new(agent_api, FULL)                       # personal task
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "breakdown"}, headers=SHARED)
    assert r.status_code == 404                       # indistinguishable from missing
    assert load_jobs(str(vault_repo)) == []


def test_shared_role_breakdown_shared_task_202(agent_api):
    tid = _new(agent_api, SHARED, title="Buy milk", category="chore")
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "breakdown"}, headers=SHARED)
    assert r.status_code == 202
    assert r.json()["shared"] is True


def test_full_role_breakdown_202(agent_api):
    tid = _new(agent_api, FULL)
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "breakdown"}, headers=FULL)
    assert r.status_code == 202


def test_post_agent_unconfigured_503(agent_api, monkeypatch):
    tid = _new(agent_api, FULL)
    monkeypatch.delenv("SIDEKICK_AGENT_CLONE")
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 503
    assert r.json() == {"error": "agent runner not configured"}


def test_post_agent_idempotency_replays_the_same_job(agent_api, vault_repo):
    tid = _new(agent_api, FULL)
    key = {"Idempotency-Key": "agent-key-1"}
    r1 = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"},
                        headers={**FULL, **key})
    r2 = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"},
                        headers={**FULL, **key})
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["id"] == r2.json()["id"]
    assert len(load_jobs(str(vault_repo))) == 1       # one job, not two


def test_post_agent_requires_auth(agent_api):
    r = agent_api.post("/tasks/x/agent", json={"action": "research"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_agent.py -q`
Expected: 11 failures — `create_app() got an unexpected keyword argument 'agent_jobs'` and/or 404s on the missing route

- [ ] **Step 3: Write the implementation**

In `server/app.py`:

**(a)** Extend the module docstring's last sentence (line 7) — after "…enforced HERE (the PWA's hiding is convenience, not security).", add:

```
Agent jobs (spec sub-project 3) are validated and enqueued here; they execute
in server/agent_jobs.py's single worker, in a separate vault clone.
```

**(b)** After the `from server.idempotency import IdempotencyStore  # noqa: E402` import (line 21), add:

```python
from server.agent_jobs import AgentJobs  # noqa: E402
```

**(c)** After `VALID_CATEGORIES = {"phone", "admin", "errand", "chore"}` (line 24), add:

```python
VALID_AGENT_ACTIONS = {"research", "breakdown"}
```

**(d)** Change the factory signature and wiring — replace:

```python
def create_app(config=None):
    config = config or load_config()
    sidekick.configure(config.vault)
    idem = IdempotencyStore(os.path.join(config.vault, ".sidekick-idempotency.json"))

    app = FastAPI(title="Sidekick host API")
    app.state.config = config
    app.state.idem = idem
```

with:

```python
def create_app(config=None, agent_jobs=None):
    config = config or load_config()
    sidekick.configure(config.vault)
    idem = IdempotencyStore(os.path.join(config.vault, ".sidekick-idempotency.json"))
    # tests may inject a worker-off AgentJobs; production gets the real worker
    agent_jobs = agent_jobs or AgentJobs(config.vault)

    app = FastAPI(title="Sidekick host API")
    app.state.config = config
    app.state.idem = idem
    app.state.agent_jobs = agent_jobs
```

**(e)** After the `post_complete` handler (before `return app`), add:

```python
    @app.post("/tasks/{task_id}/agent")
    async def post_agent(task_id: str, request: Request,
                         authorization: str = Header(default=""),
                         idempotency_key: str = Header(default="")):
        ident = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        action = data.get("action")
        if action not in VALID_AGENT_ACTIONS:
            raise HTTPException(status_code=400,
                                detail=f"action must be one of {sorted(VALID_AGENT_ACTIONS)}")
        if ident["role"] == "shared" and action != "breakdown":
            # research is full-role only (spec SP2/SP3); rejected at action level
            # — BEFORE any task lookup — so it can never leak task existence
            raise HTTPException(status_code=403, detail="forbidden")
        if not AgentJobs.configured():
            raise HTTPException(status_code=503, detail="agent runner not configured")

        def run():
            with vault_lock(config.vault):
                try:
                    fm, body = sidekick.read_note(sidekick.task_path(task_id))
                except FileNotFoundError:
                    raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                if ident["role"] == "shared" and not fm.get("shared"):
                    # a personal task must be indistinguishable from a missing one
                    raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                if fm.get("status", "open") != "open":
                    raise HTTPException(status_code=409, detail=f"task is not open: {task_id}")
                title = next((l[2:].strip() for l in body.splitlines()
                              if l.startswith("# ")), task_id)
                shared = bool(fm.get("shared"))
                category = fm.get("category")
            job = agent_jobs.enqueue(task_id=task_id, action=action, title=title,
                                     category=category, shared=shared,
                                     requested_by=ident["name"])
            # NOTE: an idempotent replay returns THIS enqueue-time snapshot
            # (status "queued") — clients poll GET /agent/jobs/{id} for live state
            return 202, job

        scope = f"{ident['name']}:{request.url.path}"
        return _idem_replay_or_run(scope, idempotency_key, run)
```

- [ ] **Step 4: Run the new tests, then the full suite**

Run: `python3 -m pytest server/tests/test_api_agent.py -q`
Expected: `11 passed`

Run: `python3 -m pytest server/tests/ -q`
Expected: all pass, `0 failed` (existing endpoints untouched)

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_agent.py
git commit -m "server: POST /tasks/{id}/agent — enqueue research/breakdown with role rules"
```

---

### Task 5: `GET /agent/jobs` + `GET /agent/jobs/{id}` + end-to-end HTTP test

**Files:**
- Modify: `server/app.py` (two GET handlers, after `post_agent`)
- Test: `server/tests/test_api_agent.py` (append)

**Interfaces:**
- Consumes: `agent_jobs.list_jobs` / `agent_jobs.get` (Task 3).
- Produces: `GET /agent/jobs` → `{"jobs": [...]}` newest first, capped 50; role `shared` sees ONLY jobs on shared tasks; role `full` sees all. `GET /agent/jobs/{id}` → the record (status `queued|running|done|failed` + `summary` + `log_tail`); 404 for unknown ids AND — for role `shared` — for jobs on personal tasks (no-leak).

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_api_agent.py`:

```python
# ── job status endpoints ──────────────────────────────────────────────────────
def test_jobs_list_newest_first(agent_api):
    t1 = _new(agent_api, FULL, title="First")
    t2 = _new(agent_api, FULL, title="Second")
    id1 = agent_api.post(f"/tasks/{t1}/agent", json={"action": "research"},
                         headers=FULL).json()["id"]
    id2 = agent_api.post(f"/tasks/{t2}/agent", json={"action": "research"},
                         headers=FULL).json()["id"]
    r = agent_api.get("/agent/jobs", headers=FULL)
    assert r.status_code == 200
    assert [j["id"] for j in r.json()["jobs"]] == [id2, id1]


def test_jobs_list_shared_role_sees_only_shared_jobs(agent_api):
    tp = _new(agent_api, FULL)                                    # personal
    ts = _new(agent_api, SHARED, title="Buy milk", category="chore")  # shared
    agent_api.post(f"/tasks/{tp}/agent", json={"action": "research"}, headers=FULL)
    shared_job = agent_api.post(f"/tasks/{ts}/agent", json={"action": "breakdown"},
                                headers=FULL).json()["id"]
    jobs = agent_api.get("/agent/jobs", headers=SHARED).json()["jobs"]
    assert [j["id"] for j in jobs] == [shared_job]                # personal never leaks


def test_job_get_by_id_and_unknown_404(agent_api):
    tid = _new(agent_api, FULL)
    jid = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"},
                         headers=FULL).json()["id"]
    r = agent_api.get(f"/agent/jobs/{jid}", headers=FULL)
    assert r.status_code == 200
    assert r.json()["task_id"] == tid
    assert agent_api.get("/agent/jobs/nope", headers=FULL).status_code == 404


def test_job_get_shared_role_404_on_personal_job(agent_api):
    tid = _new(agent_api, FULL)                                   # personal
    jid = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"},
                         headers=FULL).json()["id"]
    r = agent_api.get(f"/agent/jobs/{jid}", headers=SHARED)
    assert r.status_code == 404                                   # no-leak


def test_jobs_endpoints_require_auth(agent_api):
    assert agent_api.get("/agent/jobs").status_code == 401
    assert agent_api.get("/agent/jobs/x").status_code == 401


def test_agent_job_end_to_end(vault_repo, bare_remote, tmp_path, agent_env):
    """The full path over HTTP with a STARTED worker and a fake command:
    POST → queue → runner (pull, run, push) → GET shows done + summary.
    No pi, no network — agent_env substitutes a local script."""
    cfg = Config(vault=str(vault_repo), tokens=TOKENS, push=True, remote="origin")
    client = TestClient(create_app(cfg))              # default AgentJobs: worker ON
    tid = _new(client, FULL)
    job_id = client.post(f"/tasks/{tid}/agent", json={"action": "research"},
                         headers=FULL).json()["id"]
    deadline = time.time() + 15
    job = None
    while time.time() < deadline:
        job = client.get(f"/agent/jobs/{job_id}", headers=FULL).json()
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", f"job did not finish: {job}"
    assert job["summary"] == "plan set: call the dentist first"
    verify = clone(bare_remote, tmp_path / "verify-e2e")
    assert (verify / "agent-note.md").exists()        # the work reached the remote
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_agent.py -q`
Expected: 11 passed (Task 4's), 6 failures (404s on the missing GET routes)

- [ ] **Step 3: Write the implementation**

In `server/app.py`, after the `post_agent` handler (still before `return app`), add:

```python
    @app.get("/agent/jobs")
    def get_agent_jobs(authorization: str = Header(default="")):
        ident = require_auth(authorization)
        # role `shared` sees ONLY jobs on shared tasks; role `full` sees all
        return {"jobs": agent_jobs.list_jobs(shared_only=(ident["role"] == "shared"))}

    @app.get("/agent/jobs/{job_id}")
    def get_agent_job(job_id: str, authorization: str = Header(default="")):
        ident = require_auth(authorization)
        job = agent_jobs.get(job_id)
        if job is None or (ident["role"] == "shared" and not job.get("shared")):
            # a personal job must be indistinguishable from a missing one
            raise HTTPException(status_code=404, detail=f"no such job: {job_id}")
        return job
```

- [ ] **Step 4: Run the file, then the full server suite**

Run: `python3 -m pytest server/tests/test_api_agent.py -q`
Expected: `17 passed`

Run: `python3 -m pytest server/tests/ -q && python3 -m pytest tests/ -q`
Expected: all pass, `0 failed`

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_agent.py
git commit -m "server: GET /agent/jobs endpoints — status polling with role filtering"
```

---

### Task 6: Web API client (`web/src/lib/api.ts`)

**Files:**
- Modify: `web/src/lib/api.ts`
- Test: `web/src/lib/api.test.ts`

**Interfaces:**
- Consumes: existing `base()`, `headers()`, `handle()`.
- Produces: `AgentAction`, `AgentJobStatus`, `AgentJob` types; `startAgentJob(taskId, action) -> Promise<AgentJob>` (POST with Idempotency-Key, mirroring `createTask`); `getAgentJob(id) -> Promise<AgentJob>`.

- [ ] **Step 1: Write the failing tests**

In `web/src/lib/api.test.ts`, extend the import (line 2) to:

```ts
import { getFeed, getMe, createTask, completeTask, getVapidPublicKey, subscribePush, startAgentJob, getAgentJob, ApiError } from "./api";
```

Append at the end of the file:

```ts
describe("agent api", () => {
  const job = {
    id: "j1", task_id: "t1", action: "research", status: "queued",
    summary: null, error: null, log_tail: null,
    created_at: "T", started_at: null, finished_at: null
  };

  it("POSTs the action to /agent with an Idempotency-Key", async () => {
    const f = mockFetch(202, job);
    vi.stubGlobal("fetch", f);
    const res = await startAgentJob("t1", "research");
    expect(res.status).toBe("queued");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/tasks/t1/agent");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({ action: "research" });
    expect(typeof opts.headers["Idempotency-Key"]).toBe("string");
    expect(opts.headers["Idempotency-Key"].length).toBeGreaterThan(0);
  });

  it("GETs a job by id with the bearer token", async () => {
    const f = mockFetch(200, { ...job, status: "done", summary: "plan set" });
    vi.stubGlobal("fetch", f);
    const res = await getAgentJob("j1");
    expect(res.summary).toBe("plan set");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/agent/jobs/j1");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("surfaces 403 when the role may not run the action", async () => {
    vi.stubGlobal("fetch", mockFetch(403, { error: "forbidden" }));
    await expect(startAgentJob("t1", "research")).rejects.toMatchObject({ status: 403 });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: failures — `startAgentJob is not a function` (or import error)

- [ ] **Step 3: Write the implementation**

Append to `web/src/lib/api.ts`:

```ts
export type AgentAction = "research" | "breakdown";
export type AgentJobStatus = "queued" | "running" | "done" | "failed";

export interface AgentJob {
  id: string;
  task_id: string;
  action: AgentAction;
  status: AgentJobStatus;
  summary: string | null;
  error: string | null;
  log_tail: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export async function startAgentJob(taskId: string, action: AgentAction): Promise<AgentJob> {
  return handle(await fetch(`${base()}/api/tasks/${encodeURIComponent(taskId)}/agent`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ action })
  }));
}

export async function getAgentJob(id: string): Promise<AgentJob> {
  return handle(await fetch(`${base()}/api/agent/jobs/${encodeURIComponent(id)}`, { headers: headers() }));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: all pass (existing + 3 new)

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "web: agent api client — startAgentJob/getAgentJob"
```

---

### Task 7: PWA — "Ask Sidekick" on dashboard task cards + polling

**Files:**
- Modify: `web/src/routes/Dashboard.svelte`
- Modify: `web/src/routes/+page.svelte`
- Test: `web/src/routes/dashboard.test.ts` (append), `web/src/routes/ask-sidekick.test.ts` (new)

**Interfaces:**
- Consumes: Task 6 client. The dashboard route is a full-role surface in practice (role `shared` is routed to `/shared`); the server enforces roles regardless.
- Produces: `Dashboard.svelte` gains optional props `onAgent(id)` and `agentJobs: Record<taskId, AgentJob>` — each open-task card gets an "Ask Sidekick" button (disabled while its job is queued/running) and a status chip. `+page.svelte` starts research jobs and polls `GET /agent/jobs/{id}` every 5 s while the page is open, refreshing the feed on `done` (the plan itself arrives via the sync timer, possibly minutes later).

- [ ] **Step 1: Write the failing tests**

In `web/src/routes/dashboard.test.ts`, change line 1 to add `vi`, and line 2 to add `fireEvent`:

```ts
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
```

Append at the end of the file:

```ts
describe("Ask Sidekick", () => {
  const job = (status: string, summary: string | null = null) => ({
    id: "j1", task_id: "t2", action: "research", status, summary,
    error: null, log_tail: null, created_at: "T", started_at: null, finished_at: null
  });

  it("fires onAgent with the task id", async () => {
    const onAgent = vi.fn();
    render(Dashboard, { props: { feed, onAgent } });
    await fireEvent.click(screen.getByRole("button", { name: /ask sidekick about replace fan/i }));
    expect(onAgent).toHaveBeenCalledWith("t1");
  });

  it("shows the status chip and disables only the busy task's button", () => {
    render(Dashboard, { props: { feed, agentJobs: { t2: job("running") } as any } });
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /ask sidekick about email landlord/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /ask sidekick about replace fan/i })).toBeEnabled();
  });

  it("shows the summary on a done job", () => {
    render(Dashboard, { props: { feed, agentJobs: { t2: job("done", "plan set") } as any } });
    expect(screen.getByText("done — plan set")).toBeInTheDocument();
  });
});
```

Create `web/src/routes/ask-sidekick.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import type { Feed } from "$lib/types";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/settings", () => ({ hasToken: () => true }));
vi.mock("$lib/api", () => ({
  getFeed: vi.fn(),
  completeTask: vi.fn(),
  startAgentJob: vi.fn(),
  getAgentJob: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));

import Page from "./+page.svelte";
import { getFeed, startAgentJob, getAgentJob } from "$lib/api";

const feed: Feed = {
  events: [],
  active: [{ id: "t1", task: "Replace fan", category: "chore", sat_for_hours: 12, plan: null }]
};

const job = (status: string, summary: string | null = null) => ({
  id: "j1", task_id: "t1", action: "research", status, summary,
  error: null, log_tail: null, created_at: "T", started_at: null, finished_at: null
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getFeed).mockResolvedValue(feed);
});
afterEach(() => vi.useRealTimers());

describe("Ask Sidekick (dashboard route)", () => {
  it("starts a research job and polls it to done every 5s", async () => {
    vi.mocked(startAgentJob).mockResolvedValue(job("queued") as any);
    vi.mocked(getAgentJob)
      .mockResolvedValueOnce(job("running") as any)
      .mockResolvedValueOnce(job("done", "plan set: buy the fan") as any);

    render(Page);
    await waitFor(() => expect(screen.getByText("Replace fan")).toBeInTheDocument());

    vi.useFakeTimers();
    await fireEvent.click(screen.getByRole("button", { name: /ask sidekick about replace fan/i }));
    await vi.advanceTimersByTimeAsync(0);               // let the POST resolve
    expect(startAgentJob).toHaveBeenCalledWith("t1", "research");

    await vi.advanceTimersByTimeAsync(5000);            // poll 1 → running
    expect(getAgentJob).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);            // poll 2 → done + feed reload
    expect(getAgentJob).toHaveBeenCalledTimes(2);
    expect(getFeed).toHaveBeenCalledTimes(2);           // mount + reload on done
    vi.useRealTimers();
    await waitFor(() => expect(screen.getByText(/done — plan set: buy the fan/i)).toBeInTheDocument());
  });

  it("surfaces an error when the job cannot start", async () => {
    vi.mocked(startAgentJob).mockRejectedValue(new Error("agent runner not configured"));
    render(Page);
    await waitFor(() => expect(screen.getByText("Replace fan")).toBeInTheDocument());
    await fireEvent.click(screen.getByRole("button", { name: /ask sidekick/i }));
    await waitFor(() => expect(screen.getByText(/agent runner not configured/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/routes/dashboard.test.ts src/routes/ask-sidekick.test.ts`
Expected: the 3 pre-existing dashboard tests pass; all 5 new tests fail (no button)

- [ ] **Step 3: Modify `Dashboard.svelte`**

**(a)** Replace the script's import + props block:

```ts
  import type { Feed } from "$lib/types";
  import { hero, branchVMs, recentLog, catHue, dur } from "$lib/game";
  import { computeStats, WEEKDAY_NAMES } from "$lib/stats";

  let { feed, onComplete = (_id: string) => {}, pending = new Set<string>() }:
    { feed: Feed; onComplete?: (id: string) => void; pending?: Set<string> } = $props();
```

with:

```ts
  import type { Feed } from "$lib/types";
  import type { AgentJob } from "$lib/api";
  import { hero, branchVMs, recentLog, catHue, dur } from "$lib/game";
  import { computeStats, WEEKDAY_NAMES } from "$lib/stats";

  let { feed, onComplete = (_id: string) => {}, pending = new Set<string>(),
        onAgent = (_id: string) => {}, agentJobs = {} }:
    { feed: Feed; onComplete?: (id: string) => void; pending?: Set<string>;
      onAgent?: (id: string) => void; agentJobs?: Record<string, AgentJob> } = $props();
```

**(b)** After the `safeHref` function, add:

```ts
  function isAgentBusy(id: string): boolean {
    const j = agentJobs[id];
    return !!j && (j.status === "queued" || j.status === "running");
  }
  function chipText(j: AgentJob): string {
    if (j.status === "done") return j.summary ? `done — ${j.summary}` : "done";
    if (j.status === "failed") return "failed";
    return j.status;
  }
```

**(c)** In the task-card markup, replace:

```svelte
      <button class="btn btn-done" aria-label="Done" aria-busy={pending.has(t.id)} disabled={pending.has(t.id)} onclick={() => onComplete(t.id)}>
        {pending.has(t.id) ? "Completing…" : "Done"}
      </button>
    </article>
```

with:

```svelte
      <button class="btn btn-done" aria-label="Done" aria-busy={pending.has(t.id)} disabled={pending.has(t.id)} onclick={() => onComplete(t.id)}>
        {pending.has(t.id) ? "Completing…" : "Done"}
      </button>
      <div class="tc-agent">
        <button class="btn" disabled={isAgentBusy(t.id)} onclick={() => onAgent(t.id)}
                aria-label={"Ask Sidekick about " + t.task}>
          {isAgentBusy(t.id) ? "Sidekick working…" : "Ask Sidekick"}
        </button>
        {#if agentJobs[t.id]}
          <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
        {/if}
      </div>
    </article>
```

**(d)** Append a style block at the end of the file:

```svelte
<style>
  .tc-agent { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px;
          border: 1px solid rgba(128, 128, 128, 0.35); opacity: 0.85; }
  .chip-queued, .chip-running { animation: chip-pulse 1.5s ease-in-out infinite; }
  .chip-failed { border-color: rgba(220, 60, 60, 0.6); }
  @keyframes chip-pulse { 50% { opacity: 0.45; } }
</style>
```

- [ ] **Step 4: Rewrite `web/src/routes/+page.svelte`**

Replace the whole file with:

```svelte
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import Dashboard from "./Dashboard.svelte";
  import { getFeed, completeTask, startAgentJob, getAgentJob, ApiError, type AgentJob } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { Feed } from "$lib/types";

  let feed = $state<Feed | null>(null);
  let error = $state("");
  let pending = $state(new Set<string>());
  let agentJobs = $state<Record<string, AgentJob>>({});
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function load() {
    error = "";
    try { feed = await getFeed(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  async function onComplete(id: string) {
    if (!feed || pending.has(id)) return;
    const removed = feed.active.find(t => t.id === id);
    if (!removed) return;
    pending = new Set(pending).add(id);
    feed = { ...feed, active: feed.active.filter(t => t.id !== id) };  // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                                    // reconcile (ledger/branches)
    } catch (e) {
      feed = { ...feed, active: [removed, ...feed.active] };           // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  // ── agent jobs (spec sub-project 3) ───────────────────────────────────────
  function jobActive(j: AgentJob): boolean {
    return j.status === "queued" || j.status === "running";
  }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
  function startPolling() { if (!pollTimer) pollTimer = setInterval(poll, 5000); }

  async function poll() {
    const active = Object.values(agentJobs).filter(jobActive);
    if (active.length === 0) { stopPolling(); return; }
    for (const j of active) {
      try {
        const fresh = await getAgentJob(j.id);
        agentJobs = { ...agentJobs, [fresh.task_id]: fresh };
        // the agent's plan reaches this clone via the host's sync timer —
        // reload on done, but it may still take a couple of minutes to appear
        if (fresh.status === "done") await load();
      } catch { /* transient — keep polling */ }
    }
  }

  async function onAgent(id: string) {
    if (agentJobs[id] && jobActive(agentJobs[id])) return;
    error = "";
    try {
      const job = await startAgentJob(id, "research");
      agentJobs = { ...agentJobs, [id]: job };
      startPolling();
    } catch (e) {
      error = e instanceof Error ? e.message : "couldn't start the agent — try again";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
  onDestroy(stopPolling);
</script>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{:else if feed}
  <Dashboard {feed} {onComplete} {pending} {onAgent} {agentJobs} />
{:else}
  <p class="muted">Loading…</p>
{/if}
```

- [ ] **Step 5: Run the web suite**

Run: `cd web && npx vitest run`
Expected: all pass (existing suites unchanged — the new Dashboard props are optional with defaults)

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/Dashboard.svelte web/src/routes/+page.svelte web/src/routes/dashboard.test.ts web/src/routes/ask-sidekick.test.ts
git commit -m "web: Ask Sidekick on dashboard cards — start research job, poll status"
```

---

### Task 8: PWA — "Break it down" on the shared list

**Files:**
- Modify: `web/src/routes/shared/+page.svelte`
- Test: `web/src/routes/shared/shared.test.ts`

**Interfaces:**
- Consumes: Task 6 client. Both roles may use this (server allows breakdown on shared tasks for role `shared`, everything for role `full`).
- Produces: each shared-list row gets a "Break it down" button + status chip; same 5 s polling as Task 7 (duplicated ~25 lines rather than a premature shared abstraction — two call sites, different actions and reload targets).

- [ ] **Step 1: Write the failing tests**

In `web/src/routes/shared/shared.test.ts`, replace the `vi.mock("$lib/api", ...)` factory with:

```ts
vi.mock("$lib/api", () => ({
  getFeed: vi.fn(),
  createTask: vi.fn(async () => ({ id: "new1" })),
  completeTask: vi.fn(async () => ({
    id: "new", status: "done", completed_at: "T", sat_for_hours: 1, already_done: false
  })),
  startAgentJob: vi.fn(),
  getAgentJob: vi.fn(),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));
```

and extend the import below it:

```ts
import { getFeed, createTask, completeTask, startAgentJob } from "$lib/api";
```

Append inside the `describe("Shared list", ...)` block:

```ts
  it("break it down starts a breakdown job and shows the chip", async () => {
    vi.mocked(startAgentJob).mockResolvedValue({
      id: "j1", task_id: "new", action: "breakdown", status: "queued",
      summary: null, error: null, log_tail: null,
      created_at: "T", started_at: null, finished_at: null
    } as any);
    render(SharedPage);
    await waitFor(() => expect(screen.getByText("New shared")).toBeInTheDocument());
    await fireEvent.click(screen.getByRole("button", { name: /break down new shared/i }));
    await waitFor(() => expect(startAgentJob).toHaveBeenCalledWith("new", "breakdown"));
    expect(screen.getByText("queued")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/routes/shared/shared.test.ts`
Expected: 4 pass, 1 fails (no such button)

- [ ] **Step 3: Write the implementation**

Replace `web/src/routes/shared/+page.svelte` with:

```svelte
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import { getFeed, createTask, completeTask, startAgentJob, getAgentJob, ApiError, type AgentJob } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { ActiveTask } from "$lib/types";

  let tasks = $state<ActiveTask[] | null>(null);
  let title = $state("");
  let busy = $state(false);
  let error = $state("");
  let pending = $state(new Set<string>());
  let agentJobs = $state<Record<string, AgentJob>>({});
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  // newest first: read_active sorts longest-sitting first, so invert by sat hours
  const newestFirst = (list: ActiveTask[]) =>
    [...list].sort((a, b) => (a.sat_for_hours ?? 0) - (b.sat_for_hours ?? 0));

  async function load() {
    error = "";
    try {
      const feed = await getFeed();
      // role `shared` gets a pre-filtered feed; for role `full` this filter does the same job
      tasks = newestFirst(feed.active.filter(t => t.shared));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  async function add(e: Event) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    busy = true; error = "";
    try {
      await createTask(title.trim(), "chore", true);  // fixed category: the box has no picker
      title = "";
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't add — try again";
    } finally {
      busy = false;
    }
  }

  async function tick(id: string) {
    if (!tasks || pending.has(id)) return;
    const removed = tasks.find(t => t.id === id);
    if (!removed) return;
    pending = new Set(pending).add(id);
    tasks = tasks.filter(t => t.id !== id);              // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                       // reconcile: fetch new items from other user
    } catch (e) {
      tasks = newestFirst([removed, ...tasks]);          // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  // ── agent jobs (spec sub-project 3): breakdown, both roles ────────────────
  function jobActive(j: AgentJob): boolean {
    return j.status === "queued" || j.status === "running";
  }
  function chipText(j: AgentJob): string {
    if (j.status === "done") return j.summary ? `done — ${j.summary}` : "done";
    if (j.status === "failed") return "failed";
    return j.status;
  }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
  function startPolling() { if (!pollTimer) pollTimer = setInterval(poll, 5000); }

  async function poll() {
    const active = Object.values(agentJobs).filter(jobActive);
    if (active.length === 0) { stopPolling(); return; }
    for (const j of active) {
      try {
        const fresh = await getAgentJob(j.id);
        agentJobs = { ...agentJobs, [fresh.task_id]: fresh };
        // sub-tasks reach this list via the host's sync timer — reload on done,
        // but they may still take a couple of minutes to appear
        if (fresh.status === "done") await load();
      } catch { /* transient — keep polling */ }
    }
  }

  async function breakItDown(id: string) {
    if (agentJobs[id] && jobActive(agentJobs[id])) return;
    error = "";
    try {
      const job = await startAgentJob(id, "breakdown");
      agentJobs = { ...agentJobs, [id]: job };
      startPolling();
    } catch (e) {
      error = e instanceof Error ? e.message : "couldn't start — try again";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
  onDestroy(stopPolling);
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Shared list</h1>

<form class="add-row" onsubmit={add}>
  <input type="text" bind:value={title} placeholder="Add to the list…"
         aria-label="New shared task" />
  <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
</form>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{/if}

{#if tasks}
  {#if tasks.length === 0}
    <p class="muted">Nothing on the list.</p>
  {:else}
    <ul class="list">
      {#each tasks as t (t.id)}
        <li>
          <label>
            <input type="checkbox" disabled={pending.has(t.id)}
                   onchange={() => tick(t.id)} aria-label={"Complete " + t.task} />
            <span>{t.task}</span>
          </label>
          <div class="row-agent">
            <button class="btn btn-mini" disabled={!!agentJobs[t.id] && jobActive(agentJobs[t.id])}
                    onclick={() => breakItDown(t.id)} aria-label={"Break down " + t.task}>
              {!!agentJobs[t.id] && jobActive(agentJobs[t.id]) ? "Working…" : "Break it down"}
            </button>
            {#if agentJobs[t.id]}
              <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
{:else if !error}
  <p class="muted">Loading…</p>
{/if}

<style>
  .add-row { display: flex; gap: 8px; margin-bottom: 18px; }
  .add-row input[type="text"] {
    flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(128, 128, 128, 0.35); background: transparent;
    color: inherit; font-size: 16px;   /* ≥16px prevents iOS focus zoom */
  }
  .list { list-style: none; padding: 0; margin: 0; }
  .list li { padding: 12px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.2); }
  .list label { display: flex; align-items: center; gap: 12px; font-size: 17px; }
  .list input[type="checkbox"] { width: 22px; height: 22px; flex: none; }
  .row-agent { display: flex; align-items: center; gap: 8px; margin: 8px 0 0 34px; }
  .btn-mini { font-size: 13px; padding: 4px 10px; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px;
          border: 1px solid rgba(128, 128, 128, 0.35); opacity: 0.85; }
  .chip-queued, .chip-running { animation: chip-pulse 1.5s ease-in-out infinite; }
  .chip-failed { border-color: rgba(220, 60, 60, 0.6); }
  @keyframes chip-pulse { 50% { opacity: 0.45; } }
</style>
```

- [ ] **Step 4: Run the full web suite**

Run: `cd web && npx vitest run`
Expected: all pass (5 shared-list tests incl. the new one; nothing else regressed)

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/shared/+page.svelte web/src/routes/shared/shared.test.ts
git commit -m "web: Break it down on the shared list — start breakdown job, poll status"
```

---

### Task 9: Deploy docs — "Agent runner (pi headless)" section

**Files:**
- Modify: `deploy/README.md` (insert after the "Web-push nudges" section, before "Operating notes")

**Interfaces:**
- Consumes: the env knobs from Task 3 (`SIDEKICK_AGENT_CLONE`, `SIDEKICK_AGENT_CMD`, `SIDEKICK_AGENT_TIMEOUT`), the existing `/etc/sidekick.env` + `sidekick` user layout.
- Produces: copy-paste ops instructions **including the explicit spec deviation** (same user, separate clone) so the human sees it at deploy time.

- [ ] **Step 1: Write the section**

Insert into `deploy/README.md`:

```markdown
## Agent runner (pi headless)

The API can hand a task to Claude ("Ask Sidekick" / "Break it down"): jobs run
inside the API process, strictly one at a time, as `pi -p "<prompt>"` in a
**separate clone** — never `/srv/sidekick`. Results arrive as pushed commits;
the sync timer delivers them to the serving clone and the phones.

> **Deviation from the design spec, on purpose:** the spec calls for a dedicated
> low-privilege user. Spawning subprocesses as a *different* user from inside
> the hardened systemd API service is nontrivial (sudoers or a second daemon),
> so the agent runs as the same `sidekick` service user, isolated only by the
> separate clone — pi can reach anything the `sidekick` user can, including the
> serving clone. Accepted for now; revisit with a separate jobs daemon if it
> ever bites.

One-time setup on the VPS:

    # 1. the agent's own clone (reuses the sidekick user's deploy key)
    sudo -u sidekick mkdir -p /home/sidekick/agent
    sudo -u sidekick git clone git@github.com:FellowDalton/sidekick.git /home/sidekick/agent/sidekick
    sudo -u sidekick git -C /home/sidekick/agent/sidekick config user.name "Sidekick Agent"
    sudo -u sidekick git -C /home/sidekick/agent/sidekick config user.email "agent@sidekick.local"

    # 2. the prompts tell the model to run `python3 sidekick.py ...` — it needs pyyaml
    sudo apt-get install -y python3-yaml

    # 3. install pi for the sidekick user (see pi.dev install docs), then bring
    #    the auth over from the Mac (subscription OAuth tokens; they auto-refresh).
    #    On the Mac:  scp -r ~/.pi/agent root@<vps-ip>:/home/sidekick/.pi/agent
    sudo chown -R sidekick:sidekick /home/sidekick/.pi
    sudo chmod 600 /home/sidekick/.pi/agent/auth.json
    sudo -u sidekick -H pi -p "reply with exactly: ok"      # auth smoke test

Add to `/etc/sidekick.env` (then `sudo systemctl restart sidekick`):

    SIDEKICK_AGENT_CLONE=/home/sidekick/agent/sidekick
    # SIDEKICK_AGENT_CMD=pi -p          # the default; use an absolute path
    #                                     (e.g. /home/sidekick/.local/bin/pi -p)
    #                                     if pi is not on the service's PATH
    # SIDEKICK_AGENT_TIMEOUT=900        # seconds; the default

Dry-run smoke test **without spending model quota**: temporarily set
`SIDEKICK_AGENT_CMD=echo` in `/etc/sidekick.env`, restart, then:

    curl -s -X POST -H "Authorization: Bearer <token>" -H 'Content-Type: application/json' \
      -d '{"action":"research"}' https://sidekick.tail81b55b.ts.net/api/tasks/<task-id>/agent
    # → 202 {"id":"<job-id>","status":"queued",...}
    curl -s -H "Authorization: Bearer <token>" https://sidekick.tail81b55b.ts.net/api/agent/jobs/<job-id>
    # → "status":"done" with the prompt's last line echoed back as the summary

Put `SIDEKICK_AGENT_CMD` back (or remove the line) and restart. Job logs live in
`/srv/sidekick/.sidekick-agent-logs/<job-id>.log`; job state in
`/srv/sidekick/.sidekick-agent-jobs.json` (both gitignored). Jobs consume
Claude/Codex subscription quota — the single-worker queue is what bounds spend.
An API restart fails any queued/running job ("interrupted by restart"); just
start it again from the phone.
```

- [ ] **Step 2: Sanity check**

Run: `python3 -m pytest server/tests/ -q && python3 -m pytest tests/ -q`
Expected: all pass (docs-only change)

- [ ] **Step 3: Commit**

```bash
git add deploy/README.md
git commit -m "deploy: agent runner ops — clone, pi auth, env knobs, echo dry-run"
```

---

## Deployment note (manual ops, after merge)

Not part of the code tasks — on the VPS, in order:

1. `sudo -u sidekick git -C /srv/sidekick pull` (brings the new server code), then `sudo systemctl restart sidekick`.
2. Follow the new **"Agent runner (pi headless)"** section of `deploy/README.md`: agent clone → `python3-yaml` → pi install + `auth.json` copy from the Mac → env additions → restart.
3. **Echo dry run first** (`SIDEKICK_AGENT_CMD=echo`, as documented) — proves queue → runner → push → status without touching pi or quota.
4. First real run: create a throwaway task from the phone, tap **Ask Sidekick**, watch `journalctl -u sidekick -f` and the job log; confirm the plan appears on the dashboard within a few minutes (job time + sync-timer lag), then review the agent's commit on GitHub.
5. Prerequisite check: sub-project 1's `sidekick-sync.timer` must be enabled — without it the agent's pushes never reach the serving clone or the phones.

**Honest limits:** the agent is quota-bounded, not sandboxed (see the deviation note in the README); job results reach the phone with sync-timer latency (≤ ~3 min after the job finishes); the PWA only polls while the page is open — closing the app doesn't cancel the job, and its result still arrives via git.
