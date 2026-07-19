# Task Descriptions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Optional multiline descriptions on tasks — entered at capture, shown clamped/expandable on dashboard cards and list rows, editable in place.

**Architecture:** `description:` frontmatter (never the markdown body — that stays orchestrator prose space); engine `create_task(description=)` + `set_description()`; `POST /tasks/{id}/description` endpoint mirroring `complete`'s role rules; web textarea capture + clamp/expand/edit UI.

**Tech Stack:** Python 3 + pyyaml (engine), FastAPI + pytest (server), SvelteKit / Svelte 5 runes + vitest + @testing-library/svelte (web).

**Spec:** `docs/superpowers/specs/2026-07-19-task-descriptions-design.md`

## Global Constraints

- `sidekick.py` deterministic, pyyaml only; `ledger.jsonl` written ONLY by `complete()`; engine validation raises `ValueError` (the CLI dispatch's existing try/except converts).
- The `description` frontmatter field is NEVER written empty/null — absent means none; clearing removes the field.
- Server cap: description max **4000** chars after strip; longer → 400. Empty/whitespace at create → treated as absent; at the describe endpoint → clears.
- The describe endpoint's role rules mirror `POST /tasks/{id}/complete` exactly: shared role sees 404 for personal tasks (indistinguishable from missing), checked before anything else.
- Done children never render descriptions in the UI.
- Server tests: `python3 -m pytest server/tests -q` (repo root). Web tests: `cd web && npm test`.

---

### Task 1: Engine — `description` on create, `set_description`, feed passthrough

**Files:**
- Modify: `sidekick.py`
- Test: `server/tests/test_engine_description.py` (create)

**Interfaces:**
- Produces: `create_task(..., description=None)` (strip; empty → field omitted); `set_description(task_id, text)` — strip; non-empty sets `fm["description"]`, empty removes it; `ValueError` if task missing (`FileNotFoundError` → ValueError) or `fm.status != "open"`; prints `description set on <id>` / `description cleared on <id>`. CLI: `new … --description`, and subcommand `set-description <id> [--file f]` (text from `--file` or stdin, mirroring `set-plan`), both regenerating. Feed: active items (both open and done branches in `read_active`) gain `"description": fm.get("description")`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_engine_description.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_engine_description.py -q`
Expected: FAIL — unexpected keyword `description` / no attribute `set_description` / KeyError.

- [ ] **Step 3: Implement**

In `sidekick.py`:

1. `create_task` — add the keyword and conditional write (beside the `list_` handling):

```python
def create_task(title, category, *, from_=None, shared=False, parent=None, list_=None,
                description=None):
```
and after the `if list_:` block:
```python
    description = (description or "").strip()
    if description:
        fm["description"] = description
```

2. New function after `set_plan`:

```python
def set_description(task_id, text):
    """Set, replace, or clear the task's free-text description (frontmatter field —
    the markdown body stays the orchestrator's space). Empty/whitespace text clears.
    ValueError on a missing or non-open task."""
    try:
        fm, body = read_note(task_path(task_id))
    except FileNotFoundError:
        raise ValueError(f"no such task: {task_id}")
    if fm.get("status", "open") != "open":
        raise ValueError(f"task is not open: {task_id}")
    text = (text or "").strip()
    if text:
        fm["description"] = text
        write_note(task_path(task_id), fm, body)
        print(f"description set on {task_id}")
    else:
        fm.pop("description", None)
        write_note(task_path(task_id), fm, body)
        print(f"description cleared on {task_id}")
```

3. `read_active` — add `"description": fm.get("description"),` to BOTH the open and done item dicts.

4. CLI — `new` parser gains `pn.add_argument("--description", default=None, help="optional details shown on the task")`; new subcommand beside `set-plan`:

```python
    pd2 = sub.add_parser("set-description"); pd2.add_argument("id")
    pd2.add_argument("--file", help="text file; omit to read stdin")
```

dispatch (inside the existing try): `new` passes `description=a.description`; and:

```python
        elif a.cmd == "set-description":
            raw = open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read()
            set_description(a.id, raw); regenerate()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests -q` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add sidekick.py server/tests/test_engine_description.py
git commit -m "engine: task descriptions — create --description, set-description, feed field"
```

---

### Task 2: Server — create with description + `POST /tasks/{id}/description`

**Files:**
- Modify: `server/app.py`
- Test: `server/tests/test_api_description.py` (create)

**Interfaces:**
- Consumes: Task 1's engine.
- Produces: `POST /tasks` optional `description` (400 non-string or > 4000 after strip; empty → not forwarded). `POST /tasks/{task_id}/description` `{description}`: 400 missing/non-string/oversize; shared-role 404 masking BEFORE all else (mirror `post_complete`); 404 unknown; 409 non-open (from the engine's ValueError); empty clears; idempotency + vault lock + regenerate + commit `api: describe <id>`; 200 → the updated active entry.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_api_description.py`:

```python
"""Task-description endpoints (task-descriptions spec, 2026-07-19)."""
import sidekick

from server.tests.conftest import AUTH


def _mk(client, title="Buy paint", **extra):
    body = {"title": title, "category": "errand", **extra}
    r = client.post("/tasks", headers=AUTH, json=body)
    assert r.status_code == 201
    return r.json()


def test_create_task_with_description(client):
    entry = _mk(client, description="Matte white,\ntwo cans")
    assert entry["description"] == "Matte white,\ntwo cans"


def test_create_task_description_validation(client):
    r = client.post("/tasks", headers=AUTH,
                    json={"title": "X", "category": "errand", "description": 5})
    assert r.status_code == 400
    r = client.post("/tasks", headers=AUTH,
                    json={"title": "X", "category": "errand", "description": "y" * 4001})
    assert r.status_code == 400


def test_describe_sets_and_clears(client):
    entry = _mk(client)
    r = client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                    json={"description": "Two cans"})
    assert r.status_code == 200
    assert r.json()["description"] == "Two cans"
    r = client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                    json={"description": "  "})
    assert r.status_code == 200
    assert r.json()["description"] is None


def test_describe_errors(client, app_config):
    assert client.post("/tasks/20990101-nope/description", headers=AUTH,
                       json={"description": "x"}).status_code == 404
    entry = _mk(client)
    assert client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                       json={}).status_code == 400
    assert client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                       json={"description": "y" * 4001}).status_code == 400
    sidekick.configure(app_config.vault)
    sidekick.complete(entry["id"])
    assert client.post(f"/tasks/{entry['id']}/description", headers=AUTH,
                       json={"description": "x"}).status_code == 409
```

Add one shared-role masking test following the exact fixture pattern `server/tests/test_api_roles.py` uses for the complete endpoint (token-map config with a shared token): a shared-role caller describing a PERSONAL task gets 404 (not 403); describing a SHARED task succeeds. Mirror that file's client/fixture construction verbatim.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_description.py -q`
Expected: KeyError `description` on create; 404s (route missing) on describe.

- [ ] **Step 3: Implement**

In `server/app.py`:

1. Shared validator (near `_read_json`):

```python
    def _clean_description(value):
        """None | stripped string (may be empty). Raises 400 on wrong type/size."""
        if value is None:
            return None
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="description must be a string")
        value = value.strip()
        if len(value) > 4000:
            raise HTTPException(status_code=400,
                                detail="description must be at most 4000 characters")
        return value
```

2. `post_task` — after the `list_id` handling:

```python
        description = _clean_description(data.get("description"))
```

and pass `description=description or None` through to `sidekick.create_task(...)`.

3. New endpoint after `post_complete` (same skeleton):

```python
    @app.post("/tasks/{task_id}/description")
    async def post_description(task_id: str, request: Request,
                               authorization: str = Header(default=""),
                               idempotency_key: str = Header(default="")):
        ident = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        if "description" not in data:
            raise HTTPException(status_code=400, detail="description is required")
        description = _clean_description(data.get("description"))
        if description is None:
            raise HTTPException(status_code=400, detail="description must be a string")

        def run():
            with vault_lock(config.vault):
                if ident["role"] == "shared":
                    # a personal task must be indistinguishable from a missing one
                    try:
                        fm, _ = sidekick.read_note(sidekick.task_path(task_id))
                    except FileNotFoundError:
                        raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                    if not fm.get("shared"):
                        raise HTTPException(status_code=404, detail=f"no such task: {task_id}")
                try:
                    sidekick.set_description(task_id, description)
                except ValueError as e:
                    msg = str(e)
                    if msg.startswith("no such task"):
                        raise HTTPException(status_code=404, detail=msg)
                    raise HTTPException(status_code=409, detail=msg)
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: describe {task_id}",
                                         push=config.push, remote=config.remote)
                entry = next((a for a in sidekick.read_active() if a["id"] == task_id), None)
            return 200, entry

        scope = f"{ident['name']}:{request.url.path}"
        return _idem_replay_or_run(scope, idempotency_key, run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests -q` — full suite green.

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_description.py
git commit -m "server: task descriptions — create field + POST /tasks/{id}/description"
```

---

### Task 3: Web api client + types

**Files:**
- Modify: `web/src/lib/types.ts`, `web/src/lib/api.ts`
- Test: `web/src/lib/api.test.ts` (extend, existing mock style)

**Interfaces:**
- Produces: `ActiveTask.description?: string | null`; `createTask(title, category, shared = false, list?, description?)` — body gains `description` only when non-empty; `setTaskDescription(id: string, description: string): Promise<ActiveTask>` — POST `/api/tasks/{id}/description` with Idempotency-Key.

- [ ] **Step 1: Write the failing tests** (adapt to the file's mocking helpers; assertions are the contract)

```ts
it("createTask includes description only when given", async () => {
  // body: { title, category, shared: true, description: "details" }
});
it("setTaskDescription POSTs to /api/tasks/{id}/description", async () => {
  // url contains "/api/tasks/t1/description"; body { description: "x" };
  // Idempotency-Key header present
});
```

- [ ] **Step 2: fail** → **Step 3: Implement**

`types.ts`: add `description?: string | null;` to `ActiveTask`.
`api.ts`: extend `createTask`'s body construction with `if (description) body.description = description;` (new trailing optional param), and:

```ts
export async function setTaskDescription(id: string, description: string): Promise<ActiveTask> {
  return handle(await fetch(`${base()}/api/tasks/${encodeURIComponent(id)}/description`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ description })
  }));
}
```

- [ ] **Step 4:** `cd web && npm test` green (pre-existing createTask tests unchanged).
- [ ] **Step 5: Commit** — `web: api — createTask description, setTaskDescription`

---

### Task 4: List detail — capture details + row display/edit

**Files:**
- Modify: `web/src/routes/shared/list/[id]/+page.svelte`
- Test: `web/src/routes/shared/list/list-detail.test.ts` (extend)

**Interfaces:**
- Consumes: Task 3's client.
- Produces (behavior): under the add box's title input, a small `+ details` toggle button reveals an auto-growing `<textarea aria-label="Details">`; submit passes the description (when non-empty) to `createTask` and clears both. Open rows with a description show it clamped to 2 lines (`-webkit-line-clamp`), `aria-label="Details for <task>"`, tap toggles expanded; expanded state shows an `Edit` button swapping to a textarea + Save/Cancel wired to `setTaskDescription` with optimistic update (update `feed.active` locally), reload-reconcile on success, rollback + error message on failure. Done rows never render descriptions.

- [ ] **Step 1: Write the failing tests** (extend the existing mock factory with `setTaskDescription: vi.fn()`):

```ts
it("adds a task with details from the expanded textarea", async () => {
  // click "+ details", type into Details textarea, submit form
  // expect createTask called with (title, "chore", true, "groceries", "the details")
});
it("shows a clamped description that expands on tap", async () => {
  // task fixture with description; assert text visible; class toggles on click
});
it("edits a description and saves optimistically", async () => {
  // expand -> Edit -> change textarea -> Save
  // expect setTaskDescription called with (id, newText); row shows newText immediately
});
it("rolls back the description edit on failure", async () => {
  // setTaskDescription rejects; row shows the ORIGINAL text and an error message
});
it("does not render a description on a done row", async () => {
  // done child fixture with description; queryByLabelText("Details for …") is null
});
```

- [ ] **Step 2: fail** → **Step 3: Implement** (follow the component's existing state/error patterns; auto-grow via `rows={3}` + `field-sizing: content` CSS with a max-height fallback comment — keep it simple).
- [ ] **Step 4:** focused file then `cd web && npm test` green.
- [ ] **Step 5: Commit** — `web: list detail — capture details textarea, clamped/editable descriptions`

---

### Task 5: Dashboard cards — description display + edit

**Files:**
- Modify: `web/src/routes/Dashboard.svelte`, `web/src/routes/+page.svelte` (only if a new callback prop is needed)
- Test: `web/src/routes/dashboard.test.ts` (extend)

**Interfaces:**
- Consumes: Task 3's client.
- Produces (behavior): open cards with `t.description` render it between the title row and the plan block, clamped to 2 lines, tap to expand, `Edit` in expanded state (textarea + Save/Cancel → `setTaskDescription`, optimistic via a new optional `onDescribe` prop or direct call — match how the component currently reaches the api: it does NOT call the api directly, it takes callbacks; so add `onDescribe = (id: string, text: string) => {}` prop wired in `+page.svelte` to `setTaskDescription` + optimistic feed update + reload, mirroring `onComplete`). Done children never render descriptions.

- [ ] **Step 1: Write the failing tests:**

```ts
it("renders a clamped description on a card and expands on tap", ...);
it("calls onDescribe with the edited text on Save", ...);
it("does not render a description on a done child card", ...);
```

- [ ] **Step 2: fail** → **Step 3: Implement** (keep the recursive snippet structure; description block only in the `t.status !== "done"` branch).
- [ ] **Step 4:** `cd web && npm test` green.
- [ ] **Step 5: Commit** — `web: dashboard cards — clamped/editable task descriptions`

---

### Task 6: Verification + deploy

- [ ] Both suites green (`python3 -m pytest server/tests -q`; `cd web && npm test`).
- [ ] Throwaway-vault smoke: `new` with `--description`, `set-description` via stdin, regenerate → field in `sidekick-data.js`.
- [ ] Push main; on the VPS: pull serving clone + agent clone, `bash /srv/sidekick/deploy/bootstrap.sh` (web rebuild), `systemctl restart sidekick` (bootstrap does NOT restart a running unit), verify `/api/feed` entries carry `description` and a live describe round-trip.

## Self-review notes

- Spec coverage: engine (T1), API incl. role masking + caps (T2), client (T3), capture+rows (T4), cards (T5), deploy (T6). Body untouched everywhere; ledger untouched.
- The dashboard has no capture form (confirmed) — capture-with-details lives only in the list add box, per the amended spec.
- Type consistency: `description` field name everywhere; `setTaskDescription` returns the updated `ActiveTask` (matches the endpoint's 200 body).
