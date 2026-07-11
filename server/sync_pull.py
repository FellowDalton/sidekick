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
