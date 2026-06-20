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
    assert set(payload.keys()) == {"events", "active"}
    assert any(a["task"] == "Sweep the garage" for a in payload["active"])
    assert payload["events"] == []
