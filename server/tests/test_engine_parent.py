"""Engine: parent/child task linkage (nested sub-tasks spec, 2026-07-19)."""
import pytest
import sidekick


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "tasks").mkdir(parents=True)
    (v / "ledger.jsonl").write_text("", encoding="utf-8")
    sidekick.configure(str(v))
    return v


def test_new_with_parent_writes_parent_frontmatter(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id)
    fm, _ = sidekick.read_note(sidekick.task_path(child_id))
    assert fm["parent"] == parent_id


def test_new_without_parent_writes_no_parent_field(vault):
    tid = sidekick.create_task("Solo task", "chore")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert "parent" not in fm


def test_new_with_missing_parent_fails(vault):
    with pytest.raises(ValueError):
        sidekick.create_task("Orphan", "chore", parent="20990101-nope")


def test_new_with_done_parent_fails(vault):
    parent_id = sidekick.create_task("Old task", "chore")
    sidekick.complete(parent_id)
    with pytest.raises(ValueError):
        sidekick.create_task("Too late", "chore", parent=parent_id)


def test_read_active_exposes_parent_and_status(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id)
    by_id = {a["id"]: a for a in sidekick.read_active()}
    assert by_id[parent_id]["parent"] is None
    assert by_id[parent_id]["status"] == "open"
    assert by_id[child_id]["parent"] == parent_id
    assert by_id[child_id]["status"] == "open"


def test_done_child_stays_in_feed_while_parent_open(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id, shared=True)
    sidekick.complete(child_id)
    by_id = {a["id"]: a for a in sidekick.read_active()}
    assert child_id in by_id
    assert by_id[child_id]["status"] == "done"
    assert by_id[child_id]["parent"] == parent_id
    assert by_id[child_id]["shared"] is True          # role filtering still works
    assert by_id[child_id]["completed_at"]            # ISO stamp present
    assert by_id[child_id]["plan"] is None


def test_done_child_leaves_feed_once_parent_done(vault):
    parent_id = sidekick.create_task("Plan the party", "chore")
    child_id = sidekick.create_task("Book the venue", "chore", parent=parent_id)
    sidekick.complete(child_id)
    sidekick.complete(parent_id)
    assert sidekick.read_active() == []


def test_done_task_without_parent_stays_out_of_feed(vault):
    tid = sidekick.create_task("Solo task", "chore")
    sidekick.complete(tid)
    assert sidekick.read_active() == []
