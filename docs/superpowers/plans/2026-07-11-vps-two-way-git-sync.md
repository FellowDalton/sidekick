# VPS Two-Way Git Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The VPS's serving clone periodically pulls from GitHub (under the same lock as API writes), so pushes from the Mac, claude.ai/code, or the future agent reach the phones within minutes.

**Architecture:** A new inter-process file lock (`fcntl.flock` on `.git/sidekick-write.lock`) replaces the API's in-process `threading.Lock`; a new `sync_pull` module (run by a systemd timer every 3 minutes) takes that lock and runs `git pull --rebase`, aborting cleanly on conflict. Sub-project 1 of `docs/superpowers/specs/2026-07-10-sidekick-next-phase-design.md`.

**Tech Stack:** Python 3 stdlib (`fcntl`, `subprocess`, `contextlib`), FastAPI (existing), pytest (existing `server/tests/` fixtures), systemd oneshot service + timer.

## Global Constraints

- **No new Python dependencies** — `fcntl` and `contextlib` are stdlib. `server/requirements.txt` is untouched.
- **The engine stays the sole writer of the ledger** (spec: integrity rules). This plan only adds git *pull* mechanics; it never writes vault data.
- **The vault is never left mid-rebase** (spec: "pull-rebase conflicts on the VPS abort cleanly and are logged; the vault is never left mid-rebase").
- **Single uvicorn worker stays mandatory** (existing `deploy/sidekick.service` comment) — the file lock adds *inter-process* safety (API vs sync job); it does not make multi-worker safe (the idempotency store is still per-process).
- All commits run with the repo root as cwd; run tests with `python3 -m pytest server/tests/ -q` from the repo root.
- Existing test fixtures live in `server/tests/conftest.py` (`vault_repo`, `bare_remote`, `clone`, `git`, `AUTH`) — reuse them, don't reinvent.

## File Structure

```
server/vault_lock.py          NEW  inter-process vault write lock (context manager)
server/sync_pull.py           NEW  pull runner: config → lock → git_sync.pull_latest (CLI: python -m server.sync_pull)
server/git_sync.py            MOD  add pull_latest(repo, remote=...) beside commit_and_push
server/app.py                 MOD  swap threading.Lock → vault_lock
server/tests/test_vault_lock.py  NEW
server/tests/test_sync_pull.py   NEW  covers pull_latest + sync_pull.run
deploy/sidekick-sync.service  NEW  systemd oneshot
deploy/sidekick-sync.timer    NEW  every 3 min
deploy/README.md              MOD  install/enable instructions
```

---

### Task 1: Inter-process vault lock (`server/vault_lock.py`)

**Files:**
- Create: `server/vault_lock.py`
- Test: `server/tests/test_vault_lock.py`

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces: `vault_lock(vault: str)` — a context manager. Blocking exclusive acquire of `<vault>/.git/sidekick-write.lock`; releases on exit. Opens a **fresh fd per acquisition** so it excludes both other processes and other threads in the same process. Raises `FileNotFoundError` if `<vault>/.git` does not exist (a vault is always a git clone).

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_vault_lock.py`:

```python
"""The vault lock must be exclusive across independent acquisitions (each opens its
own fd, so this covers other processes AND other threads in this process)."""
import fcntl
import os

import pytest

from server.vault_lock import vault_lock, lock_path


def test_lock_excludes_second_acquisition(vault_repo):
    with vault_lock(str(vault_repo)):
        # simulate a second process: open our own fd and try a non-blocking flock
        fd = os.open(lock_path(str(vault_repo)), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)


def test_lock_released_on_exit(vault_repo):
    with vault_lock(str(vault_repo)):
        pass
    # after release a non-blocking acquire must succeed
    fd = os.open(lock_path(str(vault_repo)), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # must not raise
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_lock_released_on_exception(vault_repo):
    with pytest.raises(ValueError):
        with vault_lock(str(vault_repo)):
            raise ValueError("boom")
    fd = os.open(lock_path(str(vault_repo)), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # must not raise
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def test_lockfile_lives_inside_dot_git(vault_repo):
    # inside .git/ means `git add -A` can never stage it
    assert lock_path(str(vault_repo)) == str(vault_repo / ".git" / "sidekick-write.lock")


def test_missing_dot_git_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        with vault_lock(str(tmp_path / "not-a-repo")):
            pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_vault_lock.py -q`
Expected: 5 failures/errors with `ModuleNotFoundError: No module named 'server.vault_lock'`

- [ ] **Step 3: Write the implementation**

Create `server/vault_lock.py`:

```python
"""Inter-process write lock for the vault. The API process and the periodic sync
job must both hold this before mutating or pulling the serving clone, so a pull
never races a task write. Implemented as fcntl.flock on a file inside .git/
(never stageable by `git add -A`). A fresh fd per acquisition makes it exclusive
across threads in the same process too — flock locks belong to the open file
description, not the process."""
import fcntl
import os
from contextlib import contextmanager

_LOCK_NAME = "sidekick-write.lock"


def lock_path(vault):
    git_dir = os.path.join(vault, ".git")
    if not os.path.isdir(git_dir):
        raise FileNotFoundError(f"{vault} is not a git clone (no .git directory)")
    return os.path.join(git_dir, _LOCK_NAME)


@contextmanager
def vault_lock(vault):
    fd = os.open(lock_path(vault), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_vault_lock.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add server/vault_lock.py server/tests/test_vault_lock.py
git commit -m "server: inter-process vault write lock (flock in .git/)"
```

---

### Task 2: `git_sync.pull_latest`

**Files:**
- Modify: `server/git_sync.py` (append after `commit_and_push`, line 48)
- Test: `server/tests/test_sync_pull.py` (new file; Task 3 adds more tests to it)

**Interfaces:**
- Consumes: `_run(args, cwd)`, `current_branch(repo)`, `GitSyncError` — all already in `server/git_sync.py`.
- Produces: `pull_latest(repo: str, *, remote: str = "origin") -> str` — returns `"updated"` if HEAD moved, `"unchanged"` otherwise. On rebase conflict: aborts the rebase (tree left clean) and raises `GitSyncError`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_sync_pull.py`:

```python
"""pull_latest must bring remote commits into the serving clone, report whether
anything changed, and abort cleanly on conflict (never left mid-rebase)."""
import pytest
from pathlib import Path

from server import git_sync
from server.tests.conftest import git, clone


def _push_remote_task(bare_remote: Path, tmp_path: Path, name: str, content: str) -> Path:
    other = clone(bare_remote, tmp_path / f"other-{name}")
    (other / "tasks").mkdir(exist_ok=True)
    (other / "tasks" / name).write_text(content, encoding="utf-8")
    git(["add", "-A"], other)
    git(["commit", "-m", f"remote: {name}"], other)
    git(["push", "origin", "main"], other)
    return other


def test_pull_latest_brings_remote_changes(vault_repo, bare_remote, tmp_path):
    _push_remote_task(bare_remote, tmp_path, "from-cloud.md", "researched\n")
    assert git_sync.pull_latest(str(vault_repo)) == "updated"
    assert (vault_repo / "tasks" / "from-cloud.md").read_text(encoding="utf-8") == "researched\n"


def test_pull_latest_reports_unchanged(vault_repo):
    assert git_sync.pull_latest(str(vault_repo)) == "unchanged"


def test_pull_latest_conflict_aborts_clean(vault_repo, bare_remote, tmp_path):
    # remote and local commit DIFFERENT content to the SAME file → rebase conflict
    _push_remote_task(bare_remote, tmp_path, "x.md", "remote content\n")
    (vault_repo / "tasks" / "x.md").write_text("local content\n", encoding="utf-8")
    git(["add", "-A"], vault_repo)
    git(["commit", "-m", "local x"], vault_repo)

    with pytest.raises(git_sync.GitSyncError):
        git_sync.pull_latest(str(vault_repo))

    assert not (vault_repo / ".git" / "rebase-merge").exists()
    assert not (vault_repo / ".git" / "rebase-apply").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_sync_pull.py -q`
Expected: 3 failures with `AttributeError: module 'server.git_sync' has no attribute 'pull_latest'`

- [ ] **Step 3: Write the implementation**

Append to `server/git_sync.py`:

```python
def pull_latest(repo, *, remote="origin"):
    """Bring the clone up to date with the remote (the periodic-sync half of the
    two-way flow; commit_and_push is the publish half). Returns "updated" if HEAD
    moved, "unchanged" otherwise. On rebase conflict the rebase is aborted — the
    tree is never left mid-rebase — and GitSyncError propagates to the caller."""
    branch = current_branch(repo)
    before = _run(["rev-parse", "HEAD"], repo)
    try:
        _run(["pull", "--rebase", remote, branch], repo)
    except GitSyncError:
        subprocess.run(["git", "rebase", "--abort"], cwd=repo,
                       capture_output=True, text=True)
        raise
    after = _run(["rev-parse", "HEAD"], repo)
    return "updated" if after != before else "unchanged"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_sync_pull.py -q`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add server/git_sync.py server/tests/test_sync_pull.py
git commit -m "server: git_sync.pull_latest — rebase pull with clean abort"
```

---

### Task 3: Sync runner (`server/sync_pull.py`)

**Files:**
- Create: `server/sync_pull.py`
- Test: `server/tests/test_sync_pull.py` (append to the file from Task 2)

**Interfaces:**
- Consumes: `Config` / `load_config()` from `server/config.py` (fields: `vault`, `token`, `push`, `remote`); `vault_lock(vault)` from Task 1; `git_sync.pull_latest(repo, remote=...)` from Task 2.
- Produces: `run(config=None) -> str` returning `"disabled" | "updated" | "unchanged"` (raises `GitSyncError` on conflict); `main() -> int` CLI entrypoint (0 on success, 1 on error) so systemd can run `python -m server.sync_pull`.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_sync_pull.py`:

```python
def _config(vault_repo, **kw):
    from server.config import Config
    kw.setdefault("push", True)
    return Config(vault=str(vault_repo), token="test-token", **kw)


def test_run_pulls_under_config(vault_repo, bare_remote, tmp_path):
    from server import sync_pull
    _push_remote_task(bare_remote, tmp_path, "from-phone.md", "captured\n")
    assert sync_pull.run(_config(vault_repo)) == "updated"
    assert (vault_repo / "tasks" / "from-phone.md").exists()


def test_run_disabled_when_push_off(vault_repo):
    # push=False marks a dev/offline instance: no remote to track, so no pull either
    from server import sync_pull
    assert sync_pull.run(_config(vault_repo, push=False)) == "disabled"


def test_run_takes_the_vault_lock(vault_repo, bare_remote, tmp_path, monkeypatch):
    """While run() is inside pull_latest, the vault lock must be held."""
    import fcntl, os
    from server import sync_pull, git_sync
    from server.vault_lock import lock_path

    _push_remote_task(bare_remote, tmp_path, "locked.md", "x\n")
    real_pull = git_sync.pull_latest
    seen = {}

    def spying_pull(repo, *, remote="origin"):
        fd = os.open(lock_path(str(vault_repo)), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            seen["locked"] = False          # acquired → run() was NOT holding it
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            seen["locked"] = True           # blocked → run() holds the lock. Good.
        finally:
            os.close(fd)
        return real_pull(repo, remote=remote)

    monkeypatch.setattr(sync_pull.git_sync, "pull_latest", spying_pull)
    sync_pull.run(_config(vault_repo))
    assert seen["locked"] is True


def test_main_exit_codes(vault_repo, bare_remote, tmp_path, monkeypatch, capsys):
    from server import sync_pull
    monkeypatch.setenv("SIDEKICK_VAULT", str(vault_repo))
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "test-token")

    _push_remote_task(bare_remote, tmp_path, "ok.md", "y\n")
    assert sync_pull.main() == 0
    assert "updated" in capsys.readouterr().out

    # force a conflict → exit 1, error on stderr
    _push_remote_task(bare_remote, tmp_path, "boom.md", "remote\n")
    (vault_repo / "tasks" / "boom.md").write_text("local\n", encoding="utf-8")
    git(["add", "-A"], vault_repo)
    git(["commit", "-m", "local boom"], vault_repo)
    assert sync_pull.main() == 1
    assert "sync-pull" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_sync_pull.py -q`
Expected: 3 passed (Task 2's), 4 failures with `ModuleNotFoundError: No module named 'server.sync_pull'` (or `ImportError` inside the tests)

- [ ] **Step 3: Write the implementation**

Create `server/sync_pull.py`:

```python
"""Periodic pull for the serving clone — the systemd-timer half of two-way sync.
The API publishes on every write (commit_and_push); this job brings in everything
pushed from elsewhere (Mac, claude.ai/code, the agent) between writes. It holds
the same inter-process vault lock as the API, so a pull never races a task write.
Deterministic; no model logic."""
import sys

from server import git_sync
from server.config import load_config
from server.vault_lock import vault_lock


def run(config=None):
    """Pull the vault up to date. Returns "disabled", "updated" or "unchanged";
    raises git_sync.GitSyncError on conflict (after a clean rebase --abort)."""
    config = config or load_config()
    if not config.push:
        # push=False marks a dev/offline instance: no remote to track, so no pull
        return "disabled"
    with vault_lock(config.vault):
        return git_sync.pull_latest(config.vault, remote=config.remote)


def main():
    try:
        result = run()
    except Exception as e:
        print(f"sync-pull: {e}", file=sys.stderr)
        return 1
    print(f"sync-pull: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_sync_pull.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add server/sync_pull.py server/tests/test_sync_pull.py
git commit -m "server: sync_pull runner — periodic pull under the vault lock"
```

---

### Task 4: API writes take the inter-process lock

**Files:**
- Modify: `server/app.py` (lines 3, 7, 26, 31, 81, 103)

**Interfaces:**
- Consumes: `vault_lock(vault)` from Task 1.
- Produces: no new interface — `create_app(config)` behaves identically from the outside; `app.state.write_lock` is **removed** (nothing references it — verified by grep).

- [ ] **Step 1: Run the full existing suite first (baseline)**

Run: `python3 -m pytest server/tests/ -q`
Expected: all pass (25 tests: 18 pre-existing + 5 from Task 1 + baseline of this file's growth — count may read `30 passed` after Tasks 1–3; the point is zero failures)

- [ ] **Step 2: Make the swap**

In `server/app.py`:

Line 7 — delete `import threading`.

Line 17 area — add the import after the `IdempotencyStore` import:

```python
from server.idempotency import IdempotencyStore  # noqa: E402
from server.vault_lock import vault_lock  # noqa: E402
```

Line 26 — delete `write_lock = threading.Lock()`.

Line 31 — delete `app.state.write_lock = write_lock`.

Lines 81 and 103 — replace both occurrences of

```python
            with write_lock:
```

with

```python
            with vault_lock(config.vault):
```

Line 3 of the module docstring — update the sentence `Mutations are serialized by a write lock — run with a single worker.` to:

```
Mutations are serialized by an inter-process vault lock (shared with the periodic
sync job — see server/sync_pull.py); still run with a single worker (the
idempotency store is per-process).
```

- [ ] **Step 3: Run the full suite to verify nothing broke**

Run: `python3 -m pytest server/tests/ -q`
Expected: same count as Step 1, `0 failed`

- [ ] **Step 4: Commit**

```bash
git add server/app.py
git commit -m "server: API writes hold the inter-process vault lock"
```

---

### Task 5: systemd units + deploy docs

**Files:**
- Create: `deploy/sidekick-sync.service`
- Create: `deploy/sidekick-sync.timer`
- Modify: `deploy/README.md` (add an "Enable the sync timer" section after the existing service-install instructions)

**Interfaces:**
- Consumes: `python -m server.sync_pull` CLI from Task 3; `/etc/sidekick.env` and the `/srv/sidekick` layout already established by `deploy/sidekick.service`.
- Produces: two unit files an operator copies to `/etc/systemd/system/` (documented commands below).

- [ ] **Step 1: Write the service unit**

Create `deploy/sidekick-sync.service`:

```ini
[Unit]
Description=Sidekick vault sync (git pull --rebase under the write lock)
Documentation=https://github.com/FellowDalton/sidekick/blob/main/deploy/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=sidekick
Group=sidekick
WorkingDirectory=/srv/sidekick
EnvironmentFile=/etc/sidekick.env
ExecStart=/srv/sidekick/.venv/bin/python -m server.sync_pull
# Same hardening posture as sidekick.service: only its own clone.
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true
```

- [ ] **Step 2: Write the timer unit**

Create `deploy/sidekick-sync.timer`:

```ini
[Unit]
Description=Run sidekick vault sync every 3 minutes

[Timer]
OnCalendar=*:0/3
RandomizedDelaySec=15
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Document install in `deploy/README.md`**

Append this section (adjust placement to sit with the other systemd instructions):

```markdown
## Enable the sync timer (two-way sync)

The API publishes on every write, but only the timer brings in commits pushed
from elsewhere (the Mac, claude.ai/code, the agent). On the VPS:

    sudo cp deploy/sidekick-sync.service deploy/sidekick-sync.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sidekick-sync.timer

Verify:

    systemctl list-timers sidekick-sync.timer     # next run scheduled
    sudo systemctl start sidekick-sync.service    # run once now
    journalctl -u sidekick-sync.service -n 5      # expect "sync-pull: updated|unchanged"

A conflicting pull exits 1 with the vault left clean (rebase aborted); check
`journalctl -u sidekick-sync.service` if the phones stop seeing Mac-side changes.
```

- [ ] **Step 4: Sanity-check the units parse (no systemd on macOS — visual check + full test suite)**

Run: `python3 -m pytest server/tests/ -q && python3 -m pytest tests/ -q`
Expected: all pass (server suite + the 11 root vault tests, untouched)

- [ ] **Step 5: Commit**

```bash
git add deploy/sidekick-sync.service deploy/sidekick-sync.timer deploy/README.md
git commit -m "deploy: sidekick-sync timer — periodic vault pull on the VPS"
```

---

## Deployment note (manual ops, after merge)

**Deferred from spec:** "alert via nudger channel if pull conflicts persist" needs the web-push nudger (sub-project 4). Until then the signal is `journalctl -u sidekick-sync.service` + exit code 1. Add the alert when sub-project 4 lands.

Not part of the code tasks: pull `main` on the VPS (`sudo -u sidekick git -C /srv/sidekick pull`), then run the README's "Enable the sync timer" commands, then `sudo systemctl restart sidekick` so the API picks up the vault-lock change. End-to-end check: push a trivial commit from the Mac, wait ≤3 min, confirm it appears via `GET /feed` on the phone.
