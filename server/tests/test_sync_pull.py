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
