"""Agent endpoints (spec sub-project 3). POST enqueues; the server is the
security boundary: research is full-role only, role `shared` touches only
shared tasks, and a personal task is indistinguishable from a missing one."""
import time

import pytest
from fastapi.testclient import TestClient

from server.agent_jobs import AgentJobs, load_jobs
from server.app import create_app
from server.config import Config
from server.tests.conftest import clone

FULL = {"Authorization": "Bearer full-token"}
SHARED = {"Authorization": "Bearer shared-token"}

TOKENS = {"full-token": {"name": "dalton", "role": "full"},
          "shared-token": {"name": "wife", "role": "shared"}}


@pytest.fixture
def agent_api(vault_repo, agent_clone, monkeypatch):
    """Client with the runner configured but the worker OFF — enqueued jobs stay
    queued, so status assertions are deterministic. Execution is covered by
    test_agent_jobs.py and the end-to-end test below."""
    monkeypatch.setenv("SIDEKICK_AGENT_CLONE", str(agent_clone))
    cfg = Config(vault=str(vault_repo), tokens=TOKENS, push=True, remote="origin")
    jobs = AgentJobs(str(vault_repo), start_worker=False)
    return TestClient(create_app(cfg, agent_jobs=jobs))


def _new(client, headers, title="Fix the bike", category="errand", shared=False):
    body = {"title": title, "category": category}
    if shared:
        body["shared"] = True
    return client.post("/tasks", json=body, headers=headers).json()["id"]


def test_post_agent_enqueues_research(agent_api):
    tid = _new(agent_api, FULL)
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 202
    job = r.json()
    assert job["task_id"] == tid
    assert job["action"] == "research"
    assert job["status"] == "queued"
    assert len(job["id"]) == 32


def test_post_agent_invalid_action_400(agent_api):
    tid = _new(agent_api, FULL)
    for body in ({"action": "explode"}, {}, None):
        r = agent_api.post(f"/tasks/{tid}/agent", json=body, headers=FULL)
        assert r.status_code == 400


def test_post_agent_unknown_task_404(agent_api):
    r = agent_api.post("/tasks/nope/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 404
    assert r.json() == {"error": "no such task: nope"}


def test_post_agent_done_task_409(agent_api):
    tid = _new(agent_api, FULL)
    agent_api.post(f"/tasks/{tid}/complete", json={}, headers=FULL)
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 409


def test_shared_role_research_403_on_visible_task(agent_api, vault_repo):
    # a task she CAN see (it's shared) — research is still full-role only,
    # so the 403 fires, but only AFTER visibility is established
    tid = _new(agent_api, SHARED, title="Buy milk", category="chore")
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=SHARED)
    assert r.status_code == 403
    assert load_jobs(str(vault_repo)) == []           # nothing enqueued


def test_shared_role_breakdown_personal_task_404(agent_api, vault_repo):
    tid = _new(agent_api, FULL)                       # personal task
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "breakdown"}, headers=SHARED)
    assert r.status_code == 404                       # indistinguishable from missing
    assert load_jobs(str(vault_repo)) == []


def test_shared_role_research_personal_task_404_matches_missing(agent_api, vault_repo):
    # a personal task (created with the FULL token, no shared flag) must be
    # indistinguishable from a missing one — the 404 must fire BEFORE the
    # role/action 403, even though `research` would also be forbidden for her
    tid = _new(agent_api, FULL)                       # personal task
    r_personal = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"},
                                headers=SHARED)
    r_missing = agent_api.post("/tasks/nope-nope/agent", json={"action": "research"},
                               headers=SHARED)
    assert r_personal.status_code == r_missing.status_code == 404
    assert r_personal.json() == {"error": f"no such task: {tid}"}
    assert r_missing.json() == {"error": "no such task: nope-nope"}
    assert load_jobs(str(vault_repo)) == []


def test_shared_role_research_missing_task_404(agent_api, vault_repo):
    r = agent_api.post("/tasks/nope/agent", json={"action": "research"}, headers=SHARED)
    assert r.status_code == 404
    assert r.json() == {"error": "no such task: nope"}
    assert load_jobs(str(vault_repo)) == []


def test_shared_role_breakdown_shared_task_202(agent_api):
    tid = _new(agent_api, SHARED, title="Buy milk", category="chore")
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "breakdown"}, headers=SHARED)
    assert r.status_code == 202
    assert r.json()["shared"] is True


def test_full_role_breakdown_202(agent_api):
    tid = _new(agent_api, FULL)
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "breakdown"}, headers=FULL)
    assert r.status_code == 202


def test_post_agent_unconfigured_503(agent_api, monkeypatch):
    tid = _new(agent_api, FULL)
    monkeypatch.delenv("SIDEKICK_AGENT_CLONE")
    r = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"}, headers=FULL)
    assert r.status_code == 503
    assert r.json() == {"error": "agent runner not configured"}


def test_post_agent_idempotency_replays_the_same_job(agent_api, vault_repo):
    tid = _new(agent_api, FULL)
    key = {"Idempotency-Key": "agent-key-1"}
    r1 = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"},
                        headers={**FULL, **key})
    r2 = agent_api.post(f"/tasks/{tid}/agent", json={"action": "research"},
                        headers={**FULL, **key})
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["id"] == r2.json()["id"]
    assert len(load_jobs(str(vault_repo))) == 1       # one job, not two


def test_post_agent_requires_auth(agent_api):
    r = agent_api.post("/tasks/x/agent", json={"action": "research"})
    assert r.status_code == 401
