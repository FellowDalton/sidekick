"""Host server configuration. Values come from explicit kwargs (tests) or the
environment (production). vault + token are required."""
import os

_FALSEY = ("0", "false", "False", "")


class Config:
    def __init__(self, vault=None, token=None, push=None, remote=None):
        self.vault = vault if vault is not None else os.environ.get("SIDEKICK_VAULT")
        self.token = token if token is not None else os.environ.get("SIDEKICK_API_TOKEN")
        if push is not None:
            self.push = push
        else:
            self.push = os.environ.get("SIDEKICK_GIT_PUSH", "1") not in _FALSEY
        self.remote = remote if remote is not None else os.environ.get("SIDEKICK_GIT_REMOTE", "origin")
        if not self.vault:
            raise RuntimeError("SIDEKICK_VAULT is required")
        if not self.token:
            raise RuntimeError("SIDEKICK_API_TOKEN is required")


def load_config():
    return Config()
