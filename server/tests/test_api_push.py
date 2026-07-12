"""/push endpoints: subscribe stores under the calling token's identity (never
client-chosen); the public-key endpoint spares the client hardcoding VAPID."""
import json

from server.tests.conftest import AUTH

SUB = {"endpoint": "https://push.example/x", "keys": {"p256dh": "pk", "auth": "au"}}


def test_subscribe_stores_for_token_identity(client, vault_repo):
    r = client.post("/push/subscribe", headers=AUTH, json=SUB)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "subscriptions": 1}
    data = json.loads((vault_repo / ".sidekick-push.json").read_text(encoding="utf-8"))
    assert data["dalton"] == [SUB]


def test_subscribe_requires_auth(client):
    assert client.post("/push/subscribe", json=SUB).status_code == 401


def test_subscribe_rejects_malformed_body(client):
    r = client.post("/push/subscribe", headers=AUTH, json={"nope": 1})
    assert r.status_code == 400


def test_shared_role_may_subscribe(vault_repo):
    # the store/API stays general; ROUTING (nobody sends to wife this phase)
    # lives in the nudge job, not here
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server.config import Config
    cfg = Config(vault=str(vault_repo),
                 tokens={"wife-token": {"name": "wife", "role": "shared"}}, push=False)
    c = TestClient(create_app(cfg))
    r = c.post("/push/subscribe", headers={"Authorization": "Bearer wife-token"}, json=SUB)
    assert r.status_code == 200
    data = json.loads((vault_repo / ".sidekick-push.json").read_text(encoding="utf-8"))
    assert data["wife"] == [SUB]


def test_vapid_public_key(client, monkeypatch):
    monkeypatch.setenv("SIDEKICK_VAPID_PUBLIC", "pubkey-123")
    r = client.get("/push/vapid-public-key", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"key": "pubkey-123"}


def test_vapid_public_key_unconfigured_is_503(client, monkeypatch):
    monkeypatch.delenv("SIDEKICK_VAPID_PUBLIC", raising=False)
    assert client.get("/push/vapid-public-key", headers=AUTH).status_code == 503


def test_vapid_public_key_requires_auth(client):
    assert client.get("/push/vapid-public-key").status_code == 401


def test_subscribe_rejects_oversized_endpoint(client, vault_repo):
    oversized = SUB.copy()
    oversized["endpoint"] = "https://push.example/" + "x" * 5000
    r = client.post("/push/subscribe", headers=AUTH, json=oversized)
    assert r.status_code == 400
    assert r.json() == {"error": "subscription field too large"}
    # verify nothing was stored
    push_file = vault_repo / ".sidekick-push.json"
    if push_file.exists():
        data = json.loads(push_file.read_text(encoding="utf-8"))
        assert "dalton" not in data or data["dalton"] == []


def test_subscribe_rejects_oversized_p256dh(client, vault_repo):
    oversized = SUB.copy()
    oversized["keys"] = SUB["keys"].copy()
    oversized["keys"]["p256dh"] = "pk" * 200  # exceeds 256 char limit
    r = client.post("/push/subscribe", headers=AUTH, json=oversized)
    assert r.status_code == 400
    assert r.json() == {"error": "subscription field too large"}
    # verify nothing was stored
    push_file = vault_repo / ".sidekick-push.json"
    if push_file.exists():
        data = json.loads(push_file.read_text(encoding="utf-8"))
        assert "dalton" not in data or data["dalton"] == []


def test_subscribe_rejects_oversized_auth(client, vault_repo):
    oversized = SUB.copy()
    oversized["keys"] = SUB["keys"].copy()
    oversized["keys"]["auth"] = "au" * 50  # exceeds 64 char limit
    r = client.post("/push/subscribe", headers=AUTH, json=oversized)
    assert r.status_code == 400
    assert r.json() == {"error": "subscription field too large"}
    # verify nothing was stored
    push_file = vault_repo / ".sidekick-push.json"
    if push_file.exists():
        data = json.loads(push_file.read_text(encoding="utf-8"))
        assert "dalton" not in data or data["dalton"] == []


def test_subscribe_rejects_non_string_p256dh(client, vault_repo):
    bad = SUB.copy()
    bad["keys"] = SUB["keys"].copy()
    bad["keys"]["p256dh"] = 12345
    r = client.post("/push/subscribe", headers=AUTH, json=bad)
    assert r.status_code == 400
    assert r.json() == {"error": "a PushSubscription JSON (endpoint + keys) is required"}
    push_file = vault_repo / ".sidekick-push.json"
    if push_file.exists():
        data = json.loads(push_file.read_text(encoding="utf-8"))
        assert "dalton" not in data or data["dalton"] == []


def test_subscribe_rejects_non_string_auth(client, vault_repo):
    bad = SUB.copy()
    bad["keys"] = SUB["keys"].copy()
    bad["keys"]["auth"] = True
    r = client.post("/push/subscribe", headers=AUTH, json=bad)
    assert r.status_code == 400
    assert r.json() == {"error": "a PushSubscription JSON (endpoint + keys) is required"}
    push_file = vault_repo / ".sidekick-push.json"
    if push_file.exists():
        data = json.loads(push_file.read_text(encoding="utf-8"))
        assert "dalton" not in data or data["dalton"] == []


def test_subscribe_rejects_non_https_endpoint(client, vault_repo):
    bad = SUB.copy()
    bad["endpoint"] = "http://push.example/x"
    r = client.post("/push/subscribe", headers=AUTH, json=bad)
    assert r.status_code == 400
    assert r.json() == {"error": "a PushSubscription JSON (endpoint + keys) is required"}
    push_file = vault_repo / ".sidekick-push.json"
    if push_file.exists():
        data = json.loads(push_file.read_text(encoding="utf-8"))
        assert "dalton" not in data or data["dalton"] == []
