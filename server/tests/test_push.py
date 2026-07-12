"""Subscription store + web-push delivery. pywebpush is ALWAYS mocked (no network);
the store, 404/410 pruning, and identity routing are tested for real."""
import json

import pytest
from pywebpush import WebPushException

from server import push

SUB_A = {"endpoint": "https://push.example/a", "keys": {"p256dh": "pk-a", "auth": "au-a"}}
SUB_B = {"endpoint": "https://push.example/b", "keys": {"p256dh": "pk-b", "auth": "au-b"}}


@pytest.fixture
def vapid_env(monkeypatch):
    monkeypatch.setenv("SIDEKICK_VAPID_PRIVATE", "test-private-key")
    monkeypatch.setenv("SIDEKICK_VAPID_PUBLIC", "test-public-key")
    monkeypatch.setenv("SIDEKICK_VAPID_SUB", "mailto:test@sidekick.local")


def _config(vault_repo):
    from server.config import Config
    return Config(vault=str(vault_repo), token="test-token", push=False)


def _store(vault_repo):
    return json.loads((vault_repo / ".sidekick-push.json").read_text(encoding="utf-8"))


# ── the store ───────────────────────────────────────────────────────────────
def test_save_subscription_persists(vault_repo):
    assert push.save_subscription(str(vault_repo), "dalton", SUB_A) == 1
    assert _store(vault_repo) == {"dalton": [SUB_A]}


def test_resubscribe_same_endpoint_replaces(vault_repo):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    updated = dict(SUB_A, keys={"p256dh": "pk-new", "auth": "au-new"})
    assert push.save_subscription(str(vault_repo), "dalton", updated) == 1
    assert _store(vault_repo)["dalton"] == [updated]


def test_subscriptions_are_per_identity(vault_repo):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    push.save_subscription(str(vault_repo), "wife", SUB_B)
    data = _store(vault_repo)
    assert data["dalton"] == [SUB_A] and data["wife"] == [SUB_B]


# ── delivery ────────────────────────────────────────────────────────────────
def test_send_delivers_to_named_identity_only(vault_repo, vapid_env, monkeypatch):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    push.save_subscription(str(vault_repo), "wife", SUB_B)
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kw: sent.append(kw))
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 1
    assert len(sent) == 1
    assert sent[0]["subscription_info"] == SUB_A          # wife's endpoint never touched
    assert json.loads(sent[0]["data"]) == {"title": "T", "body": "B"}
    assert sent[0]["vapid_private_key"] == "test-private-key"
    assert sent[0]["vapid_claims"] == {"sub": "mailto:test@sidekick.local"}


def test_send_without_subscriptions_returns_zero(vault_repo, vapid_env, monkeypatch):
    monkeypatch.setattr(push, "webpush",
                        lambda **kw: pytest.fail("nothing to send to"))
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 0


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_send_prunes_gone_subscriptions(vault_repo, vapid_env, monkeypatch):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    push.save_subscription(str(vault_repo), "dalton", SUB_B)

    def fake(subscription_info, **kw):
        if subscription_info["endpoint"] == SUB_A["endpoint"]:
            raise WebPushException("gone", response=_Resp(410))

    monkeypatch.setattr(push, "webpush", fake)
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 1
    assert _store(vault_repo)["dalton"] == [SUB_B]


def test_send_keeps_subscription_on_transient_failure(vault_repo, vapid_env, monkeypatch):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)

    def fake(**kw):
        raise WebPushException("boom", response=_Resp(500))

    monkeypatch.setattr(push, "webpush", fake)
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 0
    assert _store(vault_repo)["dalton"] == [SUB_A]        # 500 is not "gone" — keep it


def test_send_unconfigured_raises(vault_repo, monkeypatch):
    monkeypatch.delenv("SIDEKICK_VAPID_PRIVATE", raising=False)
    monkeypatch.delenv("SIDEKICK_VAPID_SUB", raising=False)
    with pytest.raises(RuntimeError):
        push.send_to_identity(_config(vault_repo), "dalton", "T", "B")
