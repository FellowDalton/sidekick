"""The agent job store: gitignored runtime state in the vault root (like the
idempotency and push stores). Restart safety: queued/running records are marked
failed ("interrupted by restart") — the queue lives in memory, so no job can
survive its process."""
from server import agent_jobs


def _job(i="j1", status="queued", shared=False):
    return {"id": i, "task_id": "t-" + i, "action": "research", "title": "T",
            "category": "admin", "shared": shared, "requested_by": "dalton",
            "status": status, "created_at": "2026-07-12T00:00:00Z",
            "started_at": None, "finished_at": None,
            "summary": None, "error": None, "log_tail": None}


def test_load_missing_store_is_empty(tmp_path):
    assert agent_jobs.load_jobs(str(tmp_path)) == []


def test_load_corrupt_store_is_empty(tmp_path):
    (tmp_path / agent_jobs.STORE_NAME).write_text("{not json", encoding="utf-8")
    assert agent_jobs.load_jobs(str(tmp_path)) == []


def test_save_load_roundtrip_caps_to_newest(tmp_path):
    jobs = [_job(f"j{i}") for i in range(agent_jobs.STORE_CAP + 5)]
    agent_jobs.save_jobs(str(tmp_path), jobs)
    kept = agent_jobs.load_jobs(str(tmp_path))
    assert len(kept) == agent_jobs.STORE_CAP
    assert kept[-1]["id"] == f"j{agent_jobs.STORE_CAP + 4}"   # newest survive


def test_mark_interrupted_fails_unfinished_jobs_only(tmp_path):
    agent_jobs.save_jobs(str(tmp_path), [_job("a", "queued"), _job("b", "running"),
                                         _job("c", "done"), _job("d", "failed")])
    assert agent_jobs.mark_interrupted(str(tmp_path)) == 2
    by_id = {j["id"]: j for j in agent_jobs.load_jobs(str(tmp_path))}
    assert by_id["a"]["status"] == "failed"
    assert by_id["a"]["error"] == "interrupted by restart"
    assert by_id["a"]["finished_at"] is not None
    assert by_id["b"]["status"] == "failed"
    assert by_id["c"]["status"] == "done"        # finished records untouched
    assert by_id["d"]["error"] is None
