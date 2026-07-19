"""Task-description endpoints (task-descriptions spec, 2026-07-19)."""
import pytest
from fastapi.testclient import TestClient

import sidekick
from server.app import create_app
from server.config import Config
from server.tests.conftest import AUTH

FULL = {"Authorization": "Bearer full-token"}
SHARED = {"Authorization": "Bearer shared-token"}


def _mk(client, title="Buy paint", **extra):
    body = {"title": title, "category": "errand", **extra}
    r = client.post("/tasks", headers=AUTH, json=body)
    assert r.status_code == 201
    return r.json()


def test_create_task_with_description(client):
    entry = _mk(client, description="Matte white,\ntwo cans")
    assert entry["description"] == "Matte white,\ntwo cans"


def test_create_task_description_validation(client):
    r = client.post("/tasks", headers=AUTH,
                    json={"title": "X", "category": "errand", "description": 5})
    assert r.status_code == 400
    r = client.post("/tasks", headers=AUTH,
                    json={"title": "X", "category": "errand", "description": "y" * 4001})
    assert r.status_code == 400


def test_describe_sets_and_clears(client):
    entry = _mk(client)
    r = client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                    json={"description": "Two cans"})
    assert r.status_code == 200
    assert r.json()["description"] == "Two cans"
    r = client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                    json={"description": "  "})
    assert r.status_code == 200
    assert r.json()["description"] is None


def test_describe_errors(client, app_config):
    assert client.post("/tasks/20990101-nope/description", headers=AUTH,
                       json={"description": "x"}).status_code == 404
    entry = _mk(client)
    assert client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                       json={}).status_code == 400
    assert client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                       json={"description": "y" * 4001}).status_code == 400
    sidekick.configure(app_config.vault)
    sidekick.complete(entry["id"])
    assert client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                       json={"description": "x"}).status_code == 409


@pytest.fixture
def roles_client(vault_repo):
    cfg = Config(vault=str(vault_repo),
                 tokens={"full-token": {"name": "dalton", "role": "full"},
                         "shared-token": {"name": "wife", "role": "shared"}},
                 push=True, remote="origin")
    return TestClient(create_app(cfg))


def test_shared_describe_404_on_personal_task(roles_client):
    tid = roles_client.post("/tasks", json={"title": "Personal thing", "category": "admin"},
                           headers=FULL).json()["id"]
    r = roles_client.post(f"/tasks/{tid}/description", json={"description": "x"}, headers=SHARED)
    assert r.status_code == 404            # indistinguishable from a missing task


def test_shared_can_describe_shared_task(roles_client):
    tid = roles_client.post("/tasks", json={"title": "Buy milk", "category": "chore"},
                           headers=SHARED).json()["id"]
    r = roles_client.post(f"/tasks/{tid}/description", json={"description": "Two gallons"},
                         headers=SHARED)
    assert r.status_code == 200
    assert r.json()["description"] == "Two gallons"
