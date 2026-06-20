# Sidekick Phone App — Phase 1: Host Engine + HTTP API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the always-on host backbone of the phone app: a thin HTTP API that wraps the existing `sidekick.py` engine so a client can read the feed, complete a task, and capture a new task — with `sidekick.py` still the sole, append-only, code-only writer of the ledger, and every change committed/pushed to the canonical Git remote.

**Architecture:** A new `server/` FastAPI package imports `sidekick.py` and exposes `GET /feed`, `POST /tasks`, `POST /tasks/{id}/complete`. Mutations are serialized by a write lock, guarded by single-user bearer auth and `Idempotency-Key` replay, applied through the engine, then published to git (`commit → pull --rebase → push`) with a union-merge driver on `ledger.jsonl` so concurrent appends never conflict. This is **Phase 1 only** — the SvelteKit PWA (Phase 2), the offline outbox / Capacitor / nudge-relocation (Phase 3), and the Mac Obsidian-Git setup (Phase 4) are separate future plans (spec §10).

**Tech Stack:** Python 3 + `pyyaml` (existing) + **FastAPI** + **uvicorn** (runtime); **pytest** + **httpx** (dev, for FastAPI's `TestClient`). Git for the sync fabric. Root tests stay stdlib `unittest`; new `server/` tests are pytest.

## Global Constraints

Every task's requirements implicitly include these (copied from the spec):

- **`sidekick.py` stays the sole writer of `ledger.jsonl`** — append-only, code-only, no model logic. The server calls `sidekick.py` functions; it must **never** write `ledger.jsonl`, task files, or the feed directly.
- **`complete()` must be idempotent** — an already-done task is never re-appended (no second ledger event) — and must honor an optional caller-supplied `completed_at` (defaulting to `now_iso()`).
- **`ledger.jsonl` uses a git `union` merge driver** (`.gitattributes`) so concurrent appends from host and Mac merge by keeping both lines, never conflicting. Safe because levels/branches are *derived* from the full event set (order-independent).
- **All endpoints require `Authorization: Bearer <token>`** (else `401`); mutating endpoints accept an `Idempotency-Key` header for safe retries.
- **`GET /feed` returns exactly `{"events": [...], "active": [...]}`** — the same shape as `window.SIDEKICK`.
- **Writes are serialized** by a process-wide lock; the server runs with a **single worker**.
- **Dependency additions only:** `fastapi`, `uvicorn` (runtime); `pytest`, `httpx` (dev). `pyyaml` already present. No other new deps.
- **Category set is exactly** `phone | admin | errand | chore`.
- **Do not change** the `ledger.jsonl` event schema, the wiki, the dashboard feed shape, or `sidekick.html`. The existing `tests/test_regenerate.py` and `tests/test_wiki.py` must stay green.
- **Error response body shape is `{"error": "<message>"}`** for all 4xx/5xx the API raises.
- **Hosting** requires persistent storage; the build is vendor-agnostic (deploy is documented, not automated).

---

## File Structure

- **`sidekick.py`** (modify) — add `configure(vault)` (re-point path globals) and extend `complete(task_id, completed_at=None)` to be idempotent and return a structured dict. No other engine change.
- **`tests/test_engine_api.py`** (create) — stdlib `unittest` for the two `sidekick.py` extensions.
- **`.gitattributes`** (create) — `ledger.jsonl merge=union`.
- **`.gitignore`** (modify) — ignore the idempotency store file.
- **`server/__init__.py`** (create) — makes `server` an importable package.
- **`server/requirements.txt`** (create) — `fastapi`, `uvicorn[standard]`.
- **`server/requirements-dev.txt`** (create) — `pytest`, `httpx`.
- **`server/git_sync.py`** (create) — deterministic `commit_and_push` with rebase/retry.
- **`server/idempotency.py`** (create) — persistent `IdempotencyStore`.
- **`server/config.py`** (create) — `Config` (env or explicit) + `load_config()`.
- **`server/app.py`** (create) — the FastAPI `create_app(config)` factory: auth, `GET /feed`, then (Task 5) the write endpoints.
- **`server/tests/conftest.py`** (create) — shared pytest fixtures: `bare_remote`, `vault_repo`, then (Task 4) `app_config`, `client`.
- **`server/tests/test_git_sync.py`** / **`test_idempotency.py`** / **`test_api_feed.py`** / **`test_api_writes.py`** (create) — pytest suites.
- **`server/README.md`** (create) — run + deploy doc.
- **`README.md`** (modify) — one-line pointer to `server/`.

---

## Task 1: Engine extensions in `sidekick.py` (`configure` + idempotent `complete`)

**Files:**
- Modify: `sidekick.py` (add `configure()` near the paths block; rewrite `complete()` ~lines 116-132)
- Test: `tests/test_engine_api.py` (create)

**Interfaces:**
- Consumes: existing `read_note`, `write_note`, `now_iso`, `hours_since`, `task_path`, `create_task`, and the path globals.
- Produces:
  - `configure(vault: str) -> None` — sets `VAULT, TASKS, LEDGER, DATA_JS, RENDER_JS, WIKI, WIKI_INDEX` from `vault`.
  - `complete(task_id: str, completed_at: str | None = None) -> dict` — idempotent; returns `{"id","task","category","status","completed_at","sat_for_hours","already_done"}`. Raises `FileNotFoundError` if the task file is absent.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_engine_api.py`:

```python
"""Unit tests for the host-API engine extensions in sidekick.py: configure() and the
idempotent, completed_at-honoring complete(). Imports sidekick directly and repoints
it at a throwaway vault via configure()."""
import json, tempfile, unittest
from pathlib import Path

import sidekick


class EngineApiExtensions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "tasks").mkdir()
        (self.vault / "ledger.jsonl").write_text("", encoding="utf-8")
        sidekick.configure(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger_lines(self):
        return [l for l in (self.vault / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_configure_repoints_paths(self):
        self.assertEqual(sidekick.LEDGER, str(self.vault / "ledger.jsonl"))
        self.assertEqual(sidekick.TASKS, str(self.vault / "tasks"))

    def test_complete_honors_completed_at_and_appends_once(self):
        tid = sidekick.create_task("Call dentist", "phone")
        res = sidekick.complete(tid, completed_at="2026-06-20T09:00:00Z")
        self.assertEqual(res["status"], "done")
        self.assertEqual(res["completed_at"], "2026-06-20T09:00:00Z")
        self.assertFalse(res["already_done"])
        lines = self._ledger_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["completed_at"], "2026-06-20T09:00:00Z")

    def test_complete_is_idempotent(self):
        tid = sidekick.create_task("Renew passport", "admin")
        sidekick.complete(tid)
        again = sidekick.complete(tid)
        self.assertTrue(again["already_done"])
        self.assertEqual(len(self._ledger_lines()), 1)  # no second event

    def test_complete_missing_task_raises(self):
        with self.assertRaises(FileNotFoundError):
            sidekick.complete("nope-does-not-exist")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest tests.test_engine_api -v`
Expected: FAIL — `AttributeError: module 'sidekick' has no attribute 'configure'` (and `complete()` doesn't accept `completed_at`).

- [ ] **Step 3: Add `configure()`**

In `sidekick.py`, immediately after the `WIKI_INDEX = ...` line in the paths block (the constants added by the wiki feature), add:

```python
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
```

- [ ] **Step 4: Rewrite `complete()` to be idempotent and return a dict**

Replace the entire existing `complete()` function with:

```python
def complete(task_id, completed_at=None):
    """Append the completion event to the ledger (its only writer), then mark the task
    done. Idempotent: an already-done task is NOT re-appended. `completed_at` (ISO
    string) lets a caller (e.g. the phone) stamp the moment of completion; defaults to
    now. Returns a result dict. Raises FileNotFoundError if the task file is absent."""
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

(The CLI path `complete(a.id); regenerate()` in `main()` is unchanged — it ignores the return value and `completed_at` defaults to `None`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m unittest tests.test_engine_api -v`
Expected: PASS — 4 tests.

Then the whole root suite (must stay green):
Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — `test_engine_api` (4) + `test_regenerate` (2) + `test_wiki` (5).

- [ ] **Step 6: Commit**

```bash
git add sidekick.py tests/test_engine_api.py
git commit -m "feat: sidekick.py configure() + idempotent complete(completed_at)

Adds configure(vault) to re-point the engine's paths (for the host server and
tests) and makes complete() idempotent (no second ledger event for an already-
done task), honor an optional caller-supplied completed_at, and return a result
dict. CLI behavior unchanged. Engine stays the sole, append-only ledger writer.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 2: Server scaffolding + Git sync fabric

**Files:**
- Create: `server/__init__.py`, `server/requirements.txt`, `server/requirements-dev.txt`, `server/git_sync.py`, `server/tests/conftest.py`, `server/tests/test_git_sync.py`
- Create: `.gitattributes`

**Interfaces:**
- Produces:
  - `git_sync.commit_and_push(repo: str, message: str, *, push=True, remote="origin", retries=3) -> str` (returns new HEAD sha; raises `git_sync.GitSyncError`).
  - `git_sync.current_branch(repo: str) -> str`.
  - pytest fixtures `bare_remote` (a `Path` to a bare repo) and `vault_repo` (a `Path` to a working clone seeded with `tasks/`, empty `ledger.jsonl`, `.gitattributes`, an `origin` pointing at `bare_remote`, and `main` pushed).

- [ ] **Step 1: Create the package marker, requirements, and `.gitattributes`**

Create `server/__init__.py` (empty file):

```python
```

Create `server/requirements.txt`:

```
fastapi
uvicorn[standard]
```

Create `server/requirements-dev.txt`:

```
pytest
httpx
```

Create `.gitattributes` at the repo root:

```
# Append-only ledger: union-merge so concurrent appends never conflict (host + Mac).
ledger.jsonl merge=union
```

Install the deps (front-loaded so every later server task can run its tests):

Run: `pip install -r server/requirements.txt -r server/requirements-dev.txt`
Expected: installs fastapi, uvicorn, pytest, httpx successfully.

- [ ] **Step 2: Write the shared test fixtures**

Create `server/tests/conftest.py`:

```python
"""Shared fixtures for the host server tests. Builds throwaway git vaults with a bare
remote so the real CLI + git automation are exercised end to end (no network: the
remote is a local bare repo)."""
import subprocess
from pathlib import Path

import pytest


def git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def init_vault_repo(path: Path, remote_url: str):
    """Seed a vault working clone: tasks/, empty ledger, union-merge attr, push main."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "tasks").mkdir()
    (path / "ledger.jsonl").write_text("", encoding="utf-8")
    (path / ".gitattributes").write_text("ledger.jsonl merge=union\n", encoding="utf-8")
    git(["init", "-b", "main"], path)
    git(["config", "user.email", "test@sidekick.local"], path)
    git(["config", "user.name", "Sidekick Test"], path)
    git(["add", "-A"], path)
    git(["commit", "-m", "init vault"], path)
    git(["remote", "add", "origin", remote_url], path)
    git(["push", "-u", "origin", "main"], path)


@pytest.fixture
def bare_remote(tmp_path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)],
                   check=True, capture_output=True, text=True)
    return remote


@pytest.fixture
def vault_repo(tmp_path, bare_remote) -> Path:
    vault = tmp_path / "host"
    init_vault_repo(vault, str(bare_remote))
    return vault


def clone(remote: Path, dest: Path) -> Path:
    subprocess.run(["git", "clone", str(remote), str(dest)],
                   check=True, capture_output=True, text=True)
    git(["config", "user.email", "other@sidekick.local"], dest)
    git(["config", "user.name", "Other Clone"], dest)
    return dest
```

- [ ] **Step 3: Write the failing git_sync tests**

Create `server/tests/test_git_sync.py`:

```python
"""git_sync.commit_and_push must publish local changes and absorb a concurrent remote
push via union-merge on the ledger (no conflict, both events survive)."""
from pathlib import Path

from server import git_sync
from server.tests.conftest import git, clone


def _append_ledger(repo: Path, line: str):
    with open(repo / "ledger.jsonl", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def test_commit_and_push_publishes_to_remote(vault_repo, bare_remote, tmp_path):
    _append_ledger(vault_repo, '{"task":"A"}')
    head = git_sync.commit_and_push(str(vault_repo), "api: A")
    assert len(head) >= 7
    check = clone(bare_remote, tmp_path / "check")
    assert '{"task":"A"}' in (check / "ledger.jsonl").read_text(encoding="utf-8")


def test_rebase_absorbs_concurrent_remote_append(vault_repo, bare_remote, tmp_path):
    # another clone pushes a different ledger line first
    other = clone(bare_remote, tmp_path / "other")
    _append_ledger(other, '{"task":"REMOTE"}')
    git(["add", "-A"], other)
    git(["commit", "-m", "remote append"], other)
    git(["push", "origin", "main"], other)

    # host appends locally, then commit_and_push must pull --rebase (union merge) + push
    _append_ledger(vault_repo, '{"task":"LOCAL"}')
    git_sync.commit_and_push(str(vault_repo), "api: LOCAL")

    final = clone(bare_remote, tmp_path / "final")
    text = (final / "ledger.jsonl").read_text(encoding="utf-8")
    assert '{"task":"REMOTE"}' in text
    assert '{"task":"LOCAL"}' in text


def test_nothing_to_commit_is_safe(vault_repo):
    head1 = git_sync.commit_and_push(str(vault_repo), "noop")
    head2 = git_sync.commit_and_push(str(vault_repo), "noop again")
    assert head1 == head2  # no empty commits created
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `pytest server/tests/test_git_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.git_sync'`.

- [ ] **Step 5: Implement `git_sync.py`**

Create `server/git_sync.py`:

```python
"""Deterministic git automation for the host engine: stage + commit local vault changes
and publish them to the canonical remote, absorbing concurrent pushes via pull --rebase.
The ledger's union-merge driver (.gitattributes) keeps concurrent appends conflict-free.
No model logic; pure mechanics."""
import subprocess


class GitSyncError(RuntimeError):
    pass


def _run(args, cwd):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        raise GitSyncError(f"git {' '.join(args)} failed: {(p.stderr or p.stdout).strip()}")
    return p.stdout.strip()


def current_branch(repo):
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], repo)


def commit_and_push(repo, message, *, push=True, remote="origin", retries=3):
    """Stage everything, commit (safe when nothing changed), then pull --rebase + push
    with bounded retry to absorb concurrent remote changes. Returns the new HEAD sha.
    With push=False, commits locally only (dev/offline)."""
    _run(["add", "-A"], repo)
    commit = subprocess.run(["git", "commit", "-m", message],
                            cwd=repo, capture_output=True, text=True)
    nothing = "nothing to commit" in (commit.stdout + commit.stderr)
    if commit.returncode != 0 and not nothing:
        raise GitSyncError(f"git commit failed: {(commit.stderr or commit.stdout).strip()}")
    if not push:
        return _run(["rev-parse", "HEAD"], repo)
    branch = current_branch(repo)
    last = None
    for _ in range(retries):
        try:
            _run(["pull", "--rebase", remote, branch], repo)
            _run(["push", remote, branch], repo)
            return _run(["rev-parse", "HEAD"], repo)
        except GitSyncError as e:
            last = e
    raise GitSyncError(f"push failed after {retries} retries: {last}")
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest server/tests/test_git_sync.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 7: Commit**

```bash
git add server/__init__.py server/requirements.txt server/requirements-dev.txt \
        server/git_sync.py server/tests/conftest.py server/tests/test_git_sync.py .gitattributes
git commit -m "feat: server scaffolding + git sync fabric (union-merge ledger)

Adds the server/ package, runtime/dev requirements, a union-merge .gitattributes
for ledger.jsonl, and git_sync.commit_and_push (add/commit/pull --rebase/push with
retry). Shared pytest fixtures build throwaway vaults with a local bare remote, so
git automation and union-merge of concurrent ledger appends are tested end to end.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 3: Idempotency store

**Files:**
- Create: `server/idempotency.py`, `server/tests/test_idempotency.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `IdempotencyStore(path: str)` with `.get(key) -> dict | None` (returns `{"status_code", "body"}`) and `.put(key, status_code, body) -> None` (persists atomically).

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_idempotency.py`:

```python
"""IdempotencyStore persists request results keyed by Idempotency-Key, so a retried
request replays instead of re-applying. Survives restart; tolerates a corrupt file."""
from server.idempotency import IdempotencyStore


def test_put_then_get(tmp_path):
    s = IdempotencyStore(str(tmp_path / "idem.json"))
    assert s.get("k1") is None
    s.put("k1", 201, {"id": "x"})
    assert s.get("k1") == {"status_code": 201, "body": {"id": "x"}}


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "idem.json")
    IdempotencyStore(path).put("k2", 200, {"ok": True})
    assert IdempotencyStore(path).get("k2") == {"status_code": 200, "body": {"ok": True}}


def test_corrupt_file_degrades_to_empty(tmp_path):
    path = tmp_path / "idem.json"
    path.write_text("{not valid json", encoding="utf-8")
    s = IdempotencyStore(str(path))
    assert s.get("anything") is None  # no crash
    s.put("k3", 200, {"ok": 1})       # still usable
    assert s.get("k3") == {"status_code": 200, "body": {"ok": 1}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest server/tests/test_idempotency.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.idempotency'`.

- [ ] **Step 3: Implement `idempotency.py`**

Create `server/idempotency.py`:

```python
"""Tiny persistent idempotency store. Maps an Idempotency-Key to the response
(status code + JSON body) that was returned, so a retried mutating request replays the
same result rather than applying the change twice. Persisted to a JSON file in the
vault (gitignored), atomically (tmp + os.replace), so it survives restarts."""
import json
import os


class IdempotencyStore:
    def __init__(self, path):
        self.path = path
        self._data = {}
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self._data = loaded
            except (ValueError, OSError):
                self._data = {}   # corrupt/unreadable -> start empty, never crash

    def get(self, key):
        return self._data.get(key)

    def put(self, key, status_code, body):
        self._data[key] = {"status_code": status_code, "body": body}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False)
        os.replace(tmp, self.path)
```

- [ ] **Step 4: Ignore the store file**

In `.gitignore`, under the `# secrets & logs` section, add:

```
# host API idempotency store (runtime state, per-vault)
.sidekick-idempotency.json
```

(The `*.tmp` rule already covers the atomic temp file.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest server/tests/test_idempotency.py -v`
Expected: PASS — 3 tests.

- [ ] **Step 6: Commit**

```bash
git add server/idempotency.py server/tests/test_idempotency.py .gitignore
git commit -m "feat: persistent idempotency store for mutating API requests

Maps Idempotency-Key -> {status_code, body}, persisted atomically to a gitignored
JSON file so retried complete/capture requests replay instead of double-applying.
Degrades to empty on a corrupt file.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 4: Config + FastAPI app factory + auth + `GET /feed`

**Files:**
- Create: `server/config.py`, `server/app.py`, `server/tests/test_api_feed.py`
- Modify: `server/tests/conftest.py` (append `app_config` and `client` fixtures)

**Interfaces:**
- Consumes: `sidekick.configure`, `sidekick.read_ledger`, `sidekick.read_active`, `IdempotencyStore`, `git_sync` (wired now, used by Task 5).
- Produces:
  - `Config(vault=None, token=None, push=None, remote=None)` — falls back to env (`SIDEKICK_VAULT`, `SIDEKICK_API_TOKEN`, `SIDEKICK_GIT_PUSH`, `SIDEKICK_GIT_REMOTE`); raises if vault/token missing. `load_config() -> Config`.
  - `create_app(config: Config | None = None) -> FastAPI` exposing `GET /feed`.
  - fixtures `app_config` (a `Config` for `vault_repo` with token `test-token`) and `client` (a `TestClient`).

- [ ] **Step 1: Write the failing feed tests and add the fixtures**

Append to `server/tests/conftest.py`:

```python
@pytest.fixture
def app_config(vault_repo):
    from server.config import Config
    return Config(vault=str(vault_repo), token="test-token", push=True, remote="origin")


@pytest.fixture
def client(app_config):
    from fastapi.testclient import TestClient
    from server.app import create_app
    return TestClient(create_app(app_config))


AUTH = {"Authorization": "Bearer test-token"}
```

Create `server/tests/test_api_feed.py`:

```python
"""GET /feed requires auth and returns the {events, active} read-model."""
import sidekick

from server.tests.conftest import AUTH


def test_feed_requires_auth(client):
    r = client.get("/feed")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_feed_returns_events_and_active(client, app_config):
    # seed one open task directly through the engine (already pointed at the vault)
    sidekick.configure(app_config.vault)
    sidekick.create_task("Sweep the garage", "chore")
    r = client.get("/feed", headers=AUTH)
    assert r.status_code == 200
    payload = r.json()
    assert set(payload.keys()) == {"events", "active"}
    assert any(a["task"] == "Sweep the garage" for a in payload["active"])
    assert payload["events"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest server/tests/test_api_feed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.config'` (and `server.app`).

- [ ] **Step 3: Implement `config.py`**

Create `server/config.py`:

```python
"""Host server configuration. Values come from explicit kwargs (tests) or the
environment (production). vault + token are required."""
import os

_FALSEY = ("0", "false", "False", "")


class Config:
    def __init__(self, vault=None, token=None, push=None, remote=None):
        self.vault = vault if vault is not None else os.environ.get("SIDEKICK_VAULT")
        self.token = token if token is not None else os.environ.get("SIDEKICK_API_TOKEN")
        if push is not None:
            self.push = push
        else:
            self.push = os.environ.get("SIDEKICK_GIT_PUSH", "1") not in _FALSEY
        self.remote = remote if remote is not None else os.environ.get("SIDEKICK_GIT_REMOTE", "origin")
        if not self.vault:
            raise RuntimeError("SIDEKICK_VAULT is required")
        if not self.token:
            raise RuntimeError("SIDEKICK_API_TOKEN is required")


def load_config():
    return Config()
```

- [ ] **Step 4: Implement `app.py` (factory + auth + GET /feed)**

Create `server/app.py`:

```python
"""The host HTTP API: a thin wrapper over sidekick.py. The engine stays the SOLE writer
of the ledger; this layer only routes requests, enforces bearer auth and idempotency,
and publishes each change to git. Mutations are serialized by a write lock — run with a
single worker. Phase 1: GET /feed here; the write endpoints are added in Task 5."""
import os
import sys
import threading

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

# ensure the repo root (where sidekick.py lives) is importable, even under uvicorn
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidekick                       # noqa: E402
from server.config import load_config  # noqa: E402
from server import git_sync            # noqa: E402
from server.idempotency import IdempotencyStore  # noqa: E402

VALID_CATEGORIES = {"phone", "admin", "errand", "chore"}


def create_app(config=None):
    config = config or load_config()
    sidekick.configure(config.vault)
    idem = IdempotencyStore(os.path.join(config.vault, ".sidekick-idempotency.json"))
    write_lock = threading.Lock()

    app = FastAPI(title="Sidekick host API")
    app.state.config = config
    app.state.idem = idem
    app.state.write_lock = write_lock

    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    def require_auth(authorization):
        if authorization != f"Bearer {config.token}":
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/feed")
    def get_feed(authorization: str = Header(default="")):
        require_auth(authorization)
        return {"events": sidekick.read_ledger(), "active": sidekick.read_active()}

    return app
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest server/tests/test_api_feed.py -v`
Expected: PASS — 2 tests.

- [ ] **Step 6: Commit**

```bash
git add server/config.py server/app.py server/tests/test_api_feed.py server/tests/conftest.py
git commit -m "feat: FastAPI app factory with bearer auth + GET /feed

create_app(config) points the engine at the vault, wires the idempotency store and a
write lock, and serves GET /feed ({events, active}) behind single-user bearer auth.
Errors render as {\"error\": ...}. Config reads explicit kwargs or the environment.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 5: Write endpoints — `POST /tasks` and `POST /tasks/{id}/complete`

**Files:**
- Modify: `server/app.py` (add the two routes + an idempotency helper inside `create_app`)
- Create: `server/tests/test_api_writes.py`

**Interfaces:**
- Consumes: `sidekick.create_task`, `sidekick.complete`, `sidekick.regenerate`, `sidekick.read_active`, `git_sync.commit_and_push`, the `idem` store, and `write_lock` from Task 4.
- Produces: `POST /tasks` → `201` task entry; `POST /tasks/{id}/complete` → `200` result dict. Both honor `Idempotency-Key`; both publish to git.

- [ ] **Step 1: Write the failing write-endpoint tests**

Create `server/tests/test_api_writes.py`:

```python
"""POST /tasks and POST /tasks/{id}/complete: auth, validation, idempotency, and that
each write reaches the engine, the feed, and the git remote."""
from server.tests.conftest import AUTH, clone


def test_create_requires_auth(client):
    r = client.post("/tasks", json={"title": "x", "category": "phone"})
    assert r.status_code == 401


def test_create_task_appears_in_feed_and_remote(client, bare_remote, tmp_path):
    r = client.post("/tasks", json={"title": "Book MOT", "category": "errand"}, headers=AUTH)
    assert r.status_code == 201
    tid = r.json()["id"]
    assert r.json()["task"] == "Book MOT"

    feed = client.get("/feed", headers=AUTH).json()
    assert any(a["id"] == tid for a in feed["active"])

    pushed = clone(bare_remote, tmp_path / "verify")
    assert (pushed / "tasks" / f"{tid}.md").exists()


def test_create_rejects_bad_category(client):
    r = client.post("/tasks", json={"title": "x", "category": "nope"}, headers=AUTH)
    assert r.status_code == 400
    assert "category" in r.json()["error"]


def test_create_missing_title(client):
    r = client.post("/tasks", json={"category": "phone"}, headers=AUTH)
    assert r.status_code == 400


def test_create_is_idempotent_by_key(client):
    headers = {**AUTH, "Idempotency-Key": "key-abc"}
    first = client.post("/tasks", json={"title": "Once", "category": "admin"}, headers=headers)
    second = client.post("/tasks", json={"title": "Once", "category": "admin"}, headers=headers)
    assert first.json() == second.json()  # replayed, not re-created
    active = client.get("/feed", headers=AUTH).json()["active"]
    assert sum(1 for a in active if a["task"] == "Once") == 1


def test_complete_appends_one_event_and_is_idempotent(client):
    tid = client.post("/tasks", json={"title": "Pay rent", "category": "admin"},
                      headers=AUTH).json()["id"]
    r = client.post(f"/tasks/{tid}/complete",
                    json={"completed_at": "2026-06-20T08:00:00Z"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] == "2026-06-20T08:00:00Z"

    again = client.post(f"/tasks/{tid}/complete", json={}, headers=AUTH)
    assert again.status_code == 200
    assert again.json()["already_done"] is True

    events = client.get("/feed", headers=AUTH).json()["events"]
    assert sum(1 for e in events if e["task"] == "Pay rent") == 1  # exactly one event


def test_complete_unknown_task_404(client):
    r = client.post("/tasks/does-not-exist/complete", json={}, headers=AUTH)
    assert r.status_code == 404
    assert "does-not-exist" in r.json()["error"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest server/tests/test_api_writes.py -v`
Expected: FAIL — `404`/`405` (routes not defined) so the assertions fail (e.g. `test_create_task_appears_in_feed_and_remote` gets 404, not 201).

- [ ] **Step 3: Add the write endpoints to `create_app`**

In `server/app.py`, inside `create_app`, **after** the `get_feed` route and **before** `return app`, add:

```python
    def _read_json(request_body):
        return request_body if isinstance(request_body, dict) else {}

    def _idem_replay_or_run(idem_key, fn):
        if idem_key:
            prior = idem.get(idem_key)
            if prior is not None:
                return JSONResponse(status_code=prior["status_code"], content=prior["body"])
        status_code, body = fn()
        if idem_key:
            idem.put(idem_key, status_code, body)
        return JSONResponse(status_code=status_code, content=body)

    @app.post("/tasks")
    async def post_task(request: Request,
                        authorization: str = Header(default=""),
                        idempotency_key: str = Header(default="")):
        require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        title = data.get("title")
        category = data.get("category")
        if not title or not isinstance(title, str):
            raise HTTPException(status_code=400, detail="title is required")
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400,
                                detail=f"category must be one of {sorted(VALID_CATEGORIES)}")

        def run():
            with write_lock:
                tid = sidekick.create_task(title, category)
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: new {tid}",
                                         push=config.push, remote=config.remote)
                entry = next((a for a in sidekick.read_active() if a["id"] == tid), None)
            return 201, entry

        return _idem_replay_or_run(idempotency_key, run)

    @app.post("/tasks/{task_id}/complete")
    async def post_complete(task_id: str, request: Request,
                            authorization: str = Header(default=""),
                            idempotency_key: str = Header(default="")):
        require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        completed_at = data.get("completed_at")

        def run():
            with write_lock:
                try:
                    result = sidekick.complete(task_id, completed_at=completed_at)
                except FileNotFoundError:
                    raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: complete {task_id}",
                                         push=config.push, remote=config.remote)
            return 200, result

        return _idem_replay_or_run(idempotency_key, run)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest server/tests/test_api_writes.py -v`
Expected: PASS — 7 tests.

Then the full server suite:
Run: `pytest server/tests -v`
Expected: PASS — git_sync (3) + idempotency (3) + feed (2) + writes (7) = 15.

And the root suite stays green:
Run: `python3 -m unittest discover -s tests -v`
Expected: PASS — engine_api (4) + regenerate (2) + wiki (5).

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_writes.py
git commit -m "feat: POST /tasks and POST /tasks/{id}/complete (idempotent, git-published)

Adds the write endpoints: validate + create/complete through the engine under a write
lock, regenerate, then commit/push to the remote. Idempotency-Key replays cached
results; bad category/missing title -> 400; unknown task -> 404. complete() honors a
phone-supplied completed_at. The engine remains the sole ledger writer.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Task 6: Run + deploy documentation

**Files:**
- Create: `server/README.md`
- Modify: `README.md` (one-line pointer)

**Interfaces:** Documentation only — no tests. Verify by `grep`.

- [ ] **Step 1: Write `server/README.md`**

Create `server/README.md`:

````markdown
# Sidekick host API (phone app — Phase 1)

The always-on backbone of the phone app: a thin FastAPI wrapper over `sidekick.py`.
The engine stays the **sole, append-only writer of `ledger.jsonl`**; this service only
routes requests, enforces auth + idempotency, and publishes each change to git. The
vault (markdown + ledger) remains the source of truth; this host holds the canonical
working clone and the Mac syncs via the Obsidian Git plugin (Phase 4).

## Endpoints
All require `Authorization: Bearer <token>`. Mutations accept an `Idempotency-Key` header.

| Method | Path | Body | Result |
|---|---|---|---|
| GET  | `/feed` | — | `{ "events": [...], "active": [...] }` |
| POST | `/tasks` | `{ "title", "category" }` (`phone\|admin\|errand\|chore`) | `201` task entry |
| POST | `/tasks/{id}/complete` | `{ "completed_at"? }` (ISO) | `200` result |

Errors render as `{ "error": "<message>" }` (`401` no/bad token, `400` bad input,
`404` unknown task, `409`/`5xx` git/host trouble).

## Configuration (environment)
- `SIDEKICK_VAULT` (required) — path to the vault working clone on this host.
- `SIDEKICK_API_TOKEN` (required) — the bearer token the phone sends.
- `SIDEKICK_GIT_PUSH` (default `1`) — set `0` to commit locally without pushing (dev).
- `SIDEKICK_GIT_REMOTE` (default `origin`) — the canonical remote to publish to.

## Run locally
```bash
pip install -r server/requirements.txt
export SIDEKICK_VAULT=/path/to/vault
export SIDEKICK_API_TOKEN=$(openssl rand -hex 24)
# single worker: the write lock is per-process
uvicorn "server.app:create_app" --factory --host 127.0.0.1 --port 8000 --workers 1
```

## Deploy on a VPS (e.g. Hetzner)
The host stores **canonical data**, so it needs **persistent storage** (a VPS disk, or
a free tier with a real persistent volume — not ephemeral).

1. Clone the vault repo and set a commit identity (the engine commits as this user):
   ```bash
   git clone <canonical-remote-url> /srv/sidekick-vault
   git -C /srv/sidekick-vault config user.email "host@sidekick"
   git -C /srv/sidekick-vault config user.name  "Sidekick Host"
   ```
2. Install deps into a venv; set `SIDEKICK_VAULT=/srv/sidekick-vault` and a strong
   `SIDEKICK_API_TOKEN`.
3. Run uvicorn (single worker) under a process manager. Example `systemd` unit
   (`/etc/systemd/system/sidekick.service`):
   ```ini
   [Service]
   Environment=SIDEKICK_VAULT=/srv/sidekick-vault
   Environment=SIDEKICK_API_TOKEN=<your-token>
   WorkingDirectory=/srv/sidekick
   ExecStart=/srv/sidekick/.venv/bin/uvicorn server.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
   Restart=always
   [Install]
   WantedBy=multi-user.target
   ```
4. Terminate TLS with a reverse proxy. Example `Caddyfile` (auto Let's Encrypt):
   ```
   sidekick.example.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   The bearer token must only ever travel over HTTPS.

## Mac side (Phase 4, summary)
Install the **Obsidian Git** plugin in the vault, point it at the same canonical remote,
and enable auto pull + auto commit/push. `ledger.jsonl` uses a `union` merge driver
(`.gitattributes`) so the host's and the Mac's appends never conflict.

## Tests
```bash
pip install -r server/requirements.txt -r server/requirements-dev.txt
pytest server/tests -v
```
````

- [ ] **Step 2: Add a pointer from the root README**

In `README.md`, in the "Honest state & what's actually left" section, append this sentence to the final paragraph (the one ending "the map is done; the dials are the work."):

```markdown
The phone app's Phase 1 (an always-on host API over `sidekick.py`) lives in `server/` — see `server/README.md`; the SvelteKit PWA and the rest are later phases (`docs/superpowers/specs/2026-06-20-sidekick-phone-app-design.md`).
```

- [ ] **Step 3: Verify the docs**

```bash
grep -q "Sidekick host API" server/README.md && echo "OK: server README" || echo "FAIL"
grep -q "server/README.md" README.md && echo "OK: root pointer" || echo "FAIL"
python3 -m unittest discover -s tests -v && pytest server/tests -q
```

Expected: two `OK:` lines; root suite (11) and server suite (15) all green.

- [ ] **Step 4: Commit**

```bash
git add server/README.md README.md
git commit -m "docs: run + deploy guide for the host API; pointer from root README

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fs93yKz9sfGTgW7e4QRkpQ"
```

---

## Notes for the executor

- **Scope is Phase 1 only.** No SvelteKit/PWA, no offline outbox, no Capacitor, no nudge relocation, no Mac Obsidian-Git automation — those are later plans (spec §10). Don't build ahead.
- **`pip install` is required before the server tests run** (Task 2 Step 1 front-loads it). If a fresh subagent hits `ModuleNotFoundError: fastapi/httpx/pytest`, run `pip install -r server/requirements.txt -r server/requirements-dev.txt`.
- **Single worker is intentional** — the write lock is per-process; multiple workers would break write serialization. This is documented in `server/README.md`, not enforced in code.
- **The idempotency store is per-vault runtime state** and gitignored; it is not part of the vault's data.

## Self-Review (completed during authoring)

- **Spec coverage:** §5.1 engine wrapping + `complete(completed_at?)` + write discipline (lock/idempotency/regenerate/commit-push) → Tasks 1, 4, 5. §5.2 git union-merge + commit/pull-rebase/push → Task 2. §5.4 bearer auth + (TLS in deploy doc) → Tasks 4, 6. §7 API contract (all three endpoints, headers, status codes, error shape) → Tasks 4, 5. §8 edge cases (idempotent complete, unknown task 404, non-ff rebase retry, bad token 401) → Tasks 1, 2, 5 tests. §9 hosting/persistent storage → Task 6 doc. §11 testing strategy (throwaway vault + bare remote, idempotency, union-merge, auth) → all task tests. §12 integrity (engine sole writer; feed shape; derived scoring) → Global Constraints + Task 1/4. Phases 2-4 are explicitly out of scope.
- **Placeholder scan:** every code/edit/command step is concrete; no TBD/"handle errors"/"similar to".
- **Type consistency:** `configure`, `complete(task_id, completed_at=None) -> dict` (keys `id/task/category/status/completed_at/sat_for_hours/already_done`), `commit_and_push(repo, message, *, push, remote, retries) -> sha`, `IdempotencyStore.get/put`, `Config(vault, token, push, remote)`, `create_app(config)`, and the `{events, active}` feed shape are used identically across the tasks and their tests. Header params `authorization`/`idempotency_key` map to `Authorization`/`Idempotency-Key`.
