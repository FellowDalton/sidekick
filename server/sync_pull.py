"""Periodic pull for the serving clone — the systemd-timer half of two-way sync.
The API publishes on every write (commit_and_push); this job brings in everything
pushed from elsewhere (Mac, claude.ai/code, the agent) between writes. It holds
the same inter-process vault lock as the API, so a pull never races a task write.
Deterministic; no model logic. Repeated failures alert Dalton over web push
(server.push) — once per streak, on the ALERT_AFTER-th consecutive failure; the
streak file lives inside .git/ so `git add -A` can never stage it."""
import os
import sys

from server import git_sync, push
from server.config import load_config
from server.vault_lock import vault_lock

ALERT_AFTER = 3          # consecutive failures before the one push alert
ALERT_IDENTITY = "dalton"


def run(config=None):
    """Pull the vault up to date. Returns "disabled", "updated" or "unchanged";
    raises git_sync.GitSyncError on conflict (after a clean rebase --abort)."""
    config = config or load_config()
    if not config.push:
        # push=False marks a dev/offline instance: no remote to track, so no pull
        return "disabled"
    with vault_lock(config.vault):
        return git_sync.pull_latest(config.vault, remote=config.remote)


def _streak_path(vault):
    return os.path.join(vault, ".git", "sidekick-sync-failures")


def _read_streak(vault):
    try:
        with open(_streak_path(vault), encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError, OSError):
        return 0


def _note_success(config):
    try:
        os.unlink(_streak_path(config.vault))
    except OSError:
        pass


def _note_failure(config, exc):
    """Count consecutive failures; on the ALERT_AFTER-th, alert Dalton via web
    push. Best-effort only — an alert problem must never mask the sync failure."""
    streak = _read_streak(config.vault) + 1
    try:
        with open(_streak_path(config.vault), "w", encoding="utf-8") as f:
            f.write(str(streak))
    except OSError:
        return
    if streak == ALERT_AFTER:
        try:
            push.send_to_identity(config, ALERT_IDENTITY, "Sidekick sync failing",
                                  f"git pull has failed {streak}x in a row: {exc}")
        except Exception as e:
            print(f"sync-pull: alert failed ({e})", file=sys.stderr)


def main():
    try:
        config = load_config()
    except Exception as e:
        print(f"sync-pull: {e}", file=sys.stderr)
        return 1
    try:
        result = run(config)
    except Exception as e:
        print(f"sync-pull: {e}", file=sys.stderr)
        _note_failure(config, e)
        return 1
    _note_success(config)
    print(f"sync-pull: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
