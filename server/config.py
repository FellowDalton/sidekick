"""Host server configuration. Values come from explicit kwargs (tests) or the
environment (production). vault + at least one API token are required.

Tokens (spec sub-project 2): SIDEKICK_API_TOKENS is a JSON map
    {"<token>": {"name": "dalton", "role": "full"},
     "<token2>": {"name": "wife", "role": "shared"}}
Backward compatible: a lone SIDEKICK_API_TOKEN (or the legacy `token` kwarg)
maps to {"name": "dalton", "role": "full"}. Explicit kwargs beat the environment."""
import json
import os

_FALSEY = ("0", "false", "False", "")
_ROLES = ("full", "shared")


def _legacy_map(token):
    return {token: {"name": "dalton", "role": "full"}}


class Config:
    def __init__(self, vault=None, token=None, tokens=None, push=None, remote=None):
        self.vault = vault if vault is not None else os.environ.get("SIDEKICK_VAULT")
        if push is not None:
            self.push = push
        else:
            self.push = os.environ.get("SIDEKICK_GIT_PUSH", "1") not in _FALSEY
        self.remote = remote if remote is not None else os.environ.get("SIDEKICK_GIT_REMOTE", "origin")
        if not self.vault:
            raise RuntimeError("SIDEKICK_VAULT is required")

        # token map — explicit kwargs (tests) beat the environment (production)
        if tokens is None and token is not None:
            tokens = _legacy_map(token)
        if tokens is None:
            raw = os.environ.get("SIDEKICK_API_TOKENS")
            if raw:
                try:
                    tokens = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"SIDEKICK_API_TOKENS is not valid JSON: {e}")
        if tokens is None:
            legacy = os.environ.get("SIDEKICK_API_TOKEN")
            if legacy:
                tokens = _legacy_map(legacy)
        if not tokens or not isinstance(tokens, dict):
            raise RuntimeError("SIDEKICK_API_TOKENS (or SIDEKICK_API_TOKEN) is required")
        for tok, ident in tokens.items():
            if (not isinstance(ident, dict) or not ident.get("name")
                    or ident.get("role") not in _ROLES):
                raise RuntimeError(
                    'SIDEKICK_API_TOKENS entries must be {"name": "...", "role": "full"|"shared"}'
                    f" (bad entry for token ending ...{str(tok)[-4:]})")
        self.tokens = tokens


def load_config():
    return Config()
