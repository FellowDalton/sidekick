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
            # leave no half-finished rebase behind, so the next attempt — and the
            # next request — starts from a clean working tree
            subprocess.run(["git", "rebase", "--abort"], cwd=repo,
                           capture_output=True, text=True)
    raise GitSyncError(f"push failed after {retries} retries: {last}")


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
