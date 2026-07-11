"""Role/identity enforcement (spec sub-project 2). Two tokens — dalton (full) and
wife (shared) — hit the same app. The server is the security boundary; the PWA's
hiding is convenience."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Config

FULL = {"Authorization": "Bearer full-token"}
SHARED = {"Authorization": "Bearer shared-token"}


@pytest.fixture
def roles_client(vault_repo):
    cfg = Config(vault=str(vault_repo),
                 tokens={"full-token": {"name": "dalton", "role": "full"},
                         "shared-token": {"name": "wife", "role": "shared"}},
                 push=True, remote="origin")
    return TestClient(create_app(cfg))


def test_me_full(roles_client):
    r = roles_client.get("/me", headers=FULL)
    assert r.status_code == 200
    assert r.json() == {"name": "dalton", "role": "full"}


def test_me_shared(roles_client):
    r = roles_client.get("/me", headers=SHARED)
    assert r.status_code == 200
    assert r.json() == {"name": "wife", "role": "shared"}


def test_me_requires_auth(roles_client):
    r = roles_client.get("/me")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_me_rejects_unknown_token(roles_client):
    r = roles_client.get("/me", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def _new(client, headers, body):
    return client.post("/tasks", json=body, headers=headers)


def test_shared_post_is_forced_shared_and_from_wife(roles_client):
    # the body tries to lie about both fields — the server must ignore it
    r = _new(roles_client, SHARED,
             {"title": "Buy milk", "category": "chore", "shared": False, "from": "dalton"})
    assert r.status_code == 201
    assert r.json()["shared"] is True      # forced by role
    assert r.json()["from"] == "wife"      # identity, never client-supplied


def test_full_post_defaults_personal_and_from_dalton(roles_client):
    r = _new(roles_client, FULL, {"title": "File taxes", "category": "admin", "from": "wife"})
    assert r.status_code == 201
    assert r.json()["shared"] is False
    assert r.json()["from"] == "dalton"    # identity wins over the body


def test_full_post_can_opt_into_shared(roles_client):
    r = _new(roles_client, FULL, {"title": "Plan trip", "category": "admin", "shared": True})
    assert r.json()["shared"] is True
    assert r.json()["from"] == "dalton"


def test_shared_feed_only_shared_tasks_and_no_events(roles_client):
    _new(roles_client, FULL, {"title": "Personal thing", "category": "admin"})
    shared_id = _new(roles_client, SHARED,
                     {"title": "Buy milk", "category": "chore"}).json()["id"]
    done = _new(roles_client, FULL, {"title": "Old chore", "category": "chore"}).json()["id"]
    roles_client.post(f"/tasks/{done}/complete", json={}, headers=FULL)  # makes a ledger event

    feed = roles_client.get("/feed", headers=SHARED).json()
    assert feed["events"] == []                                  # no game feed for role shared
    assert [a["id"] for a in feed["active"]] == [shared_id]      # personal tasks never leak


def test_full_feed_unchanged(roles_client):
    _new(roles_client, FULL, {"title": "Personal thing", "category": "admin"})
    _new(roles_client, SHARED, {"title": "Buy milk", "category": "chore"})
    feed = roles_client.get("/feed", headers=FULL).json()
    assert len(feed["active"]) == 2        # full role sees everything


def test_shared_complete_404_on_personal_task(roles_client):
    tid = _new(roles_client, FULL, {"title": "Personal thing", "category": "admin"}).json()["id"]
    r = roles_client.post(f"/tasks/{tid}/complete", json={}, headers=SHARED)
    assert r.status_code == 404            # indistinguishable from a missing task
    feed = roles_client.get("/feed", headers=FULL).json()
    assert any(a["id"] == tid for a in feed["active"])   # and it was NOT completed


def test_shared_can_complete_shared_task(roles_client):
    tid = _new(roles_client, SHARED, {"title": "Buy milk", "category": "chore"}).json()["id"]
    r = roles_client.post(f"/tasks/{tid}/complete", json={}, headers=SHARED)
    assert r.status_code == 200
    assert r.json()["status"] == "done"


def test_shared_complete_unknown_task_404(roles_client):
    r = roles_client.post("/tasks/nope/complete", json={}, headers=SHARED)
    assert r.status_code == 404
