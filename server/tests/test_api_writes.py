"""POST /tasks and POST /tasks/{id}/complete: auth, validation, idempotency, and that
each write reaches the engine, the feed, and the git remote."""
from server.tests.conftest import AUTH, clone


def test_create_requires_auth(client):
    r = client.post("/tasks", json={"title": "x", "category": "phone"})
    assert r.status_code == 401


def test_create_task_appears_in_feed_and_remote(client, bare_remote, tmp_path):
    r = client.post("/tasks", json={"title": "Book MOT", "category": "errand"}, headers=AUTH)
    assert r.status_code == 201
    tid = r.json()["id"]
    assert r.json()["task"] == "Book MOT"

    feed = client.get("/feed", headers=AUTH).json()
    assert any(a["id"] == tid for a in feed["active"])

    pushed = clone(bare_remote, tmp_path / "verify")
    assert (pushed / "tasks" / f"{tid}.md").exists()


def test_create_rejects_bad_category(client):
    r = client.post("/tasks", json={"title": "x", "category": "nope"}, headers=AUTH)
    assert r.status_code == 400
    assert "category" in r.json()["error"]


def test_create_missing_title(client):
    r = client.post("/tasks", json={"category": "phone"}, headers=AUTH)
    assert r.status_code == 400


def test_create_is_idempotent_by_key(client):
    headers = {**AUTH, "Idempotency-Key": "key-abc"}
    first = client.post("/tasks", json={"title": "Once", "category": "admin"}, headers=headers)
    second = client.post("/tasks", json={"title": "Once", "category": "admin"}, headers=headers)
    assert first.json() == second.json()  # replayed, not re-created
    active = client.get("/feed", headers=AUTH).json()["active"]
    assert sum(1 for a in active if a["task"] == "Once") == 1


def test_complete_appends_one_event_and_is_idempotent(client):
    tid = client.post("/tasks", json={"title": "Pay rent", "category": "admin"},
                      headers=AUTH).json()["id"]
    r = client.post(f"/tasks/{tid}/complete",
                    json={"completed_at": "2026-06-20T08:00:00Z"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["status"] == "done"
    assert r.json()["completed_at"] == "2026-06-20T08:00:00Z"

    again = client.post(f"/tasks/{tid}/complete", json={}, headers=AUTH)
    assert again.status_code == 200
    assert again.json()["already_done"] is True

    events = client.get("/feed", headers=AUTH).json()["events"]
    assert sum(1 for e in events if e["task"] == "Pay rent") == 1  # exactly one event


def test_complete_unknown_task_404(client):
    r = client.post("/tasks/does-not-exist/complete", json={}, headers=AUTH)
    assert r.status_code == 404
    assert "does-not-exist" in r.json()["error"]


def test_complete_idempotency_key_replays(client):
    tid = client.post("/tasks", json={"title": "Water plants", "category": "chore"},
                      headers=AUTH).json()["id"]
    headers = {**AUTH, "Idempotency-Key": "complete-key-1"}
    first = client.post(f"/tasks/{tid}/complete",
                        json={"completed_at": "2026-06-20T07:00:00Z"}, headers=headers)
    # same key, DIFFERENT body -> must replay the first response, not re-apply
    second = client.post(f"/tasks/{tid}/complete",
                         json={"completed_at": "2026-06-20T23:00:00Z"}, headers=headers)
    assert second.status_code == first.status_code
    assert second.json() == first.json()
    assert second.json()["completed_at"] == "2026-06-20T07:00:00Z"  # replayed, not the 23:00 retry
    events = client.get("/feed", headers=AUTH).json()["events"]
    assert sum(1 for e in events if e["task"] == "Water plants") == 1  # exactly one event
