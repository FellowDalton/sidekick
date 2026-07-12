# Web-Push Nudges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The daily nudge reaches Dalton's iPhone as a web-push notification sent by the always-on VPS — no Mac-awake dependency, no Beeper. Silent when nothing is genuinely stalled. Sub-project 4 of `docs/superpowers/specs/2026-07-10-sidekick-next-phase-design.md`.

**Architecture:** A new `server/push.py` owns a per-identity subscription store (`<vault>/.sidekick-push.json`, gitignored runtime state like the idempotency store) and delivery via `pywebpush` with VAPID keys from the environment. Two new authenticated API endpoints let the PWA subscribe (`POST /push/subscribe`) and fetch the VAPID public key (`GET /push/vapid-public-key`). A new `server/nudge_job.py` (systemd oneshot + daily timer, 09:00 Europe/Copenhagen) ports `nudge.py`'s deterministic decide (`pick_task` / `deterministic_message` / `min_sat_hours`) and sends to identity `dalton` only; an optional `SIDEKICK_NUDGE_CMD` (e.g. `pi -p`, absent until sub-project 3) may re-word — never re-decide — the message. The PWA gains a push handler in the service worker (via workbox `importScripts`, keeping the generated precache SW) and an "Enable notifications" button in Settings. `server/sync_pull.py` gains the alert deferred by the git-sync plan: 3 consecutive pull failures → one push alert to Dalton.

**Tech Stack:** FastAPI (existing), `pywebpush` (the one new Python dependency — spec-sanctioned, pinned), pytest (existing `server/tests/` fixtures), systemd oneshot + timer, `@vite-pwa/sveltekit` generateSW + workbox `importScripts`, Svelte 5 + Vitest.

## Global Constraints

- **Wife receives no push this phase** (spec): routing is hardcoded to identity `dalton` in the nudge job and in the sync-pull alert (`NUDGE_IDENTITY` / `ALERT_IDENTITY` constants). The `push.send_to_identity(config, name, title, body)` API itself stays general — any identity may subscribe and be addressed later; nothing *calls* it for `wife` now.
- **The nudge job never writes vault data**: `tasks/`, `ledger.jsonl`, `sidekick-data.js` are untouched (the engine stays the sole writer). Its only mutation is subscription pruning inside the **gitignored** `.sidekick-push.json` — the same class of runtime state as `.sidekick-idempotency.json`. The gitignore entry lands in Task 1.
- **Deterministic-only must work with no pi installed**: `SIDEKICK_NUDGE_CMD` unset/empty ⇒ no subprocess is spawned at all (the `use_claude`-style knob); when set, ANY wording failure (missing binary, non-zero exit, timeout, empty output) falls back to the deterministic message — a wording failure never cancels the send.
- **`pywebpush` is MOCKED in every server test** — no test may hit the network. The subscription store, pruning, and identity routing are tested for real against throwaway vaults.
- **`nudge.py` (Beeper + launchd) stays in the repo untouched** — it becomes the documented offline fallback (CLAUDE.md note in Task 5).
- **The PWA's existing precache + NetworkFirst `/api/feed` caching must keep working**: the SW stays in generateSW mode; the push handler arrives via workbox `importScripts` of a small static file, not an injectManifest rewrite.
- Server route paths are `/push/*`; the phone reaches them as `/api/push/*` (Caddy strips the `/api` prefix, same as every other endpoint).
- All commands run from the repo root. Server tests: `python3 -m pytest server/tests/ -q`. Web tests: `cd web && npm test`.
- Existing test fixtures live in `server/tests/conftest.py` (`vault_repo`, `bare_remote`, `clone`, `git`, `AUTH`) — reuse them, don't reinvent.
- The branch may be mid-flight on other features: locate edit points by the quoted snippets, not line numbers.

## File Structure

```
server/push.py                     NEW  subscription store + web-push delivery (send_to_identity)
server/nudge_job.py                NEW  daily decide + send (CLI: python -m server.nudge_job [--dry-run])
server/app.py                      MOD  POST /push/subscribe, GET /push/vapid-public-key
server/sync_pull.py                MOD  failure-streak alert via push (closes the git-sync plan's deferral)
server/requirements.txt            MOD  + pywebpush (pinned)
server/tests/test_push.py          NEW
server/tests/test_api_push.py      NEW
server/tests/test_nudge_job.py     NEW
server/tests/test_sync_pull.py     MOD  streak/alert tests appended
.gitignore                         MOD  + .sidekick-push.json
web/src/lib/api.ts                 MOD  getVapidPublicKey, subscribePush
web/src/lib/push.ts                NEW  enablePush() client flow
web/src/lib/push.test.ts           NEW
web/src/lib/api.test.ts            MOD  push endpoint tests appended
web/src/routes/settings/+page.svelte      MOD  Notifications section
web/src/routes/settings/settings.test.ts  MOD  rewritten: existing tests + push button tests
web/static/push-sw.js              NEW  push + notificationclick handlers
web/vite.config.ts                 MOD  workbox.importScripts: ["push-sw.js"]
deploy/sidekick-nudge.service      NEW  systemd oneshot
deploy/sidekick-nudge.timer        NEW  daily 09:00 Europe/Copenhagen
deploy/README.md                   MOD  VAPID keys, env, timer install, iPhone steps
CLAUDE.md                          MOD  nudge.py demoted to documented offline fallback
```

---

### Task 1: `server/push.py` — subscription store + web-push delivery

**Files:**
- Create: `server/push.py`
- Test: `server/tests/test_push.py`
- Modify: `server/requirements.txt`, `.gitignore`

**Interfaces:**
- Consumes: `vault_lock(vault)` from `server/vault_lock.py`; `pywebpush.webpush` / `WebPushException` (new dep); env `SIDEKICK_VAPID_PRIVATE`, `SIDEKICK_VAPID_SUB` (a `mailto:` URI).
- Produces: `store_path(vault) -> str`; `save_subscription(vault, name, sub) -> int` (identity's subscription count; re-subscribing the same endpoint replaces, not duplicates); `send_to_identity(config, name, title, body) -> int` (count delivered; prunes subscriptions the push service reports gone with 404/410; raises `RuntimeError` if VAPID env is missing).

- [ ] **Step 1: Install the dependency and pin it**

Run: `python3 -m pip install "pywebpush==2.0.3"`
Expected: `Successfully installed ... pywebpush-2.0.3` (if pip can't resolve exactly 2.0.3, use the latest 2.0.x and pin THAT version consistently here and in requirements.txt)

In `server/requirements.txt`, replace:

```
fastapi
uvicorn[standard]
```

with:

```
fastapi
uvicorn[standard]
pywebpush==2.0.3
```

In `.gitignore`, replace:

```
# host API idempotency store (runtime state, per-vault)
.sidekick-idempotency.json
```

with:

```
# host API idempotency store (runtime state, per-vault)
.sidekick-idempotency.json

# web-push subscription store (runtime state, per-vault; never in git)
.sidekick-push.json
```

- [ ] **Step 2: Write the failing tests**

Create `server/tests/test_push.py`:

```python
"""Subscription store + web-push delivery. pywebpush is ALWAYS mocked (no network);
the store, 404/410 pruning, and identity routing are tested for real."""
import json

import pytest
from pywebpush import WebPushException

from server import push

SUB_A = {"endpoint": "https://push.example/a", "keys": {"p256dh": "pk-a", "auth": "au-a"}}
SUB_B = {"endpoint": "https://push.example/b", "keys": {"p256dh": "pk-b", "auth": "au-b"}}


@pytest.fixture
def vapid_env(monkeypatch):
    monkeypatch.setenv("SIDEKICK_VAPID_PRIVATE", "test-private-key")
    monkeypatch.setenv("SIDEKICK_VAPID_PUBLIC", "test-public-key")
    monkeypatch.setenv("SIDEKICK_VAPID_SUB", "mailto:test@sidekick.local")


def _config(vault_repo):
    from server.config import Config
    return Config(vault=str(vault_repo), token="test-token", push=False)


def _store(vault_repo):
    return json.loads((vault_repo / ".sidekick-push.json").read_text(encoding="utf-8"))


# ── the store ───────────────────────────────────────────────────────────────
def test_save_subscription_persists(vault_repo):
    assert push.save_subscription(str(vault_repo), "dalton", SUB_A) == 1
    assert _store(vault_repo) == {"dalton": [SUB_A]}


def test_resubscribe_same_endpoint_replaces(vault_repo):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    updated = dict(SUB_A, keys={"p256dh": "pk-new", "auth": "au-new"})
    assert push.save_subscription(str(vault_repo), "dalton", updated) == 1
    assert _store(vault_repo)["dalton"] == [updated]


def test_subscriptions_are_per_identity(vault_repo):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    push.save_subscription(str(vault_repo), "wife", SUB_B)
    data = _store(vault_repo)
    assert data["dalton"] == [SUB_A] and data["wife"] == [SUB_B]


# ── delivery ────────────────────────────────────────────────────────────────
def test_send_delivers_to_named_identity_only(vault_repo, vapid_env, monkeypatch):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    push.save_subscription(str(vault_repo), "wife", SUB_B)
    sent = []
    monkeypatch.setattr(push, "webpush", lambda **kw: sent.append(kw))
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 1
    assert len(sent) == 1
    assert sent[0]["subscription_info"] == SUB_A          # wife's endpoint never touched
    assert json.loads(sent[0]["data"]) == {"title": "T", "body": "B"}
    assert sent[0]["vapid_private_key"] == "test-private-key"
    assert sent[0]["vapid_claims"] == {"sub": "mailto:test@sidekick.local"}


def test_send_without_subscriptions_returns_zero(vault_repo, vapid_env, monkeypatch):
    monkeypatch.setattr(push, "webpush",
                        lambda **kw: pytest.fail("nothing to send to"))
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 0


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_send_prunes_gone_subscriptions(vault_repo, vapid_env, monkeypatch):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)
    push.save_subscription(str(vault_repo), "dalton", SUB_B)

    def fake(subscription_info, **kw):
        if subscription_info["endpoint"] == SUB_A["endpoint"]:
            raise WebPushException("gone", response=_Resp(410))

    monkeypatch.setattr(push, "webpush", fake)
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 1
    assert _store(vault_repo)["dalton"] == [SUB_B]


def test_send_keeps_subscription_on_transient_failure(vault_repo, vapid_env, monkeypatch):
    push.save_subscription(str(vault_repo), "dalton", SUB_A)

    def fake(**kw):
        raise WebPushException("boom", response=_Resp(500))

    monkeypatch.setattr(push, "webpush", fake)
    assert push.send_to_identity(_config(vault_repo), "dalton", "T", "B") == 0
    assert _store(vault_repo)["dalton"] == [SUB_A]        # 500 is not "gone" — keep it


def test_send_unconfigured_raises(vault_repo, monkeypatch):
    monkeypatch.delenv("SIDEKICK_VAPID_PRIVATE", raising=False)
    monkeypatch.delenv("SIDEKICK_VAPID_SUB", raising=False)
    with pytest.raises(RuntimeError):
        push.send_to_identity(_config(vault_repo), "dalton", "T", "B")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_push.py -q`
Expected: 8 failures/errors with `ModuleNotFoundError: No module named 'server.push'`

- [ ] **Step 4: Write the implementation**

Create `server/push.py`:

```python
"""Web-push delivery (spec sub-project 4). Subscriptions live in
<vault>/.sidekick-push.json — gitignored runtime state, like the idempotency
store — mapping identity name → list of browser PushSubscription dicts.
Sending prunes subscriptions the push service reports gone (404/410); other
per-subscription failures are skipped (best-effort — a nudge is a nudge, not
an alarm). VAPID keys come from the environment. This module is deliberately
GENERAL (any identity can be stored and addressed); ROUTING — who actually
gets nudged — is the caller's decision (server/nudge_job.py: dalton only this
phase). Store mutations hold the vault lock: the API's subscribe handler and
the nudge job's pruning may run in different processes."""
import json
import os

from pywebpush import webpush, WebPushException

from server.vault_lock import vault_lock

STORE_NAME = ".sidekick-push.json"


def store_path(vault):
    return os.path.join(vault, STORE_NAME)


def _load(vault):
    try:
        with open(store_path(vault), encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(vault, data):
    tmp = store_path(vault) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, store_path(vault))


def save_subscription(vault, name, sub):
    """Store one browser PushSubscription for an identity. Re-subscribing from
    the same browser (same endpoint) replaces, not duplicates. Returns the
    identity's subscription count."""
    with vault_lock(vault):
        data = _load(vault)
        subs = [s for s in data.get(name, []) if s.get("endpoint") != sub.get("endpoint")]
        subs.append(sub)
        data[name] = subs
        _save(vault, data)
        return len(subs)


def _vapid_env():
    """(private_key, claims_sub) from the environment, or None when push isn't set up."""
    priv = os.environ.get("SIDEKICK_VAPID_PRIVATE", "")
    sub = os.environ.get("SIDEKICK_VAPID_SUB", "")
    if not priv or not sub:
        return None
    return priv, sub


def send_to_identity(config, name, title, body):
    """Send one notification to every subscription of `name`. Returns the number
    delivered. Raises RuntimeError if VAPID keys are not configured."""
    env = _vapid_env()
    if env is None:
        raise RuntimeError(
            "web push not configured (set SIDEKICK_VAPID_PRIVATE / SIDEKICK_VAPID_SUB)")
    priv, claims_sub = env
    with vault_lock(config.vault):
        subs = _load(config.vault).get(name, [])
    payload = json.dumps({"title": title, "body": body})
    delivered, gone = 0, []
    for sub in subs:
        try:
            webpush(subscription_info=sub, data=payload,
                    vapid_private_key=priv,
                    vapid_claims={"sub": claims_sub})  # fresh dict: pywebpush mutates it
            delivered += 1
        except WebPushException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (404, 410):
                gone.append(sub.get("endpoint"))
            # anything else: skip this subscription, keep going (best-effort)
    if gone:
        with vault_lock(config.vault):
            data = _load(config.vault)
            data[name] = [s for s in data.get(name, []) if s.get("endpoint") not in gone]
            _save(config.vault, data)
    return delivered
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_push.py -q`
Expected: `8 passed`

- [ ] **Step 6: Commit**

```bash
git add server/push.py server/tests/test_push.py server/requirements.txt .gitignore
git commit -m "server: web-push delivery + per-identity subscription store"
```

---

### Task 2: API endpoints — `POST /push/subscribe` + `GET /push/vapid-public-key`

**Files:**
- Modify: `server/app.py`
- Test: `server/tests/test_api_push.py`

**Interfaces:**
- Consumes: `require_auth` / `_read_json` (existing closures in `create_app`); `push.save_subscription` from Task 1; env `SIDEKICK_VAPID_PUBLIC`.
- Produces: `POST /push/subscribe` (auth'd; body = the browser's `PushSubscription.toJSON()`; stores under the **token's** identity — never client-chosen; 400 on malformed body) → `{"ok": true, "subscriptions": n}`. `GET /push/vapid-public-key` (auth'd; 503 when unconfigured) → `{"key": "<base64url>"}` so the client never hardcodes the key.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_api_push.py`:

```python
"""/push endpoints: subscribe stores under the calling token's identity (never
client-chosen); the public-key endpoint spares the client hardcoding VAPID."""
import json

from server.tests.conftest import AUTH

SUB = {"endpoint": "https://push.example/x", "keys": {"p256dh": "pk", "auth": "au"}}


def test_subscribe_stores_for_token_identity(client, vault_repo):
    r = client.post("/push/subscribe", headers=AUTH, json=SUB)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "subscriptions": 1}
    data = json.loads((vault_repo / ".sidekick-push.json").read_text(encoding="utf-8"))
    assert data["dalton"] == [SUB]


def test_subscribe_requires_auth(client):
    assert client.post("/push/subscribe", json=SUB).status_code == 401


def test_subscribe_rejects_malformed_body(client):
    r = client.post("/push/subscribe", headers=AUTH, json={"nope": 1})
    assert r.status_code == 400


def test_shared_role_may_subscribe(vault_repo):
    # the store/API stays general; ROUTING (nobody sends to wife this phase)
    # lives in the nudge job, not here
    from fastapi.testclient import TestClient
    from server.app import create_app
    from server.config import Config
    cfg = Config(vault=str(vault_repo),
                 tokens={"wife-token": {"name": "wife", "role": "shared"}}, push=False)
    c = TestClient(create_app(cfg))
    r = c.post("/push/subscribe", headers={"Authorization": "Bearer wife-token"}, json=SUB)
    assert r.status_code == 200
    data = json.loads((vault_repo / ".sidekick-push.json").read_text(encoding="utf-8"))
    assert data["wife"] == [SUB]


def test_vapid_public_key(client, monkeypatch):
    monkeypatch.setenv("SIDEKICK_VAPID_PUBLIC", "pubkey-123")
    r = client.get("/push/vapid-public-key", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"key": "pubkey-123"}


def test_vapid_public_key_unconfigured_is_503(client, monkeypatch):
    monkeypatch.delenv("SIDEKICK_VAPID_PUBLIC", raising=False)
    assert client.get("/push/vapid-public-key", headers=AUTH).status_code == 503


def test_vapid_public_key_requires_auth(client):
    assert client.get("/push/vapid-public-key").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_push.py -q`
Expected: 7 failures (the routes don't exist yet, so FastAPI answers 404/405 where the tests expect 200/400/401/503)

- [ ] **Step 3: Write the implementation**

In `server/app.py`, locate the imports:

```python
from server.config import load_config  # noqa: E402
from server import git_sync            # noqa: E402
```

and add the push import after them:

```python
from server.config import load_config  # noqa: E402
from server import git_sync            # noqa: E402
from server import push                # noqa: E402
```

Then locate the `_read_json` helper inside `create_app`:

```python
    def _read_json(request_body):
        return request_body if isinstance(request_body, dict) else {}
```

and insert the two routes immediately after it:

```python
    @app.get("/push/vapid-public-key")
    def get_vapid_public_key(authorization: str = Header(default="")):
        require_auth(authorization)
        key = os.environ.get("SIDEKICK_VAPID_PUBLIC", "")
        if not key:
            raise HTTPException(status_code=503, detail="web push not configured")
        return {"key": key}

    @app.post("/push/subscribe")
    async def post_push_subscribe(request: Request,
                                  authorization: str = Header(default="")):
        # stored under the TOKEN's identity — never client-chosen (same rule as `from`)
        ident = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        endpoint = data.get("endpoint")
        keys = data.get("keys")
        if (not endpoint or not isinstance(endpoint, str) or not isinstance(keys, dict)
                or not keys.get("p256dh") or not keys.get("auth")):
            raise HTTPException(status_code=400,
                                detail="a PushSubscription JSON (endpoint + keys) is required")
        sub = {"endpoint": endpoint,
               "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}
        count = push.save_subscription(config.vault, ident["name"], sub)
        return {"ok": True, "subscriptions": count}
```

- [ ] **Step 4: Run the full server suite**

Run: `python3 -m pytest server/tests/ -q`
Expected: all pass, `0 failed` (the pre-existing tests plus 8 from Task 1 and 7 from this task)

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_push.py
git commit -m "server: /push/subscribe + /push/vapid-public-key endpoints"
```

---

### Task 3: `server/nudge_job.py` — the daily decide + send

**Files:**
- Create: `server/nudge_job.py`
- Test: `server/tests/test_nudge_job.py`

**Interfaces:**
- Consumes: `sidekick.configure` / `sidekick.read_active()` (fields: `id`, `task`, `category`, `sat_for_hours`, `plan`, `from`, `shared`); `load_config()`; `push.send_to_identity` from Task 1; env `SIDEKICK_NUDGE_MIN_SAT_HOURS` (default 48), `SIDEKICK_NUDGE_CMD` (default empty ⇒ deterministic-only), `SIDEKICK_NUDGE_TIMEOUT_SEC` (default 60).
- Produces: `pick_task(active, min_sat)`, `deterministic_message(t)`, `model_message(cmd, t)`, `decide(active, min_sat, cmd="")` → `(title, body, source)` or `None`; `run(config=None, dry_run=False) -> int`; `main(argv=None) -> int` so systemd runs `python -m server.nudge_job` and a human runs `python -m server.nudge_job --dry-run`.
- The DECISION (send vs silent, which task) is always deterministic — ported from `nudge.py`. The model, when configured, WORDS the message only; any failure falls back to the deterministic wording. Reads are lock-free (same as `GET /feed`); the job's only possible write is subscription pruning inside `send_to_identity`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_nudge_job.py`:

```python
"""The daily nudge job. Deterministic decide ported from nudge.py; optional model
WORDING (never decision); delivery via server.push to dalton only. Web-push send
is always mocked; the decide logic runs pure and against a real throwaway vault."""
import datetime as dt
import shlex
import sys

import pytest

from server import nudge_job


def _t(task="Pay tax", sat=100, plan=None, category="admin"):
    return {"id": "x", "task": task, "category": category,
            "sat_for_hours": sat, "plan": plan, "from": None, "shared": False}


PLAN = {"summary": "ready", "steps": [{"text": "Call SKAT", "href": "https://skat.dk"}]}


# ── pick_task (ported behavior) ─────────────────────────────────────────────
def test_pick_prefers_planned_over_longer_unplanned():
    a, b = _t("no plan", sat=120), _t("planned", sat=60, plan=PLAN)
    assert nudge_job.pick_task([a, b], 48) is b


def test_pick_longest_among_planned():
    older, newer = _t("older", sat=90, plan=PLAN), _t("newer", sat=60, plan=PLAN)
    assert nudge_job.pick_task([newer, older], 48) is older


def test_pick_silent_when_nothing_stalled():
    assert nudge_job.pick_task([], 48) is None
    assert nudge_job.pick_task([_t(sat=10)], 48) is None


def test_pick_falls_back_to_unplanned_when_no_plans():
    a = _t("bare", sat=80)
    assert nudge_job.pick_task([a], 48) is a


# ── deterministic wording ───────────────────────────────────────────────────
def test_message_with_plan_names_first_step_and_href():
    m = nudge_job.deterministic_message(_t(sat=72, plan=PLAN))
    assert "Pay tax" in m and "3d" in m and "Call SKAT" in m and "https://skat.dk" in m


def test_message_without_plan_suggests_asking():
    m = nudge_job.deterministic_message(_t(sat=20))
    assert "Pay tax" in m and "20h" in m and "first step" in m


# ── model wording: ANY failure → None (fallback fires) ──────────────────────
def _cmd(tmp_path, script):
    p = tmp_path / "fake-pi.py"
    p.write_text(script, encoding="utf-8")
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}"


def test_model_message_returns_first_line(tmp_path):
    cmd = _cmd(tmp_path, 'print("A kind nudge about tax")\n')
    assert nudge_job.model_message(cmd, _t(plan=PLAN)) == "A kind nudge about tax"


def test_model_message_none_on_missing_binary():
    assert nudge_job.model_message("/nonexistent/pi -p", _t()) is None


def test_model_message_none_on_nonzero_exit(tmp_path):
    cmd = _cmd(tmp_path, 'import sys; sys.exit(3)\n')
    assert nudge_job.model_message(cmd, _t()) is None


def test_model_message_none_on_none_reply(tmp_path):
    cmd = _cmd(tmp_path, 'print("NUDGE: NONE")\n')
    assert nudge_job.model_message(cmd, _t()) is None


# ── decide ──────────────────────────────────────────────────────────────────
def test_decide_silent_when_nothing_stalled():
    assert nudge_job.decide([_t(sat=5)], 48) is None


def test_decide_deterministic_without_cmd():
    title, body, source = nudge_job.decide([_t(sat=72, plan=PLAN)], 48, cmd="")
    assert title == "Sidekick" and source == "deterministic" and "Call SKAT" in body


def test_decide_uses_model_wording(monkeypatch):
    monkeypatch.setattr(nudge_job, "model_message", lambda cmd, t: "worded!")
    _, body, source = nudge_job.decide([_t(sat=72, plan=PLAN)], 48, cmd="pi -p")
    assert body == "worded!" and source == "model"


def test_decide_falls_back_when_model_fails(monkeypatch):
    monkeypatch.setattr(nudge_job, "model_message", lambda cmd, t: None)
    _, body, source = nudge_job.decide([_t(sat=72, plan=PLAN)], 48, cmd="pi -p")
    assert source == "deterministic" and "Call SKAT" in body


# ── run (vault-backed) ──────────────────────────────────────────────────────
def _write_task(vault, tid, title, hours_ago, plan_step=None):
    created = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat()
    plan = f"plan:\n  summary: ready\n  steps:\n    - text: {plan_step}\n" if plan_step else ""
    (vault / "tasks" / f"{tid}.md").write_text(
        f"---\ncategory: admin\ncreated: '{created}'\nstatus: open\n{plan}---\n# {title}\n",
        encoding="utf-8")


def _config(vault_repo):
    from server.config import Config
    return Config(vault=str(vault_repo), token="test-token", push=False)


@pytest.fixture(autouse=True)
def _clean_nudge_env(monkeypatch):
    monkeypatch.delenv("SIDEKICK_NUDGE_CMD", raising=False)
    monkeypatch.delenv("SIDEKICK_NUDGE_MIN_SAT_HOURS", raising=False)


def test_run_dry_run_decides_but_never_sends(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda *a, **kw: pytest.fail("dry-run must not send"))
    assert nudge_job.run(_config(vault_repo), dry_run=True) == 0
    assert "DRY-RUN" in capsys.readouterr().out


def test_run_sends_to_dalton_only(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    sent = []
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda config, name, title, body: (sent.append((name, title, body)), 1)[1])
    assert nudge_job.run(_config(vault_repo)) == 0
    assert len(sent) == 1
    name, title, body = sent[0]
    assert name == "dalton"                    # spec: wife receives no push this phase
    assert title == "Sidekick" and "Call SKAT" in body


def test_run_silent_when_everything_fresh(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260710-new", "Fresh task", hours_ago=2)
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda *a, **kw: pytest.fail("must stay silent"))
    assert nudge_job.run(_config(vault_repo)) == 0
    assert "silent" in capsys.readouterr().out


def test_run_min_sat_hours_from_env(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    monkeypatch.setenv("SIDEKICK_NUDGE_MIN_SAT_HOURS", "1000")
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda *a, **kw: pytest.fail("must stay silent"))
    assert nudge_job.run(_config(vault_repo)) == 0
    assert "silent" in capsys.readouterr().out


def test_run_never_writes_vault_data(vault_repo, monkeypatch):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    task_before = (vault_repo / "tasks" / "20260701-pay-tax.md").read_text(encoding="utf-8")
    ledger_before = (vault_repo / "ledger.jsonl").read_text(encoding="utf-8")
    monkeypatch.setattr(nudge_job.push, "send_to_identity", lambda *a, **kw: 1)
    nudge_job.run(_config(vault_repo))
    assert (vault_repo / "tasks" / "20260701-pay-tax.md").read_text(encoding="utf-8") == task_before
    assert (vault_repo / "ledger.jsonl").read_text(encoding="utf-8") == ledger_before


def test_main_exit_codes(vault_repo, monkeypatch, capsys):
    monkeypatch.setenv("SIDEKICK_VAULT", str(vault_repo))
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "test-token")
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    assert nudge_job.main(["--dry-run"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    # actually sending without VAPID keys configured must fail LOUDLY (exit 1)
    monkeypatch.delenv("SIDEKICK_VAPID_PRIVATE", raising=False)
    monkeypatch.delenv("SIDEKICK_VAPID_SUB", raising=False)
    assert nudge_job.main([]) == 1
    assert "nudge:" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_nudge_job.py -q`
Expected: 20 failures/errors with `ModuleNotFoundError: No module named 'server.nudge_job'`

- [ ] **Step 3: Write the implementation**

Create `server/nudge_job.py`:

```python
"""Daily nudge, delivered by web push (spec sub-project 4). Ports nudge.py's
DETERMINISTIC decide: the longest-sitting open task at least min_sat_hours old,
preferring one with a prepared plan, first step in the body so starting is
trivial; silent when nothing is genuinely stalled. An optional model may WORD
the message (SIDEKICK_NUDGE_CMD, e.g. "pi -p" — absent until the agent runner
lands); the model never decides more than phrasing, and ANY wording failure
falls back to the deterministic text, so a broken model call never costs the
nudge. Routing is hardcoded: dalton gets every nudge, wife gets none this
phase. Never writes vault data (tasks/, ledger.jsonl); the only mutation is
subscription pruning inside the gitignored push store.

Run: python -m server.nudge_job [--dry-run]    (systemd: deploy/sidekick-nudge.timer)"""
import argparse
import os
import shlex
import subprocess
import sys

# ensure the repo root (where sidekick.py lives) is importable, same as server/app.py
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidekick                         # noqa: E402
from server import push                 # noqa: E402
from server.config import load_config   # noqa: E402

NUDGE_IDENTITY = "dalton"       # spec: Dalton gets all nudges; wife gets NONE this phase
DEFAULT_MIN_SAT_HOURS = 48.0


def pick_task(active, min_sat):
    """Longest-sitting stalled task, preferring one with a prepared plan.
    (Ported verbatim from nudge.py.)"""
    stalled = [t for t in active if (t.get("sat_for_hours") or 0) >= min_sat]
    if not stalled:
        return None
    pool = [t for t in stalled if t.get("plan")] or stalled
    pool.sort(key=lambda t: t.get("sat_for_hours") or 0, reverse=True)
    return pool[0]


def _sat_str(h):
    h = h or 0
    return f"{round(h/24)}d" if h >= 24 else f"{round(h)}h"


def deterministic_message(t):
    """The always-works wording (nudge.py's, minus its "Sidekick ·" prefix —
    the notification TITLE carries the app name now)."""
    plan = t.get("plan")
    if plan and plan.get("steps"):
        s0 = plan["steps"][0]
        extra = ""
        href = s0.get("href", "")
        if href.startswith("http"):
            extra = f" {href}"
        return (f"“{t['task']}” has sat {_sat_str(t.get('sat_for_hours'))}. "
                f"First step's ready: {s0.get('text', '')}.{extra}")
    return (f"“{t['task']}” has sat {_sat_str(t.get('sat_for_hours'))}. "
            "Open Claude Code and ask for a first step?")


def model_message(cmd, t):
    """Ask a model command (e.g. `pi -p`) to WORD the nudge for the already-picked
    task. Returns one line, or None on ANY failure — wording never costs the send."""
    plan = t.get("plan")
    first = plan["steps"][0]["text"] if (plan and plan.get("steps")) else None
    prompt = (
        "Word ONE short push-notification nudge (under 200 characters) for this "
        "stalled task. Kind, not naggy. Name the task and, if given, its prepared "
        "first step so starting is trivial. Output only the message text, no preamble.\n\n"
        f"Task: {t['task']} [{t.get('category')}], sitting {_sat_str(t.get('sat_for_hours'))}"
        + (f"; prepared first step: {first}" if first else "; no plan yet")
    )
    timeout = float(os.environ.get("SIDEKICK_NUDGE_TIMEOUT_SEC", "60"))
    try:
        out = subprocess.run(shlex.split(cmd) + [prompt],
                             capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    line = next((l.strip().strip('"').strip()
                 for l in (out.stdout or "").splitlines() if l.strip()), "")
    if not line or line.upper().replace(" ", "").startswith("NUDGE:NONE") or line.upper() == "NONE":
        return None
    return line[:300]


def decide(active, min_sat, cmd=""):
    """(title, body, source) or None for silence. The DECISION (send vs silent,
    which task) is always deterministic; `cmd` affects wording only."""
    t = pick_task(active, min_sat)
    if t is None:
        return None
    if cmd:
        worded = model_message(cmd, t)
        if worded:
            return ("Sidekick", worded, "model")
    return ("Sidekick", deterministic_message(t), "deterministic")


def run(config=None, dry_run=False):
    config = config or load_config()
    sidekick.configure(config.vault)
    active = sidekick.read_active()          # lock-free read, same as GET /feed
    min_sat = float(os.environ.get("SIDEKICK_NUDGE_MIN_SAT_HOURS",
                                   str(DEFAULT_MIN_SAT_HOURS)))
    cmd = os.environ.get("SIDEKICK_NUDGE_CMD", "").strip()
    decision = decide(active, min_sat, cmd)
    if decision is None:
        print(f"nudge: silent (open={len(active)}, none sat >= {min_sat:g}h)")
        return 0
    title, body, source = decision
    if dry_run:
        print(f"nudge DRY-RUN [{source}] -> {NUDGE_IDENTITY}: {body}")
        return 0
    delivered = push.send_to_identity(config, NUDGE_IDENTITY, title, body)
    print(f"nudge [{source}]: delivered to {delivered} subscription(s): {body}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Sidekick web-push nudge (daily)")
    ap.add_argument("--dry-run", action="store_true", help="decide + print, send nothing")
    args = ap.parse_args(argv)
    try:
        return run(dry_run=args.dry_run)
    except Exception as e:
        print(f"nudge: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests/test_nudge_job.py -q`
Expected: `20 passed`

- [ ] **Step 5: Commit**

```bash
git add server/nudge_job.py server/tests/test_nudge_job.py
git commit -m "server: nudge_job — deterministic decide, optional model wording, push to dalton"
```

---

### Task 4: Sync-pull failure alerts through the push channel

The git-sync plan deferred "alert via nudger channel if pull conflicts persist" to this sub-project — this task closes it. A streak file in `.git/` (never stageable) counts consecutive failures; the 3rd in a row sends ONE push alert to Dalton; success resets. An alert failure never masks the sync failure.

**Files:**
- Modify: `server/sync_pull.py`
- Test: `server/tests/test_sync_pull.py` (append)

**Interfaces:**
- Consumes: `push.send_to_identity` from Task 1; existing `run(config)` unchanged.
- Produces: `main()` keeps its contract (0 success / 1 error, same stdout/stderr lines — the existing `test_main_exit_codes` must keep passing) and additionally maintains `<vault>/.git/sidekick-sync-failures`, alerting `ALERT_IDENTITY = "dalton"` exactly when the streak hits `ALERT_AFTER = 3`.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/test_sync_pull.py`:

```python
# ── failure-streak alert (sub-project 4: closes the git-sync plan's deferral) ──

def _make_conflict(vault_repo, bare_remote, tmp_path, name="clash.md"):
    _push_remote_task(bare_remote, tmp_path, name, "remote content\n")
    (vault_repo / "tasks" / name).write_text("local content\n", encoding="utf-8")
    git(["add", "-A"], vault_repo)
    git(["commit", "-m", f"local {name}"], vault_repo)


def test_alert_fires_once_on_third_consecutive_failure(vault_repo, bare_remote, tmp_path,
                                                       monkeypatch, capsys):
    from server import sync_pull, push
    monkeypatch.setenv("SIDEKICK_VAULT", str(vault_repo))
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "test-token")
    _make_conflict(vault_repo, bare_remote, tmp_path)
    alerts = []
    monkeypatch.setattr(push, "send_to_identity",
                        lambda config, name, title, body: (alerts.append((name, body)), 1)[1])
    assert sync_pull.main() == 1
    assert sync_pull.main() == 1
    assert alerts == []                      # not yet
    assert sync_pull.main() == 1
    assert len(alerts) == 1                  # exactly on the third
    assert alerts[0][0] == "dalton" and "3" in alerts[0][1]
    assert sync_pull.main() == 1
    assert len(alerts) == 1                  # once per streak, not every run
    capsys.readouterr()


def test_success_resets_the_streak(vault_repo, bare_remote, tmp_path, monkeypatch, capsys):
    from server import sync_pull
    monkeypatch.setenv("SIDEKICK_VAULT", str(vault_repo))
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "test-token")
    streak = vault_repo / ".git" / "sidekick-sync-failures"
    streak.write_text("2", encoding="utf-8")
    _push_remote_task(bare_remote, tmp_path, "fine.md", "ok\n")
    assert sync_pull.main() == 0
    assert not streak.exists()
    capsys.readouterr()


def test_alert_failure_never_masks_the_sync_error(vault_repo, bare_remote, tmp_path,
                                                  monkeypatch, capsys):
    from server import sync_pull, push
    monkeypatch.setenv("SIDEKICK_VAULT", str(vault_repo))
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "test-token")
    _make_conflict(vault_repo, bare_remote, tmp_path)
    (vault_repo / ".git" / "sidekick-sync-failures").write_text("2", encoding="utf-8")

    def boom(*a, **kw):
        raise RuntimeError("web push not configured")

    monkeypatch.setattr(push, "send_to_identity", boom)
    assert sync_pull.main() == 1             # still the sync failure's exit code
    assert "sync-pull:" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_sync_pull.py -q`
Expected: the pre-existing tests pass; the 3 new tests fail (no streak file is written, so `test_alert_fires_once...` fails its `len(alerts) == 1` assert, `test_success_resets_the_streak` fails `not streak.exists()`, and the mask test fails only if `main()` misbehaves)

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `server/sync_pull.py` (currently 36 lines; `run()` is carried over unchanged) with:

```python
"""Periodic pull for the serving clone — the systemd-timer half of two-way sync.
The API publishes on every write (commit_and_push); this job brings in everything
pushed from elsewhere (Mac, claude.ai/code, the agent) between writes. It holds
the same inter-process vault lock as the API, so a pull never races a task write.
Deterministic; no model logic. Repeated failures alert Dalton over web push
(server.push) — once per streak, on the ALERT_AFTER-th consecutive failure; the
streak file lives inside .git/ so `git add -A` can never stage it."""
import os
import sys

from server import git_sync, push
from server.config import load_config
from server.vault_lock import vault_lock

ALERT_AFTER = 3          # consecutive failures before the one push alert
ALERT_IDENTITY = "dalton"


def run(config=None):
    """Pull the vault up to date. Returns "disabled", "updated" or "unchanged";
    raises git_sync.GitSyncError on conflict (after a clean rebase --abort)."""
    config = config or load_config()
    if not config.push:
        # push=False marks a dev/offline instance: no remote to track, so no pull
        return "disabled"
    with vault_lock(config.vault):
        return git_sync.pull_latest(config.vault, remote=config.remote)


def _streak_path(vault):
    return os.path.join(vault, ".git", "sidekick-sync-failures")


def _read_streak(vault):
    try:
        with open(_streak_path(vault), encoding="utf-8") as f:
            return int(f.read().strip() or 0)
    except (FileNotFoundError, ValueError, OSError):
        return 0


def _note_success(config):
    try:
        os.unlink(_streak_path(config.vault))
    except OSError:
        pass


def _note_failure(config, exc):
    """Count consecutive failures; on the ALERT_AFTER-th, alert Dalton via web
    push. Best-effort only — an alert problem must never mask the sync failure."""
    streak = _read_streak(config.vault) + 1
    try:
        with open(_streak_path(config.vault), "w", encoding="utf-8") as f:
            f.write(str(streak))
    except OSError:
        return
    if streak == ALERT_AFTER:
        try:
            push.send_to_identity(config, ALERT_IDENTITY, "Sidekick sync failing",
                                  f"git pull has failed {streak}x in a row: {exc}")
        except Exception as e:
            print(f"sync-pull: alert failed ({e})", file=sys.stderr)


def main():
    try:
        config = load_config()
    except Exception as e:
        print(f"sync-pull: {e}", file=sys.stderr)
        return 1
    try:
        result = run(config)
    except Exception as e:
        print(f"sync-pull: {e}", file=sys.stderr)
        _note_failure(config, e)
        return 1
    _note_success(config)
    print(f"sync-pull: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full server suite**

Run: `python3 -m pytest server/tests/ -q`
Expected: all pass, `0 failed` (including the pre-existing `test_main_exit_codes` — the stdout/stderr contract is unchanged)

- [ ] **Step 5: Commit**

```bash
git add server/sync_pull.py server/tests/test_sync_pull.py
git commit -m "server: sync-pull alerts dalton via web push after 3 consecutive failures"
```

---

### Task 5: systemd units + deploy/CLAUDE.md docs

**Files:**
- Create: `deploy/sidekick-nudge.service`, `deploy/sidekick-nudge.timer`
- Modify: `deploy/README.md` (new section after "Enable the sync timer"), `CLAUDE.md` (nudge section intro)

**Interfaces:**
- Consumes: `python -m server.nudge_job` from Task 3; `/etc/sidekick.env` + `/srv/sidekick` + `User=sidekick` + hardening conventions from `deploy/sidekick.service` / `deploy/sidekick-sync.service`.
- Produces: unit files an operator copies to `/etc/systemd/system/`. **Timezone decision (explicit):** systemd timers evaluate `OnCalendar` in the SYSTEM timezone (the VPS runs UTC), but systemd ≥ 235 accepts an explicit timezone inside the spec — Ubuntu 24.04 ships systemd 255. We use `OnCalendar=*-*-* 09:00:00 Europe/Copenhagen` rather than hardcoding `07:00 UTC`, so DST transitions never shift the nudge hour.

- [ ] **Step 1: Write the service unit**

Create `deploy/sidekick-nudge.service`:

```ini
[Unit]
Description=Sidekick daily nudge (web push)
Documentation=https://github.com/FellowDalton/sidekick/blob/main/deploy/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=sidekick
Group=sidekick
WorkingDirectory=/srv/sidekick
EnvironmentFile=/etc/sidekick.env
ExecStart=/srv/sidekick/.venv/bin/python -m server.nudge_job
# A hung model-wording call must not linger (the job caps wording at 60s anyway).
TimeoutStartSec=180
# Same hardening posture as sidekick.service: only its own clone.
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true
```

- [ ] **Step 2: Write the timer unit**

Create `deploy/sidekick-nudge.timer`:

```ini
[Unit]
Description=Run the sidekick nudge daily at 09:00 Copenhagen time

[Timer]
# The timezone is explicit IN the OnCalendar spec (systemd >= 235; Ubuntu 24.04
# ships 255), so this fires at 09:00 Europe/Copenhagen regardless of the VPS's
# system timezone (UTC) and stays correct across DST transitions.
OnCalendar=*-*-* 09:00:00 Europe/Copenhagen
# Box asleep/rebooting at 09:00? Fire on next boot instead of skipping the day.
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Document setup in `deploy/README.md`**

Locate the end of the existing sync-timer section:

```markdown
A conflicting pull exits 1 with the vault left clean (rebase aborted); check
`journalctl -u sidekick-sync.service` if the phones stop seeing Mac-side changes.
```

and insert after it:

```markdown
## Web-push nudges (daily, 09:00 Copenhagen)

The VPS sends the daily nudge as a web-push notification (`server/nudge_job.py`).
One-time setup on the VPS:

    # 1. deps into the venv (pywebpush is in server/requirements.txt)
    sudo -u sidekick /srv/sidekick/.venv/bin/pip install -r /srv/sidekick/server/requirements.txt

    # 2. generate the VAPID keypair — prints two env lines, paste them into /etc/sidekick.env
    sudo -u sidekick /srv/sidekick/.venv/bin/python - <<'EOF'
    import base64
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    print("SIDEKICK_VAPID_PRIVATE=" + b64(key.private_numbers().private_value.to_bytes(32, "big")))
    print("SIDEKICK_VAPID_PUBLIC=" + b64(key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)))
    EOF

Add to `/etc/sidekick.env` (one line each, values unquoted):

    SIDEKICK_VAPID_PRIVATE=...          # from the generator above
    SIDEKICK_VAPID_PUBLIC=...           # from the generator above
    SIDEKICK_VAPID_SUB=mailto:nikoflash@gmail.com
    SIDEKICK_NUDGE_MIN_SAT_HOURS=48     # optional; this is the default
    # SIDEKICK_NUDGE_CMD=pi -p          # optional model wording — leave unset until
    #                                     pi lands on the box (agent-runner sub-project);
    #                                     unset = deterministic wording, always works

Then install and verify:

    sudo systemctl restart sidekick     # the API serves the public key from the env
    sudo cp deploy/sidekick-nudge.service deploy/sidekick-nudge.timer /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now sidekick-nudge.timer

    systemctl list-timers sidekick-nudge.timer   # next run: 09:00 Europe/Copenhagen
    sudo -u sidekick bash -c 'set -a; . /etc/sidekick.env; cd /srv/sidekick && .venv/bin/python -m server.nudge_job --dry-run'
    sudo systemctl start sidekick-nudge.service && journalctl -u sidekick-nudge -n 3

Phone (Dalton's iPhone; the shared-role token gets no push this phase):

1. Open the **installed** (Home-Screen) Sidekick app — iOS only allows web push there,
   never in a plain Safari tab.
2. Settings → **Enable notifications** → Allow when iOS asks.
3. With a stalled task present, `sudo systemctl start sidekick-nudge.service` → the
   banner arrives on the phone.

Subscriptions live in `/srv/sidekick/.sidekick-push.json` (gitignored). The sync job
uses the same channel: three consecutive `git pull` failures send one alert.
The old Mac path (`nudge.py` + launchd + Beeper) remains the documented offline fallback.
```

- [ ] **Step 4: Demote nudge.py in `CLAUDE.md`**

Locate:

```markdown
`nudge.py` is fired by **launchd** (not Claude Code — a session can't push itself). It reads the vault, decides whether to nudge, and sends one message to you via Beeper → iMessage.
```

and replace with:

```markdown
**The VPS is the primary nudge path now:** `server/nudge_job.py` + `deploy/sidekick-nudge.timer` send the daily nudge as a web-push notification to the phone (setup: `deploy/README.md` → "Web-push nudges"). Everything below is the **offline fallback** for when the VPS route is down.

`nudge.py` is fired by **launchd** (not Claude Code — a session can't push itself). It reads the vault, decides whether to nudge, and sends one message to you via Beeper → iMessage.
```

(Only the first sentence block gains the preamble; the rest of the paragraph and section stay as-is.)

- [ ] **Step 5: Verify nothing broke, then commit**

Run: `python3 -m pytest server/tests/ -q && python3 -m pytest tests/ -q`
Expected: all pass (units and docs are not executed by tests — this is the regression gate)

```bash
git add deploy/sidekick-nudge.service deploy/sidekick-nudge.timer deploy/README.md CLAUDE.md
git commit -m "deploy: sidekick-nudge timer (09:00 Europe/Copenhagen) + web-push docs"
```

---

### Task 6: Web API client + `enablePush()` flow

**Files:**
- Modify: `web/src/lib/api.ts`, `web/src/lib/api.test.ts`
- Create: `web/src/lib/push.ts`
- Test: `web/src/lib/push.test.ts`

**Interfaces:**
- Consumes: existing `base()` / `headers()` / `handle()` in `api.ts`; browser `Notification`, `navigator.serviceWorker`, `PushManager` (all stubbed in tests).
- Produces: `getVapidPublicKey(): Promise<string>`; `subscribePush(sub: PushSubscriptionJSON): Promise<void>`; `pushSupported(): boolean`; `enablePush(): Promise<"enabled" | "denied" | "unsupported">` — MUST be called from a user gesture (iOS grants `Notification.requestPermission` only then, and only in the installed PWA).

- [ ] **Step 1: Write the failing tests**

In `web/src/lib/api.test.ts`, locate the import line:

```ts
import { getFeed, getMe, createTask, completeTask, ApiError } from "./api";
```

replace it with:

```ts
import { getFeed, getMe, createTask, completeTask, getVapidPublicKey, subscribePush, ApiError } from "./api";
```

and append to the end of the file:

```ts
describe("push api", () => {
  it("GETs the VAPID public key with the bearer token", async () => {
    const f = mockFetch(200, { key: "BPubKey" });
    vi.stubGlobal("fetch", f);
    expect(await getVapidPublicKey()).toBe("BPubKey");
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/push/vapid-public-key");
    expect(opts.headers["Authorization"]).toBe("Bearer t0ken");
  });

  it("POSTs the subscription JSON to /api/push/subscribe", async () => {
    const f = mockFetch(200, { ok: true, subscriptions: 1 });
    vi.stubGlobal("fetch", f);
    const sub = { endpoint: "https://push.example/e", keys: { p256dh: "p", auth: "a" } };
    await subscribePush(sub as PushSubscriptionJSON);
    const [url, opts] = f.mock.calls[0];
    expect(url).toBe("/api/push/subscribe");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual(sub);
  });

  it("surfaces 503 when push is not configured on the host", async () => {
    vi.stubGlobal("fetch", mockFetch(503, { error: "web push not configured" }));
    await expect(getVapidPublicKey()).rejects.toMatchObject({ status: 503 });
  });
});
```

Create `web/src/lib/push.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { enablePush, pushSupported } from "./push";
import { settings } from "./settings";

const SUB_JSON = { endpoint: "https://push.example/e", keys: { p256dh: "p", auth: "a" } };

const subscribe = vi.fn(async (_opts?: PushSubscriptionOptionsInit) => ({ toJSON: () => SUB_JSON }));

function mockApiFetch() {
  return vi.fn(async (url: string) => {
    if (url === "/api/push/vapid-public-key")
      return new Response(JSON.stringify({ key: "BFakeServerKey" }), {
        status: 200, headers: { "Content-Type": "application/json" }
      });
    if (url === "/api/push/subscribe")
      return new Response(JSON.stringify({ ok: true, subscriptions: 1 }), {
        status: 200, headers: { "Content-Type": "application/json" }
      });
    throw new Error(`unexpected fetch: ${url}`);
  });
}

function stubPushEnv(permission: NotificationPermission = "granted") {
  vi.stubGlobal("Notification", { requestPermission: vi.fn(async () => permission) });
  vi.stubGlobal("PushManager", function () { /* presence check only */ });
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { ready: Promise.resolve({ pushManager: { subscribe } }) }
  });
}

beforeEach(() => {
  settings.set({ token: "t0ken", apiBase: "" });
  subscribe.mockClear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete (navigator as any).serviceWorker;   // keep pushSupported() honest again
});

describe("enablePush", () => {
  it("permission → subscribe with the server's VAPID key → POST /api/push/subscribe", async () => {
    stubPushEnv();
    const f = mockApiFetch();
    vi.stubGlobal("fetch", f);
    expect(await enablePush()).toBe("enabled");
    const opts = subscribe.mock.calls[0][0]!;
    expect(opts.userVisibleOnly).toBe(true);
    expect(opts.applicationServerKey).toBeInstanceOf(Uint8Array);
    const post = f.mock.calls.find(([u]) => u === "/api/push/subscribe");
    expect(post).toBeDefined();
  });

  it("returns 'denied' without subscribing or touching the network", async () => {
    stubPushEnv("denied");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("no network expected"); }));
    expect(await enablePush()).toBe("denied");
    expect(subscribe).not.toHaveBeenCalled();
  });

  it("returns 'unsupported' when the push APIs are missing (plain jsdom)", async () => {
    expect(pushSupported()).toBe(false);
    expect(await enablePush()).toBe("unsupported");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npm test`
Expected: failures — `api.test.ts` cannot import `getVapidPublicKey` / `subscribePush`; `push.test.ts` fails resolving `./push`

- [ ] **Step 3: Write the implementation**

Append to `web/src/lib/api.ts`:

```ts
export async function getVapidPublicKey(): Promise<string> {
  const res = await handle(await fetch(`${base()}/api/push/vapid-public-key`, { headers: headers() }));
  return res.key;
}

export async function subscribePush(sub: PushSubscriptionJSON): Promise<void> {
  await handle(await fetch(`${base()}/api/push/subscribe`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(sub)
  }));
}
```

Create `web/src/lib/push.ts`:

```ts
// Client half of web push (spec sub-project 4). On iOS ALL of these must hold:
// the PWA is installed (Home Screen), the call happens inside a user gesture,
// and the user grants Notification permission. The VAPID public key comes from
// the server (GET /api/push/vapid-public-key) so it is never hardcoded here.
import { getVapidPublicKey, subscribePush } from "./api";

export type EnableResult = "enabled" | "denied" | "unsupported";

export function pushSupported(): boolean {
  return typeof Notification !== "undefined"
    && "serviceWorker" in navigator
    && "PushManager" in window;
}

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const b64 = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(b64);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Must be called from a user gesture (the Settings button click). */
export async function enablePush(): Promise<EnableResult> {
  if (!pushSupported()) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") return "denied";
  const key = await getVapidPublicKey();
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(key)
  });
  await subscribePush(sub.toJSON());
  return "enabled";
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npm test`
Expected: all test files pass, `0 failed`

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/lib/api.test.ts web/src/lib/push.ts web/src/lib/push.test.ts
git commit -m "web: push api client + enablePush() subscribe flow"
```

---

### Task 7: Settings page — Enable notifications

**Files:**
- Modify: `web/src/routes/settings/+page.svelte`
- Test: `web/src/routes/settings/settings.test.ts` (rewritten: the two existing tests are kept verbatim, push tests added)

**Interfaces:**
- Consumes: `enablePush` from Task 6 (mocked in tests).
- Produces: a "Notifications" section with an **Enable notifications** button (the required user gesture) and honest status lines for `enabled` / `denied` / `unsupported` / thrown errors.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `web/src/routes/settings/settings.test.ts` with:

```ts
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/svelte";
import { get } from "svelte/store";
import Settings from "./+page.svelte";
import { settings } from "$lib/settings";
import { enablePush } from "$lib/push";

vi.mock("$lib/push", () => ({
  enablePush: vi.fn(async () => "enabled" as const)
}));

beforeEach(() => {
  settings.set({ token: "", apiBase: "" });
  vi.mocked(enablePush).mockClear();
  vi.mocked(enablePush).mockResolvedValue("enabled");
});

describe("Settings", () => {
  it("writes the entered token into the settings store", async () => {
    render(Settings);
    await fireEvent.input(screen.getByLabelText(/token/i), { target: { value: "secret-123" } });
    expect(get(settings).token).toBe("secret-123");
  });

  it("prefills from the existing settings", () => {
    settings.set({ token: "abc", apiBase: "" });
    render(Settings);
    expect((screen.getByLabelText(/token/i) as HTMLInputElement).value).toBe("abc");
  });
});

describe("Settings — notifications", () => {
  it("runs the enable-push flow from the button (the user gesture)", async () => {
    render(Settings);
    await fireEvent.click(screen.getByRole("button", { name: /enable notifications/i }));
    expect(enablePush).toHaveBeenCalledOnce();
    expect(await screen.findByText(/notifications enabled/i)).toBeInTheDocument();
  });

  it("explains a denied permission", async () => {
    vi.mocked(enablePush).mockResolvedValue("denied");
    render(Settings);
    await fireEvent.click(screen.getByRole("button", { name: /enable notifications/i }));
    expect(await screen.findByText(/permission denied/i)).toBeInTheDocument();
  });

  it("explains unsupported browsers (iOS Safari outside the installed app)", async () => {
    vi.mocked(enablePush).mockResolvedValue("unsupported");
    render(Settings);
    await fireEvent.click(screen.getByRole("button", { name: /enable notifications/i }));
    expect(await screen.findByText(/home screen/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npm test`
Expected: the two carried-over tests pass; the three notifications tests fail (no button named "Enable notifications" renders yet)

- [ ] **Step 3: Write the implementation**

Replace the entire contents of `web/src/routes/settings/+page.svelte` with:

```svelte
<script lang="ts">
  import { settings } from "$lib/settings";
  import { enablePush, type EnableResult } from "$lib/push";

  let token = $state($settings.token);
  let apiBase = $state($settings.apiBase);
  let pushState = $state<"" | "working" | "error" | EnableResult>("");

  // keep the store in sync as the user types (persists to localStorage via the store)
  $effect(() => { settings.set({ token: token.trim(), apiBase: apiBase.trim() }); });

  // MUST run inside the click handler: iOS only grants Notification permission
  // from a user gesture, and only in the installed (Home-Screen) PWA.
  async function onEnablePush() {
    pushState = "working";
    try {
      pushState = await enablePush();
    } catch {
      pushState = "error";
    }
  }
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Settings</h1>
<label class="field">
  <span>API token</span>
  <input type="password" bind:value={token} placeholder="paste your bearer token" autocomplete="off" />
</label>
<label class="field">
  <span>API base URL (optional)</span>
  <input type="text" bind:value={apiBase} placeholder="leave blank to use this site (/api)" autocomplete="off" />
</label>
<p class="muted">Stored only in this browser. Leave the base URL blank in normal use — the app proxies <code>/api</code> to the host.</p>
{#if token.trim()}<p class="msg-ok">Token saved. Open the Dashboard.</p>{/if}

<h2 class="tc-name" style="font-size:18px;margin:26px 0 10px">Notifications</h2>
<button class="btn btn-primary" onclick={onEnablePush} disabled={pushState === "working"}>
  {pushState === "working" ? "Enabling…" : "Enable notifications"}
</button>
{#if pushState === "enabled"}
  <p class="msg-ok">Notifications enabled on this device.</p>
{:else if pushState === "denied"}
  <p class="muted">Permission denied — allow notifications for Sidekick in the phone's settings, then try again.</p>
{:else if pushState === "unsupported"}
  <p class="muted">This browser can't receive push. On iPhone, add Sidekick to the Home Screen and open it from there first.</p>
{:else if pushState === "error"}
  <p class="muted">Couldn't subscribe — check the API token, then try again.</p>
{/if}
<p class="muted">One nudge a day at 09:00, and only when something's genuinely stalled.</p>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npm test`
Expected: all test files pass, `0 failed`

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/settings/+page.svelte web/src/routes/settings/settings.test.ts
git commit -m "web: Enable-notifications button in Settings (user-gesture push opt-in)"
```

---

### Task 8: Service-worker push handler

**Files:**
- Create: `web/static/push-sw.js`
- Modify: `web/vite.config.ts`

**Interfaces:**
- Consumes: the generated workbox SW (generateSW mode — unchanged strategy). `@vite-pwa/sveltekit` passes `workbox.importScripts` straight through to workbox-build's `generateSW`, which emits an `importScripts("push-sw.js")` line into the generated `sw.js` — the smallest correct way to add handlers without switching to `injectManifest` and re-owning precache/NetworkFirst by hand. Files in `web/static/` are copied to the build root, so the URL resolves inside the SW scope.
- Produces: `push` handler (shows a notification from the `{title, body}` JSON payload sent by `server/push.py`) and `notificationclick` handler (focuses the open PWA or opens `/`, the manifest `start_url`). Kept deliberately tiny: it is exercised by the build check below plus the documented manual device check (Deployment note) — no cheap unit-test harness exists for SW event handlers and the logic is 25 lines of platform calls.

- [ ] **Step 1: Write the handler**

Create `web/static/push-sw.js`:

```js
// Imported into the generated service worker via workbox `importScripts`
// (see vite.config.ts). Payload contract with server/push.py: {"title","body"}.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    /* non-JSON payload: fall through to defaults */
  }
  const title = data.title || "Sidekick";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    data: { url: "/" }
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if ("focus" in c) return c.focus();
      }
      return self.clients.openWindow(url);
    })
  );
});
```

- [ ] **Step 2: Wire it into the generated SW**

In `web/vite.config.ts`, locate:

```ts
      workbox: {
        globPatterns: ["**/*.{js,css,html,png,svg,woff2}"],
```

and replace with:

```ts
      workbox: {
        // static/push-sw.js carries the push + notificationclick handlers; importScripts
        // keeps us in generateSW mode (precache + NetworkFirst config stay generated).
        importScripts: ["push-sw.js"],
        globPatterns: ["**/*.{js,css,html,png,svg,woff2}"],
```

- [ ] **Step 3: Verify the build wires it up and nothing regressed**

Run: `cd web && npm test && npm run build`
Expected: tests pass; build succeeds

Run: `grep -o 'importScripts([^)]*)' web/build/sw.js | head -1 && ls web/build/push-sw.js`
Expected: an `importScripts(...)` line referencing `push-sw.js`, and the file present in the build output

Run: `grep -c "sidekick-feed" web/build/sw.js`
Expected: `1` or more (the existing NetworkFirst runtime cache is still in the generated SW)

- [ ] **Step 4: Commit**

```bash
git add web/static/push-sw.js web/vite.config.ts
git commit -m "web: service-worker push + notificationclick handlers via workbox importScripts"
```

---

## Deployment note (manual ops, after merge)

This closes the git-sync plan's deferral: sync-pull failures now alert over the nudger channel (3 consecutive failures → one push, reset on success).

Not part of the code tasks — on the VPS, after `sudo -u sidekick git -C /srv/sidekick pull`:

1. **Install the dependency:** `sudo -u sidekick /srv/sidekick/.venv/bin/pip install -r /srv/sidekick/server/requirements.txt` (brings in `pywebpush` + its `cryptography`).
2. **Generate the VAPID keypair** (one-time; keys never rotate casually — rotating invalidates every stored subscription):
   ```bash
   sudo -u sidekick /srv/sidekick/.venv/bin/python - <<'EOF'
   import base64
   from cryptography.hazmat.primitives.asymmetric import ec
   from cryptography.hazmat.primitives import serialization
   key = ec.generate_private_key(ec.SECP256R1())
   b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
   print("SIDEKICK_VAPID_PRIVATE=" + b64(key.private_numbers().private_value.to_bytes(32, "big")))
   print("SIDEKICK_VAPID_PUBLIC=" + b64(key.public_key().public_bytes(
       serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)))
   EOF
   ```
3. **Append to `/etc/sidekick.env`:** the two printed lines, plus `SIDEKICK_VAPID_SUB=mailto:nikoflash@gmail.com` and optionally `SIDEKICK_NUDGE_MIN_SAT_HOURS=48`. Leave `SIDEKICK_NUDGE_CMD` **unset** until pi is installed (sub-project 3) — the job is deterministic-only without it.
4. **Rebuild + restart:** re-run `sudo bash /srv/sidekick/deploy/bootstrap.sh` (rebuilds the web bundle so the new service worker ships, refreshes the venv, restarts services) — or minimally `sudo systemctl restart sidekick` if only the env changed.
5. **Install the timer:** `sudo cp deploy/sidekick-nudge.service deploy/sidekick-nudge.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now sidekick-nudge.timer`. Verify with `systemctl list-timers sidekick-nudge.timer` (next run 09:00 Europe/Copenhagen) and a dry run: `sudo -u sidekick bash -c 'set -a; . /etc/sidekick.env; cd /srv/sidekick && .venv/bin/python -m server.nudge_job --dry-run'`.
6. **iPhone:** open the **installed** (Home-Screen) Sidekick app — close and reopen once so the auto-updating service worker picks up the push handler — then Settings → **Enable notifications** → Allow. End-to-end check: with a task sitting past the threshold, `sudo systemctl start sidekick-nudge.service` and watch the banner land; `journalctl -u sidekick-nudge -n 3` shows what was decided.
7. **Honest iOS caveat:** web push works **only** in the installed (Home-Screen) PWA on iOS 16.4+ — never in a plain Safari tab — and delivery is best-effort under OS throttling: the nudge is a nudge, not an alarm. If iOS revokes the subscription (app deleted/reinstalled), the send prunes the dead endpoint and the fix is tapping **Enable notifications** again. The wife's phone needs none of this — she receives no push this phase (a "new shared task" ping is explicitly deferred). The Mac's `nudge.py` + launchd + Beeper path stays in the repo as the documented offline fallback.
