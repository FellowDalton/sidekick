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
