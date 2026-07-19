"""Named-list endpoints (named-lists spec, 2026-07-19)."""
import sidekick

from server.tests.conftest import AUTH


def test_post_list_creates_and_feed_exposes(client, app_config):
    r = client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    assert r.status_code == 201
    entry = r.json()
    assert entry["id"] == "groceries" and entry["name"] == "Groceries"
    feed = client.get("/feed", headers=AUTH).json()
    assert feed["lists"] == [entry]


def test_post_list_validates_name(client):
    assert client.post("/lists", headers=AUTH, json={}).status_code == 400
    assert client.post("/lists", headers=AUTH, json={"name": "x" * 61}).status_code == 400
    assert client.post("/lists", headers=AUTH, json={"name": "To-dos"}).status_code == 400


def test_post_list_collision_409(client):
    client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    assert client.post("/lists", headers=AUTH, json={"name": "groceries"}).status_code == 409


def test_delete_list_paths(client, app_config):
    client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    sidekick.configure(app_config.vault)
    tid = sidekick.create_task("Buy milk", "errand", list_="groceries")
    assert client.delete("/lists/groceries", headers=AUTH).status_code == 409
    sidekick.complete(tid)
    assert client.delete("/lists/groceries", headers=AUTH).status_code == 200
    assert client.delete("/lists/groceries", headers=AUTH).status_code == 404
    assert client.delete("/lists/todos", headers=AUTH).status_code == 404


def test_post_task_with_list(client, app_config):
    client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    r = client.post("/tasks", headers=AUTH,
                    json={"title": "Buy milk", "category": "errand", "list": "groceries"})
    assert r.status_code == 201
    assert r.json()["list"] == "groceries"
    bad = client.post("/tasks", headers=AUTH,
                      json={"title": "Buy milk", "category": "errand", "list": "nope"})
    assert bad.status_code == 400
