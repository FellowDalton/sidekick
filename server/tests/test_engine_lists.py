"""Engine: named-list registry (named-lists spec, 2026-07-19)."""
import pytest
import sidekick


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "tasks").mkdir(parents=True)
    (v / "ledger.jsonl").write_text("", encoding="utf-8")
    sidekick.configure(str(v))
    return v


def test_lists_empty_without_registry(vault):
    assert sidekick.read_lists() == []


def test_list_new_roundtrip_and_slug(vault):
    entry = sidekick.list_new("Ferie indkøb!")
    assert entry["id"] == "ferie-indkb"          # slug() strips non-word chars
    assert entry["name"] == "Ferie indkøb!"
    assert entry["created"]
    assert sidekick.read_lists() == [entry]


def test_list_new_rejects_reserved_and_collision(vault):
    with pytest.raises(ValueError):
        sidekick.list_new("To-dos")              # slugs to the reserved id "todos"... see impl
    sidekick.list_new("Groceries")
    with pytest.raises(ValueError):
        sidekick.list_new("groceries")           # same slug -> collision


def test_list_delete_refuses_while_open_tasks_remain(vault):
    sidekick.list_new("Groceries")
    tid = sidekick.create_task("Buy milk", "errand", list_="groceries")
    with pytest.raises(ValueError):
        sidekick.list_delete("groceries")
    sidekick.complete(tid)
    sidekick.list_delete("groceries")            # emptied -> allowed
    assert sidekick.read_lists() == []


def test_list_delete_unknown_raises(vault):
    with pytest.raises(ValueError):
        sidekick.list_delete("nope")


def test_create_task_validates_list(vault):
    with pytest.raises(ValueError):
        sidekick.create_task("Buy milk", "errand", list_="nope")
    sidekick.list_new("Groceries")
    tid = sidekick.create_task("Buy milk", "errand", list_="groceries")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert fm["list"] == "groceries"


def test_feed_exposes_list_field(vault):
    sidekick.list_new("Groceries")
    with_list = sidekick.create_task("Buy milk", "errand", list_="groceries")
    without = sidekick.create_task("Solo", "chore")
    by_id = {a["id"]: a for a in sidekick.read_active()}
    assert by_id[with_list]["list"] == "groceries"
    assert by_id[without]["list"] is None
