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
