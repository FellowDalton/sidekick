"""Config token map (spec sub-project 2): SIDEKICK_API_TOKENS is a JSON map
token -> {name, role}; a lone legacy SIDEKICK_API_TOKEN (or `token` kwarg) still
works and maps to dalton/full. Invalid maps fail fast at startup."""
import json

import pytest

from server.config import Config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("SIDEKICK_API_TOKEN", raising=False)
    monkeypatch.delenv("SIDEKICK_API_TOKENS", raising=False)


def test_legacy_token_kwarg_maps_to_dalton_full(tmp_path):
    cfg = Config(vault=str(tmp_path), token="t-legacy")
    assert cfg.tokens == {"t-legacy": {"name": "dalton", "role": "full"}}


def test_tokens_kwarg_wins(tmp_path):
    tokens = {"t-d": {"name": "dalton", "role": "full"},
              "t-w": {"name": "wife", "role": "shared"}}
    cfg = Config(vault=str(tmp_path), tokens=tokens)
    assert cfg.tokens == tokens


def test_env_tokens_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDEKICK_API_TOKENS", json.dumps(
        {"t-w": {"name": "wife", "role": "shared"}}))
    cfg = Config(vault=str(tmp_path))
    assert cfg.tokens == {"t-w": {"name": "wife", "role": "shared"}}


def test_env_legacy_token_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "t-old")
    cfg = Config(vault=str(tmp_path))
    assert cfg.tokens == {"t-old": {"name": "dalton", "role": "full"}}


def test_no_tokens_at_all_raises(tmp_path):
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path))


def test_env_tokens_bad_json_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDEKICK_API_TOKENS", "{not json")
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path))


def test_bad_role_raises(tmp_path):
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path), tokens={"t": {"name": "x", "role": "admin"}})


def test_missing_name_raises(tmp_path):
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path), tokens={"t": {"role": "full"}})


def test_env_tokens_null_does_not_fall_back(tmp_path, monkeypatch):
    """SIDEKICK_API_TOKENS=null must not silently fall back to SIDEKICK_API_TOKEN."""
    monkeypatch.setenv("SIDEKICK_API_TOKENS", "null")
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "t-legacy")
    with pytest.raises(RuntimeError, match="must be a JSON object"):
        Config(vault=str(tmp_path))


def test_env_tokens_array_raises(tmp_path, monkeypatch):
    """SIDEKICK_API_TOKENS as array must raise, not fall back."""
    monkeypatch.setenv("SIDEKICK_API_TOKENS", "[1, 2, 3]")
    with pytest.raises(RuntimeError, match="must be a JSON object"):
        Config(vault=str(tmp_path))


def test_env_tokens_string_raises(tmp_path, monkeypatch):
    """SIDEKICK_API_TOKENS as string must raise, not fall back."""
    monkeypatch.setenv("SIDEKICK_API_TOKENS", '"abc"')
    with pytest.raises(RuntimeError, match="must be a JSON object"):
        Config(vault=str(tmp_path))


def test_env_tokens_number_raises(tmp_path, monkeypatch):
    """SIDEKICK_API_TOKENS as number must raise, not fall back."""
    monkeypatch.setenv("SIDEKICK_API_TOKENS", "123")
    with pytest.raises(RuntimeError, match="must be a JSON object"):
        Config(vault=str(tmp_path))
