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
