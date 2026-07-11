"""Role/identity enforcement (spec sub-project 2). Two tokens — dalton (full) and
wife (shared) — hit the same app. The server is the security boundary; the PWA's
hiding is convenience."""
import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Config

FULL = {"Authorization": "Bearer full-token"}
SHARED = {"Authorization": "Bearer shared-token"}


@pytest.fixture
def roles_client(vault_repo):
    cfg = Config(vault=str(vault_repo),
                 tokens={"full-token": {"name": "dalton", "role": "full"},
                         "shared-token": {"name": "wife", "role": "shared"}},
                 push=True, remote="origin")
    return TestClient(create_app(cfg))


def test_me_full(roles_client):
    r = roles_client.get("/me", headers=FULL)
    assert r.status_code == 200
    assert r.json() == {"name": "dalton", "role": "full"}


def test_me_shared(roles_client):
    r = roles_client.get("/me", headers=SHARED)
    assert r.status_code == 200
    assert r.json() == {"name": "wife", "role": "shared"}


def test_me_requires_auth(roles_client):
    r = roles_client.get("/me")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_me_rejects_unknown_token(roles_client):
    r = roles_client.get("/me", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401
