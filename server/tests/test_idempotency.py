"""IdempotencyStore persists request results keyed by Idempotency-Key, so a retried
request replays instead of re-applying. Survives restart; tolerates a corrupt file."""
from server.idempotency import IdempotencyStore


def test_put_then_get(tmp_path):
    s = IdempotencyStore(str(tmp_path / "idem.json"))
    assert s.get("k1") is None
    s.put("k1", 201, {"id": "x"})
    assert s.get("k1") == {"status_code": 201, "body": {"id": "x"}}


def test_persists_across_instances(tmp_path):
    path = str(tmp_path / "idem.json")
    IdempotencyStore(path).put("k2", 200, {"ok": True})
    assert IdempotencyStore(path).get("k2") == {"status_code": 200, "body": {"ok": True}}


def test_corrupt_file_degrades_to_empty(tmp_path):
    path = tmp_path / "idem.json"
    path.write_text("{not valid json", encoding="utf-8")
    s = IdempotencyStore(str(path))
    assert s.get("anything") is None  # no crash
    s.put("k3", 200, {"ok": 1})       # still usable
    assert s.get("k3") == {"status_code": 200, "body": {"ok": 1}}
