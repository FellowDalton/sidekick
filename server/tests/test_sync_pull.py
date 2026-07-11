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
