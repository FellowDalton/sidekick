"""git_sync.commit_and_push must publish local changes and absorb a concurrent remote
push via union-merge on the ledger (no conflict, both events survive)."""
import pytest
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


def test_nonledger_conflict_leaves_repo_clean(vault_repo, bare_remote, tmp_path):
    # two clones write DIFFERENT content to the SAME task file (task files are not union-merged)
    other = clone(bare_remote, tmp_path / "other")
    (other / "tasks").mkdir(exist_ok=True)
    (other / "tasks" / "x.md").write_text("remote content\n", encoding="utf-8")
    git(["add", "-A"], other)
    git(["commit", "-m", "remote task"], other)
    git(["push", "origin", "main"], other)

    (vault_repo / "tasks" / "x.md").write_text("local content\n", encoding="utf-8")
    with pytest.raises(git_sync.GitSyncError):
        git_sync.commit_and_push(str(vault_repo), "local task")

    # the failed rebase must have been aborted — repo not left mid-rebase
    assert not (vault_repo / ".git" / "rebase-merge").exists()
    assert not (vault_repo / ".git" / "rebase-apply").exists()
