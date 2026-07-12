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


@pytest.fixture
def app_config(vault_repo):
    from server.config import Config
    return Config(vault=str(vault_repo), token="test-token", push=True, remote="origin")


@pytest.fixture
def client(app_config):
    from fastapi.testclient import TestClient
    from server.app import create_app
    return TestClient(create_app(app_config))


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


AUTH = {"Authorization": "Bearer test-token"}
