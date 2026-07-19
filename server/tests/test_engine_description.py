"""Engine: task descriptions (task-descriptions spec, 2026-07-19)."""
import pytest
import sidekick


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    (v / "tasks").mkdir(parents=True)
    (v / "ledger.jsonl").write_text("", encoding="utf-8")
    sidekick.configure(str(v))
    return v


def test_create_with_description(vault):
    tid = sidekick.create_task("Buy paint", "errand", description="Matte white,\ntwo cans")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert fm["description"] == "Matte white,\ntwo cans"


def test_create_strips_and_omits_empty_description(vault):
    tid = sidekick.create_task("Buy paint", "errand", description="   \n  ")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert "description" not in fm


def test_set_description_sets_replaces_and_clears(vault):
    tid = sidekick.create_task("Buy paint", "errand")
    sidekick.set_description(tid, "First version")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert fm["description"] == "First version"
    sidekick.set_description(tid, "Second version")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert fm["description"] == "Second version"
    sidekick.set_description(tid, "   ")
    fm, _ = sidekick.read_note(sidekick.task_path(tid))
    assert "description" not in fm


def test_set_description_missing_or_done_task_raises(vault):
    with pytest.raises(ValueError):
        sidekick.set_description("20990101-nope", "text")
    tid = sidekick.create_task("Old", "chore")
    sidekick.complete(tid)
    with pytest.raises(ValueError):
        sidekick.set_description(tid, "text")


def test_feed_exposes_description(vault):
    with_d = sidekick.create_task("Buy paint", "errand", description="Matte white")
    without = sidekick.create_task("Solo", "chore")
    by_id = {a["id"]: a for a in sidekick.read_active()}
    assert by_id[with_d]["description"] == "Matte white"
    assert by_id[without]["description"] is None
