"""Inter-process write lock for the vault. The API process and the periodic sync
job must both hold this before mutating or pulling the serving clone, so a pull
never races a task write. Implemented as fcntl.flock on a file inside .git/
(never stageable by `git add -A`). A fresh fd per acquisition makes it exclusive
across threads in the same process too — flock locks belong to the open file
description, not the process."""
import fcntl
import os
from contextlib import contextmanager

_LOCK_NAME = "sidekick-write.lock"


def lock_path(vault):
    git_dir = os.path.join(vault, ".git")
    if not os.path.isdir(git_dir):
        raise FileNotFoundError(f"{vault} is not a git clone (no .git directory)")
    return os.path.join(git_dir, _LOCK_NAME)


@contextmanager
def vault_lock(vault):
    fd = os.open(lock_path(vault), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
