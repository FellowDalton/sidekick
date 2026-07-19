"""GET /feed requires auth and returns the {events, active} read-model."""
import sidekick

from server.tests.conftest import AUTH


def test_feed_requires_auth(client):
    r = client.get("/feed")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_feed_returns_events_and_active(client, app_config):
    # seed one open task directly through the engine (already pointed at the vault)
    sidekick.configure(app_config.vault)
    sidekick.create_task("Sweep the garage", "chore")
    r = client.get("/feed", headers=AUTH)
    assert r.status_code == 200
    payload = r.json()
    assert set(payload.keys()) == {"events", "active", "lists"}
    assert any(a["task"] == "Sweep the garage" for a in payload["active"])
    assert payload["events"] == []


def test_feed_shared_role_sees_done_shared_child(client, app_config):
    """A completed shared sub-task stays visible to both roles while its parent is open."""
    sidekick.configure(app_config.vault)
    parent_id = sidekick.create_task("Plan the party", "chore", shared=True)
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id, shared=True)
    sidekick.complete(child_id)
    r = client.get("/feed", headers=AUTH)
    assert r.status_code == 200
    by_id = {a["id"]: a for a in r.json()["active"]}
    assert by_id[child_id]["status"] == "done"
    assert by_id[child_id]["parent"] == parent_id
