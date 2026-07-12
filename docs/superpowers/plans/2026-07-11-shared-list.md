# Shared List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second bearer token with role `shared` lets Dalton's wife use exactly one thing — a plain shared checkbox list (add box on top, tick to complete) at `/shared` in the existing PWA — while Dalton's role `full` keeps the whole app and gains the same Shared page. Enforcement is server-side on every endpoint; the UI's hiding/redirects are convenience only.

**Architecture:** `SIDEKICK_API_TOKENS` (JSON map token → `{name, role}`) replaces the single-token config, with the lone legacy `SIDEKICK_API_TOKEN` still accepted (mapped to `dalton`/`full`). `require_auth` returns the identity; a new `GET /me` lets the PWA route by role. The engine (`sidekick.py`) learns two optional frontmatter fields — `from:` (creator, always server-assigned) and `shared: true` (shared-list membership) — and surfaces both in `read_active`, which is all the API needs to filter the feed and gate completes. Sub-project 2 of `docs/superpowers/specs/2026-07-10-sidekick-next-phase-design.md`.

**Tech Stack:** Python 3 stdlib (`json`) + FastAPI (existing) + pytest (`server/tests/` fixtures); stdlib `unittest` in `tests/` for the engine; SvelteKit 5 + Vitest + @testing-library/svelte in `web/` (existing patterns).

## Global Constraints

- **No new Python dependencies** (`json` is stdlib) and **no new npm dependencies**. `server/requirements.txt` and `web/package.json` deps are untouched.
- **The engine stays the sole writer of the ledger and task files.** The API mutates only through `sidekick.py` calls inside `with vault_lock(config.vault):` — exactly as today.
- **`from` is ALWAYS server-assigned** from the token identity. A client-supplied `from` in a request body is ignored, for both roles.
- **Role enforcement is the security boundary** (spec: "UI hiding is convenience; the API enforcement above is the security boundary"). Role `shared` must never see personal task data or ledger events; a personal task's id must be indistinguishable from a missing one (same 404).
- **Backward compatible:** a deployment with only `SIDEKICK_API_TOKEN` set keeps working unchanged (it maps to `{"name": "dalton", "role": "full"}`); the existing PWA token flow is untouched for role `full`.
- **Single uvicorn worker stays mandatory** (idempotency store is per-process; unchanged).
- **Excluded from this plan:** the "break it down" agent button and all agent endpoints (sub-project 3); `via`/`note` ledger fields (sub-project 5). The `/shared` page is exactly: add box, checkbox list, tick-to-complete.
- Test commands (run from the repo root):
  - server: `python3 -m pytest server/tests/ -q`
  - engine (stdlib-unittest files, collected by pytest): `python3 -m pytest tests/ -q`
  - web: `npm --prefix web test` (the `test` script is `vitest run`; equivalent to `cd web && npm test`)
- Later tasks consume exactly the names earlier tasks produce — do not rename `create_task(..., from_=, shared=)`, `Config.tokens`, `require_auth`'s identity dict, `getMe`/`Identity`, `identity`/`loadIdentity`/`resetIdentity`.

## File Structure

```
sidekick.py                            MOD  create_task(from_=, shared=), read_active surfaces both, `new` CLI flags
tests/test_shared_frontmatter.py       NEW  engine tests (stdlib unittest)
server/config.py                       MOD  tokens map (SIDEKICK_API_TOKENS, legacy fallback)
server/tests/test_config_tokens.py     NEW
server/app.py                          MOD  require_auth → identity, GET /me, role enforcement
server/tests/test_api_roles.py         NEW  /me + enforcement (two-token client)
web/src/lib/types.ts                   MOD  ActiveTask.from / .shared
web/src/lib/api.ts                     MOD  Identity + getMe, shared-aware createTask
web/src/lib/api.test.ts                MOD  getMe + shared-body tests
web/src/lib/role.ts                    NEW  identity store + loadIdentity/resetIdentity
web/src/lib/role.test.ts               NEW
web/src/routes/shared/+page.svelte     NEW  add box + checkbox list, tick = complete
web/src/routes/shared/shared.test.ts   NEW
web/src/routes/+layout.svelte          MOD  role-aware nav + shared-role redirect
web/src/routes/layout.test.ts          NEW
web/e2e/app.spec.ts                    MOD  mock /api/me (full role) so e2e stays green
server/README.md                       MOD  /me row + SIDEKICK_API_TOKENS docs
web/README.md                          MOD  shared-page one-liner
CLAUDE.md                              MOD  frontmatter one-liner (from/shared)
```

---

### Task 1: Engine frontmatter — `from:` and `shared:` (`sidekick.py`)

**Files:**
- Modify: `sidekick.py` (`create_task` line 110, `read_active` line 160, `new` parser + dispatch lines 283/292–293)
- Test: `tests/test_shared_frontmatter.py` (new)

**Interfaces:**
- Consumes: existing `write_note`, `read_note`, `task_path`, `now_iso`, `slug`.
- Produces: `create_task(title, category, *, from_=None, shared=False)` — writes `from:` and `shared: true` frontmatter keys **only when set** (absent = personal; defaults produce byte-identical files to today). `read_active()` entries gain `"from"` (str or None) and `"shared"` (bool, always present). CLI: `sidekick.py new` gains `--from` (dest `from_`) and `--shared`. `regenerate` needs no change — it serializes `read_active()` as-is.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_shared_frontmatter.py`:

```python
"""Shared-list frontmatter (spec sub-project 2): create_task can stamp `from:` and
`shared: true`; read_active surfaces both so the API can enforce roles. Defaults are
unchanged — a plain create writes neither key (absent = personal)."""
import tempfile, unittest
from pathlib import Path

import sidekick


class SharedFrontmatter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "tasks").mkdir()
        (self.vault / "ledger.jsonl").write_text("", encoding="utf-8")
        sidekick.configure(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_create_stays_personal(self):
        tid = sidekick.create_task("Buy milk", "errand")
        fm, _ = sidekick.read_note(sidekick.task_path(tid))
        self.assertNotIn("from", fm)
        self.assertNotIn("shared", fm)

    def test_create_writes_from_and_shared(self):
        tid = sidekick.create_task("Buy milk", "errand", from_="wife", shared=True)
        fm, _ = sidekick.read_note(sidekick.task_path(tid))
        self.assertEqual(fm["from"], "wife")
        self.assertIs(fm["shared"], True)

    def test_read_active_surfaces_the_fields(self):
        shared = sidekick.create_task("Buy milk", "errand", from_="wife", shared=True)
        personal = sidekick.create_task("File taxes", "admin")
        by_id = {a["id"]: a for a in sidekick.read_active()}
        self.assertEqual(by_id[shared]["from"], "wife")
        self.assertIs(by_id[shared]["shared"], True)
        self.assertIsNone(by_id[personal]["from"])
        self.assertIs(by_id[personal]["shared"], False)

    def test_complete_still_works_on_shared_tasks(self):
        tid = sidekick.create_task("Buy milk", "errand", from_="wife", shared=True)
        res = sidekick.complete(tid)
        self.assertEqual(res["status"], "done")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_shared_frontmatter.py -q`
Expected: `3 failed, 1 passed` — the three kwarg-using tests fail with `TypeError: create_task() got an unexpected keyword argument 'from_'`; `test_default_create_stays_personal` passes already (it is the regression guard that defaults don't change).

- [ ] **Step 3: Write the implementation**

In `sidekick.py`, replace `create_task` (line 110):

```python
def create_task(title, category, *, from_=None, shared=False):
    """Create an open task. `from_` (dalton|wife|sidekick) and `shared` are the
    shared-list frontmatter fields (spec sub-project 2) — written only when set,
    so a plain create produces the same file as before."""
    os.makedirs(TASKS, exist_ok=True)
    task_id = dt.datetime.now().strftime("%Y%m%d") + "-" + slug(title)
    n, base = 2, task_id
    while os.path.exists(task_path(task_id)):
        task_id = f"{base}-{n}"; n += 1
    fm = {"category": category, "created": now_iso(), "status": "open"}
    if from_:
        fm["from"] = from_
    if shared:
        fm["shared"] = True
    write_note(task_path(task_id), fm, f"# {title}\n")
    print(f"created {task_id}")
    return task_id
```

In `read_active` (line 171), replace the `active.append({...})` call with:

```python
        active.append({
            "id": name[:-3],
            "task": title,
            "category": fm.get("category"),
            "sat_for_hours": hours_since(fm.get("created")),
            "plan": fm.get("plan"),
            "from": fm.get("from"),
            "shared": bool(fm.get("shared")),
        })
```

In `main()`, replace the `new` parser line (line 283):

```python
    pn = sub.add_parser("new");      pn.add_argument("title"); pn.add_argument("--category", required=True)
    pn.add_argument("--from", dest="from_", default=None, help="who created it (dalton|wife|sidekick)")
    pn.add_argument("--shared", action="store_true", help="put it on the shared list")
```

and the `new` dispatch (lines 292–293):

```python
    elif a.cmd == "new":
        create_task(a.title, a.category, from_=a.from_, shared=a.shared); regenerate()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/ -q`
Expected: all pass, `0 failed` (the 4 new tests plus every pre-existing engine test — `read_active`'s two extra keys are additive).

Also run: `python3 -m pytest server/tests/ -q`
Expected: all pass (the server calls `create_task(title, category)` positionally; defaults keep it working).

- [ ] **Step 5: Commit**

```bash
git add sidekick.py tests/test_shared_frontmatter.py
git commit -m "engine: optional from/shared task frontmatter (shared list SP2)"
```

---

### Task 2: Config token map (`SIDEKICK_API_TOKENS`)

**Files:**
- Modify: `server/config.py` (full rewrite below)
- Modify: `server/app.py` (`require_auth`, line 41–43 — mechanical swap so the suite stays green; identity comes in Task 3)
- Test: `server/tests/test_config_tokens.py` (new)

**Interfaces:**
- Consumes: env `SIDEKICK_API_TOKENS` (JSON map `{"<token>": {"name": str, "role": "full"|"shared"}}`), env `SIDEKICK_API_TOKEN` (legacy), existing `token=` kwarg (legacy, used by every existing test fixture).
- Produces: `Config.tokens` — a validated dict token → `{"name", "role"}`. Precedence: `tokens=` kwarg > `token=` kwarg (legacy-mapped) > env `SIDEKICK_API_TOKENS` > env `SIDEKICK_API_TOKEN` (legacy-mapped). Explicit kwargs beat the environment, as today. `Config.token` attribute is **removed** (its only consumer, `require_auth`, is updated in the same task; verified by grep — nothing else reads it).

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_config_tokens.py`:

```python
"""Config token map (spec sub-project 2): SIDEKICK_API_TOKENS is a JSON map
token -> {name, role}; a lone legacy SIDEKICK_API_TOKEN (or `token` kwarg) still
works and maps to dalton/full. Invalid maps fail fast at startup."""
import json

import pytest

from server.config import Config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("SIDEKICK_API_TOKEN", raising=False)
    monkeypatch.delenv("SIDEKICK_API_TOKENS", raising=False)


def test_legacy_token_kwarg_maps_to_dalton_full(tmp_path):
    cfg = Config(vault=str(tmp_path), token="t-legacy")
    assert cfg.tokens == {"t-legacy": {"name": "dalton", "role": "full"}}


def test_tokens_kwarg_wins(tmp_path):
    tokens = {"t-d": {"name": "dalton", "role": "full"},
              "t-w": {"name": "wife", "role": "shared"}}
    cfg = Config(vault=str(tmp_path), tokens=tokens)
    assert cfg.tokens == tokens


def test_env_tokens_json(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDEKICK_API_TOKENS", json.dumps(
        {"t-w": {"name": "wife", "role": "shared"}}))
    cfg = Config(vault=str(tmp_path))
    assert cfg.tokens == {"t-w": {"name": "wife", "role": "shared"}}


def test_env_legacy_token_still_works(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "t-old")
    cfg = Config(vault=str(tmp_path))
    assert cfg.tokens == {"t-old": {"name": "dalton", "role": "full"}}


def test_no_tokens_at_all_raises(tmp_path):
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path))


def test_env_tokens_bad_json_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDEKICK_API_TOKENS", "{not json")
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path))


def test_bad_role_raises(tmp_path):
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path), tokens={"t": {"name": "x", "role": "admin"}})


def test_missing_name_raises(tmp_path):
    with pytest.raises(RuntimeError):
        Config(vault=str(tmp_path), tokens={"t": {"role": "full"}})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_config_tokens.py -q`
Expected: `6 failed, 2 passed` — `tokens=` is an unexpected kwarg (`TypeError`) and `cfg.tokens` doesn't exist (`AttributeError`); `test_no_tokens_at_all_raises` and `test_env_tokens_bad_json_raises` pass pre-change for the wrong reason (the legacy "SIDEKICK_API_TOKEN is required" error).

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `server/config.py` with:

```python
"""Host server configuration. Values come from explicit kwargs (tests) or the
environment (production). vault + at least one API token are required.

Tokens (spec sub-project 2): SIDEKICK_API_TOKENS is a JSON map
    {"<token>": {"name": "dalton", "role": "full"},
     "<token2>": {"name": "wife", "role": "shared"}}
Backward compatible: a lone SIDEKICK_API_TOKEN (or the legacy `token` kwarg)
maps to {"name": "dalton", "role": "full"}. Explicit kwargs beat the environment."""
import json
import os

_FALSEY = ("0", "false", "False", "")
_ROLES = ("full", "shared")


def _legacy_map(token):
    return {token: {"name": "dalton", "role": "full"}}


class Config:
    def __init__(self, vault=None, token=None, tokens=None, push=None, remote=None):
        self.vault = vault if vault is not None else os.environ.get("SIDEKICK_VAULT")
        if push is not None:
            self.push = push
        else:
            self.push = os.environ.get("SIDEKICK_GIT_PUSH", "1") not in _FALSEY
        self.remote = remote if remote is not None else os.environ.get("SIDEKICK_GIT_REMOTE", "origin")
        if not self.vault:
            raise RuntimeError("SIDEKICK_VAULT is required")

        # token map — explicit kwargs (tests) beat the environment (production)
        if tokens is None and token is not None:
            tokens = _legacy_map(token)
        if tokens is None:
            raw = os.environ.get("SIDEKICK_API_TOKENS")
            if raw:
                try:
                    tokens = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"SIDEKICK_API_TOKENS is not valid JSON: {e}")
        if tokens is None:
            legacy = os.environ.get("SIDEKICK_API_TOKEN")
            if legacy:
                tokens = _legacy_map(legacy)
        if not tokens or not isinstance(tokens, dict):
            raise RuntimeError("SIDEKICK_API_TOKENS (or SIDEKICK_API_TOKEN) is required")
        for tok, ident in tokens.items():
            if (not isinstance(ident, dict) or not ident.get("name")
                    or ident.get("role") not in _ROLES):
                raise RuntimeError(
                    'SIDEKICK_API_TOKENS entries must be {"name": "...", "role": "full"|"shared"}'
                    f" (bad entry for token ending ...{str(tok)[-4:]})")
        self.tokens = tokens


def load_config():
    return Config()
```

In `server/app.py`, replace `require_auth` (lines 41–43):

```python
    def require_auth(authorization):
        if not (authorization.startswith("Bearer ")
                and authorization[len("Bearer "):] in config.tokens):
            raise HTTPException(status_code=401, detail="unauthorized")
```

(`config.token` no longer exists; this membership check keeps every existing endpoint and test green. Task 3 upgrades it to return the identity.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/ -q`
Expected: all pass, `0 failed` (8 new config tests; every existing fixture builds `Config(..., token="test-token", ...)`, which legacy-maps).

- [ ] **Step 5: Commit**

```bash
git add server/config.py server/app.py server/tests/test_config_tokens.py
git commit -m "server: SIDEKICK_API_TOKENS token->identity map (legacy token still works)"
```

---

### Task 3: Identity-returning auth + `GET /me`

**Files:**
- Modify: `server/app.py` (`require_auth` + new `/me` route, inserted directly before the `/feed` route)
- Test: `server/tests/test_api_roles.py` (new file; Task 4 appends the enforcement tests)

**Interfaces:**
- Consumes: `Config.tokens` from Task 2; `vault_repo` fixture from `server/tests/conftest.py`.
- Produces: `require_auth(authorization)` now **returns** the identity dict `{"name": str, "role": "full"|"shared"}` (still raises `HTTPException(401)` on anything unknown); `GET /me` → `200 {"name": ..., "role": ...}`. Test module exports `FULL`, `SHARED` header constants and the `roles_client` fixture that Task 4 reuses.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_api_roles.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_roles.py -q`
Expected: `4 failed` — the `/me` route doesn't exist yet, so every request gets FastAPI's 404.

- [ ] **Step 3: Write the implementation**

In `server/app.py`, replace the Task 2 version of `require_auth` with:

```python
    def require_auth(authorization):
        """Return the calling token's identity {"name", "role"}; 401 on anything else."""
        if authorization.startswith("Bearer "):
            ident = config.tokens.get(authorization[len("Bearer "):])
            if ident is not None:
                return ident
        raise HTTPException(status_code=401, detail="unauthorized")
```

Directly after `require_auth` (before the `/feed` route), add:

```python
    @app.get("/me")
    def get_me(authorization: str = Header(default="")):
        ident = require_auth(authorization)
        return {"name": ident["name"], "role": ident["role"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/ -q`
Expected: all pass, `0 failed` (`test_api_roles.py` reads `4 passed`; existing endpoints ignore `require_auth`'s new return value).

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_roles.py
git commit -m "server: require_auth returns the token identity; GET /me"
```

---

### Task 4: Role enforcement on `/feed` and the write endpoints

**Files:**
- Modify: `server/app.py` (module docstring, `get_feed`, `post_task`, `post_complete`)
- Test: `server/tests/test_api_roles.py` (append to the Task 3 file)

**Interfaces:**
- Consumes: identity dict from `require_auth` (Task 3); `sidekick.create_task(title, category, from_=..., shared=...)`, `read_active()` entries' `"shared"`/`"from"` keys (Task 1); `sidekick.read_note` / `sidekick.task_path` (existing) for the shared-complete gate.
- Produces: role `shared`: `GET /feed` → `{"events": [], "active": [only shared tasks]}`; `POST /tasks` → forced `shared=True`; `POST /tasks/{id}/complete` → 404 unless the task exists **and** is shared (indistinguishable from missing). Role `full`: unchanged, plus optional `"shared": true` in the `POST /tasks` body. Both roles: `from_` = identity name, always.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_api_roles.py`:

```python
def _new(client, headers, body):
    return client.post("/tasks", json=body, headers=headers)


def test_shared_post_is_forced_shared_and_from_wife(roles_client):
    # the body tries to lie about both fields — the server must ignore it
    r = _new(roles_client, SHARED,
             {"title": "Buy milk", "category": "chore", "shared": False, "from": "dalton"})
    assert r.status_code == 201
    assert r.json()["shared"] is True      # forced by role
    assert r.json()["from"] == "wife"      # identity, never client-supplied


def test_full_post_defaults_personal_and_from_dalton(roles_client):
    r = _new(roles_client, FULL, {"title": "File taxes", "category": "admin", "from": "wife"})
    assert r.status_code == 201
    assert r.json()["shared"] is False
    assert r.json()["from"] == "dalton"    # identity wins over the body


def test_full_post_can_opt_into_shared(roles_client):
    r = _new(roles_client, FULL, {"title": "Plan trip", "category": "admin", "shared": True})
    assert r.json()["shared"] is True
    assert r.json()["from"] == "dalton"


def test_shared_feed_only_shared_tasks_and_no_events(roles_client):
    _new(roles_client, FULL, {"title": "Personal thing", "category": "admin"})
    shared_id = _new(roles_client, SHARED,
                     {"title": "Buy milk", "category": "chore"}).json()["id"]
    done = _new(roles_client, FULL, {"title": "Old chore", "category": "chore"}).json()["id"]
    roles_client.post(f"/tasks/{done}/complete", json={}, headers=FULL)  # makes a ledger event

    feed = roles_client.get("/feed", headers=SHARED).json()
    assert feed["events"] == []                                  # no game feed for role shared
    assert [a["id"] for a in feed["active"]] == [shared_id]      # personal tasks never leak


def test_full_feed_unchanged(roles_client):
    _new(roles_client, FULL, {"title": "Personal thing", "category": "admin"})
    _new(roles_client, SHARED, {"title": "Buy milk", "category": "chore"})
    feed = roles_client.get("/feed", headers=FULL).json()
    assert len(feed["active"]) == 2        # full role sees everything


def test_shared_complete_404_on_personal_task(roles_client):
    tid = _new(roles_client, FULL, {"title": "Personal thing", "category": "admin"}).json()["id"]
    r = roles_client.post(f"/tasks/{tid}/complete", json={}, headers=SHARED)
    assert r.status_code == 404            # indistinguishable from a missing task
    feed = roles_client.get("/feed", headers=FULL).json()
    assert any(a["id"] == tid for a in feed["active"])   # and it was NOT completed


def test_shared_can_complete_shared_task(roles_client):
    tid = _new(roles_client, SHARED, {"title": "Buy milk", "category": "chore"}).json()["id"]
    r = roles_client.post(f"/tasks/{tid}/complete", json={}, headers=SHARED)
    assert r.status_code == 200
    assert r.json()["status"] == "done"


def test_shared_complete_unknown_task_404(roles_client):
    r = roles_client.post("/tasks/nope/complete", json={}, headers=SHARED)
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_roles.py -q`
Expected: `5 failed, 7 passed` — the three POST-identity tests, the shared-feed filter, and the personal-task-404 test fail (endpoints ignore the role today); the 4 `/me` tests and the three behavior-preserving guards still pass.

- [ ] **Step 3: Write the implementation**

In `server/app.py`, replace the module docstring (lines 1–6) with:

```python
"""The host HTTP API: a thin wrapper over sidekick.py. The engine stays the SOLE writer
of the ledger; this layer only routes requests, enforces bearer auth and idempotency,
and publishes each change to git. Mutations are serialized by an inter-process vault lock
(shared with the periodic sync job — see server/sync_pull.py); still run with a single
worker (the idempotency store is per-process). Tokens map to identities (name + role);
role `shared` sees and touches ONLY shared tasks — enforced HERE (the PWA's hiding is
convenience, not security)."""
```

Replace `get_feed`:

```python
    @app.get("/feed")
    def get_feed(authorization: str = Header(default="")):
        ident = require_auth(authorization)
        if ident["role"] == "shared":
            # her page doesn't need the game feed; personal data never leaves the host
            return {"events": [],
                    "active": [a for a in sidekick.read_active() if a["shared"]]}
        return {"events": sidekick.read_ledger(), "active": sidekick.read_active()}
```

Replace `post_task`:

```python
    @app.post("/tasks")
    async def post_task(request: Request,
                        authorization: str = Header(default=""),
                        idempotency_key: str = Header(default="")):
        identity = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        title = data.get("title")
        category = data.get("category")
        if not title or not isinstance(title, str):
            raise HTTPException(status_code=400, detail="title is required")
        if category not in VALID_CATEGORIES:
            raise HTTPException(status_code=400,
                                detail=f"category must be one of {sorted(VALID_CATEGORIES)}")
        # role `shared` is forced onto the shared list; role `full` may opt in.
        # `from` is ALWAYS the token identity — never client-supplied (spec SP2).
        shared = True if identity["role"] == "shared" else bool(data.get("shared"))

        def run():
            with vault_lock(config.vault):
                tid = sidekick.create_task(title, category,
                                           from_=identity["name"], shared=shared)
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: new {tid}",
                                         push=config.push, remote=config.remote)
                entry = next((a for a in sidekick.read_active() if a["id"] == tid), None)
            return 201, entry

        return _idem_replay_or_run(idempotency_key, run)
```

Replace `post_complete`:

```python
    @app.post("/tasks/{task_id}/complete")
    async def post_complete(task_id: str, request: Request,
                            authorization: str = Header(default=""),
                            idempotency_key: str = Header(default="")):
        identity = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        completed_at = data.get("completed_at")

        def run():
            with vault_lock(config.vault):
                if identity["role"] == "shared":
                    # a personal task must be indistinguishable from a missing one
                    try:
                        fm, _ = sidekick.read_note(sidekick.task_path(task_id))
                    except FileNotFoundError:
                        raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                    if not fm.get("shared"):
                        raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                try:
                    result = sidekick.complete(task_id, completed_at=completed_at)
                except FileNotFoundError:
                    raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: complete {task_id}",
                                         push=config.push, remote=config.remote)
            return 200, result

        return _idem_replay_or_run(idempotency_key, run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/ -q && python3 -m pytest tests/ -q`
Expected: all pass, `0 failed` (`test_api_roles.py` reads `12 passed`; existing write tests still pass — their single legacy token maps to `dalton`/`full` and the response entries merely gain `from`/`shared` keys).

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_roles.py
git commit -m "server: role enforcement — shared feed filter, forced shared/from, 404 gate"
```

---

### Task 5: Web API client — `getMe`, shared-aware `createTask`, identity store

**Files:**
- Modify: `web/src/lib/types.ts` (ActiveTask)
- Modify: `web/src/lib/api.ts` (Identity, getMe, createTask)
- Modify: `web/src/lib/api.test.ts` (import + appended tests)
- Create: `web/src/lib/role.ts`
- Test: `web/src/lib/role.test.ts` (new)

**Interfaces:**
- Consumes: `GET /me` (Task 3), `POST /tasks` optional `shared` body field (Task 4), existing `settings` store / `base()` / `headers()` in `api.ts`.
- Produces: `export interface Identity { name: string; role: "full" | "shared" }`; `getMe(): Promise<Identity>`; `createTask(title, category, shared = false)` — body includes `shared: true` only when asked (default body is byte-identical to today); `ActiveTask` gains optional `from` / `shared`; `role.ts` exports the `identity` store (`Writable<Identity | null>`, localStorage-persisted under `sidekick.identity`), `loadIdentity(token)` (fetches `/me` once per distinct token; failure clears and allows retry) and `resetIdentity()`.

- [ ] **Step 1: Write the failing tests**

In `web/src/lib/api.test.ts`, change line 2 from

```ts
import { getFeed, createTask, completeTask, ApiError } from "./api";
```

to

```ts
import { getFeed, getMe, createTask, completeTask, ApiError } from "./api";
```

and append at the end of the file:

```ts
describe("getMe", () => {
  it("calls /api/me with the bearer token and returns the identity", async () => {
    const f = mockFetch(200, { name: "wife", role: "shared" });
    vi.stubGlobal("fetch", f);
    const me = await getMe();
    expect(me).toEqual({ name: "wife", role: "shared" });
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/me");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("throws ApiError(401) on an unknown token", async () => {
    vi.stubGlobal("fetch", mockFetch(401, { error: "unauthorized" }));
    await expect(getMe()).rejects.toMatchObject({ status: 401 });
  });
});

describe("createTask (shared)", () => {
  it("includes shared: true in the body when asked", async () => {
    const f = mockFetch(201, {
      id: "s1", task: "Buy milk", category: "chore", sat_for_hours: 0,
      plan: null, from: "wife", shared: true
    });
    vi.stubGlobal("fetch", f);
    await createTask("Buy milk", "chore", true);
    const [, opts] = f.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual({ title: "Buy milk", category: "chore", shared: true });
  });

  it("omits shared from the body by default (backward compatible)", async () => {
    const f = mockFetch(201, { id: "x", task: "Buy milk", category: "errand", sat_for_hours: 0, plan: null });
    vi.stubGlobal("fetch", f);
    await createTask("Buy milk", "errand");
    const [, opts] = f.mock.calls[0];
    expect(JSON.parse(opts.body)).toEqual({ title: "Buy milk", category: "errand" });
  });
});
```

Create `web/src/lib/role.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { get } from "svelte/store";

vi.mock("./api", () => ({ getMe: vi.fn() }));

import { identity, loadIdentity, resetIdentity } from "./role";
import { getMe } from "./api";

beforeEach(() => {
  vi.clearAllMocks();
  resetIdentity();
});

describe("identity store", () => {
  it("fetches /me and stores the identity", async () => {
    vi.mocked(getMe).mockResolvedValue({ name: "wife", role: "shared" });
    await loadIdentity("tok-1");
    expect(get(identity)).toEqual({ name: "wife", role: "shared" });
  });

  it("does not re-fetch for the same token", async () => {
    vi.mocked(getMe).mockResolvedValue({ name: "dalton", role: "full" });
    await loadIdentity("tok-1");
    await loadIdentity("tok-1");
    expect(getMe).toHaveBeenCalledTimes(1);
  });

  it("clears the identity when the token is empty", async () => {
    vi.mocked(getMe).mockResolvedValue({ name: "dalton", role: "full" });
    await loadIdentity("tok-1");
    await loadIdentity("");
    expect(get(identity)).toBeNull();
    expect(getMe).toHaveBeenCalledTimes(1);
  });

  it("nulls the identity on failure and retries on the next call", async () => {
    vi.mocked(getMe).mockRejectedValueOnce(new Error("down"));
    await loadIdentity("tok-1");
    expect(get(identity)).toBeNull();
    vi.mocked(getMe).mockResolvedValue({ name: "dalton", role: "full" });
    await loadIdentity("tok-1");
    expect(get(identity)).toEqual({ name: "dalton", role: "full" });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix web test`
Expected: `api.test.ts` errors (`getMe` is not exported) and `role.test.ts` errors (cannot resolve `./role`); every other test file still passes.

- [ ] **Step 3: Write the implementation**

In `web/src/lib/types.ts`, replace the `ActiveTask` interface with:

```ts
export interface ActiveTask {
  id: string;
  task: string;
  category: Category | string;
  sat_for_hours: number | null;
  plan: Plan | null;
  from?: string | null;   // who created it — server-assigned from the token identity
  shared?: boolean;       // membership in the shared list
}
```

In `web/src/lib/api.ts`, replace `createTask` with:

```ts
export async function createTask(title: string, category: Category, shared = false): Promise<ActiveTask> {
  return handle(await fetch(`${base()}/api/tasks`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify(shared ? { title, category, shared: true } : { title, category })
  }));
}
```

and add after `getFeed`:

```ts
export interface Identity { name: string; role: "full" | "shared"; }

export async function getMe(): Promise<Identity> {
  return handle(await fetch(`${base()}/api/me`, { headers: headers() }));
}
```

Create `web/src/lib/role.ts`:

```ts
import { writable } from "svelte/store";
import { browser } from "$app/environment";
import { getMe, type Identity } from "./api";

const KEY = "sidekick.identity";

function load(): Identity | null {
  if (!browser) return null;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const v = JSON.parse(raw);
      if (v && v.name && (v.role === "full" || v.role === "shared")) {
        return { name: v.name, role: v.role };
      }
    }
  } catch { /* ignore */ }
  return null;
}

/** The token's identity as the server sees it (GET /me). null = unknown / no token.
 *  This store only steers the UI — the API enforces roles server-side. */
export const identity = writable<Identity | null>(load());

if (browser) {
  identity.subscribe(v => {
    try {
      if (v) localStorage.setItem(KEY, JSON.stringify(v));
      else localStorage.removeItem(KEY);
    } catch { /* ignore */ }
  });
}

let lastToken: string | null = null;

/** Forget the cached identity (token cleared; tests). */
export function resetIdentity() {
  lastToken = null;
  identity.set(null);
}

/** Resolve the token's role via GET /me. No-op for a repeat token; on failure the
 *  identity is cleared and the next call retries. */
export async function loadIdentity(token: string): Promise<void> {
  const t = token.trim();
  if (!t) { resetIdentity(); return; }
  if (t === lastToken) return;
  lastToken = t;
  try {
    identity.set(await getMe());
  } catch {
    lastToken = null;
    identity.set(null);
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm --prefix web test`
Expected: all pass, 0 failed (`api.test.ts` now reads 10 tests, `role.test.ts` 4; the existing capture test still passes — `createTask("Book MOT", "errand")` matches the new signature's default).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/lib/api.test.ts web/src/lib/role.ts web/src/lib/role.test.ts
git commit -m "web: getMe + identity role store; createTask can flag shared"
```

---

### Task 6: The `/shared` page

**Files:**
- Create: `web/src/routes/shared/+page.svelte`
- Test: `web/src/routes/shared/shared.test.ts` (new)

**Interfaces:**
- Consumes: `getFeed`, `createTask(title, "chore", true)`, `completeTask(id, iso)` (idempotency keys built in), `ApiError` from `$lib/api`; `hasToken` from `$lib/settings`; `ActiveTask.shared` (Task 5).
- Produces: route `/shared` — add box on top, checkbox list of shared tasks **newest first** (ascending `sat_for_hours`), tick = optimistic complete with rollback. Works identically for both roles: the client filters `active` by `shared` (for role `shared` the server has already filtered; the filter is a no-op). New shared captures use the fixed category `chore` (the API requires a category; the wife's box has no picker).

- [ ] **Step 1: Write the failing tests**

Create `web/src/routes/shared/shared.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import type { Feed } from "$lib/types";

vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/settings", () => ({ hasToken: () => true }));
vi.mock("$lib/api", () => ({
  getFeed: vi.fn(),
  createTask: vi.fn(async () => ({ id: "new1" })),
  completeTask: vi.fn(async () => ({
    id: "new", status: "done", completed_at: "T", sat_for_hours: 1, already_done: false
  })),
  ApiError: class extends Error {
    status: number;
    constructor(status: number, msg: string) { super(msg); this.status = status; }
  }
}));

import SharedPage from "./+page.svelte";
import { getFeed, createTask, completeTask } from "$lib/api";

const feed: Feed = {
  events: [],
  active: [
    { id: "old", task: "Old shared", category: "chore", sat_for_hours: 50, plan: null, from: "dalton", shared: true },
    { id: "personal", task: "Personal thing", category: "admin", sat_for_hours: 10, plan: null, from: "dalton", shared: false },
    { id: "new", task: "New shared", category: "chore", sat_for_hours: 5, plan: null, from: "wife", shared: true }
  ]
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getFeed).mockResolvedValue(feed);
});

describe("Shared list", () => {
  it("shows only shared tasks, newest first", async () => {
    render(SharedPage);
    await waitFor(() => expect(screen.getByText("New shared")).toBeInTheDocument());
    expect(screen.queryByText("Personal thing")).toBeNull();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("New shared");
    expect(items[1]).toHaveTextContent("Old shared");
  });

  it("adds a task from the box as a shared chore and reloads", async () => {
    render(SharedPage);
    await waitFor(() => expect(getFeed).toHaveBeenCalled());
    await fireEvent.input(screen.getByLabelText(/new shared task/i), { target: { value: "Buy milk" } });
    await fireEvent.click(screen.getByRole("button", { name: /add/i }));
    await waitFor(() => expect(createTask).toHaveBeenCalledWith("Buy milk", "chore", true));
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));
  });

  it("ticking a checkbox completes the task and removes it", async () => {
    render(SharedPage);
    await waitFor(() => expect(screen.getByText("New shared")).toBeInTheDocument());
    await fireEvent.click(screen.getByRole("checkbox", { name: /complete new shared/i }));
    await waitFor(() => expect(completeTask).toHaveBeenCalledWith("new", expect.any(String)));
    expect(screen.queryByText("New shared")).toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix web test`
Expected: `shared.test.ts` errors (cannot resolve `./+page.svelte`); everything else still passes.

- [ ] **Step 3: Write the implementation**

Create `web/src/routes/shared/+page.svelte`:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { getFeed, createTask, completeTask, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { ActiveTask } from "$lib/types";

  let tasks = $state<ActiveTask[] | null>(null);
  let title = $state("");
  let busy = $state(false);
  let error = $state("");
  let pending = $state(new Set<string>());

  // newest first: read_active sorts longest-sitting first, so invert by sat hours
  const newestFirst = (list: ActiveTask[]) =>
    [...list].sort((a, b) => (a.sat_for_hours ?? 0) - (b.sat_for_hours ?? 0));

  async function load() {
    error = "";
    try {
      const feed = await getFeed();
      // role `shared` gets a pre-filtered feed; for role `full` this filter does the same job
      tasks = newestFirst(feed.active.filter(t => t.shared));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  async function add(e: Event) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    busy = true; error = "";
    try {
      await createTask(title.trim(), "chore", true);  // fixed category: the box has no picker
      title = "";
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't add — try again";
    } finally {
      busy = false;
    }
  }

  async function tick(id: string) {
    if (!tasks || pending.has(id)) return;
    const removed = tasks.find(t => t.id === id);
    if (!removed) return;
    pending = new Set(pending).add(id);
    tasks = tasks.filter(t => t.id !== id);              // optimistic
    try {
      await completeTask(id, new Date().toISOString());
    } catch (e) {
      tasks = newestFirst([removed, ...tasks]);          // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Shared list</h1>

<form class="add-row" onsubmit={add}>
  <input type="text" bind:value={title} placeholder="Add to the list…"
         aria-label="New shared task" />
  <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
</form>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{/if}

{#if tasks}
  {#if tasks.length === 0}
    <p class="muted">Nothing on the list.</p>
  {:else}
    <ul class="list">
      {#each tasks as t (t.id)}
        <li>
          <label>
            <input type="checkbox" disabled={pending.has(t.id)}
                   onchange={() => tick(t.id)} aria-label={"Complete " + t.task} />
            <span>{t.task}</span>
          </label>
        </li>
      {/each}
    </ul>
  {/if}
{:else if !error}
  <p class="muted">Loading…</p>
{/if}

<style>
  .add-row { display: flex; gap: 8px; margin-bottom: 18px; }
  .add-row input[type="text"] {
    flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(128, 128, 128, 0.35); background: transparent;
    color: inherit; font-size: 16px;   /* ≥16px prevents iOS focus zoom */
  }
  .list { list-style: none; padding: 0; margin: 0; }
  .list li { padding: 12px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.2); }
  .list label { display: flex; align-items: center; gap: 12px; font-size: 17px; }
  .list input[type="checkbox"] { width: 22px; height: 22px; flex: none; }
</style>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm --prefix web test`
Expected: all pass, 0 failed (`shared.test.ts` reads `3 passed`).

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/shared/+page.svelte web/src/routes/shared/shared.test.ts
git commit -m "web: /shared page — add box + checkbox list, tick to complete"
```

---

### Task 7: Role-aware nav + routing

**Files:**
- Modify: `web/src/routes/+layout.svelte` (full replacement below)
- Modify: `web/e2e/app.spec.ts` (one added route mock)
- Test: `web/src/routes/layout.test.ts` (new)

**Interfaces:**
- Consumes: `identity`, `loadIdentity` from `$lib/role` (Task 5); `settings` store; `/shared` route (Task 6).
- Produces: role `shared` → nav shows only **Shared** and **Settings**, and every other path redirects to `/shared` (Settings stays reachable — it's where the token is pasted; the API remains the boundary). Role `full` (or unknown identity) → existing nav plus a **Shared** link. `loadIdentity($settings.token)` runs reactively, so pasting a token on Settings resolves the role without a reload.

- [ ] **Step 1: Write the failing tests**

Create `web/src/routes/layout.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";

vi.mock("$app/stores", async () => {
  const { writable } = await import("svelte/store");
  return { page: writable({ url: new URL("http://localhost/") }) };
});
vi.mock("$app/navigation", () => ({ goto: vi.fn() }));
vi.mock("$lib/role", async () => {
  const { writable } = await import("svelte/store");
  return { identity: writable(null), loadIdentity: vi.fn() };
});

import Layout from "./+layout.svelte";
import { page } from "$app/stores";
import { goto } from "$app/navigation";
import { identity } from "$lib/role";

const setPage = (path: string) =>
  (page as any).set({ url: new URL(`http://localhost${path}`) });

function renderLayout() {
  const children = createRawSnippet(() => ({ render: () => "<main>content</main>" }));
  return render(Layout, { props: { children } });
}

beforeEach(() => {
  vi.mocked(goto).mockClear();
  identity.set(null);
  setPage("/");
});

describe("role-aware layout", () => {
  it("shows the full nav plus a Shared link for role full", () => {
    identity.set({ name: "dalton", role: "full" });
    renderLayout();
    expect(screen.getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "New" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Shared" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("shows only Shared + Settings for role shared", () => {
    identity.set({ name: "wife", role: "shared" });
    setPage("/shared");
    renderLayout();
    expect(screen.queryByRole("link", { name: "Dashboard" })).toBeNull();
    expect(screen.queryByRole("link", { name: "New" })).toBeNull();
    expect(screen.getByRole("link", { name: "Shared" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("redirects role shared away from every other route", async () => {
    identity.set({ name: "wife", role: "shared" });
    setPage("/");
    renderLayout();
    await waitFor(() => expect(goto).toHaveBeenCalledWith("/shared"));
  });

  it("leaves role shared alone on /settings", async () => {
    identity.set({ name: "wife", role: "shared" });
    setPage("/settings");
    renderLayout();
    await new Promise((r) => setTimeout(r, 0));   // let effects flush
    expect(goto).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm --prefix web test`
Expected: in `layout.test.ts`: `3 failed, 1 passed` — no Shared link yet, the shared-role nav still shows Dashboard, and no redirect fires; the `/settings` no-redirect guard passes trivially.

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `web/src/routes/+layout.svelte` with:

```svelte
<script lang="ts">
  import "../app.css";
  import { page } from "$app/stores";
  import { goto } from "$app/navigation";
  import { settings } from "$lib/settings";
  import { identity, loadIdentity } from "$lib/role";
  let { children } = $props();
  const is = (p: string) => $page.url.pathname === p;

  // resolve the token's role whenever the token changes (no-op for a repeat token)
  $effect(() => { loadIdentity($settings.token); });

  // role `shared` lives on /shared (+ /settings for token entry); everything else
  // redirects there. This is CONVENIENCE — the API is the security boundary.
  $effect(() => {
    const path = $page.url.pathname;
    if ($identity?.role === "shared" && path !== "/shared" && path !== "/settings") {
      goto("/shared");
    }
  });
</script>

<div class="wrap">
  <nav class="nav">
    {#if $identity?.role === "shared"}
      <a href="/shared" class:active={is("/shared")}>Shared</a>
      <a href="/settings" class:active={is("/settings")}>Settings</a>
    {:else}
      <a href="/" class:active={is("/")}>Dashboard</a>
      <a href="/new" class:active={is("/new")}>New</a>
      <a href="/shared" class:active={is("/shared")}>Shared</a>
      <a href="/settings" class:active={is("/settings")}>Settings</a>
    {/if}
  </nav>
  {@render children()}
</div>
```

In `web/e2e/app.spec.ts`, directly after the line

```ts
  await page.route("**/api/feed", r => r.fulfill({ json: feed }));
```

add:

```ts
  await page.route("**/api/me", r => r.fulfill({ json: { name: "dalton", role: "full" } }));
```

(The layout now calls `/me` on load; without the mock the e2e run would leave the identity null — which still renders the full nav, but mocking it keeps the e2e honest. `npm test` does not run e2e; run `npm --prefix web run e2e` only if Playwright browsers are installed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm --prefix web test`
Expected: all pass, 0 failed (`layout.test.ts` reads `4 passed`; existing suites untouched).

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/+layout.svelte web/src/routes/layout.test.ts web/e2e/app.spec.ts
git commit -m "web: role-aware nav; role shared pinned to /shared (+ /settings)"
```

---

### Task 8: Docs touch-up

**Files:**
- Modify: `server/README.md` (endpoints table + configuration section)
- Modify: `web/README.md` (intro)
- Modify: `CLAUDE.md` (tasks frontmatter one-liner)

**Interfaces:**
- Consumes: everything shipped in Tasks 1–7.
- Produces: docs that match the deployed behavior; no code.

- [ ] **Step 1: server/README.md**

In the endpoints table, add this row directly under the `GET /feed` row:

```markdown
| GET  | `/me` | — | `{ "name": ..., "role": "full"\|"shared" }` for the calling token |
```

After the table's error-format paragraph, add:

```markdown
Role `shared` (the shared-list token) is enforced server-side on every endpoint:
`/feed` returns only `shared: true` tasks with `events: []`; `POST /tasks` is forced
`shared: true`; complete is 404 unless the task is shared. `from` is always set from
the token identity — never from the client.
```

In the configuration section, replace the line

```markdown
- `SIDEKICK_API_TOKEN` (required) — the bearer token the phone sends.
```

with

```markdown
- `SIDEKICK_API_TOKENS` — JSON map of bearer tokens to identities, e.g.
  `{"<token>":{"name":"dalton","role":"full"},"<token2>":{"name":"wife","role":"shared"}}`
  (compact JSON, no spaces — systemd `EnvironmentFile`-safe).
- `SIDEKICK_API_TOKEN` (legacy fallback) — a single token, mapped to `dalton`/`full`.
  One of the two is required; `SIDEKICK_API_TOKENS` wins when both are set.
```

- [ ] **Step 2: web/README.md**

After the opening paragraph, add:

```markdown
Role `shared` tokens land on **/shared** — a plain add-box + checkbox list — and are
redirected away from everything else (Settings stays reachable for token entry); role
`full` gets the whole app plus a Shared tab. The server enforces the roles; the UI
only mirrors them.
```

- [ ] **Step 3: CLAUDE.md**

Replace the line

```markdown
- `tasks/*.md` — open tasks, one markdown file each, metadata in YAML frontmatter (category, created, status, plan). Editable by hand in Obsidian.
```

with

```markdown
- `tasks/*.md` — open tasks, one markdown file each, metadata in YAML frontmatter (category, created, status, plan; optional `from:` creator and `shared: true` shared-list membership — code-written via sidekick.py). Editable by hand in Obsidian.
```

- [ ] **Step 4: Full verification run**

Run: `python3 -m pytest server/tests/ -q && python3 -m pytest tests/ -q && npm --prefix web test`
Expected: all three suites pass, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add server/README.md web/README.md CLAUDE.md
git commit -m "docs: shared list — token map, /me, /shared"
```

---

## Deployment note (manual ops, after merge)

Not part of the code tasks. **On the VPS** (after the sync timer or a manual pull has delivered the merged code):

```bash
# 1) pull the new code and generate the wife's token
sudo -u sidekick git -C /srv/sidekick pull
WIFE_TOKEN=$(openssl rand -hex 24)
DALTON_TOKEN=$(grep -E '^SIDEKICK_API_TOKEN=' /etc/sidekick.env | cut -d= -f2-)

# 2) add the token map (compact JSON, no spaces — systemd EnvironmentFile-safe).
#    Reusing Dalton's existing token means his installed PWA needs no re-entry.
echo "SIDEKICK_API_TOKENS={\"$DALTON_TOKEN\":{\"name\":\"dalton\",\"role\":\"full\"},\"$WIFE_TOKEN\":{\"name\":\"wife\",\"role\":\"shared\"}}" | sudo tee -a /etc/sidekick.env
echo "wife's token: $WIFE_TOKEN"   # save it — you'll paste it on her phone once

# 3) rebuild the PWA and restart the API
cd /srv/sidekick/web && npm install && npm run build
sudo systemctl restart sidekick

# 4) verify both roles over the tailnet
curl -s -H "Authorization: Bearer $DALTON_TOKEN" https://sidekick.tail81b55b.ts.net/api/me
# → {"name":"dalton","role":"full"}
curl -s -H "Authorization: Bearer $WIFE_TOKEN" https://sidekick.tail81b55b.ts.net/api/me
# → {"name":"wife","role":"shared"}
```

**On the wife's Android phone:**

1. **Tailscale:** in the Tailscale admin console (login.tailscale.com) invite her as a user (the free Personal plan covers 3 users). She installs the **Tailscale** app from the Play Store, signs in, and joins the tailnet — MagicDNS makes `sidekick.tail81b55b.ts.net` resolve.
2. **PWA:** in Chrome open `https://sidekick.tail81b55b.ts.net` → ⋮ menu → **Add to Home screen / Install app**.
3. **Token:** open the installed app → it lands on Settings → paste `$WIFE_TOKEN`. The app fetches `/me`, sees role `shared`, and pins her to the Shared list.

Dalton's phone needs nothing — his token is unchanged; his app just gains the Shared tab. Her list depends on Tailscale staying connected on her phone (spec's honest limit; Funnel is explicitly deferred).
