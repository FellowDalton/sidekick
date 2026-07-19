# Named Lists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the shared page into a Google Keep-style grid of named list cards; tapping a card opens a per-list detail view holding the add box, checkboxes, "Break it down", and the nested sub-task tree.

**Architecture:** A code-written `lists.json` registry in the vault root (git-synced) plus a `list:` frontmatter field on top-level tasks; the feed exposes both. The web shared page becomes the grid; a new `/shared/list/[id]` route is the detail view (absorbing the nested-subtasks plan's shelved Task 6). Sub-tasks never carry `list` — the UI builds the full tree, then selects roots by list.

**Tech Stack:** Python 3 + pyyaml (engine), FastAPI + pytest (server), SvelteKit / Svelte 5 runes + vitest + @testing-library/svelte (web).

**Spec:** `docs/superpowers/specs/2026-07-19-named-lists-design.md`
**Prerequisite:** the nested-subtasks plan (`2026-07-19-nested-subtasks.md`) Tasks 1–5 are DONE — `parent`/`status` in the feed, `$lib/tree.ts` with `buildTree`/`doneCount`/`showNudge`, and the `ValueError`-raising engine validation + CLI wrapper exist.

## Global Constraints

- `sidekick.py` stays DETERMINISTIC; pyyaml only. `lists.json` is code-written — never hand-edited, never touched by the model.
- `ledger.jsonl` untouched. No XP/stats changes.
- Engine validation raises `ValueError` (the CLI wrapper converts to exit; the server maps to 4xx).
- The default list id is exactly `todos`, display name `To-dos`. It is implicit: never in `lists.json`, cannot be created or deleted.
- Server tests: `python3 -m pytest server/tests -q` from repo root. Web tests: `npm test` in `web/`.
- Nudge copy stays exactly `N/N done — finish it?`.

---

### Task 1: Engine — list registry + `--list` + feed exposure

**Files:**
- Modify: `sidekick.py`
- Test: `server/tests/test_engine_lists.py` (create)

**Interfaces:**
- Produces:
  - `DEFAULT_LIST_ID = "todos"` (module constant)
  - `read_lists() -> list[dict]` — registry entries `{"id", "name", "created"}`, `[]` when no file.
  - `list_new(name) -> dict` — id = `slug(name)`; `ValueError` on empty name, reserved id, or collision.
  - `list_delete(list_id) -> None` — `ValueError` if unknown or if any open task references it.
  - `create_task(..., list_=None)` — `ValueError` if `list_` is not a registry id; writes `list:` frontmatter.
  - Active feed items gain `"list": fm.get("list")`; the regenerate payload and `LISTS` path global gain a `lists` entry.
  - CLI: `list-new "<name>"`, `list-delete <id>`, `new … --list <id>`.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_engine_lists.py`:

```python
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
```

Note on the reserved-id test: `slug("To-dos")` yields `"to-dos"`, not `"todos"` — the implementation must therefore reject BOTH the exact reserved id and its display name's slug. To keep the rule simple and safe, `list_new` rejects any candidate id in `{"todos", "to-dos"}`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_engine_lists.py -q`
Expected: FAIL — `AttributeError: module 'sidekick' has no attribute 'read_lists'` etc.

- [ ] **Step 3: Implement**

In `sidekick.py`:

1. Paths — add beside the other globals AND inside `configure()`:

```python
LISTS = os.path.join(VAULT, "lists.json")
```

(in `configure()`: `LISTS = os.path.join(VAULT, "lists.json")` and add `LISTS` to the `global` statement.)

2. The registry (place after the frontmatter helpers):

```python
# ── named lists (code-written registry — never hand-edit lists.json) ─────────
DEFAULT_LIST_ID = "todos"
_RESERVED_LIST_IDS = {"todos", "to-dos"}   # the built-in To-dos list, both spellings

def read_lists():
    """Registry entries [{'id','name','created'}]. The default To-dos list is
    implicit and never stored here."""
    if not os.path.exists(LISTS):
        return []
    data = json.loads(open(LISTS, encoding="utf-8").read() or '{"lists": []}')
    return data.get("lists", []) if isinstance(data, dict) else []

def _write_lists(lists):
    tmp = LISTS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"lists": lists}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, LISTS)     # atomic: a half-written registry is never read

def list_new(name):
    name = (name or "").strip()
    if not name:
        raise ValueError("list name is required")
    list_id = slug(name)
    if list_id in _RESERVED_LIST_IDS:
        raise ValueError("that name is reserved for the built-in To-dos list")
    lists = read_lists()
    if any(l["id"] == list_id for l in lists):
        raise ValueError(f"list {list_id} already exists")
    entry = {"id": list_id, "name": name, "created": now_iso()}
    _write_lists(lists + [entry])
    print(f"created list {list_id}")
    return entry

def list_delete(list_id):
    if not any(l["id"] == list_id for l in read_lists()):
        raise ValueError(f"no such list: {list_id}")
    open_count = sum(1 for a in read_active()
                     if a["status"] == "open" and a.get("list") == list_id)
    if open_count:
        raise ValueError(f"list {list_id} still has {open_count} open task(s)")
    _write_lists([l for l in read_lists() if l["id"] != list_id])
    print(f"deleted list {list_id}")
```

3. `create_task` — add the keyword and validation (after the `parent` check), and the frontmatter write (after the `parent` write):

```python
def create_task(title, category, *, from_=None, shared=False, parent=None, list_=None):
```
```python
    if list_ is not None and not any(l["id"] == list_ for l in read_lists()):
        raise ValueError(f"no such list: {list_}")
```
```python
    if list_:
        fm["list"] = list_
```

4. `read_active` — add `"list": fm.get("list")` to BOTH the open and done item dicts.

5. `regenerate` — the payload becomes:

```python
    payload = {"events": events, "active": read_active(),
               "stats": compute_stats(events), "lists": read_lists()}
```

6. CLI — new subcommands beside the others, dispatched inside the existing `try` wrapper:

```python
    pl = sub.add_parser("list-new");    pl.add_argument("name")
    pd = sub.add_parser("list-delete"); pd.add_argument("id")
```
```python
        elif a.cmd == "list-new":
            list_new(a.name); regenerate()
        elif a.cmd == "list-delete":
            list_delete(a.id); regenerate()
```

and the `new` parser gains:

```python
    pn.add_argument("--list", dest="list_", default=None, help="named-list id (see list-new)")
```

with the dispatch passing `list_=a.list_`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add sidekick.py server/tests/test_engine_lists.py
git commit -m "engine: named-list registry (lists.json), new --list, feed exposure"
```

---

### Task 2: Server — `/lists` endpoints, `POST /tasks` list, `/feed` lists

**Files:**
- Modify: `server/app.py`
- Test: `server/tests/test_api_lists.py` (create)

**Interfaces:**
- Consumes: Task 1's engine functions.
- Produces:
  - `POST /lists {"name"}` → 201 registry entry; 400 bad/reserved name; 409 collision; idempotency-key aware; commits `api: new list <id>`.
  - `DELETE /lists/{list_id}` → 200 `{"ok": true}`; 404 unknown (incl. `todos`); 409 while open tasks remain; commits `api: delete list <id>`.
  - `POST /tasks` accepts optional `"list"` (400 unknown id).
  - `/feed` gains `"lists"` for both roles.

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_api_lists.py`:

```python
"""Named-list endpoints (named-lists spec, 2026-07-19)."""
import sidekick

from server.tests.conftest import AUTH


def test_post_list_creates_and_feed_exposes(client, app_config):
    r = client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    assert r.status_code == 201
    entry = r.json()
    assert entry["id"] == "groceries" and entry["name"] == "Groceries"
    feed = client.get("/feed", headers=AUTH).json()
    assert feed["lists"] == [entry]


def test_post_list_validates_name(client):
    assert client.post("/lists", headers=AUTH, json={}).status_code == 400
    assert client.post("/lists", headers=AUTH, json={"name": "x" * 61}).status_code == 400
    assert client.post("/lists", headers=AUTH, json={"name": "To-dos"}).status_code == 400


def test_post_list_collision_409(client):
    client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    assert client.post("/lists", headers=AUTH, json={"name": "groceries"}).status_code == 409


def test_delete_list_paths(client, app_config):
    client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    sidekick.configure(app_config.vault)
    tid = sidekick.create_task("Buy milk", "errand", list_="groceries")
    assert client.delete("/lists/groceries", headers=AUTH).status_code == 409
    sidekick.complete(tid)
    assert client.delete("/lists/groceries", headers=AUTH).status_code == 200
    assert client.delete("/lists/groceries", headers=AUTH).status_code == 404
    assert client.delete("/lists/todos", headers=AUTH).status_code == 404


def test_post_task_with_list(client, app_config):
    client.post("/lists", headers=AUTH, json={"name": "Groceries"})
    r = client.post("/tasks", headers=AUTH,
                    json={"title": "Buy milk", "category": "errand", "list": "groceries"})
    assert r.status_code == 201
    assert r.json()["list"] == "groceries"
    bad = client.post("/tasks", headers=AUTH,
                      json={"title": "Buy milk", "category": "errand", "list": "nope"})
    assert bad.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest server/tests/test_api_lists.py -q`
Expected: 404s / KeyErrors — endpoints and feed key don't exist.

- [ ] **Step 3: Implement**

In `server/app.py`:

1. `/feed` — add `"lists": sidekick.read_lists()` to BOTH role branches' response dicts.

2. New endpoints (after `post_task`, following its exact auth/idempotency/lock/commit shape):

```python
    @app.post("/lists")
    async def post_list(request: Request,
                        authorization: str = Header(default=""),
                        idempotency_key: str = Header(default="")):
        ident = require_auth(authorization)
        try:
            data = _read_json(await request.json())
        except Exception:
            data = {}
        name = data.get("name")
        if not name or not isinstance(name, str) or not (1 <= len(name.strip()) <= 60):
            raise HTTPException(status_code=400, detail="name is required (1-60 characters)")
        name = name.strip()

        def run():
            with vault_lock(config.vault):
                list_id = sidekick.slug(name)
                if any(l["id"] == list_id for l in sidekick.read_lists()):
                    raise HTTPException(status_code=409, detail=f"list {list_id} already exists")
                try:
                    entry = sidekick.list_new(name)
                except ValueError as e:          # reserved name (or race on the check above)
                    raise HTTPException(status_code=400, detail=str(e))
                sidekick.regenerate()
                git_sync.commit_and_push(config.vault, f"api: new list {entry['id']}",
                                         push=config.push, remote=config.remote)
            return 201, entry

        scope = f"{ident['name']}:{request.url.path}"
        return _idem_replay_or_run(scope, idempotency_key, run)

    @app.delete("/lists/{list_id}")
    def delete_list(list_id: str, authorization: str = Header(default="")):
        require_auth(authorization)
        with vault_lock(config.vault):
            if not any(l["id"] == list_id for l in sidekick.read_lists()):
                # the built-in To-dos list is not a resource — it 404s like any unknown id
                raise HTTPException(status_code=404, detail=f"no such list: {list_id}")
            try:
                sidekick.list_delete(list_id)
            except ValueError as e:              # still has open tasks
                raise HTTPException(status_code=409, detail=str(e))
            sidekick.regenerate()
            git_sync.commit_and_push(config.vault, f"api: delete list {list_id}",
                                     push=config.push, remote=config.remote)
        return {"ok": True}
```

3. `post_task` — read and validate the field (beside the `shared` handling):

```python
        list_id = data.get("list")
        if list_id is not None and not isinstance(list_id, str):
            raise HTTPException(status_code=400, detail="list must be a string id")
```

and inside `run()`, before `create_task`:

```python
                if list_id is not None and not any(
                        l["id"] == list_id for l in sidekick.read_lists()):
                    raise HTTPException(status_code=400, detail=f"no such list: {list_id}")
```

then pass it through:

```python
                tid = sidekick.create_task(title, category,
                                           from_=ident["name"], shared=shared, list_=list_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest server/tests -q`
Expected: full suite green.

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/tests/test_api_lists.py
git commit -m "server: POST/DELETE /lists, POST /tasks list field, /feed lists"
```

---

### Task 3: Web API client + types

**Files:**
- Modify: `web/src/lib/types.ts`, `web/src/lib/api.ts`
- Test: `web/src/lib/api.test.ts` (extend — follow the file's existing fetch-mock pattern)

**Interfaces:**
- Produces (used by Tasks 4–5):
  - `interface TaskList { id: string; name: string; created: string; }` (types.ts); `Feed` gains `lists?: TaskList[]`; `ActiveTask` gains `list?: string | null`.
  - `createTask(title, category, shared = false, list?: string)` — sends `list` only when set.
  - `createList(name: string): Promise<TaskList>` — POST `/api/lists` with Idempotency-Key.
  - `deleteList(id: string): Promise<void>` — DELETE `/api/lists/{id}`.

- [ ] **Step 1: Write the failing tests**

Append to `web/src/lib/api.test.ts` (mirror its existing `fetch` mocking; the assertions below are the contract):

```ts
describe("named lists api", () => {
  it("createList POSTs the name to /api/lists", async () => {
    mockFetchOnce(201, { id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" });
    const entry = await createList("Groceries");
    expect(entry.id).toBe("groceries");
    const [url, init] = lastFetchCall();
    expect(url).toContain("/api/lists");
    expect(JSON.parse(init.body)).toEqual({ name: "Groceries" });
    expect(init.headers["Idempotency-Key"]).toBeTruthy();
  });

  it("deleteList DELETEs /api/lists/{id}", async () => {
    mockFetchOnce(200, { ok: true });
    await deleteList("groceries");
    const [url, init] = lastFetchCall();
    expect(url).toContain("/api/lists/groceries");
    expect(init.method).toBe("DELETE");
  });

  it("createTask includes list only when given", async () => {
    mockFetchOnce(201, { id: "t", task: "Buy milk" });
    await createTask("Buy milk", "errand", true, "groceries");
    const [, init] = lastFetchCall();
    expect(JSON.parse(init.body)).toEqual(
      { title: "Buy milk", category: "errand", shared: true, list: "groceries" });
  });
});
```

(`mockFetchOnce` / `lastFetchCall` stand for whatever helpers the file already uses — reuse them, don't invent new plumbing.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/lib/api.test.ts`
Expected: FAIL — `createList` / `deleteList` not exported.

- [ ] **Step 3: Implement**

`web/src/lib/types.ts` — add:

```ts
export interface TaskList { id: string; name: string; created: string; }
```

extend `ActiveTask` with `list?: string | null;` and `Feed` with `lists?: TaskList[];`.

`web/src/lib/api.ts` — replace `createTask` and add the list calls:

```ts
export async function createTask(title: string, category: Category, shared = false, list?: string): Promise<ActiveTask> {
  const body: Record<string, unknown> = { title, category };
  if (shared) body.shared = true;
  if (list) body.list = list;
  return handle(await fetch(`${base()}/api/tasks`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify(body)
  }));
}

export async function createList(name: string): Promise<TaskList> {
  return handle(await fetch(`${base()}/api/lists`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ name })
  }));
}

export async function deleteList(id: string): Promise<void> {
  await handle(await fetch(`${base()}/api/lists/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: headers()
  }));
}
```

(add `TaskList` to the types import.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npm test`
Expected: green — the pre-existing `createTask` test asserting `{ title, category, shared: true }` still passes because `list` is omitted when absent.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/src/lib/api.ts web/src/lib/api.test.ts
git commit -m "web: api client — createList/deleteList, createTask list param, Feed.lists"
```

---

### Task 4: Shared page becomes the list grid

**Files:**
- Modify: `web/src/routes/shared/+page.svelte` (full rewrite)
- Test: `web/src/routes/shared/shared.test.ts` (rewrite the rendering tests; keep the file's api-mocking scaffolding)

**Interfaces:**
- Consumes: `getFeed`, `createList`, `deleteList` (Task 3); `buildTree` (`$lib/tree`).
- Produces: the grid view. Cards: To-dos first, then registry order; each shows the name, up to 5 open ROOT task titles (☐ glyph), a `+N more` line, and an open count; tap navigates to `/shared/list/<id>`. "+ New list" inline form → `createList` → navigate into the new list. Empty non-default lists show a small Delete button.

- [ ] **Step 1: Write the failing tests**

Rewrite the rendering describe-blocks in `web/src/routes/shared/shared.test.ts` (keep the mock setup; the add-box/breakdown/polling tests MOVE to Task 5's detail-view test file — delete them here):

```ts
describe("shared page — list grid", () => {
  const gridFeed = {
    events: [],
    lists: [{ id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" },
            { id: "packing", name: "Packing", created: "2026-07-19T00:00:00Z" }],
    active: [
      { id: "t1", task: "Buy milk", category: "errand", sat_for_hours: 1, plan: null, shared: true, status: "open", list: "groceries" },
      { id: "t2", task: "Call plumber", category: "phone", sat_for_hours: 2, plan: null, shared: true, status: "open" },
      { id: "t2c", task: "Find number", category: "phone", sat_for_hours: 1, plan: null, shared: true, status: "open", parent: "t2" }
    ]
  };

  it("renders To-dos first, then registry lists, with open root counts", async () => {
    vi.mocked(getFeed).mockResolvedValue(gridFeed as any);
    render(Page);
    const cards = await screen.findAllByRole("link", { name: /open list/i });
    expect(cards.map(c => c.getAttribute("href"))).toEqual(
      ["/shared/list/todos", "/shared/list/groceries", "/shared/list/packing"]);
  });

  it("previews root tasks only — children never appear on a card", async () => {
    vi.mocked(getFeed).mockResolvedValue(gridFeed as any);
    render(Page);
    await screen.findByText("Call plumber");        // t2 is a To-dos root
    expect(screen.queryByText("Find number")).toBeNull();   // child of t2, hidden on grid
  });

  it("shows +N more when a list has more than 5 open roots", async () => {
    const many = Array.from({ length: 7 }, (_, i) => (
      { id: `g${i}`, task: `Item ${i}`, category: "errand", sat_for_hours: 1,
        plan: null, shared: true, status: "open", list: "groceries" }));
    vi.mocked(getFeed).mockResolvedValue({ ...gridFeed, active: many } as any);
    render(Page);
    expect(await screen.findByText("+2 more")).toBeInTheDocument();
  });

  it("creates a list and navigates into it", async () => {
    vi.mocked(getFeed).mockResolvedValue({ events: [], lists: [], active: [] } as any);
    vi.mocked(createList).mockResolvedValue(
      { id: "ferie", name: "Ferie", created: "2026-07-19T00:00:00Z" } as any);
    render(Page);
    await fireEvent.click(await screen.findByRole("button", { name: /new list/i }));
    await fireEvent.input(screen.getByLabelText("List name"), { target: { value: "Ferie" } });
    await fireEvent.submit(screen.getByLabelText("List name").closest("form")!);
    expect(createList).toHaveBeenCalledWith("Ferie");
    expect(goto).toHaveBeenCalledWith("/shared/list/ferie");
  });

  it("offers Delete only on an empty non-default list", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      events: [],
      lists: [{ id: "old", name: "Old", created: "2026-07-19T00:00:00Z" }],
      active: []
    } as any);
    render(Page);
    expect(await screen.findByRole("button", { name: "Delete Old" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete To-dos" })).toBeNull();
  });
});
```

(Extend the file's `vi.mock("$lib/api", …)` factory with `createList: vi.fn()` and `deleteList: vi.fn()`; `goto` is already mocked.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/routes/shared/shared.test.ts`
Expected: FAIL — the page still renders a flat task list.

- [ ] **Step 3: Implement**

Rewrite `web/src/routes/shared/+page.svelte`:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { getFeed, createList, deleteList, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import { buildTree } from "$lib/tree";
  import type { Feed, TaskList } from "$lib/types";

  const DEFAULT_LIST: TaskList = { id: "todos", name: "To-dos", created: "" };

  let feed = $state<Feed | null>(null);
  let error = $state("");
  let adding = $state(false);          // the "+ New list" form is open
  let newName = $state("");
  let busy = $state(false);

  async function load() {
    error = "";
    try {
      feed = await getFeed();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  // full tree of shared tasks — children follow their root's list automatically
  const roots = $derived(feed ? buildTree(feed.active.filter(t => t.shared)) : []);
  const cards = $derived([DEFAULT_LIST, ...(feed?.lists ?? [])].map(l => {
    const mine = roots.filter(n => (n.task.list ?? "todos") === l.id && n.task.status !== "done");
    return {
      list: l,
      previews: mine.slice(0, 5).map(n => n.task.task),
      more: Math.max(0, mine.length - 5),
      openCount: mine.length,
      deletable: l.id !== "todos" &&
        roots.every(n => (n.task.list ?? "todos") !== l.id),
    };
  }));

  async function addList(e: Event) {
    e.preventDefault();
    if (!newName.trim() || busy) return;
    busy = true; error = "";
    try {
      const entry = await createList(newName.trim());
      goto(`/shared/list/${entry.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't create — try again";
    } finally {
      busy = false;
    }
  }

  async function removeList(id: string) {
    error = "";
    try {
      await deleteList(id);
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't delete — try again";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Shared lists</h1>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{/if}

{#if feed}
  <div class="grid">
    {#each cards as c (c.list.id)}
      <a class="card" href={"/shared/list/" + c.list.id}
         aria-label={"Open list " + c.list.name}>
        <div class="card-head">
          <span class="card-name">{c.list.name}</span>
          <span class="count">{c.openCount} open</span>
        </div>
        {#if c.previews.length === 0}
          <p class="muted empty">Nothing here.</p>
        {:else}
          <ul class="preview">
            {#each c.previews as p}<li>☐ {p}</li>{/each}
          </ul>
          {#if c.more > 0}<div class="muted more">+{c.more} more</div>{/if}
        {/if}
        {#if c.deletable}
          <button class="btn btn-mini del" aria-label={"Delete " + c.list.name}
                  onclick={(e) => { e.preventDefault(); removeList(c.list.id); }}>
            Delete
          </button>
        {/if}
      </a>
    {/each}
  </div>

  {#if adding}
    <form class="add-row" onsubmit={addList}>
      <input type="text" bind:value={newName} placeholder="List name…" aria-label="List name" />
      <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Creating…" : "Create"}</button>
    </form>
  {:else}
    <button class="btn" onclick={() => { adding = true; }}>+ New list</button>
  {/if}
{:else if !error}
  <p class="muted">Loading…</p>
{/if}

<style>
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 18px; }
  .card { display: block; padding: 12px 14px; border-radius: 14px;
          border: 1px solid rgba(128, 128, 128, 0.35); text-decoration: none; color: inherit;
          position: relative; }
  .card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
               margin-bottom: 8px; }
  .card-name { font-weight: 600; font-size: 16px; }
  .count { font-size: 12px; opacity: 0.7; flex: none; }
  .preview { list-style: none; padding: 0; margin: 0; font-size: 13px; line-height: 1.7; }
  .preview li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .more { font-size: 12px; margin-top: 4px; }
  .empty { font-size: 13px; }
  .del { position: absolute; right: 10px; bottom: 10px; }
  .add-row { display: flex; gap: 8px; }
  .add-row input[type="text"] {
    flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(128, 128, 128, 0.35); background: transparent;
    color: inherit; font-size: 16px;   /* ≥16px prevents iOS focus zoom */
  }
</style>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/routes/shared/shared.test.ts`
Expected: green.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/shared/+page.svelte web/src/routes/shared/shared.test.ts
git commit -m "web: shared page becomes Keep-style list grid with previews and new-list flow"
```

---

### Task 5: List detail view — the tree lives here

This absorbs the nested-subtasks plan's shelved Task 6: same tree rendering, done rows, nudge, breakdown/polling and optimistic complete — now scoped to one list.

**Files:**
- Create: `web/src/routes/shared/list/[id]/+page.svelte`
- Test: `web/src/routes/shared/list/list-detail.test.ts` (create; move the add-box/complete/breakdown/polling tests deleted from `shared.test.ts` in Task 4 here, adapted)

**Interfaces:**
- Consumes: `buildTree`, `doneCount`, `showNudge`, `TreeNode` (`$lib/tree`); `getFeed`, `createTask`, `completeTask`, `startAgentJob`, `getAgentJob` (`$lib/api`); route param `id`.
- Produces: visual behavior only. Roots shown = tasks whose `list ?? "todos"` equals the route id; children follow their root regardless of `list`. Add box creates into this list (omits `list` for `todos`). Unknown id → "list not found" + back link.

- [ ] **Step 1: Write the failing tests**

Create `web/src/routes/shared/list/list-detail.test.ts`. Mock `$lib/api` exactly as `shared.test.ts` does, mock the route param the way the repo mocks `$app` modules (e.g. `vi.mock("$app/state", () => ({ page: { params: { id: "groceries" } } }))` — match the SvelteKit version's import used in the component):

```ts
describe("list detail view", () => {
  const feed = {
    events: [],
    lists: [{ id: "groceries", name: "Groceries", created: "2026-07-19T00:00:00Z" }],
    active: [
      { id: "p", task: "Plan the party", category: "chore", sat_for_hours: 5, plan: null, shared: true, status: "open", list: "groceries" },
      { id: "c1", task: "Book the venue", category: "chore", sat_for_hours: 2, plan: null, shared: true, parent: "p", status: "open" },
      { id: "c2", task: "Order the cake", category: "chore", sat_for_hours: null, plan: null, shared: true, parent: "p", status: "done", completed_at: "2026-07-19T10:00:00Z" },
      { id: "other", task: "Not in this list", category: "chore", sat_for_hours: 1, plan: null, shared: true, status: "open" }
    ]
  };

  it("shows only this list's roots, with children nested inside", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    render(Page);
    const parentRow = (await screen.findByText("Plan the party")).closest("li")!;
    expect(parentRow.textContent).toContain("Book the venue");
    expect(screen.queryByText("Not in this list")).toBeNull();   // that's a To-dos root
    const list = parentRow.closest("ul")!;
    expect(list.querySelectorAll(":scope > li").length).toBe(1);
  });

  it("renders a done child checked, disabled and struck through", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    render(Page);
    await screen.findByText("Plan the party");
    const box = screen.getByLabelText("Order the cake — done") as HTMLInputElement;
    expect(box.checked).toBe(true);
    expect(box.disabled).toBe(true);
  });

  it("shows the finish nudge when all children are done", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      ...feed,
      active: [feed.active[0], feed.active[2]]     // parent + done child only
    } as any);
    render(Page);
    expect(await screen.findByText("1/1 done — finish it?")).toBeInTheDocument();
  });

  it("still offers Break it down on a nested open child", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    render(Page);
    await screen.findByText("Plan the party");
    expect(screen.getByLabelText("Break down Book the venue")).toBeInTheDocument();
  });

  it("adds a task into this list", async () => {
    vi.mocked(getFeed).mockResolvedValue(feed as any);
    vi.mocked(createTask).mockResolvedValue({ id: "n" } as any);
    render(Page);
    await screen.findByText("Plan the party");
    await fireEvent.input(screen.getByLabelText("New task"), { target: { value: "Buy candles" } });
    await fireEvent.submit(screen.getByLabelText("New task").closest("form")!);
    expect(createTask).toHaveBeenCalledWith("Buy candles", "chore", true, "groceries");
  });

  it("shows list-not-found for an unknown id", async () => {
    vi.mocked(getFeed).mockResolvedValue({ events: [], lists: [], active: [] } as any);
    render(Page);   // param mock still says "groceries", which now doesn't exist
    expect(await screen.findByText(/list not found/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/routes/shared/list/list-detail.test.ts`
Expected: FAIL — route component doesn't exist.

- [ ] **Step 3: Implement**

Create `web/src/routes/shared/list/[id]/+page.svelte`. The script logic is the OLD shared page's (load/tick/breakdown/polling — copy from git history of `shared/+page.svelte` before Task 4, adjusting three things): (1) `tick` flips status in place (the nested-subtasks plan's Task 6 version); (2) roots filter by the route's list id; (3) `add` passes the list id. Markup is the recursive `row` snippet from the nested-subtasks plan's Task 6 verbatim, plus a header and back link:

```svelte
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { getFeed, createTask, completeTask, startAgentJob, getAgentJob, ApiError, type AgentJob } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import { buildTree, doneCount, showNudge, type TreeNode } from "$lib/tree";
  import type { ActiveTask, Feed } from "$lib/types";

  const listId = $derived(page.params.id);

  let feed = $state<Feed | null>(null);
  let title = $state("");
  let busy = $state(false);
  let error = $state("");
  let pending = $state(new Set<string>());
  let agentJobs = $state<Record<string, AgentJob>>({});
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const listName = $derived(
    listId === "todos" ? "To-dos" : (feed?.lists ?? []).find(l => l.id === listId)?.name ?? null);

  const newestFirst = (list: ActiveTask[]) =>
    [...list].sort((a, b) => (a.sat_for_hours ?? 0) - (b.sat_for_hours ?? 0));

  // full tree of shared tasks, then keep only this list's roots — children follow
  const tree = $derived(feed
    ? buildTree(newestFirst(feed.active.filter(t => t.shared)))
        .filter(n => (n.task.list ?? "todos") === listId)
    : []);

  async function load() {
    error = "";
    try {
      feed = await getFeed();
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
      await createTask(title.trim(), "chore", true,
                       listId === "todos" ? undefined : listId);  // fixed category: the box has no picker
      title = "";
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't add — try again";
    } finally {
      busy = false;
    }
  }

  async function tick(id: string) {
    if (!feed || pending.has(id)) return;
    const prev = feed;
    if (!prev.active.some(t => t.id === id)) return;
    pending = new Set(pending).add(id);
    feed = { ...prev, active: prev.active.map(t => t.id === id ? { ...t, status: "done" as const } : t) };  // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                       // reconcile: fetch new items from other user
    } catch (e) {
      feed = prev;                                        // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  // ── agent jobs: breakdown, both roles (unchanged from the old shared page) ──
  function jobActive(j: AgentJob): boolean {
    return j.status === "queued" || j.status === "running";
  }
  function chipText(j: AgentJob): string {
    if (j.status === "done") return "done — sub-tasks arrive in a few minutes";
    if (j.status === "failed") return j.error === "job lost" ? "failed (job lost)" : "failed";
    return j.status;
  }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
  function startPolling() { if (!pollTimer) pollTimer = setInterval(poll, 5000); }

  async function poll() {
    const active = Object.values(agentJobs).filter(jobActive);
    if (active.length === 0) { stopPolling(); return; }
    for (const j of active) {
      try {
        const fresh = await getAgentJob(j.id);
        agentJobs = { ...agentJobs, [fresh.task_id]: fresh };
        if (fresh.status === "done") await load();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) { stopPolling(); goto("/settings"); return; }
        if (e instanceof ApiError && e.status === 404) {
          agentJobs = { ...agentJobs, [j.task_id]: { ...j, status: "failed", error: "job lost" } };
        }
        // else: transient — keep polling
      }
    }
  }

  async function breakItDown(id: string) {
    if (agentJobs[id] && jobActive(agentJobs[id])) return;
    error = "";
    try {
      const job = await startAgentJob(id, "breakdown");
      agentJobs = { ...agentJobs, [id]: job };
      startPolling();
    } catch (e) {
      error = e instanceof Error ? e.message : "couldn't start — try again";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
  onDestroy(stopPolling);
</script>

<a href="/shared" class="muted back">← Lists</a>

{#if feed && listName === null}
  <p class="msg-err">List not found — it may have been deleted on another phone.</p>
{:else}
  <h1 class="tc-name" style="font-size:26px;margin:8px 0 18px">{listName ?? "…"}</h1>

  <form class="add-row" onsubmit={add}>
    <input type="text" bind:value={title} placeholder="Add to the list…" aria-label="New task" />
    <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
  </form>

  {#if error}
    <p class="msg-err">{error}</p>
    <button class="btn" onclick={load}>Retry</button>
  {/if}

  {#if feed}
    {#if tree.length === 0}
      <p class="muted">Nothing on the list.</p>
    {:else}
      {#snippet row(node: TreeNode)}
        {@const t = node.task}
        <li class:done-row={t.status === "done"}>
          <label>
            {#if t.status === "done"}
              <input type="checkbox" checked disabled aria-label={t.task + " — done"} />
              <span class="struck">{t.task}</span>
            {:else}
              <input type="checkbox" disabled={pending.has(t.id)}
                     onchange={() => tick(t.id)} aria-label={"Complete " + t.task} />
              <span>{t.task}</span>
              {#if showNudge(node)}
                <span class="chip nudge">{doneCount(node).done}/{doneCount(node).total} done — finish it?</span>
              {/if}
            {/if}
          </label>
          {#if t.status !== "done"}
            <div class="row-agent">
              <button class="btn btn-mini" disabled={!!agentJobs[t.id] && jobActive(agentJobs[t.id])}
                      onclick={() => breakItDown(t.id)} aria-label={"Break down " + t.task}>
                {!!agentJobs[t.id] && jobActive(agentJobs[t.id]) ? "Working…" : "Break it down"}
              </button>
              {#if agentJobs[t.id]}
                <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
              {/if}
            </div>
          {/if}
          {#if node.children.length}
            <ul class="list children">
              {#each node.children as c (c.task.id)}{@render row(c)}{/each}
            </ul>
          {/if}
        </li>
      {/snippet}
      <ul class="list">
        {#each tree as n (n.task.id)}{@render row(n)}{/each}
      </ul>
    {/if}
  {:else if !error}
    <p class="muted">Loading…</p>
  {/if}
{/if}

<style>
  .back { display: inline-block; font-size: 14px; text-decoration: none; }
  .add-row { display: flex; gap: 8px; margin-bottom: 18px; }
  .add-row input[type="text"] {
    flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(128, 128, 128, 0.35); background: transparent;
    color: inherit; font-size: 16px;   /* ≥16px prevents iOS focus zoom */
  }
  .list { list-style: none; padding: 0; margin: 0; }
  .list li { padding: 12px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.2); }
  .list label { display: flex; align-items: center; gap: 12px; font-size: 17px; flex-wrap: wrap; }
  .list input[type="checkbox"] { width: 22px; height: 22px; flex: none; }
  .row-agent { display: flex; align-items: center; gap: 8px; margin: 8px 0 0 34px; }
  .btn-mini { font-size: 13px; padding: 4px 10px; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px;
          border: 1px solid rgba(128, 128, 128, 0.35); opacity: 0.85; }
  .chip-queued, .chip-running { animation: chip-pulse 1.5s ease-in-out infinite; }
  .chip-failed { border-color: rgba(220, 60, 60, 0.6); }
  @keyframes chip-pulse { 50% { opacity: 0.45; } }
  .children { margin: 8px 0 0 22px; border-left: 2px solid rgba(128, 128, 128, 0.25); padding-left: 12px; }
  .children li:last-child { border-bottom: none; }
  .struck { text-decoration: line-through; opacity: 0.55; }
  .nudge { border-color: rgba(120, 200, 120, 0.5); }
</style>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npm test`
Expected: full web suite green.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/shared/list web/src/routes/shared/list/list-detail.test.ts
git commit -m "web: list detail view — scoped add box, nested sub-task tree, breakdown"
```

---

### Task 6: Full verification + push

- [ ] **Step 1: Run both suites**

```bash
python3 -m pytest server/tests -q
cd web && npm test && cd ..
```

- [ ] **Step 2: Throwaway-vault smoke**

```bash
V=/tmp/lists-smoke; mkdir -p $V/tasks; : > $V/ledger.jsonl
SIDEKICK_VAULT=$V python3 sidekick.py list-new "Groceries"
SIDEKICK_VAULT=$V python3 sidekick.py new "Buy milk" --category errand --list groceries --shared
SIDEKICK_VAULT=$V python3 sidekick.py regenerate
grep -o '"lists": \[' $V/sidekick-data.js     # registry present in the feed
rm -rf $V
```

- [ ] **Step 3: Push**

```bash
git push
```

Deploy note: VPS pickup = `git -C /srv/sidekick pull` + `bash /srv/sidekick/deploy/bootstrap.sh`; also `sudo -u sidekick git -C /home/sidekick/agent/sidekick pull` so the agent clone's `sidekick.py` knows `--parent`/`--list`.

## Self-review notes

- Spec coverage: registry + lifecycle (T1), API incl. role-agnostic access (T2), client (T3), grid incl. default-first ordering, previews, overflow, create/delete (T4), detail view incl. tree/add/breakdown/not-found (T5). Rename intentionally absent (out of scope).
- Type consistency: `TaskList` (types) vs registry entry `{id,name,created}` (engine/server) match; `list_` (Python kwarg) ↔ `"list"` (JSON/frontmatter/TS) is deliberate (`list` shadows the Python builtin).
- The breakdown prompt does NOT pass `--list`: children inherit their place via `parent` (spec: sub-tasks never carry `list`).
